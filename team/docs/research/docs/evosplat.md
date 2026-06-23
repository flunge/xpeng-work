# EvoSplat 技术分析文档

## 1. 概述

EvoSplat（`nail_evolsplat`）是一个前馈式（feed-forward）3D Gaussian Splatting 模型，用于从多视角图像重建三维场景。与传统的 per-scene 优化方法不同，EvoSplat 通过神经网络直接预测 3D Gaussian 的属性（位置、颜色、尺度、旋转、不透明度），实现快速的新视角合成。

核心特点：
- 基于稀疏卷积（Sparse Convolution）构建 3D 特征体积，提取几何先验
- 通过多视角图像投影采样 2D 特征，结合遮挡感知（Occlusion-Aware）机制
- 使用三线性插值从 3D 特征体积中查询逐点特征
- 多个 MLP 头分别预测 SH 颜色系数、尺度/旋转、不透明度和位置偏移
- 使用 gsplat 库进行可微光栅化渲染
- 推理时逐帧累积 Gaussian 属性，最终导出 PLY 点云

## 2. 模型结构

### 2.1 整体架构 (`model/model.py` - `EvolSplatModel`)

模型继承自 `nn.Module`，核心组件包括：

| 组件 | 类 | 输入维度 | 输出维度 | 功能 |
|------|-----|---------|---------|------|
| `sparse_conv` | `SparseCostRegNet` | 3 (RGB) | 16 | 稀疏 3D 卷积，提取体素级 3D 特征 |
| `gaussion_decoder` | `MLP` | feature_dim_in + 4 | 3 × num_sh_bases(1) = 12 | 预测 SH 颜色系数 |
| `mlp_conv` | `MLP` | 16 + 4 | 3 + 4 = 7 | 预测尺度(3) + 四元数旋转(4) |
| `mlp_opacity` | `MLP` | 16 + 4 | 1 | 预测不透明度 |
| `mlp_offset` | `MLP` | 16 | 3 | 预测位置偏移（输出经 Tanh 限制在 ±offset_max） |
| `projector` | `Projector` | - | - | 多视角投影采样 |

关键超参数：
- `voxel_size = 0.1`：体素化分辨率
- `local_radius = 1`：投影采样窗口半径，窗口大小 (2×1+1)² = 9
- `num_neibours = 3`：源视角数量
- `offset_max = 0.1`：位置偏移最大值
- `sh_degree = 1`：球谐函数阶数
- `bbx_min/max`：场景包围盒 [-16,-9,-20] ~ [16,3.8,60]
- `feature_dim_in = 4 × 3 × (2×1+1)² = 108`：2D 采样特征维度（4通道 × 3视角 × 9像素窗口）

### 2.2 前向传播流程 (`get_outputs`)

```
输入: camera, batch (含 source images, extrinsics, intrinsics, depth, target image)
  │
  ├─ 1. 构建稀疏张量 → SparseCostRegNet → dense_volume  [3D 特征体积]
  │     construct_sparse_tensor() → sparse_conv() → sparse_to_dense_volume()
  │
  ├─ 2. 多视角投影采样 2D 特征（带遮挡感知）
  │     projector.sample_within_window() → sampled_feat [N, V, W², 3]
  │
  ├─ 3. 计算投影掩码（前景 + 边界内 + 非黑色区域 + 有效采样）
  │
  ├─ 4. 三线性插值查询 3D 特征
  │     get_grid_coords() → interpolate_features() → feat_3d [N_valid, 16]
  │
  ├─ 5. 拼接观察方向和距离
  │     ob_view = normalize(means - cam_pos), ob_dist = ||means - cam_pos||
  │
  ├─ 6. MLP 预测 Gaussian 属性
  │     ├─ gaussion_decoder(sampled_2d + ob_dist + ob_view) → SH 系数
  │     ├─ mlp_conv(feat_3d + ob_dist + ob_view) → scales + quats
  │     ├─ mlp_opacity(feat_3d + ob_dist + ob_view) → opacity
  │     └─ mlp_offset(feat_3d) → position offset
  │
  ├─ 7. 距离自适应尺度裁剪
  │     near: max=0.06, mid: max=0.1, far: max=0.2
  │
  └─ 8. gsplat 光栅化渲染
        rasterization(means, quats, scales, opacities, colors, ...) → RGB + Depth
```

### 2.3 稀疏卷积模块 (`model/sparse_conv.py`)

#### SparseCostRegNet

基于 `torchsparse` 的 U-Net 结构稀疏 3D 卷积网络：

```
编码器:
  conv0 (d_in→d_out) → conv1 (d_out→16, stride=2) → conv2 (16→16)
  → conv3 (16→32, stride=2) → conv4 (32→32)
  → conv5 (32→64, stride=2) → conv6 (64→64)

解码器（带跳跃连接）:
  conv7 (64→32, deconv stride=2) + conv4 残差
  → conv9 (32→16, deconv stride=2) + conv2 残差
  → conv11 (16→d_out, deconv stride=2) + conv0 残差
```

输出为稀疏特征 `.F`（仅有效体素的特征向量）。

#### construct_sparse_tensor

将原始 3D 点坐标体素化：
1. 坐标减去包围盒最小值，归一化到正坐标系
2. `sparse_quantize` 按 `voxel_size=0.1` 离散化
3. 构建 `SparseTensor(feats, coords)` 格式（coords 含 batch 维度）

#### sparse_to_dense_volume

将稀疏特征填充到稠密体积张量 `[H, W, D, C]`，未占用体素填充默认值 0。

### 2.4 投影模块 (`model/projection.py` - `Projector`)

核心方法：

- `compute_projections(xyz, cameras, intrinsics)`：将 3D 点投影到各视角图像平面，返回像素坐标、前景掩码和投影深度
- `sample_within_window(xyz, train_imgs, ...)`：在投影位置周围 `[-R, R]` 窗口内采样 RGB 特征
  - 遮挡感知：利用源视角深度图，比较投影深度与采样深度，剔除被遮挡区域（阈值 ±10）
  - 返回 `[N, V, W², 3]` 的采样特征和可见性掩码

### 2.5 MLP 模块 (`model/mlp.py`)

通用多层感知机，支持：
- 可配置层数、宽度、激活函数
- 跳跃连接（skip connections）
- 支持 `torch` 和 `tcnn` 两种实现（当前仅用 torch）

### 2.6 Embedding 模块 (`model/embedding.py`)

标准 `nn.Embedding` 封装，用于外观嵌入（appearance embedding），当前默认关闭（`enabale_appearance_embedding = False`）。

### 2.7 基类 (`model/base_field_component.py`)

`FieldComponent` 是所有场组件的抽象基类，定义了 `in_dim`、`out_dim` 和抽象 `forward` 方法。

## 3. 训练流程

### 3.1 训练器 (`train/trainer.py` - `Trainer`)

训练采用场景级迭代策略：

```
for iteration in range(num_iterations):
    # 1. 评估阶段
    for eval_scene in eval_scenes:
        下载数据 → 初始化 DataManager → 推理所有帧 → 计算指标 → 保存

    # 2. 训练阶段
    for scene_id in scenes:
        下载数据 → 初始化 DataManager → 获取种子点
        for frame_idx in range(data_length):
            zero_grad → forward → compute_loss → backward → step → scheduler
```

每个场景独立初始化种子点（`set_datas_init`），训练完一个场景后可选删除数据。

### 3.2 损失函数

| 损失 | 公式 | 权重 |
|------|------|------|
| L1 损失 | `\|gt - pred\|.mean()` | `1 - ssim_lambda = 0.2` |
| SSIM 损失 | `1 - SSIM(gt, pred)` | `ssim_lambda = 0.8` |
| 熵正则化 | `-α·log(α) - (1-α)·log(1-α)` | `weight_entropy_loss = 0.1`，每 10 步计算一次 |

总损失：`loss = (1 - 0.8) × L1 + 0.8 × SSIM_loss + 0.1 × entropy_loss`

特殊处理：预测为黑色（0）的区域，GT 也被置为 0，避免对无效区域计算损失。

### 3.3 优化器配置 (`train/config.py`, `train/optimizers.py`)

所有参数组使用 Adam 优化器 + 指数衰减学习率调度器（带余弦预热）：

| 参数组 | 初始 LR | 最终 LR | 最大步数 | 预热步数 |
|--------|---------|---------|---------|---------|
| sparse_conv | 1e-3 | 5e-7 | 30000 | 500 |
| mlp_conv | 可配置 (默认 1e-4) | 1e-4 | 30000 | 0 |
| mlp_opacity | 1e-3 | 1e-4 | 30000 | 0 |
| mlp_offset | 1e-3 | 1e-4 | 30000 | 0 |
| gaussianDecoder | 1e-3 | 1e-4 | 30000 | 0 |

调度器公式：`lr = exp(log(lr_init)×(1-t) + log(lr_final)×t)`，其中 `t = clip((step - warmup) / (max - warmup), 0, 1)`。

使用 `GradScaler`（默认 disabled）进行混合精度训练。

### 3.4 评估指标

- PSNR（Peak Signal-to-Noise Ratio）
- SSIM（Structural Similarity Index）
- 按相机类型分别统计

## 4. 推理流程

### 4.1 推理入口 (`infer_evolsplat.py`)

```python
# 1. 加载模型
model = load_model(ckpt_path, train_mode=False)

# 2. 初始化数据
data_manager = Datamanager(case_id, root_data_folder, output_folder)
seed_points = data_manager.get_seed_points()
model.set_datas_init(data_length, seed_points, output_folder)

# 3. 预计算 3D 特征体积（冻结后不再更新）
model.init_volume()  # sparse_conv → dense_volume → mlp_offset → 初始偏移

# 4. 逐帧推理，累积 Gaussian 属性
for idx in range(data_length):
    camera, batch = data_manager.get_next_data(idx)
    model.get_outputs(camera, batch)
    # 内部根据相机类型和深度进行可见性筛选
    # 累积到 scene_gaussians 字典

# 5. 最后一帧处理完后自动保存 PLY
#    evolsplat_init.ply (原始格式) + evolsplat_vis.ply (可视化格式)
```

### 4.2 推理时的特殊逻辑

- `init_volume()`：预计算并冻结 3D 特征体积和初始位置偏移，避免重复计算
- 按相机类型（cam2/cam5/cam6）设置不同的深度过滤范围
- 使用 "首次可见 + 更近深度优先" 策略累积 Gaussian 属性
- 最终输出两种 PLY 格式：
  - `evolsplat_init.ply`：含 position, normal, scale, opacity, color, quaternion
  - `evolsplat_vis.ply`：含 SH 系数，兼容标准 3DGS 查看器

## 5. 数据处理

### 5.1 Dataset (`dataset.py`)

负责从磁盘加载和预处理单个场景的数据：

**输入数据结构：**
```
{case_id}/
├── calib.json                    # 相机标定参数
├── transform.json                # 各帧各相机的位姿 (c2w)
├── timestamp2slice.json          # 时间戳到帧索引映射
├── images_vision/                # 原始图像 (slice{idx}_{cam}.png)
├── segs_vision/                  # 语义分割图
├── segs_vision_static/           # 静态物体分割 (.npy)
├── input_ply/points3D_bkgd.ply   # 背景点云
├── ground_mask.npy               # 地面掩码
├── misc/mvsnet/
│   ├── mvsnet_depth_est/         # MVS 深度估计 (.pfm)
│   └── mvsnet_image_timestamps.json
└── colmap/                       # COLMAP 稀疏重建（可选）
```

**点云处理流程：**
1. 加载背景点云，去除地面点
2. 多相机并行处理（ThreadPoolExecutor）：
   - 按采样间隔选取关键帧
   - 从深度图反投影生成单目增强点云（距离自适应体素降采样）
   - 语义分割过滤（去除天空、地面、车辆、行人等动态物体）
3. 合并点云：单目增强点 + 背景 MVS 点 + COLMAP 点（可选）
4. 基于轨迹距离的自适应降采样：
   - 近距离（≤10m）：voxel_size = 0.03
   - 远距离（≥15m）：voxel_size = 0.2
   - 中间距离：线性插值
5. 输出包含距离掩码（near_mask, mid_mask, far_mask）

**相机配置：**
- 使用 cam2（前视）、cam5（左后）、cam6（右后）三个相机
- 坐标系转换：`c2w[:3,:3] *= [1, -1, -1]`（OpenCV → OpenGL 约定）

### 5.2 DataManager (`data_manager.py`)

封装 Dataset，提供训练/推理所需的批次数据：

- `get_seed_points()`：返回初始 3D 点云及距离掩码
- `get_data_length()`：返回总帧数
- `get_next_data(image_idx)`：构建单帧训练批次
  - 根据 image_idx 确定所属相机组
  - 选择 3 个最近源视角（`eval_source_images_from_current_imageid`）
  - 构建 batch 字典：source（images, extrinsics, intrinsics, depth）+ target（image, extrinsics, intrinsics）

## 6. 目录结构速查

```
nail_evolsplat/
├── model/
│   ├── model.py              # EvolSplatModel 主模型（前向传播、渲染、PLY 导出）
│   ├── sparse_conv.py        # SparseCostRegNet 稀疏 3D 卷积 + 体素化工具
│   ├── projection.py         # Projector 多视角投影采样（遮挡感知）
│   ├── mlp.py                # MLP 通用多层感知机
│   ├── embedding.py          # Embedding 外观嵌入
│   └── base_field_component.py  # FieldComponent 抽象基类
├── train/
│   ├── trainer.py            # Trainer 训练循环（含评估、TensorBoard 日志）
│   ├── config.py             # obtain_config() 训练配置
│   ├── optimizers.py         # Optimizers 管理器 + Adam + 指数衰减调度器
│   └── down_load_clip.py     # 数据下载工具
├── utils/
│   ├── cameras.py            # Cameras 数据类
│   ├── math.py               # inverse_sigmoid, construct_list_of_attributes, get_viewmat, num_sh_bases
│   ├── data.py               # read_depth_file, read_rgb_filename, eval_source_images_from_current_imageid
│   └── colmap.py             # read_points3D_binary
├── dataset.py                # Dataset 场景数据加载与点云预处理
├── data_manager.py           # Datamanager 批次数据构建
└── infer_evolsplat.py        # 推理入口脚本
```

## 7. 参考资料

- **3D Gaussian Splatting**: Kerbl et al., "3D Gaussian Splatting for Real-Time Radiance Field Rendering", SIGGRAPH 2023
- **gsplat**: 可微高斯光栅化库 (https://github.com/nerfstudio-project/gsplat)
- **torchsparse**: 高效稀疏卷积库 (https://github.com/mit-han-lab/torchsparse)
- **MVSNet**: 多视角立体匹配深度估计
- **COLMAP**: 基于 SfM 的稀疏重建
- **球谐函数 (SH)**: 用于视角相关颜色表示，本项目使用 1 阶 SH（4 个基函数）
