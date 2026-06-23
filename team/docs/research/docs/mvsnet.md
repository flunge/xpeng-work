# MVSNet 模块技术分析文档

## 1. 概述

### 1.1 模块定位

MVSNet 模块是 SimWorld 三维重建流水线中的**多视图立体深度估计**核心组件，位于 `/workspace/xpeng_data_process/mvsnet/`。其职责是：给定一张参考图像和若干源视图图像及其相机参数，估计参考图像每个像素的深度值，最终生成稠密点云用于下游 3DGS 训练。

### 1.2 子实现架构

模块包含两套独立的 MVS 深度估计实现：

| 子模块 | 路径 | 核心思想 | 适用场景 |
|--------|------|----------|----------|
| **CL-MVSNet** | `clmvsnet/` | 级联（Cascade）多阶段代价体 + Group-wise 相关性 + 3D UNet 正则化 | 历史实现，本文档保留其结构分析用于理解旧流程 |
| **MVS-Anywhere** | `mvsa/` | ResNet 特征编码 + 点积代价体 + PP-Decoder 深度解码 | 当前 develop 主线的实际推理实现 |

### 1.3 当前工程状态

截至当前主线代码，`xpeng_data_process/mvsnet_processor.py` 已经收敛到 `mvsa` 路径：

- 运行配置模板切到 `mvsnet/mvsa/configs/base/recon.yaml`
- 推理入口固定为 `mvsnet.mvsa.src.mvsanywhere.test_xpeng`
- 元数据生成使用 `generate_mvsnet_metadata + output_view_list + convert_to_capture_format`
- 历史 `clmvsnet` 目录已从主线预处理链路中移除，不再作为当前默认生产路径

因此，下面保留的 CL-MVSNet 结构分析更适合作为历史方案说明；如果关注当前线上行为，应优先结合 `mvsa/` 代码和 `MvsnetProcessor` 的实际调用链阅读。

### 1.4 在 SimWorld 流水线中的位置

```
数据采集 → 数据预处理(generate_data.py) → 多视图深度估计(MVSNet) → 点云融合(postprocess) → 3DGS训练
                                              ↑ 本模块
```

数据预处理阶段通过 `utils/generate_data.py` 完成工作空间准备（符号链接创建、标定文件合并、位姿对齐验证等），为 MVSNet 提供标准化输入。MVSNet 输出的深度图经后处理模块进行几何一致性检查、置信度过滤和语义掩码过滤后，融合为带颜色和语义标签的稠密点云（PLY 格式）。

当前 develop 还新增了一条和时间对齐更紧密的输入整理链路：`generate_data.py` 在组织 MVS 数据时会显式读取 `timestamp2slice.json`，把 slice 编号、原始时间戳和重建图像索引绑定起来。这意味着当前 MVS 模块不再只依赖文件遍历顺序，而是显式复用 Vision 预处理阶段已经整理好的统一时间轴。

---

## 2. 模型结构

### 2.1 CL-MVSNet 整体架构

CL-MVSNet 采用**级联多阶段（Cascade Multi-Stage）**架构，由粗到细逐步精化深度估计。核心网络类为 `CasMVSNet`，外层包装为 `CLMVSNet`（增加数据增强支持）。

```
输入图像 (B, V, 3, H, W)
    │
    ▼
┌─────────────────┐
│  FPN 特征提取器   │  ← 每个视图独立提取多尺度特征
│  (FPNFeature)    │
└─────────────────┘
    │ stage1: (B, 4C, H/4, W/4)
    │ stage2: (B, 2C, H/2, W/2)
    │ stage3: (B, C, H, W)
    ▼
┌─────────────────────────────────────────────┐
│  Stage 1 (1/4 分辨率, 粗估计)                 │
│  InitSampler → GroupWiseAgg → UNet3D → Reg  │
├─────────────────────────────────────────────┤
│  Stage 2 (1/2 分辨率, 中间精化)               │
│  UniformSampler → GroupWiseAgg → UNet3D → Reg│
├─────────────────────────────────────────────┤
│  Stage 3 (全分辨率, 精细估计)                  │
│  UniformSampler → GroupWiseAgg → UNet3D → Reg│
└─────────────────────────────────────────────┘
    │
    ▼
输出: depth (B, H, W), photometric_confidence (B, H, W), prob_volume (B, D, H, W)
```

其中 `C = base_channels`（默认 8），`V = nviews`（视图数），`D = num_hypotheses`（深度假设数）。

### 2.2 FPN 特征提取器 (FPNFeature)

采用自顶向下的特征金字塔网络，从 RGB 图像提取多尺度特征。

**网络结构：**

```python
# 编码器（自底向上）
conv0: 3 → C → C          # (B, C, H, W)      stride=1
conv1: C → 2C → 2C → 2C   # (B, 2C, H/2, W/2) stride=2
conv2: 2C → 4C → 4C → 4C  # (B, 4C, H/4, W/4) stride=2

# FPN 解码器（自顶向下）
stage1 = out1(conv2)                                    # (B, 4C, H/4, W/4)
stage2 = out2(upsample(conv2) + inner1(conv1))          # (B, 2C, H/2, W/2)
stage3 = out3(upsample(stage2_feat) + inner2(conv0))    # (B, C, H, W)
```

**张量维度流（以 base_channels=8, 输入 H=512, W=640 为例）：**

| 层 | 输出维度 | 说明 |
|----|----------|------|
| conv0 | `(B, 8, 512, 640)` | 原始分辨率特征 |
| conv1 | `(B, 16, 256, 320)` | 1/2 分辨率 |
| conv2 | `(B, 32, 128, 160)` | 1/4 分辨率 |
| stage1 | `(B, 32, 128, 160)` | FPN 最粗层 |
| stage2 | `(B, 16, 256, 320)` | FPN 中间层 |
| stage3 | `(B, 8, 512, 640)` | FPN 最细层 |

### 2.3 深度假设采样器

#### InitSampler（Stage 1）

在全局深度范围 `[depth_min, depth_max]` 内均匀采样 `D` 个深度假设平面：

```
输入: depth_values (B, 2) → [min_depth, max_depth]
输出: depth_hypotheses (B, D, H, W)

interval = (max_depth - min_depth) / (D - 1)
hypotheses[d] = min_depth + d * interval,  d ∈ [0, D-1]
```

#### UniformSampler（Stage 2, 3）

以上一阶段估计的深度为中心，在局部范围内重新采样：

```
输入: last_depth (B, H', W') → 上一阶段深度估计
参数: interval_ratio, num_hypotheses

local_min = last_depth - D/2 * interval_ratio * interval_base
local_max = last_depth + D/2 * interval_ratio * interval_base
hypotheses = linspace(local_min, local_max, D)  → (B, D, H, W)
```

通过双线性插值将假设平面上采样到当前阶段分辨率。

### 2.4 代价体构建 (GroupWiseAgg)

采用 **Group-wise Correlation** 方法构建匹配代价体，避免了传统方差方法的高内存消耗。

**核心流程：**

```
1. 参考特征扩展:  ref_volume = ref_feat.unsqueeze(2).repeat(1,1,D,1,1)
                  → (B, C, D, H, W) → reshape → (B, G, C/G, D, H, W)

2. 对每个源视图:
   a. 计算单应性变换矩阵: proj = src_proj @ inv(ref_proj)
   b. 可微分单应性变形:   warped = homo_warping(src_feat, proj, depth_hypotheses)
                          → (B, C, D, H, W) → reshape → (B, G, C/G, D, H, W)
   c. 累加变形特征:       volume_sum += warped

3. Group-wise 相关性:
   correlation = mean(volume_sum * ref_volume, dim=2) / (V-1)
   → (B, G, D, H, W)
```

**张量维度（Stage 1, G=8 groups, D=48 假设）：**

| 步骤 | 张量 | 维度 |
|------|------|------|
| 参考特征 | `ref_feat` | `(B, 32, 128, 160)` |
| 参考体积 | `ref_volume` | `(B, 8, 4, 48, 128, 160)` |
| 变形体积 | `warped_volume` | `(B, 8, 4, 48, 128, 160)` |
| 相关性代价体 | `volume_correlation` | `(B, 8, 48, 128, 160)` |

#### 可微分单应性变形 (homo_warping)

这是代价体构建的核心几何操作：

```python
# 输入
src_fea:       (B, C, H, W)        # 源视图特征
src_proj:      (B, 4, 4)           # 源视图投影矩阵
ref_proj:      (B, 4, 4)           # 参考视图投影矩阵
depth_values:  (B, D, H, W)        # 深度假设

# 计算相对变换
proj = src_proj @ inv(ref_proj)    # (B, 4, 4)
rot = proj[:, :3, :3]             # (B, 3, 3)
trans = proj[:, :3, 3:4]          # (B, 3, 1)

# 像素坐标网格
xyz = stack(meshgrid(W, H), ones)  # (3, H*W)

# 对每个深度假设进行投影
rot_depth_xyz = rot @ xyz * depth  # (B, 3, D, H*W)
proj_xyz = rot_depth_xyz + trans   # (B, 3, D, H*W)
proj_xy = proj_xyz[:,:2] / proj_xyz[:,2:3]  # 归一化

# 双线性采样
grid = normalize(proj_xy)          # → [-1, 1]
warped = grid_sample(src_fea, grid) # (B, C, D*H, W) → (B, C, D, H, W)
```

### 2.5 法线估计分支 (GroupWiseAggDepthCostVolumeandNormalCostVolume)

当 `regress_normal=True` 时，Stage 1 使用增强版代价体聚合模块，同时输出法线图：

```
代价体 (B, 8, D, H, W)
    │
    ▼
wc0: Conv3d(8→16) + ReLU + Conv3d(16→16) + ReLU
    │
    ▼
pool1/pool2/pool3: 深度维度池化 (2,3,3) stride (2,1,1)
    │
    ▼
对每个深度切片: n_convs (扩张卷积序列)
    16 → 32 → 48 → 48 → 48 → 32 → 16 → 3
    │
    ▼
累加 + L2归一化 → normal_map (B, H, W, 3)
```

扩张卷积序列使用 dilation = [1, 2, 4, 8, 16, 1, 1]，有效感受野覆盖大范围上下文。

### 2.6 3D UNet 正则化 (UNet3DCNNReg)

对代价体进行 3D 卷积正则化，采用编码器-解码器结构：

```
输入: cost_volume (B, G, D, H, W)  # G=8

编码器:
  conv0:  G → C        (B, C, D, H, W)        # C=base_channels
  conv1:  C → 2C       (B, 2C, D/2, H/2, W/2) stride=2
  conv2:  2C → 2C      (B, 2C, D/2, H/2, W/2)
  conv3:  2C → 4C      (B, 4C, D/4, H/4, W/4) stride=2
  conv4:  4C → 4C      (B, 4C, D/4, H/4, W/4)
  conv5:  4C → 8C      (B, 8C, D/8, H/8, W/8) stride=2
  conv6:  8C → 8C      (B, 8C, D/8, H/8, W/8)

解码器 (跳跃连接):
  conv7:  8C → 4C      + conv4 残差
  conv9:  4C → 2C      + conv2 残差
  conv11: 2C → C       + conv0 残差

输出头:
  prob:   C → 1        (B, 1, D, H, W)
```

### 2.7 深度回归 (RegressionDepth)

将正则化后的代价体转换为深度估计：

```python
# Softmax 概率化
prob_volume = softmax(cost_reg.squeeze(1), dim=1)  # (B, D, H, W)

# 加权求和回归深度
depth = sum(prob_volume * depth_hypotheses, dim=1)  # (B, H, W)

# 光度置信度（4-邻域平均池化）
prob_sum4 = 4 * avg_pool3d(pad(prob_volume), (4,1,1))
confidence = gather(prob_sum4, depth_index)  # (B, H, W)

# 分布一致性（基于信息熵）
entropy = -sum(pv * log(pv), dim=1)
distribution_consistency = (log(D) - entropy) / log(D)  # (B, H, W)
```

### 2.8 时序深度一致性 (Depth Temporal)

当 `depth_temporal=True` 时，网络额外对源视图进行深度估计，用于时序一致性约束：

```
对每个源视图 src_img_id ∈ {0, 1}:
  1. 交换参考/源特征和投影矩阵
  2. 使用相同的级联流水线估计源视图深度
  3. 输出 context_{id}_depth 用于损失计算
```

### 2.9 MVS-Anywhere 架构

MVS-Anywhere 采用与 CL-MVSNet 不同的设计哲学，更注重泛化性。

#### 2.9.1 特征编码器

**匹配特征编码器 (ResnetMatchingEncoder)：**

基于 ResNet-18（带抗锯齿）提取匹配特征：

```
输入: image (B, 3, H, W)

ResNet-18 前4层:
  conv1 → bn1 → relu → maxpool → layer1
  → (B, 64, H/4, W/4)

投影头:
  Conv2d(64→128, 1×1) → InstanceNorm → LeakyReLU(0.2)
  Conv2d(128→num_ch_out, 3×3) → InstanceNorm
  → (B, num_ch_out, H/4, W/4)
```

**代价体编码器 (CVEncoder)：**

将代价体与图像特征融合：

```
对每个尺度 i:
  ds_conv: 下采样卷积 (stride=2, 首层stride=1)
  concat: 拼接图像编码器特征
  conv: 两层 BasicBlock 融合
```

#### 2.9.2 代价体构建 (CostVolumeManager)

采用**点积代价体**，支持标准版和快速版（FastCostVolumeManager）。

**标准版流程：**

```
1. 生成对数深度平面:
   linear_ramp = linspace(0, 1, D)
   log_planes = exp(log(min_depth) + log(max/min) * linear_ramp)
   → depth_planes (B, D, H_match, W_match)

2. 对每个深度平面 d:
   a. 反投影: world_pts = backproject(depth_plane_d, cur_invK)  # (B, 4, H*W)
   b. 投影到源视图: src_pts = project(world_pts, src_K, src_extrinsic)
   c. 双线性采样: warped_feat = grid_sample(src_feat, src_pts)
   d. 点积匹配: dp = sum(warped_feat * cur_feat, dim=C) * mask
   e. 多视图平均: cost[d] = mean(dp, dim=views)

3. 拼接: cost_volume (B, D, H_match, W_match)
```

**快速版 (FastCostVolumeManager)：**

使用 `einops` 进行批量化操作，将所有深度平面合并为一个大 batch 一次性处理，避免 Python 循环：

```python
# 所有深度平面一次性反投影
depth_plane_B1hw = rearrange(depth_planes, "b k h w -> (b k) 1 h w")
world_points = backproject(depth_plane_B1hw, repeat(cur_invK, k=D))

# 一次性投影到所有源视图
world_points = repeat(world_points, r=num_src_frames)
cam_points = project(world_points, repeat(src_K, k=D), repeat(src_ext, k=D))

# 一次性采样
src_feats_Bfhw = repeat(src_feats, k=D)
warped = grid_sample(src_feats_Bfhw, uv_coords)

# 批量点积
dot_product = sum(warped * cur_feats, dim=feat_ch) * mask
cost_volume = dot_product.mean(dim=views)
```

#### 2.9.3 深度解码器 (DepthDecoderPP)

采用 **PP-Net（Plus-Plus）** 密集连接解码器架构：

```
编码器特征: [feat_0, feat_1, feat_2, feat_3, feat_4]  (5个尺度)
解码器通道: [64, 64, 128, 256]

解码器采用网格状连接:
  对 j=1..4 (解码器深度, 从左到右):
    对 i=max_i..0 (编码器深度, 从上到下):
      inputs = [
        right_conv(prev[i]),           # 水平连接
        upsample(diag_conv(prev[i+1])),# 对角线连接
        upsample(up_conv(outputs[-1])) # 垂直连接 (如果存在)
      ]
      output = in_conv(concat(inputs))

每个尺度输出:
  log_depth_pred_s{i}_b1hw = output_conv(output)  # (B, 1, H/2^i, W/2^i)
```

#### 2.9.4 MVSA_Wrapped 推理封装

`MVSA_Wrapped` 类将 MVS-Anywhere 模型封装为标准化接口：

```python
# 输入适配
input_adapter(images, keyview_idx, poses, intrinsics, depth_range)
  → 图像归一化 (ImageNet mean/std)
  → 位姿求逆 (world_T_cam → cam_T_world)
  → 内参缩放至 1/4 分辨率
  → 构建 4×4 内参矩阵

# 前向推理
forward(images, intrinsics, poses, min_depth, max_depth, keyview_idx)
  → 分离参考/源视图
  → 构建 cur_data / src_data 字典
  → 调用 model(phase="test", ...)
  → 返回 depth_pred_s0_b1hw
```

---

## 3. 训练流程

### 3.1 数据准备

#### 3.1.1 数据预处理 (generate_data.py)

`utils/generate_data.py` 中的 `prepare_workspace()` 函数负责将原始采集数据转换为 MVSNet 可用格式：

```
1. 创建符号链接:
   - image/ → images_vision/
   - seg_mask/ → segs_vision/
   - seg_mask_static/ → segs_vision_static/
   - calib.json, LocalPoseTopic.json, metadata.json

2. 位姿质量验证:
   - 计算 local_pose 与 smooth_pose 的对齐残差
   - 使用 Umeyama 对齐算法 (traj_alignment)
   - 过滤条件: residual.max() < 20.0 且 residual.mean() < 5.0

3. 帧采样:
   - 基于距离阈值 (slice_distance_diff_threshold)
   - 基于角度阈值 (slice_angle_diff_threshold)

4. 标定验证:
   - 检查标定角度偏差 < max_angle_diff_thr (默认 5°)
   - 检查多层停车场场景 (z_gap > 2.0m 则过滤)

5. 输出:
   - 合并后的 calib.json (含 local_pose, global_pose, intrinsic, extrinsic)
   - image_timestamps.json
   - image_slice_ids.json
   - input_trips.json
```

#### 3.1.2 数据集 (BaseMVSDataset)

`BaseMVSDataset` 是所有数据集的基类，支持多种数据源：

| 数据集 | 处理器类 | 说明 |
|--------|----------|------|
| DDAD | DDADProcessor | DDAD 自动驾驶数据集 |
| BlendedMVS | BlendedMVSProcessor | 合成+真实混合数据集 |
| Waymo | WaymoProcessor | Waymo 开放数据集 |
| KITTI | KITTIProcessor | KITTI 数据集 |
| xp_data_colmap | XPColmapProcessor | 小鹏 COLMAP 重建数据 |
| xp_data_lidar | XPLidarProcessor | 小鹏 LiDAR 深度数据 |

**数据加载流程：**

```python
__getitem__(idx):
  1. parser_meta_info(idx)  # 解析元数据: dataset_name, trip_json, ref_view, src_views
  2. 随机打乱源视图顺序 (训练时)
  3. 对每个视图:
     a. 加载图像 → image_seg (归一化后的张量)
     b. 加载深度图 → depth_ms (多尺度金字塔)
     c. 加载语义掩码 → mask_ms (多尺度)
     d. 计算投影矩阵 → proj_mat (3, 4, 4): [extrinsic, intrinsic, inv(K@E)]
  4. 生成深度假设范围:
     - 训练: 从 GT 深度的百分位数确定 [min_depth, max_depth]
     - 测试: 使用预设的相机特定深度范围
  5. 构建多尺度投影矩阵:
     stage1: intrinsic /= 4
     stage2: intrinsic /= 2
     stage3: intrinsic 原始
```

**输出数据字典：**

```python
{
  "imgs":           (V, C_seg, H, W),      # 分割后的图像特征
  "center_imgs":    (V, 3, H, W),          # 中心裁剪归一化图像
  "proj_matrices":  {                       # 多尺度投影矩阵
    "stage1": (V, 3, 4, 4),  # 1/4 分辨率
    "stage2": (V, 3, 4, 4),  # 1/2 分辨率
    "stage3": (V, 3, 4, 4),  # 全分辨率
  },
  "depth":          {"stage1"/"stage2"/"stage3": (H_s, W_s)},
  "mask":           {"stage1"/"stage2"/"stage3": (H_s, W_s)},
  "depth_values":   (D,),                  # 深度假设采样点
  "filenames":      [str, ...],            # 文件路径
  # 时序模式额外字段:
  "depth_history":       [depth_ms_ref, depth_ms_src1, depth_ms_src2],
  "depth_values_history": [dv_ref, dv_src1, dv_src2],
}
```

### 3.2 损失函数

`MVSLoss` 是一个组合损失，根据配置动态组装多个子损失：

```python
MVSLoss
├── SupDepthMultiStageLoss      # 必选: 监督深度损失
├── DepthTemporalConsistencyLoss # 可选: 时序深度一致性
├── SupNormalMultiStageLoss      # 可选: 监督法线损失
├── UnsupLossMultiStage_l05      # 可选: 无监督光度损失
└── DDSLoss                      # 可选: 深度分布相似性损失
```

#### 3.2.1 监督深度损失 (SupDepthMultiStageLoss)

对每个阶段计算 Smooth L1 Loss：

```python
for stage_idx in range(num_stage):
    depth_pred = stage_outputs['depth']           # (B, H_s, W_s)
    depth_gt = data['depth'][stage_key]           # (B, H_s, W_s)

    # 掩码: GT > 0 且在深度范围内 且语义有效
    mask = (depth_gt > 0) & (depth_gt > min_depth) & (depth_gt < max_depth)
    if use_semantic_mask:
        mask &= binary_mask

    loss += dlossw[stage_idx] * smooth_l1(pred[mask], gt[mask])

total_loss = loss * w_sup_depth
```

#### 3.2.2 时序深度一致性损失 (DepthTemporalConsistencyLoss)

通过反向投影验证相邻帧深度的一致性：

```
对每个源视图:
  1. 计算参考→源的相对位姿
  2. 使用深度反向投影参考像素到源视图
  3. 计算光度损失: |I_ref - warp(I_src)|
  4. 计算几何损失: |d_computed - d_projected| / (d_computed + d_projected)
  5. 自动掩码: 排除静态区域 (diff_color < identity_warp_err)
  6. SSIM 损失 (可选)

total = photo_loss + 0.1 * geometry_loss
```

#### 3.2.3 无监督光度损失 (UnsupLossMultiStage_l05)

使用 L0.5 范数的光度重建损失：

```python
# 对每个源视图:
warped_img, mask = inverse_warping(src_img, ref_cam, src_cam, depth)
reconstr_loss = smooth_l0_5(warped * mask, ref * mask)  # L0.5 范数

# 多视图最小化选择
reprojection_volume = stack(all_losses)
top_vals = topk(-reprojection_volume, k=1)  # 选最佳匹配

# 组合损失
unsup_loss = w_recon * reconstr_loss + 6 * ssim_loss + 0.18 * smooth_loss
```

#### 3.2.4 深度分布相似性损失 (DDSLoss)

基于 KL 散度的深度分布匹配：

```python
# 将深度范围分为 M=48 个 bin
bins = linspace(kl_min, kl_max, M)

# 对每个 bin 计算 KL 散度
for bin in bins:
    bin_mask = (depth_gt >= bin_low) & (depth_gt < bin_high)
    kl_div = q * (log(q) - log(p))  # q=GT分布, p=预测分布

dds_loss = sum(kl_divs)
```

#### 3.2.5 MVS-Anywhere 损失函数

MVS-Anywhere 使用不同的损失组合：

| 损失 | 类 | 说明 |
|------|-----|------|
| Scale-Invariant Loss | `ScaleInvariantLoss` | `sqrt(mean(d²) - λ·mean(d)²)`, λ=0.85 |
| Multi-Scale Gradient | `MSGradientLoss` | 多尺度逆深度梯度 L1 损失 |
| Normals Loss | `NormalsLoss` | `0.5 * (1 - dot(pred, gt))` 余弦距离 |
| MV Depth Loss | `MVDepthLoss` | 多视图深度一致性，log 空间 L1 |

### 3.3 训练配置

**优化器与调度器：**

```yaml
optimizer: AdamW
lr: <configurable>
weight_decay: <wd>
scheduler: "cosinelr" 或 "steplr"
warmup: <warmup_epochs>  # 线性预热
```

调度器实现：
- **StepLR**: 预热 → 阶梯衰减 `lr * decay^(milestones <= step).sum()`
- **CosineLR**: 预热 → 余弦退火 `min_lr + 0.5*(max_lr-min_lr)*(1+cos(π*t/T))`

**混合精度与梯度：**

```yaml
use_amp: true          # 自动混合精度 (FP16)
clip_grad: true        # 梯度裁剪 max_norm=10
accum_grad: true       # 梯度累积
accum_iter: <N>        # 累积步数
```

**训练命令：**

```bash
# 入口
python -m mvsnet.clmvsnet.main --config config/train.yaml

# 分布式训练
torchrun --nproc_per_node=N -m mvsnet.clmvsnet.main --config config/train.yaml
```

### 3.4 训练循环

```python
for epoch in range(start_epoch, total_epochs):
    train_sampler.set_epoch(epoch)  # 分布式 shuffle

    for batch, data in enumerate(train_loader):
        data = tocuda(data)

        # 前向 (可选数据增强)
        if use_data_augmentation:
            outputs, data = network(data, "train", epoch)
        else:
            outputs = network(data, "train", epoch)

        # 损失计算
        total_loss, losses = loss_func(data, outputs, epoch)

        # 梯度累积 + AMP
        if accum_grad:
            total_loss /= accum_iter
        scaler.scale(total_loss).backward()

        if (batch+1) % accum_iter == 0:
            clip_grad_norm_(network.parameters(), max_norm=10)
            scaler.step(optimizer)
            lr_scheduler.step(epoch + batch/len(loader))
            scaler.update()

    # 保存检查点
    save_checkpoint(epoch, model, optimizer, lr_scheduler)

    # 定期验证
    if epoch % eval_freq == 0:
        validate(epoch)
```

**评估指标：**

| 指标 | 计算方式 | 说明 |
|------|----------|------|
| AbsDepthError | `mean(|pred - gt|)` | 绝对深度误差 |
| Thres@2mm | `mean(|pred-gt| < 0.2)` | 2mm 阈值准确率 |
| Thres@4mm | `mean(|pred-gt| < 0.4)` | 4mm 阈值准确率 |
| Thres@8mm | `mean(|pred-gt| < 0.8)` | 8mm 阈值准确率 |

---

## 4. 推理与渲染

### 4.1 推理流程 (CL-MVSNet)

```
test():
  1. 加载模型权重, 设置 eval 模式
  2. 启动异步保存线程 (save_data thread)
  3. 遍历 TestImgLoader:
     a. data_cuda = tocuda(data)
     b. outputs = network(data_cuda, "test")
     c. outputs = tensor2cupy(outputs)  # 转为 CuPy 加速后续 IO
     d. 将 (data, outputs) 放入 data_cache 队列
     e. 控制队列大小 ≤ mvsnet_data_cache_size
  4. 等待保存线程完成
  5. 执行后处理 (postprocess)
```

**异步保存机制：**

```python
# 生产者 (推理线程)
data_cache.append((data, outputs))
while len(data_cache) > cache_size:
    sleep(0.01)  # 背压控制

# 消费者 (保存线程)
while event.is_set() or len(data_cache) > 0:
    data, outputs = data_cache.pop()
    save_depth_maps_and_confidence_maps_cuda(args, filenames, cams, img, outputs)
```

### 4.2 后处理流程 (postprocess)

后处理将单帧深度图融合为稠密点云，包含三个阶段：

#### 4.2.1 深度图过滤

对每个参考视图应用多重过滤：

```
1. 置信度过滤:
   confidence = read_pfm("confidence/{:08d}.pfm")
   photo_mask = confidence > conf_threshold

2. 深度范围过滤:
   depth_mask = (depth > min_depth+1) & (depth < max_depth-5)

3. 几何一致性过滤:
   对每个源视图:
     a. 将参考像素投影到源视图
     b. 在源视图深度图中采样
     c. 反投影回参考视图
     d. 检查重投影误差:
        - 像素距离 < img_dist_thres
        - 相对深度差 < depth_thres
     e. 累加几何一致性计数
   geometric_mask = count >= thres_view

4. 语义掩码过滤:
   seg_mask = read_semantic_mask(seg_path)
   # 过滤: 天空(0-1), 车辆(19-22), 动态物体(≥52), 特定类别(27)
   # 膨胀处理: kernel=(10,10), iterations=2

5. 最终掩码:
   final_mask = photo_mask & depth_mask & geometric_mask & seg_mask
```

#### 4.2.2 点云生成

```python
# 反投影到 3D
x, y, depth = meshgrid[final_mask]
xyz_ref = inv(intrinsic) @ [x, y, 1] * depth     # 相机坐标系
xyz_world = inv(extrinsic) @ [xyz_ref; 1]          # 世界坐标系

# 可选: 高度过滤 (remove_elevated_point)
xyz_ego = inv(cam_extrinsic) @ xyz_world
filter = (z > max_height) | (z < min_height)

# 输出结构化数组
points_xyzrgbs = {
    'xyz':      (N, 3) float64,
    'color':    (N, 3) uint8,
    'semantic': (N,)   uint8,
    'cam_id':   (N,)   uint8,    # debug 模式
    'image_id': (N,)   int32,    # debug 模式
    'depth':    (N,)   float32,  # debug 模式
}
```

#### 4.2.3 点云融合与保存

```
1. 并行处理所有视图 (joblib Parallel, backend='multiprocessing')
2. 按相机分组聚合点云
3. 保存单相机 PLY: {cam_id}.ply
4. 合并所有相机: mvsnet_l3.ply
5. 点云过滤 (filter_pointcloud): 统计离群点移除
```

### 4.3 MVS-Anywhere 推理

MVS-Anywhere 通过 `MVSA_Wrapped` 类提供标准化推理接口：

```python
# 输入
images:     List[(B, 3, H, W)]     # 多视图图像
intrinsics: List[(B, 3, 3)]        # 内参
poses:      List[(B, 4, 4)]        # 位姿 (world_T_cam)
depth_range: (min_depth, max_depth) # 可选

# 处理流程
1. ImageNet 归一化: mean=[0.485,0.456,0.406], std=[0.229,0.224,0.225]
2. 内参缩放至 1/4 分辨率
3. 位姿求逆: cam_T_world = inv(world_T_cam)
4. 模型推理: model(phase="test", cur_data, src_data)
5. 输出: depth_pred_s0_b1hw (B, 1, H/4, W/4)
```

### 4.4 与 SimWorld 的集成

MVSNet 的输出点云（PLY 格式）作为下游 3DGS（3D Gaussian Splatting）训练的初始化输入：

```
MVSNet 输出:
  ├── depth_est/{:08d}.pfm      # 深度图
  ├── confidence/{:08d}.pfm     # 置信度图
  ├── depth/{:08d}.png          # 可视化深度图 (uint16)
  ├── cams/{:08d}_cam.txt       # 相机参数
  ├── {cam_id}.ply              # 单相机点云
  ├── mvsnet_l3.ply             # 融合点云
  └── final.ply                 # 过滤后最终点云
```

---

## 5. 工程优化

### 5.1 内存优化

| 技术 | 实现位置 | 效果 |
|------|----------|------|
| **Group-wise Correlation** | `GroupWiseAgg` | 将 C 通道分为 G 组，代价体从 `(B,C,D,H,W)` 降为 `(B,G,D,H,W)`，内存降低 C/G 倍 |
| **级联深度假设** | `InitSampler`/`UniformSampler` | 粗阶段少量假设覆盖全范围，细阶段在局部范围密集采样 |
| **混合精度训练** | `autocast(dtype=torch.float16)` | FP16 前向传播，FP32 损失计算和梯度更新 |
| **梯度累积** | `accum_grad` | 小 batch 模拟大 batch，降低显存峰值 |
| **及时释放** | `del warped_volume` | 循环内及时释放中间变量 |

### 5.2 速度优化

| 技术 | 实现位置 | 效果 |
|------|----------|------|
| **CuPy 加速** | `tensor2cupy_str` | 推理输出直接转为 CuPy 数组，避免 GPU→CPU 拷贝 |
| **异步 IO** | `save_data` 线程 | 推理与磁盘写入并行，通过 deque 队列解耦 |
| **并行后处理** | `joblib Parallel` | 多进程并行过滤深度图和保存点云 |
| **torch.compile** | `use_torch_compile` | 可选的图编译优化，支持 `reduce-overhead` 等模式 |
| **FastCostVolume** | `FastCostVolumeManager` | einops 批量化，消除 Python 深度平面循环 |
| **SyncBatchNorm** | 分布式训练 | 跨 GPU 同步 BN 统计量 |

### 5.3 训练稳定性

| 技术 | 说明 |
|------|------|
| **GradScaler** | AMP 下的梯度缩放，防止 FP16 下溢 |
| **梯度裁剪** | `clip_grad_norm_(max_norm=10)` |
| **NaN 保护** | `loss.nan_to_num(nan=0.0)` 防止 NaN 传播 |
| **除零保护** | `homo_warping` 中 `temp[temp==0] = 1e-9` |
| **数据异常重采样** | `__getitem__` 异常时返回 `self.__getitem__(idx+1)` |

### 5.4 CUDA 后处理优化

`postprocess_cuda.py` 提供了 GPU 加速版本的后处理流程，利用 CuPy 在 GPU 上直接进行：
- 深度图读取和过滤
- 几何一致性检查
- 点云反投影计算
- 避免大量 GPU↔CPU 数据传输

---

## 6. 目录结构速查

```
mvsnet/
├── clmvsnet/                          # CL-MVSNet 主实现
│   ├── main.py                        # 训练入口
│   ├── model.py                       # Model 类 (训练/验证/测试调度)
│   ├── loss.py                        # 损失函数集合
│   ├── tool.py                        # 工具函数 (分布式、指标、可视化)
│   ├── networks/
│   │   ├── clmvsnet.py                # CLMVSNet/CasMVSNet 网络定义
│   │   ├── module.py                  # 基础模块 (Conv2d/3d, homo_warping等)
│   │   └── augmenter.py               # 数据增强
│   ├── dataset/
│   │   ├── base_dataset.py            # BaseMVSDataset 基类
│   │   ├── loader.py                  # DataLoader 工厂
│   │   ├── data_io.py                 # CPU 数据 IO
│   │   ├── data_io_cuda.py            # GPU 加速数据 IO
│   │   ├── xpdata_*.py               # 各数据集实现
│   │   └── waymo/kitti/ddad/blendedmvs_dataset.py
│   ├── postprocess/
│   │   ├── postprocess.py             # CPU 后处理 (深度过滤→点云融合)
│   │   ├── postprocess_cuda.py        # GPU 加速后处理
│   │   └── pointcloud_filter.py       # 点云统计过滤
│   ├── preprocess/
│   │   ├── preprocessor.py            # 数据预处理器 (各数据集)
│   │   └── generate_*.py             # Trip/训练数据生成脚本
│   ├── config/
│   │   ├── parser.py                  # YAML 配置解析
│   │   ├── train.yaml                 # 训练配置
│   │   ├── test.yaml                  # 测试配置
│   │   ├── recon.yaml                 # 重建配置
│   │   └── vehicle.yaml               # 车辆标定配置
│   └── utilities/
│       ├── eval_helper.py             # 点云评估工具
│       ├── visualize_depth.py         # 深度可视化
│       ├── colmap2mvsnet.py           # COLMAP 格式转换
│       └── compute_normal.py          # 法线计算
│
├── mvsa/                              # MVS-Anywhere 实现
│   ├── src/mvsanywhere/
│   │   ├── modules/
│   │   │   ├── networks.py            # 编码器/解码器网络
│   │   │   ├── cost_volume.py         # 代价体 (标准/快速)
│   │   │   └── layers.py              # 基础层
│   │   ├── losses.py                  # 损失函数
│   │   ├── experiment_modules/
│   │   │   └── rmvd_mvsa.py           # MVSA 推理封装
│   │   └── utils/
│   │       ├── geometry_utils.py      # 几何工具 (反投影/投影)
│   │       ├── generic_utils.py       # 通用工具
│   │       └── model_utils.py         # 模型加载工具
│   ├── configs/                       # 配置文件
│   ├── scripts/                       # 评估/预处理脚本
│   └── eval.py                        # 评估入口
│
└── utils/
    └── generate_data.py               # 数据工作空间准备
```

---

## 7. 参考资料

### 7.1 论文基础

| 方法 | 论文 | 核心贡献 |
|------|------|----------|
| MVSNet | Yao et al., ECCV 2018 | 可微分单应性变形 + 3D CNN 正则化 |
| Cascade MVSNet | Gu et al., CVPR 2020 | 级联代价体，由粗到细深度估计 |
| CL-MVSNet | 本项目实现 | Group-wise 相关性 + 法线回归 + 时序一致性 |
| MVS-Anywhere | 本项目集成 | 泛化性 MVS，PP-Decoder + 自动深度范围估计 |

### 7.2 关键技术点

- **可微分单应性变形 (Differentiable Homography Warping)**：`homo_warping()` 函数，通过深度假设将源视图特征变形到参考视图坐标系
- **Group-wise Correlation**：将特征通道分组计算相关性，平衡精度与内存
- **Soft Argmin 深度回归**：`depth_regression()` 使用 softmax 概率加权求和，可微分且亚像素精度
- **几何一致性检查**：`check_geometric_consistency()` 通过双向重投影验证深度估计的多视图一致性
- **对数深度采样**：MVS-Anywhere 使用对数空间均匀采样深度平面，近处密集远处稀疏

### 7.3 配置文件说明

| 配置文件 | 用途 |
|----------|------|
| `config/train.yaml` | 完整训练配置（数据集、超参数、损失权重） |
| `config/test.yaml` | 测试推理配置 |
| `config/recon.yaml` | 三维重建流水线配置 |
| `config/ips.yaml` | IPS 生产部署配置 |
| `config/vehicle.yaml` | 车辆标定参数 |
