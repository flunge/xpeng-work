# ROME 模块技术分析文档

> ROME — Road Mesh Estimation，基于可微渲染的道路表面网格重建模块

---

## 1. 概述

ROME（Road Mesh Estimation）是位于 `/workspace/xpeng_data_process/ground_processing/rome/` 的道路表面三维重建模块。其核心思想是：在 BEV（鸟瞰图）空间中构建一张可优化的三角网格（mesh），通过 **nvdiffrast** 可微光栅化引擎将该网格投影到各相机视角，与真实图像的 RGB 和语义分割标签进行比较，反向传播梯度来联合优化网格的颜色纹理、语义标签、高度场以及相机外参。

### 1.1 核心技术路线

```
多趟采集数据 (multi-trip)
    │
    ▼
XNetDataset 加载图像 / 语义标签 / 深度 / 位姿
    │
    ▼
构建 BEV 平面三角网格 (Hive Mesh)，按车辆轨迹裁剪
    │
    ▼
可微渲染循环 (nvdiffrast):
    mesh → 投影到相机视角 → 与 GT 图像/语义比较 → 反向传播
    │
    ▼
输出: BEV RGB 图 / BEV 语义图 / BEV 深度图 / OBJ 网格文件
```

### 1.2 关键依赖

| 依赖库 | 用途 |
|--------|------|
| `nvdiffrast` | NVIDIA 可微光栅化引擎，核心渲染后端 |
| `pytorch3d` | Meshes 数据结构、TexturesVertex、Laplacian 平滑损失、相机模型 |
| `pytorch_lightning` | 训练框架，DDP 分布式训练 |
| `pymeshlab` | 网格裁剪与导出 |
| `scipy` | KDTree 空间查询、高斯滤波、Delaunay 三角化 |

### 1.3 支持的运行模式

| 模式 | 说明 |
|------|------|
| `recon` | 重建模式 — 从多趟采集数据重建道路网格（主流程） |
| `reloc` | 重定位模式 — 基于已有重建结果进行重定位评估 |

---

## 2. 模型结构

### 2.1 RomeNet — 顶层模块

`RomeNet`（继承 `LightningModule`）是整个 ROME 的顶层编排类，位于 `rome_net.py`。它不是传统意义上的神经网络，而是一个**优化框架**，将网格模型、位姿模型、渲染器和损失函数组合在一起。

```
RomeNet
├── grid: SquareFlatGrid*       # 可优化网格（多种变体）
├── extrinsics: ExtrinsicModel  # 相机外参优化模型
├── renderer: NvdiffRenderer    # nvdiffrast 可微渲染器
├── loss_fuction: L1MaskedLoss  # RGB 渲染损失
├── CE_loss_with_mask: CELossWithMask  # 语义分割交叉熵损失
├── depth_loss_fuction: L1MaskedLoss   # 深度监督损失
├── optimizer / z_optimizer / pose_optimizer  # 三组独立优化器
└── dataset: XNetDataset        # 数据集（内嵌于模型中）
```

**关键属性：**

- `automatic_optimization = False` — 手动控制三组优化器的 step/zero_grad
- `bev_render_params` — BEV 正交相机参数，用于 epoch 结束时渲染鸟瞰图
- `optim_dict` — 控制哪些参数参与优化的开关字典

**Grid 类型动态选择逻辑：**

`build_grid()` 根据配置中各学习率是否为 0 来决定使用哪种 Grid 变体：

| vertices_rgb | vertices_label | vertices_z | 选择的 Grid 类 |
|:---:|:---:|:---:|---|
| ✅ | ✅ | ❌ | `SquareFlatGridRGBLabel` |
| ✅ | ❌ | ✅ | `SquareFlatGridRGBZ` |
| ✅ | ❌ | ❌ | `SquareFlatGridRGB` |
| ❌ | ✅ | ❌ | `SquareFlatGridLabel` |
| ❌ | ✅ | ✅ | `SquareFlatGridLabelZ` |
| ✅ | ✅ | ✅ | `SquareFlatGridRGBLabelZ` |

### 2.2 VoxelModel（Grid）— 可优化网格模型

位于 `models/voxel.py`，是 ROME 的核心数据结构。所有 Grid 变体共享两个基类。

#### 2.2.1 SquareFlatGridBase（无高度优化的基类）

用于 **不优化 Z 坐标** 的场景。网格顶点的 Z 值在初始化后固定。

**初始化流程：**

```python
SquareFlatGridBase.__init__(bev_x_length, bev_y_length, pose_xy, resolution, cut_range, ...)
```

1. 调用 `createHiveFlatMesh()` 生成蜂巢状平面三角网格
   - 输入：BEV 区域尺寸（米）、分辨率（默认 0.1m）
   - 输出：`vertices (N, 3)` float32、`faces (M, 3)` int64
   - 蜂巢网格的 Y 方向分辨率 = `x_resolution * 2 / √3`，奇偶行交错排列
2. 调用 `cutHiveMeshWithPoses()` 按车辆轨迹裁剪网格
   - 将轨迹点映射到网格像素坐标
   - 构建二值 mask → 膨胀（kernel = cut_range/resolution）→ 删除 mask 外的面和孤立顶点
   - 使用 `pymeshlab` 执行面删除和顶点清理
3. 或者调用 `createMultiResolutionMesh()` 生成多分辨率网格
   - 车道线区域使用高分辨率（如 0.02m），其他区域使用低分辨率（如 0.1m）
   - 使用 Delaunay 三角化生成面

**关键 Buffer：**

| Buffer 名 | 形状 | 说明 |
|-----------|------|------|
| `vertices` | `(N, 3)` | 顶点 XYZ 坐标 |
| `faces` | `(M, 3)` | 三角面索引 |
| `norm_xy` | `(N, 2)` | 归一化到 `[-1, 1]` 的 XY 坐标 |

**可优化参数：**

| 参数名 | 形状 | 说明 |
|--------|------|------|
| `vertices_rgb` | `(1, N, 3)` | 顶点 RGB 颜色，通过 `tanh` 约束到 `[0, 1]` |
| `vertices_label` | `(1, N, C)` | 顶点语义 logits，通过 `softmax` 归一化（C=7 类） |

#### 2.2.2 SquareFlatGridBaseZ（带高度优化的基类）

用于 **优化 Z 坐标** 的场景。高度由 `HeightMLP` 网络预测。

**额外组件：**

- `mlp: HeightMLP` — 从归一化 XY 坐标预测高度偏移
- `prior_vertices_z: (N, 1)` — 高度先验（从车辆轨迹 Z 值插值 + 高斯平滑得到）
- `vertices_z: (N, 1)` — 当前高度值 buffer

**高度初始化流程 `init_vertices_z()`：**

1. 构建车辆轨迹点的 KDTree
2. 将顶点 XY 映射到热力图网格
3. 膨胀热力图 → 最近邻查询轨迹 Z 值 → 高斯平滑（sigma=10）
4. 结果存入 `prior_vertices_z` buffer

#### 2.2.3 HeightMLP — 高度预测网络

```
HeightMLP(num_encoding, num_width=128)
│
├── 位置编码: norm_xy (N, 2) → encoded (N, 2*(2L+1))
│   L = num_encoding, 使用 sin/cos 频率编码
│
├── height_layer_0: Linear(pos_channel, 128) → ReLU → ... (4层)
│   输出: (N, 128)
│
└── height_layer_1: Linear(128 + pos_channel, 128) → ReLU → ... → Linear(128, 1)
    跳跃连接: cat([feature, encoded_xy])
    输出: (N, 1) — 高度偏移值
```

**位置编码维度计算：**
- 输入 `norm_xy` 维度 = 2
- 编码后维度 = `2 * (2 * num_encoding + 1)`
- 例如 `num_encoding=5` 时：`pos_channel = 2 * (2*5+1) = 22`

#### 2.2.4 SquareFlatGridRGBLabelZ — 最完整的 Grid 变体

这是生产环境中最常用的变体，同时优化 RGB、语义标签和高度。

**forward() 数据流：**

```python
def forward(self, activated_idx=None, batch_size=1, is_init=False):
    # 1. RGB: tanh 约束到 [0, 1]
    constrained_vertices_rgb = (tanh(self.vertices_rgb) + 1) / 2   # (1, N, 3)

    # 2. 语义: softmax 归一化
    softmax_vertices_label = softmax(self.vertices_label, dim=-1)   # (1, N, C)

    # 3. 拼接特征
    features = cat(constrained_vertices_rgb, softmax_vertices_label) # (1, N, 3+C)

    # 4. 高度: MLP 预测偏移 + 先验
    vertices_z = tanh(self.mlp(self.norm_xy)) * z_scale + self.prior_vertices_z  # (N, 1)

    # 5. 组装顶点
    vertices = cat(self.vertices_xy, vertices_z)  # (N, 3)

    # 6. 构建 PyTorch3D Mesh
    texture = TexturesVertex(verts_features=features)
    mesh = Meshes(verts=[vertices], faces=[self.faces], textures=texture)
    return mesh.extend(batch_size)
```

**输出 Mesh 的纹理通道布局：** `[R, G, B, label_0, label_1, ..., label_C-1]`，共 `3 + C` 通道。

**`get_verts_features()` 输出：** `(N, 2 + 1 + 3 + C)` = `[xy, z, rgb, labels]`，用于保存中间结果。

### 2.3 PoseModel / ExtrinsicModel — 位姿优化

位于 `models/pose_model.py`，用于联合优化相机外参。

#### ExtrinsicModel（生产使用）

按**相机编号**（而非帧编号）优化外参偏移，修正标定误差。

```python
class ExtrinsicModel(nn.Module):
    # 参数:
    #   rotations:    (num_camera, 3) float64 — 轴角表示的旋转偏移
    #   translations: (num_camera, 3) float64 — 平移偏移
```

**forward() 数据流：**

```python
def forward(self, camera_idx):
    # camera_idx: (B,) — batch 中每个样本的相机索引
    rotations = self.rotations[camera_idx]       # (B, 3)
    translations = self.translations[camera_idx] # (B, 3)

    # 旋转: tanh 约束 → 缩放到 ±rotation_deg 度 → 轴角转旋转矩阵
    rots = axis_angle_to_matrix(rotation_deg/180*π * tanh(rotations))  # (B, 3, 3)

    # 平移: tanh 约束 → 缩放到 ±translation_m 米
    translations = translation_m * tanh(translations.unsqueeze(2))     # (B, 3, 1)

    # 组装 4x4 变换矩阵
    poses = convert3x4_4x4(cat(rots, translations))  # (B, 4, 4)
    return poses
```

**约束范围（由配置控制）：**
- 旋转：`±rotation_deg` 度（默认 0.5°）
- 平移：`±translation_m` 米（默认 0.5m）

**应用方式：** `world2camera = extrinsics(camera_idx) @ original_world2camera`

#### PoseModel（按帧优化，备用）

按**帧编号**优化，参数为 `(num_frame, 3)`，约束范围固定为旋转 ±1°、平移 ±0.2m。

### 2.4 NvdiffRenderer — 可微渲染器

位于 `utility/nvdiff_renderer.py`，封装 nvdiffrast 实现可微光栅化。

**forward() 完整数据流：**

```
输入 render_params:
  mesh:           PyTorch3D Meshes 对象
  world2camera:   (B, 4, 4) float64
  focal_length:   (B, 2) float64 — 归一化焦距 (fx/half_w, fy/half_h)
  principal_point: (B, 2) float64 — 归一化主点偏移
  image_shape:    (B, 2) — [H, W]
  camera_model:   "perspective" | "orthographic"

处理流程:
  1. 构建 world_to_view 矩阵（转置旋转、交换平移位置）
  2. 构建投影矩阵 proj_matrix (4x4)
     - perspective: 标准针孔投影
     - orthographic: 正交投影（用于 BEV 渲染）
  3. 顶点变换: verts_world → verts_view → verts_ndc
     verts_ndc = (verts_view @ proj_matrix)[..., :3] / [..3:]
  4. 有效性检测: |ndc_x| < 1 且 |ndc_y| < 1 且 z > znear(0.01)
  5. 调用 nvdiffrast 光栅化 + 插值

输出:
  image_features: (B, H, W, 3+C+1) — [RGB, labels, silhouette]
  image_depth:    (B, H, W, 1) — 深度图
```

**分块光栅化（Tile-based）：** 当图像尺寸超过 2048 像素时，自动分块渲染后拼接，避免 GPU 显存溢出。

**silhouette 通道：** 最后一个通道为轮廓 mask，face_idx >= 0 的像素为 1，其余为 0。

### 2.5 损失函数

位于 `models/loss.py`。

| 损失函数 | 类名 | 公式 | 用途 |
|----------|------|------|------|
| RGB 渲染损失 | `L1MaskedLoss` | `\|pred - gt\| * mask` | 约束网格颜色与真实图像一致 |
| 语义分割损失 | `CELossWithMask` | `CrossEntropy(pred, gt) * mask` | 约束网格语义标签与 GT 一致 |
| 深度监督损失 | `L1MaskedLoss` | `\|depth_pred - depth_gt\| * mask` | MVS 深度监督（可选） |
| Laplacian 平滑 | `mesh_laplacian_smoothing` | PyTorch3D 内置 | 约束网格表面平滑 |
| 平滑损失 | `SmoothLoss` | 边缘感知深度平滑 | 备用，当前未在主流程使用 |
| SSIM 损失 | `SSIM` | 结构相似性 | 备用 |

**总损失组合：**

```python
total_loss = render_loss                              # RGB (权重=1)
           + seg_loss * seg_loss_weight               # 语义 (默认权重=1)
           + depth_loss * depth_loss_weight            # 深度 (默认权重=100)
           + laplacian_loss * laplacian_loss_weight    # 平滑 (默认权重=1)
```

**Mask 机制：**
- `silhouette` — 渲染轮廓 mask（网格覆盖区域）
- `static_mask` — 静态物体 mask（排除车辆、行人等动态物体）
- `static_mask2` — 更宽松的静态 mask（保留 barrier/wall，用于语义损失）
- `gt_depth_mask` — 深度有效性 mask（渲染深度 < GT 深度最大值）

---

## 3. 训练流程

### 3.1 入口与 Trainer 配置

入口文件 `train_lightning.py`：

```python
def train(world_size, configs):
    rome_net = RomeNet(configs)
    trainer = Trainer(
        max_epochs=configs['epochs'],          # 默认 9
        devices=world_size,                     # 自动检测 GPU 数量
        strategy=DDPStrategy(find_unused_parameters=False),
        accelerator="gpu",
        limit_val_batches=0,                    # 训练时不执行验证
        num_sanity_val_steps=0,
    )
    trainer.fit(rome_net)
```

**关键配置项：**

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `epochs` | 9 | 训练轮数 |
| `batch_size` | 4 | 批大小 |
| `num_workers` | 4 | DataLoader 工作线程 |
| `rand_seed` | 17 | 随机种子 |
| `lr/vertices_rgb` | 0.1 | RGB 顶点学习率 |
| `lr/vertices_label` | 0.1 | 语义顶点学习率 |
| `lr/vertices_z` | 0.001 | 高度 MLP 学习率 |
| `lr/rotations` | 0.01 | 外参旋转学习率 |
| `lr/translations` | 0.01 | 外参平移学习率 |

### 3.2 优化器配置

`configure_optimizers()` 创建三组独立的 Adam 优化器：

| 优化器 | 参数 | 学习率调度 |
|--------|------|-----------|
| `self.optimizer` | `vertices_rgb`, `vertices_label` | MultiStepLR / ExponentialLR |
| `self.z_optimizer` | HeightMLP 参数 | 无调度 |
| `self.pose_optimizer` | `rotations`, `translations` | 无调度 |

**学习率调度（默认 MultiStepLR）：**
- milestones: `[1, 7]`
- gamma: `0.1`
- 即 epoch 1 和 epoch 7 时学习率衰减 10 倍

### 3.3 training_step 详细流程

```
1. 数据准备
   sample = batch（包含 image, static_label, depth, world2camera, ...）

2. 前向传播
   mesh = self.grid(batch_size)                    # 构建当前 mesh
   world2camera = extrinsics(camera_idx) @ w2c     # 应用外参优化（epoch >= start_epoch）
   images_feature, depth = renderer(render_params) # 可微渲染

3. Mask 计算
   silhouette = images_feature[..., -1] > 0        # 渲染轮廓
   mask = silhouette * static_mask                  # 静态区域 mask
   gt_depth_mask = render_depth < gt_depth_max      # 深度有效性

4. 损失计算
   render_loss = L1(rendered_rgb, gt_image, mask * gt_depth_mask)
   seg_loss = CE(rendered_labels, gt_seg, mask) * seg_loss_weight
   depth_loss = L1(render_depth, gt_depth, combined_mask) * depth_loss_weight
   laplacian_loss = mesh_laplacian_smoothing(mesh) * laplacian_loss_weight
   total_loss = sum(above)

5. 反向传播 + 参数更新
   self.manual_backward(total_loss)
   self.optimizer.step()       # RGB + 语义
   self.z_optimizer.step()     # 高度
   self.pose_optimizer.step()  # 外参
   # 各自 zero_grad()
```

### 3.4 Epoch 结束回调

`training_epoch_end()` 在每个 epoch 结束时（rank 0）：

1. **保存网格顶点特征** → `mesh_verts/mesh_verts_{epoch}.npy`
2. **BEV 渲染**：使用正交相机从上方渲染网格
   - BEV RGB 图 → `bev_rgb_epoch_{epoch}.png`
   - BEV 语义图 → `bev_seg_epoch_{epoch}.png`（argmax 后着色）
   - BEV 深度图 → `bev_depth_epoch_{epoch}.npy`
3. 可选绘制相机轨迹到 BEV 图上

### 3.5 训练结束回调

`on_train_end()` 在训练完成后（rank 0）：

1. 导出优化后的相机外参
2. 保存网格为 OBJ 文件
   - `bev_mesh.obj` — RGB 顶点色网格
   - `bev_label_mesh.obj` — 语义标签着色网格
3. 保存模型权重
   - `grid_baseline.pt` — Grid 模型参数
   - `pose_baseline.pt` — 外参模型参数
4. 调用 `pack_recon_result()` 打包结果供下游 GTA 模块使用

---

## 4. 推理与输出

### 4.1 BEV 渲染

BEV 相机在 `build_bev_camera()` 中构建，使用**正交投影**：

```python
# 正交相机参数
world2camera = eye(4)
world2camera[:3, 3] = [-cx, cy, 0]   # cx = bev_x_length/2, cy = bev_y_length/2
world2camera[1, 1] = -1.0            # Y 轴翻转

bev_render_params = {
    "world2camera": world2camera,
    "focal_length": (1/cx, 1/cy),     # 正交投影的缩放因子
    "principal_point": (0, 0),
    "image_shape": (bev_y_pixel, bev_x_pixel),
    "camera_model": "orthographic",
}
```

**BEV 图像尺寸计算：**
- `bev_x_pixel = bev_x_length / bev_resolution`
- `bev_y_pixel = bev_y_length / bev_resolution`
- 默认分辨率 0.1m/pixel

**渲染时的 Z 偏移：** 将 `world2camera` 的 Z 平移设为 `-min(mesh_z) + 0.1`，确保所有顶点在相机前方。

### 4.2 网格导出

| 输出文件 | 格式 | 内容 |
|----------|------|------|
| `bev_mesh.obj` | OBJ + 顶点色 | RGB 颜色网格 |
| `bev_label_mesh.obj` | OBJ + 顶点色 | 语义标签着色网格 |
| `bev_label_mesh.npy` | NumPy | 每个顶点的语义类别索引 |
| `bev_depth.npy` | NumPy | BEV 深度图 `(H, W)` |
| `bev_rgb_epoch_N.png` | PNG | BEV RGB 渲染图 |
| `bev_seg_epoch_N.png` | PNG | BEV 语义渲染图 |
| `bev_seg.png` | PNG | 最终 epoch 的 BEV 语义图 |
| `mesh_verts/mesh_verts_N.npy` | NumPy | 顶点特征 `(N, 2+1+3+C)` |
| `grid_baseline.pt` | PyTorch | Grid 模型权重 |
| `pose_baseline.pt` | PyTorch | 外参模型权重 |

### 4.3 KPI 评估

验证阶段（`validation_step`）对每帧计算：

| 指标 | 计算方式 | 说明 |
|------|----------|------|
| PSNR | `skimage.metrics.peak_signal_noise_ratio` | 渲染 RGB vs GT RGB |
| SSIM | `skimage.metrics.structural_similarity` | 结构相似性 |
| IoU (per-class) | `intersection / union` | 语义分割精度 |

**语义类别 IoU 评估：**

| 类别 ID | 类别名 | 颜色 (RGB) |
|---------|--------|-----------|
| 1 | Painted Line（车道线） | (0, 0, 255) |
| 2 | Curb（路缘） | (255, 0, 0) |
| 3 | Road Surface（路面+井盖） | (211, 211, 211) |
| 4 | Sidewalk（人行道） | (0, 191, 255) |

**评估输出：**
- `kpi.txt` — 包含 PSNR/SSIM 和各类 IoU 的表格
- `pred_seg_projection.mp4` — GT 图像与预测语义叠加的视频

### 4.4 Visualizer

`utility/visualizer.py` 中的 `Visualizer` 类使用 PyTorch3D 的 `OrthographicCameras` + `MeshRasterizer` 进行 BEV 渲染（备用渲染路径，主流程使用 NvdiffRenderer）。

辅助可视化函数：
- `draw_trajectory()` — 在 BEV 图上绘制车辆轨迹和箭头
- `draw_input_pose()` — 绘制输入位姿的 XY 轨迹和 Z 高程图
- `depth2color()` / `loss2color()` — 深度/损失值的伪彩色可视化
- `save_mesh_depth_height_map()` — 网格高度场散点图

---

## 5. 数据处理

### 5.1 XNetDataset

位于 `datasets/xnet.py`，继承 `BaseDataset`（`datasets/base.py`）。负责加载多趟采集的图像、语义标签、深度图和位姿数据。

#### 5.1.1 初始化流程

```
1. 读取 trips_json → 获取所有趟次路径
2. 计算裁剪中心 (cut_center)
   - use_auto_cut_center=True: 所有参考相机位姿的平均位置
   - 否则使用配置中的 cut_center
3. 遍历每个趟次:
   a. 加载 calib.json → 相机内参、外参
   b. 计算 ref2cam / cam2ref 变换
   c. 遍历 colmap_extrinsic 中的每个 (slice, cam) 对:
      - 距离过滤: 距 cut_center > cutoff_radius 的帧被跳过
      - 下采样过滤: 相邻帧距离/角度差小于阈值的被跳过
      - 记录: image_path, label_path, depth_path, camera_K, world2camera, camera_idx
4. 平面拟合: robust_estimate_flatplane() 估计地面平面
   → transform_normal2origin 将所有位姿变换到平面坐标系（减小 Z 方差）
5. 计算 world2bev 变换: 将坐标原点移到 BEV 左下角
6. 计算 BEV 尺寸: 根据位姿范围 + cut_range 确定 bev_x_length / bev_y_length
```

#### 5.1.2 __getitem__ 返回的 sample 字典

| 键名 | 形状 / 类型 | 说明 |
|------|-------------|------|
| `image` | `(H, W, 3)` float32 | RGB 图像，归一化到 `[0, 1]` |
| `depth` | `(H, W, 1)` float32 | 深度图（米），不存在时为全零 |
| `static_label` | `(H, W)` int64 | 重映射后的语义标签（7 类） |
| `static_mask` | `(H, W)` float32 | 静态区域 mask（排除动态物体） |
| `static_mask2` | `(H, W)` float32 | 宽松版静态 mask |
| `world2camera` | `(4, 4)` float64 | 世界到相机变换矩阵 |
| `focal_length` | `(2,)` float64 | 归一化焦距 |
| `principal_point` | `(2,)` float64 | 归一化主点 |
| `image_shape` | `(2,)` | `[H, W]` |
| `camera_idx` | int | 相机唯一索引 |
| `image_path` | str | 图像文件路径 |

**图像预处理：**
- 根据语义标签裁剪图像上部（天空/建筑区域），最多裁剪 80%
- 缩放到 `(image_width, image_height)`（默认 800×800）
- 相应调整内参矩阵

#### 5.1.3 语义标签重映射

原始 Mapillary Vistas 65 类 → 7 类：

| 重映射 ID | 类别名 | 原始类别 ID |
|-----------|--------|------------|
| 0 | Mask（无效区域） | 默认 |
| 1 | Lane Marking（车道线） | 7, 8, 14, 23, 24 |
| 2 | Curb（路缘） | 2, 9 |
| 3 | Road（路面+井盖+停车位） | 13, 41, 10 |
| 4 | Sidewalk（人行道） | 15 |
| 5 | Terrain（地形） | 29 |
| 6 | Background（背景） | 其余所有 |

#### 5.1.4 静态 Mask 生成

`label2mask()` 将以下类别标记为非静态（mask=0）：

- 天空、建筑、桥梁、隧道等结构物
- 行人、骑行者等动态物体
- 植被、山脉等非路面区域
- **动态物体额外膨胀**：label >= 52（车辆类）使用 10×10 kernel 膨胀 2 次

`label2mask2()` 是更宽松的版本，保留 barrier(5)、wall(6)、bridge(16)、building(17)、tunnel(18) 等。

#### 5.1.5 坐标系变换链

```
原始世界坐标 (colmap/local/global)
    │
    ▼  transform_normal2origin (平面拟合旋转)
平面对齐坐标
    │
    ▼  world2bev (平移到 BEV 原点)
BEV 坐标 (网格坐标系)
```

**相机坐标转换：** `opencv_camera2pytorch3d_()` 将 OpenCV 相机约定转为 PyTorch3D 约定：
- `focal_length = [fx, fy] / (image_size * 0.5)`
- `principal_point = (cx, cy) - image_center) / (image_size * 0.5)`

### 5.2 BaseDataset

位于 `datasets/base.py`，提供：

- 数据列表管理（`_all` 后缀为全量，无后缀为当前激活子集）
- `set_waypoint()` — 按中心点+半径筛选数据子集
- `enable_all_data()` — 激活全部数据
- `remap_semantic()` — 使用 LUT 进行语义标签重映射
- `opencv_camera2pytorch3d_()` — 相机参数格式转换
- `check_filelist_exist()` — 多线程文件存在性检查

---

## 6. 目录结构速查

```
rome/
├── __init__.py
├── rome_net.py                  # RomeNet — 顶层 LightningModule
├── train_lightning.py           # 训练入口，Trainer 配置
│
├── models/
│   ├── voxel.py                 # Grid 模型族 + HeightMLP + FeatureMLP
│   ├── pose_model.py            # PoseModel / ExtrinsicModel / PoseModelv3
│   └── loss.py                  # L1MaskedLoss / CELossWithMask / SSIM / SmoothLoss
│
├── datasets/
│   ├── base.py                  # BaseDataset — 数据集基类
│   └── xnet.py                  # XNetDataset — 多趟数据加载
│
├── configs/
│   ├── parser.py                # load_config() — 配置解析与默认值
│   ├── recon.yaml               # 重建模式示例配置
│   ├── config.yaml              # 通用配置模板
│   └── avm.yaml                 # AVM 环视相机配置
│
├── utility/
│   ├── nvdiff_renderer.py       # NvdiffRenderer — nvdiffrast 封装
│   ├── renderer.py              # SimpleShader（PyTorch3D 备用渲染器）
│   ├── geometry.py              # 网格生成: createHiveFlatMesh / cutHiveMeshWithPoses / createMultiResolutionMesh
│   ├── visualizer.py            # Visualizer / 轨迹绘制 / 网格导出
│   ├── eval_helper.py           # KPI 计算: PSNR / SSIM / IoU / 视频生成
│   ├── image.py                 # render_semantic() 语义着色
│   ├── plane_fit.py             # robust_estimate_flatplane() 地面平面拟合
│   ├── pack_gta_input.py        # pack_recon_result() 打包下游输入
│   ├── misc.py                  # 工具函数: 外参导出、轨迹绘制等
│   ├── numpy_utils.py           # NumPy 工具
│   ├── colmap_db.py             # COLMAP 数据库操作
│   └── read_write_model.py      # COLMAP 模型读写
│
└── colmap/
    └── scripts/python/
        └── read_write_model.py  # COLMAP 模型读写（副本）
```

---

## 7. 参考资料

### 7.1 核心算法论文

- **nvdiffrast**: Laine et al., "Modular Primitives for High-Performance Differentiable Rendering", SIGGRAPH Asia 2020
- **PyTorch3D**: Ravi et al., "Accelerating 3D Deep Learning with PyTorch3D", SIGGRAPH Asia 2020
- **Laplacian Smoothing**: Nealen et al., "Laplacian Mesh Optimization", 2006

### 7.2 关键配置参数速查

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `bev_resolution` | 0.1 | BEV 分辨率（米/像素） |
| `cut_range` | 20 | 轨迹周围网格保留范围（米） |
| `cutoff_radius` | 200.0 | 距裁剪中心的最大数据加载半径（米） |
| `epochs` | 9 | 训练轮数 |
| `batch_size` | 4 | 批大小 |
| `image_width` / `image_height` | 800 / 800 | 输入图像缩放尺寸 |
| `pos_enc` | 5 | HeightMLP 位置编码频率数 |
| `mesh_z_scale` | 1.0 | 高度预测缩放因子 |
| `seg_loss_weight` | 1 | 语义损失权重 |
| `depth_loss_weight` | 100 | 深度损失权重 |
| `laplacian_loss_weight` | 1 | Laplacian 平滑权重 |
| `extrinsic/rotation_deg` | 0.5 | 外参旋转优化范围（度） |
| `extrinsic/translation_m` | 0.5 | 外参平移优化范围（米） |
| `extrinsic/start_epoch` | 0 | 开始优化外参的 epoch |
| `lr_milestones` | [1, 7] | 学习率衰减节点 |
| `lr_gamma` | 0.1 | 学习率衰减系数 |
| `pose_source` | colmap | 位姿来源: colmap / local / global |
| `use_mvs_supervise` | true | 是否使用 MVS 深度监督 |
| `grid_guassian_smoothing` | true | 高度先验是否使用高斯平滑 |
| `only_save_final_epoch_result` | true | 是否仅保存最终 epoch 结果 |

### 7.3 数据流总览

```
trips_json
  └─ trip_1/image/cam0/slice0.png  ─┐
  └─ trip_1/seg_mask/cam0/slice0.png ├─→ XNetDataset
  └─ trip_1/calib.json              ─┘       │
                                             ▼
                                    ┌─── RomeNet ───┐
                                    │               │
                              SquareFlatGrid*   ExtrinsicModel
                                    │               │
                                    ▼               ▼
                              mesh (verts,     optimized w2c
                              faces, textures)      │
                                    │               │
                                    └───────┬───────┘
                                            ▼
                                     NvdiffRenderer
                                            │
                                    ┌───────┴───────┐
                                    ▼               ▼
                              image_features    image_depth
                              (B,H,W,3+C+1)    (B,H,W,1)
                                    │               │
                                    ▼               ▼
                              L1 / CE Loss    Depth Loss + Laplacian
                                    │
                                    ▼
                              backward → optimizer.step()
                                    │
                              ┌─────┴─────┐
                              ▼           ▼
                         BEV 渲染      OBJ 导出
                         (RGB/Seg/     (bev_mesh.obj
                          Depth)        bev_label_mesh.obj)
```
