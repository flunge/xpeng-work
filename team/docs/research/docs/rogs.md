# ROGS 模块技术分析文档

> Road Surface Gaussian Splatting for Ground Reconstruction
>
> 模块路径: `xpeng_data_process/ground_processing/rogs/`

---

## 1. 概述

ROGS（Road Gaussian Splatting）是一个基于 3D Gaussian Splatting 的路面重建模块，专门用于从多相机图像中重建高精度的道路表面。其核心思想是将路面建模为一组 **2D 高斯椭圆盘**（z 方向 scale 为 0），通过可微分光栅化进行端到端优化。

### 1.1 核心特性

- **2D 高斯表示**：路面高斯的 scaling 在 z 轴方向强制为 0，形成平面椭圆盘，天然适合路面这种近似平面的几何结构
- **位姿优化（Pose Optimization）**：通过 `PoseModel` 对每帧位姿施加可学习的微小扰动（axis-angle 旋转 + 平移），补偿标定误差
- **曝光补偿（Exposure Compensation）**：通过 `ExposureModel` 对不同相机学习独立的曝光参数 `(a, b)`，统一多相机间的亮度差异
- **仿射颜色校正（Affine Color Correction）**：通过 `AffineTransform` 对每张图像学习一个 3×4 仿射矩阵，进行全局颜色线性变换和偏置校正
- **多任务损失**：同时优化 RGB 重建、语义分割、深度、高程平滑和 z 值监督
- **三角化加密**：在最后一个 epoch 前通过三角化在语义边界处插入新高斯点，提升边缘精度

### 1.2 整体数据流

```
XpengDataset (多相机图像 + 位姿 + 语义标签 + 深度)
       │
       ▼
Road (路面初始化: 矩形网格 → 轨迹裁剪 → KNN 插值 z 和旋转)
       │
       ▼
GaussianModel2D (2D 高斯参数: xy, z, rotation, scaling_xy, opacity, rgb/SH, label)
       │
       ▼
render() (可微分光栅化: PerspectiveCamera / OrthographicCamera)
       │
       ├─→ ExposureModel (曝光校正)
       ├─→ AffineTransform (仿射颜色校正)
       │
       ▼
Loss (L1 + SSIM + CrossEntropy + SmoothLoss + DepthLoss + ZLoss + AffineReg)
       │
       ▼
Optimizer (Adam, 各参数独立学习率 + 指数衰减调度)
```

---

## 2. 模型结构

### 2.1 GaussianModel2D — 2D 高斯模型

**文件**: `models/gaussian_model.py`

这是 ROGS 的核心数据结构，管理所有高斯点的可学习参数。与标准 3DGS 的关键区别在于 **z 轴 scaling 强制为 0**，使高斯退化为平面椭圆盘。

#### 2.1.1 参数定义

| 参数 | 形状 | 激活函数 | 说明 |
|------|------|----------|------|
| `_xy` | `(N, 2)` | 无 | 高斯中心 xy 坐标，可选是否优化（`opt_xy`） |
| `_z` | `(N, 1)` | 无 | 高斯中心 z 坐标（高程），始终可优化 |
| `_scaling_xy` | `(N, 2)` | `torch.exp` | xy 方向的 scale（存储为 log 空间） |
| `_rotation` | `(N, 4)` | `F.normalize` | 四元数旋转 (w, x, y, z) |
| `_opacity` | `(N, 1)` | `torch.sigmoid` | 不透明度 |
| `_rgb` | `(N, 3)` | `torch.sigmoid` | RGB 颜色（`use_rgb=True` 时） |
| `_features_dc` | `(N, 1, 3)` | 无 | SH 直流分量（`use_rgb=False` 时） |
| `_features_rest` | `(N, K, 3)` | 无 | SH 高阶分量，K = `(max_sh_degree+1)²-1` |
| `_label` | `(N, C)` | `F.softmax` | 语义标签 logits，C 为类别数（XPeng 数据集 C=7） |

> **关键设计**：`get_scaling` 属性返回 `(N, 3)` 张量，其中第三维（z 轴）强制为 0：
> ```python
> scale_xy = self.scaling_activation(self._scaling_xy)  # (N, 2)
> return torch.cat((scale_xy, torch.zeros_like(scale_xy[:, :1])), dim=-1)  # (N, 3)
> ```

#### 2.1.2 初始化 (`init_2d_gaussian`)

```
输入:
  xyz:        (N, 3)   — 初始 3D 坐标（来自 Road 模块）
  rotation:   (N, 4)   — 初始四元数旋转（来自最近轨迹点）
  rgb:        (N, 3)   — 初始颜色（全零）
  label:      (N, C)   — 初始语义标签（全零）
  resolution: float    — BEV 分辨率（默认 0.06m）

处理:
  1. scale 初始化为 resolution * 0.6（两个方向相同）
  2. opacity 初始化为 sigmoid⁻¹(1.0)（即完全不透明）
  3. 若 use_rgb=True，直接存储 RGB；否则将 RGB 转为 SH 系数
```

#### 2.1.3 坐标变换 (`transform`)

支持对所有高斯点施加 4×4 齐次变换矩阵，同时更新位置和旋转：

```python
xyz_homo = cat(xyz, ones)          # (N, 4)
xyz_new = (transform @ xyz_homo.T).T  # (N, 4)
rotation_new = quaternion_multiply(matrix_to_quaternion(transform[:3,:3]), rotation)
```

#### 2.1.4 优化器配置 (`training_setup`)

各参数使用独立学习率的 Adam 优化器：

| 参数组 | 默认学习率 | 调度策略 |
|--------|-----------|----------|
| `z` | `position_lr_init * spatial_lr_scale` | 指数衰减（`get_expon_lr_func`） |
| `xy`（可选） | `position_lr_init * spatial_lr_scale` | 同上 |
| `opacity` | `0.0001` | 固定 |
| `scaling` | `0.0001` | 固定 |
| `rotation` | `0.0001` | 固定 |
| `rgb` | `0.008` | 固定 |
| `label` | `0.1` | 固定 |
| `f_dc` | `0.0005` | 固定（SH 模式） |
| `f_rest` | `0.000025` | 固定（SH 模式，f_dc/20） |

#### 2.1.5 自适应密度控制

**Clone**（梯度大 + scale 小）：
- 条件：`‖grad‖ ≥ grad_threshold` 且 `max(scale) ≤ percent_dense * scene_extent`
- 操作：直接复制满足条件的高斯点

**Split**（梯度大 + scale 大）：
- 条件：`grad ≥ grad_threshold` 且 `max(scale) > percent_dense * scene_extent`
- 操作：在原高斯周围采样 N=2 个新点，新 scale = 原 scale / (0.8 * N)，删除原点

**Prune**（不透明度低 / 屏幕投影过大 / 世界空间过大）：
- `opacity < min_opacity`
- `max_radii2D > max_screen_size`
- `max(scale) > 0.1 * extent`

#### 2.1.6 PLY 序列化

保存格式为标准 PLY，属性列表：`x, y, z, nx, ny, nz, [r,g,b | f_dc_*, f_rest_*], opacity, label_*, scale_*, rot_*`

---

### 2.2 Road — 路面初始化

**文件**: `models/road.py`

`Road` 类负责在训练前构建路面高斯点的初始几何分布。

#### 2.2.1 初始化流程

```
1. 收集所有底盘位姿 chassis2world_unique → 提取 xyz 坐标
2. 可选：沿最后 5m 方向延伸轨迹（extend_from_last_frame，默认 30m）
3. 计算包围盒 [min_coords, max_coords]，各方向扩展 cut_range（默认 10m）
4. 创建矩形网格 create_rect_vertices()，分辨率 = bev_resolution（默认 0.06m）
5. 按轨迹裁剪 cut_point_by_pose()：
   a. 将轨迹点映射到网格像素坐标
   b. 创建二值 mask，用 kernel_size = cut_range/resolution 的核膨胀 2 次
   c. 保留 mask 内的顶点，同时构建四邻域索引 (M, 4)
6. KNN 插值：对每个网格点找最近轨迹点，用其 z 值初始化高程，用其旋转矩阵初始化朝向
7. 创建 BEV 正交相机（OrthographicCamera），用于 BEV 渲染
```

#### 2.2.2 关键输出

| 属性 | 形状 | 说明 |
|------|------|------|
| `vertices` | `(M, 3)` | 裁剪后的网格顶点坐标 |
| `rotation` | `(M, 4)` | 每个顶点的四元数旋转 |
| `rgb` | `(M, 3)` | 初始颜色（全零） |
| `label` | `(M, C)` | 初始语义标签（全零） |
| `four_indices` | `(M, 4)` | 四邻域索引（用于平滑损失） |
| `bev_camera` | `OrthographicCamera` | BEV 正交相机 |
| `ref_pose` | `(4, 4)` | 参考位姿（anchor pose） |

#### 2.2.3 BEV 相机构建

```python
bevcam2world = [[1, 0, 0, mid_x],
                [0,-1, 0, mid_y],
                [0, 0,-1, max_z + 1],  # SLACK_Z = 1m
                [0, 0, 0, 1]]
# 正交投影参数:
#   width  = bev_x_length / resolution + 1
#   height = bev_y_length / resolution + 1
#   znear  = 0
#   zfar   = bevcam_height - min_z + 1
```

---

### 2.3 PoseModel — 位姿优化模型

**文件**: `models/pose_model.py`

#### 2.3.1 PoseModel（主模型）

对每帧学习一个微小的位姿扰动 `(rotation_delta, translation_delta)`：

| 参数 | 形状 | 说明 |
|------|------|------|
| `rotations` | `(N_frame, 3)` | axis-angle 旋转增量 |
| `translations` | `(N_frame, 3)` | 平移增量 |

**前向传播**：
```python
rots = axis_angle_to_matrix(1/180 * π * tanh(rotations))   # 限制在 ±1° 内
translations = 0.2 * tanh(translations).unsqueeze(2)        # 限制在 ±0.2m 内
poses = convert3x4_4x4(cat(rots, translations))             # (N, 4, 4)
```

> 使用 `tanh` 限制扰动范围，防止位姿优化发散。梯度通过 `register_hook(clean_nan)` 清除 NaN。

#### 2.3.2 ExtrinsicModel / ExtrinsicModel2

用于相机外参微调，分别使用 axis-angle 和四元数表示旋转。返回 `(rot_delta, trans_delta)` 供外部组合。

#### 2.3.3 PoseModelv3

同时优化帧级位姿和相机级外参，将旋转/平移分为 `_ref`（帧级）和 `_cam`（相机级）两组参数。

---

### 2.4 ExposureModel — 曝光补偿模型

**文件**: `models/exposure_model.py`

对每个相机学习独立的曝光参数：

| 参数 | 形状 | 说明 |
|------|------|------|
| `exposure_a` | `(N_cam, 1)` | 乘性曝光系数（log 空间） |
| `exposure_b` | `(N_cam, 1)` | 加性偏置 |

**前向传播**：
```python
image_out = exp(a) * image + b    # 逐像素线性变换
image_out = clamp(image_out, 0, 1)
```

> 当 `num_camera == 1` 时直接返回原图（无需校正）。

---

### 2.5 AffineTransform — 仿射颜色校正

**文件**: `models/affine_model.py`

#### 2.5.1 AffineTransform 网络

对每张图像学习一个 3×4 仿射矩阵，实现全局颜色线性变换：

```
结构: Embedding(n, 4) → Linear(4, 64) → ReLU → Linear(64, 12) → reshape(3, 4)
```

输出矩阵在对角线上加 1（从单位矩阵开始学习偏移）：
```python
affine[:, :, :3] = affine[:, :, :3] + eye(3)  # A ≈ I + δA
```

**应用方式**：
```python
rgb_flat = image.view(-1, 3).T          # (3, H*W)
rgb_affine = A @ rgb_flat + b           # (3, H*W)
image_out = clamp(rgb_affine.T.view(H, W, 3), 0, 1)
```

#### 2.5.2 RoGSAffineModule 封装

封装了 AffineTransform 的训练逻辑：

- **学习率调度**：warmup（cosine ramp）→ 指数衰减
  - `warmup_steps=1000`, `base_lr=5e-4`, `lr_final=1e-4`
- **正则化损失**：鼓励仿射矩阵接近单位矩阵
  ```python
  loss = weight * (|A - I|.mean() + |b - 0|.mean())  # weight = 1e-5
  ```
- **独立优化器**：Adam，`weight_decay=1e-6`

---

### 2.6 损失函数

**文件**: `models/loss.py`

| 损失 | 类 | 公式 | 用途 |
|------|-----|------|------|
| L1 Masked | `L1MaskedLoss` | `\|pred - target\| * mask` | RGB 重建主损失 |
| MSE Masked | `MESMaskedLoss` | `(pred - target)² * mask` | 深度损失 / 评估 |
| SSIM | `SSIM` | 3×3 窗口 SSIM，带 mask | 结构相似性（评估用） |
| Smooth | `SmoothLoss` | 边缘感知深度平滑 | 深度正则化 |
| CE Masked | `CELossWithMask` | `CrossEntropy * mask` | 语义分割损失 |

#### SSIM 实现细节

使用 3×3 AvgPool2d 计算局部均值和方差，常数 `C1 = 0.01²`, `C2 = 0.03²`，输入先做 ReflectionPad2d(1)。

#### SmoothLoss 实现细节

边缘感知平滑：深度梯度乘以 `exp(-图像梯度)`，在图像边缘处降低平滑约束。


---

## 3. 训练流程

**文件**: `train.py`

### 3.1 训练入口与配置

训练通过 `train(configs)` 函数启动，配置从 YAML 文件加载（如 `configs/oss_rogs_config.yaml`），使用 `addict.Dict` 封装。

**关键配置项**：

| 配置路径 | 默认值 | 说明 |
|----------|--------|------|
| `model.bev_resolution` | `0.06` | BEV 分辨率（米） |
| `model.cut_range` | `10` | 轨迹裁剪范围（米） |
| `model.use_rgb` | `True` | 使用 RGB 还是 SH |
| `model.use_exposure` | `False` | 是否启用曝光补偿 |
| `model.opt_xy` | `False` | 是否优化 xy 坐标 |
| `optimization.epochs` | `2` | 训练轮数 |
| `optimization.seg_loss_weight` | `0.06` | 语义损失权重 |
| `optimization.smooth_loss_weight` | `0.003` | 平滑损失权重 |
| `optimization.z_weight` | `0` | z 值监督权重 |
| `optimization.depth_loss_weight` | `0` | 深度损失权重 |

### 3.2 初始化阶段

```python
# 1. 数据集
dataset = XpengDataset(dataset_cfg, use_label=..., use_depth=...)

# 2. 路面初始化
road = Road(model_cfg, dataset, device)

# 3. 高斯模型初始化
gaussians = GaussianModel2D(model_cfg)
gaussians.init_2d_gaussian(road.vertices, road.rotation, road.rgb, road.label,
                           road.resolution, road.ref_pose, dataset.cameras_extent)
gaussians.training_setup(opt)

# 4. 可选模块
exposure_model = ExposureModel(num_camera=len(camera_names))  # if use_exposure
affine_module = RoGSAffineModule(affine_cfg, num_embeddings, device)  # if affine_cfg

# 5. 预计算辅助资源
smooth_near_idx = knn_points(gaussian_xy, gaussian_xy, K=5).idx[:, 1:5]  # (N, 4) 平滑邻域
sample_xyz, z_near_idx, z_near_xy_dist = build_z_supervision_resources(...)  # z 监督
```

### 3.3 训练循环（每个 iteration）

```
for epoch in range(epochs):
    # epoch 0 结束后：剪枝从未参与 loss 的高斯点
    # 最后一个 epoch 开始前：三角化加密（仅当 OPT_SEG=True）

    for sample in dataloader:
        1. 更新学习率（z 参数指数衰减 + affine cosine warmup）
        2. 可选：每 1000 步提升 SH degree（仅 SH 模式）

        3. 构建 PerspectiveCamera(R, T, K, W, H, near=1, far=50)
        4. 渲染 RGB: render_pkg = render(cam, gaussians, pipe, bg)
           → src_render_image (3, H, W), render_depth (1, H, W), visibility_filter (N,)

        5. 曝光校正: render_image = exposure_model(cam_idx, src_render_image)
        6. 仿射校正: render_image, affine_mat = affine_module.apply(render_image, image_idx)

        7. 构建 loss_mask:
           a. valid_mask = (depth > znear) & (depth < zfar)
           b. loss_mask = valid_mask * seg_mask（如有语义 mask）
           c. 形态学操作：erode(5×5) → dilate(5×5)

        8. 计算总损失:
           total_loss = L1(render_image, gt_image, loss_mask)
                      + affine_reg_loss
                      + depth_loss * depth_weight        (可选)
                      + CE_loss(render_seg, gt_seg) * seg_weight  (可选)
                      + z_smooth_loss * smooth_weight    (可选)
                      + z_supervision_loss * z_weight    (可选)

        9. 反向传播 + 优化器 step（gaussians + exposure + affine 各自独立）
       10. 统计 ever_in_loss_epoch（记录哪些高斯参与了梯度更新）
```

### 3.4 各损失项详解

#### 3.4.1 RGB 重建损失

```python
render_loss = L1MaskedLoss(render_image, gt_image, loss_mask[:,:,None])
total_loss = render_loss.mean()
```

#### 3.4.2 语义分割损失（`seg_loss_weight > 0`）

```python
label_feature = render(cam, gaussians, pipe, bg, render_type="label")
render_seg = label_feature["render"].permute(1,2,0)  # (H, W, C)
seg_loss = CrossEntropyLoss(render_seg.reshape(-1, C), gt_seg.reshape(-1), loss_mask.reshape(-1))
total_loss += seg_loss * seg_loss_weight
```

#### 3.4.3 高程平滑损失（`smooth_loss_weight > 0`）

对可见高斯点，约束其 z 值与 4 个最近邻的 z 值一致：

```python
vis_z = gaussian_z[visibility_filter]                    # (m,)
smooth_near_z = knn_gather(gaussian_z, near_idx)         # (m, 4)
z_smooth_loss = mean((smooth_near_z - vis_z[:, None])²)  # 标量
total_loss += z_smooth_loss.sum() * smooth_loss_weight
```

#### 3.4.4 Z 值监督损失（`z_weight > 0`）

使用路面点云的 z 值监督高斯点的高程，限制在相机周围 ±10m 范围内：

```python
surround_filter = (|gaussian_x - cam_x| < 10) & (|gaussian_y - cam_y| < 10)
near_z = knn_gather(road_pointcloud_z, z_near_idx[surround_filter])
z_loss = (near_z - gaussian_z[surround_filter])²
# 可选：z_xy_dist_threshold 过滤 xy 距离过远的匹配对
total_loss += z_loss.sum() * z_weight
```

#### 3.4.5 仿射正则损失

```python
loss_affine = weight * (|A - I|.mean() + |b|.mean())  # weight = 1e-5
```

### 3.5 Epoch 级操作

#### Epoch 0 结束后：零梯度剪枝

统计整个 epoch 内从未产生过非零梯度的高斯点，将其删除：

```python
never_updated_mask = ~ever_in_loss_epoch
gaussians.prune_points(never_updated_mask)
# 重建平滑邻域索引和 z 监督资源
```

#### 最后一个 Epoch 开始前：三角化加密

当 `OPT_SEG=True` 时，对目标语义类别（lane=1, curb=2, sidewalk=4）的高斯点执行 Delaunay 三角化，在三角形边上和重心处插入新高斯点：

```python
added = densify_by_triangulation(
    gaussians,
    target_classes=(1, 2, 4),
    edge_samples=1,
    add_triangle_centroid=cfg.add_triangle_centroid,
)
```

### 3.6 保存产出物

训练结束后保存：

| 文件 | 路径 | 内容 |
|------|------|------|
| 高斯模型 PLY | `{output}/ply/final.ply` | 所有高斯参数 |
| 高斯模型 checkpoint | `{output}/final.pth` | `gaussians.capture()` |
| 曝光模型 | `{output}/exposure.pth` | ExposureModel state_dict |
| 仿射模型 | `{output}/affine_transform.pth` | AffineTransform state_dict |
| BEV 渲染结果 | `{output}/images/final/` | bev_image, bev_label, bev_height 等 |


---

## 4. 推理与渲染

### 4.1 渲染管线

**文件**: `utils/render.py`

#### 4.1.1 `render()` 函数

核心渲染函数，支持透视相机和正交相机两种模式：

```python
def render(viewpoint_camera, pc, pipe, bg_color, delta_pose=None, render_type="rgb"):
    # 1. 确定相机类型
    #    PerspectiveCamera  → camera_type=0, 计算 tanfov
    #    OrthographicCamera → camera_type=1, tanfov=0

    # 2. 空间裁剪：只光栅化相机视锥内的高斯点
    #    透视相机：前方 40m × 50m 矩形区域
    #    正交相机：投影框 + 1m 膨胀
    activate_mask = (xy >= min_xy) & (xy <= max_xy)  # (N,)

    # 3. 提取激活高斯的属性
    means3D   = pc.get_xyz[activate_mask]           # (M, 3)
    opacity   = pc.get_opacity_mask(activate_mask)   # (M, 1)
    scales    = pc.get_scaling_mask(activate_mask)   # (M, 3), z=0
    rotations = pc.get_rotation_mask(activate_mask)  # (M, 4)

    # 4. 可选：施加位姿扰动 delta_pose
    #    means3D = quaternion_apply(delta_quat, means3D) + delta_t
    #    rotations = quaternion_multiply(delta_quat, rotations)

    # 5. 颜色计算
    #    render_type="rgb":  使用 RGB 或 SH 评估
    #    render_type="label": 使用 softmax 后的语义标签

    # 6. 调用 CUDA 光栅化器
    rendered_image, radii, depth, alpha = rasterizer(
        means3D, means2D, shs=None, colors_precomp, opacities,
        scales, rotations, cov3D_precomp
    )

    # 7. 返回
    return {
        "render": rendered_image,        # (C, H, W)
        "visibility_filter": vis_filter, # (N,) 全局布尔 mask
        "depth": depth,                  # (1, H, W)
        "mask": valid_mask,              # (H, W) 布尔
    }
```

> **注意**：语义渲染使用 `diff_gaussian_rasterization_nusc` 的光栅化器（支持多通道），且所有输入 detach 以避免语义梯度影响几何参数。

#### 4.1.2 `render_blocks()` 函数

用于 BEV 正交相机的分块渲染，将大尺寸 BEV 图像拆分为 2000×2000 像素的块分别渲染后拼接：

```python
bev_cams = viewpoint_camera.split(edge_pixel=2000)
for w_cams in bev_cams:       # 列方向
    for cam in w_cams:         # 行方向
        bev_pkg = render(cam, gaussians, pipe, bg)
# 拼接所有块 → 完整 BEV 图像
```

### 4.2 渲染脚本

**文件**: `render.py`

独立的渲染推理脚本，支持命令行参数：

```bash
python -m xpeng_data_process.ground_processing.rogs.render \
    --config configs/oss_rogs_config.yaml \
    --clip_path /path/to/clip \
    --clip_id c-7ef3dca1-... \
    --fps 10 \
    --output_root /path/to/output
```

#### 4.2.1 模型加载流程 (`load_models_and_data`)

```
1. 加载数据集 XpengDataset
2. 加载高斯模型（优先 ply/final.ply，其次 final.pth）
3. 可选：加载曝光模型 exposure.pth
4. 可选：加载仿射模型 affine_transform.pth
```

#### 4.2.2 渲染流程 (`render_all`)

```
对数据集中每个样本:
  1. 构建 PerspectiveCamera
  2. render() → 曝光校正 → 仿射校正
  3. 保存逐帧 PNG 到 render_frames/{camera_name}/
  4. 写入 VideoWriter（按相机分别生成 mp4）

渲染完成后:
  5. 使用 ffmpeg hstack 拼接所有相机视频为 all_cameras.mp4
```

### 4.3 评估

**文件**: `evalution.py`

#### 4.3.1 `eval_metric()` — 透视图评估

对数据集中所有样本计算：

| 指标 | 计算方式 |
|------|----------|
| MSE | `MESMaskedLoss(render, gt, mask)` 的均值 |
| PSNR | `-10 * log10(MSE)` |
| mIoU | `eval_metrics(pred_seg, gt_seg, num_classes=5, ignore_index=255)` |

> 语义评估时将 class 0（mask）和最后一个 class（background）映射为 ignore_index=255，其余类别 index 减 1。

#### 4.3.2 `eval_bev_metric()` — BEV 评估

从保存的 BEV 图像文件中读取 GT 和预测结果，计算 MSE/PSNR/mIoU。

#### 4.3.3 `eval_z_metric()` — 高程评估

使用 ball_query（半径 0.1m）匹配 LiDAR 点和高斯点，计算 z 值的 RMSE：

```python
near_idx = ball_query(gaussian_xy, lidar_xy, K=1, radius=0.1)
loss = sqrt(mean((gt_z[valid] - pred_z[valid])²))
```

#### 4.3.4 `eval_chamfer_metric()` — Chamfer 距离

双向 KNN 距离，取 97% 分位数截断后计算 RMSE 之和：

```python
d1 = knn(gaussian → lidar).dists.sort()[:97%]
d2 = knn(lidar → gaussian).dists.sort()[:97%]
chamfer = sqrt(mean(d1²)) + sqrt(mean(d2²))
```


---

## 5. 数据处理

### 5.1 XpengDataset

**文件**: `datasets/xpeng.py`，继承自 `datasets/base.py` 的 `BaseDataset`（PyTorch Dataset）。

#### 5.1.1 数据加载

从 clip 目录读取 `transform.json`，提取每帧的：

| 字段 | 来源 | 说明 |
|------|------|------|
| `file_path` | `frame["file_path"]` | 图像相对路径 |
| `K` | `fl_x, fl_y, cx, cy` | 3×3 内参矩阵 |
| `camera2world` | `frame["transform_matrix"]` | 4×4 相机到世界变换 |
| `camera_name` | `frame["camera"]` | 相机名称（cam0-cam7） |
| `timestamp` | `frame["timestamp"]` | 时间戳 |

同时从 `localpose.json` + `anchorpose.json` 加载底盘位姿：
```python
localpose_anchored[ts] = inv(anchorpose) @ localpose_global[ts]
```

#### 5.1.2 数据预处理（`__getitem__`）

```
1. 读取图像 → BGR2RGB → 裁剪上半部分（crop_cy = H/2）
   → 归一化到 [0, 1] float32
   → 输出形状: (H/2, W, 3)

2. 更新内参: K[1][2] -= crop_cy（调整 cy）

3. 语义标签（use_label=True）:
   a. 读取原始 65 类标签
   b. label2mask(): 生成道路区域 mask（排除天空、建筑、车辆等）
      - 可移动物体（label >= 52）额外膨胀 10×10 kernel
   c. remap_semantic(): 65 类 → 7 类映射
      - 0: mask, 1: lane, 2: curb, 3: road+manhole
      - 4: sidewalk, 5: terrain, 6: background

4. 深度图（use_depth=True）:
   读取 .npy 文件，支持稀疏格式（mask + value）

5. unique_img_idx: frame_idx * num_cameras + cam_idx
   （与 reconic 保持一致的全局图像索引）
```

#### 5.1.3 语义类别映射

| 重映射 ID | 类别 | 原始 Mapillary ID |
|-----------|------|-------------------|
| 0 | mask（无效区域） | 默认 |
| 1 | 车道线 | 7, 8, 14, 23, 24 |
| 2 | 路缘 | 2, 9 |
| 3 | 道路 + 井盖 | 13, 41 |
| 4 | 人行道 | 15 |
| 5 | 地形 | 29 |
| 6 | 背景 | 其余所有 |

#### 5.1.4 文件有效性检查

- `file_check()`: 多线程（32 线程）检查图像和标签文件是否存在且非空
- `label_valid_check()`: 检查标签质量（可移动物体占比 > 30% 或非道路占比 > 90% 则丢弃）
- `getNerfppNorm()`: 计算相机中心的包围球半径，用于 `cameras_extent`

#### 5.1.5 配置的相机列表

默认使用 7 个相机：`cam0, cam2, cam3, cam4, cam5, cam6, cam7`（跳过 cam1）。

### 5.2 BaseDataset

**文件**: `datasets/base.py`

提供基础数据管理功能：

- 维护 `*_all` 后缀的列表（image_filenames_all, camera2world_all, cameras_K_all 等）
- `filter_by_index()`: 按索引过滤所有列表
- `check_filelist_exist()`: 多线程文件存在性检查
- `remap_semantic()`: 使用 LUT 进行语义标签重映射
- `getNerfppNorm()`: NeRF++ 归一化（计算相机中心包围球）

---

## 6. 目录结构速查

```
rogs/
├── __init__.py
├── train.py                    # 训练入口
├── render.py                   # 推理渲染脚本
├── evalution.py                # 评估指标计算
│
├── configs/
│   ├── oss_rogs_config.yaml    # OSS 环境配置模板
│   └── hil_rogs_config.yaml    # HIL 环境配置模板
│
├── models/
│   ├── gaussian_model.py       # GaussianModel2D — 2D 高斯核心模型
│   ├── road.py                 # Road — 路面网格初始化 + BEV 相机
│   ├── pose_model.py           # PoseModel / ExtrinsicModel — 位姿优化
│   ├── exposure_model.py       # ExposureModel — 曝光补偿
│   ├── affine_model.py         # AffineTransform + RoGSAffineModule — 仿射颜色校正
│   └── loss.py                 # 损失函数集合
│
├── datasets/
│   ├── base.py                 # BaseDataset — 数据集基类
│   └── xpeng.py                # XpengDataset — XPeng 数据集实现
│
└── utils/
    ├── render.py               # render() / render_blocks() — 可微分光栅化
    ├── general_utils.py        # 通用工具（build_scaling_rotation, inverse_sigmoid 等）
    ├── sh_utils.py             # 球谐函数工具（RGB2SH, eval_sh）
    ├── triangulation.py        # 三角化加密（densify_by_triangulation）
    ├── metrics.py              # mIoU 等评估指标
    ├── image.py                # 语义渲染可视化
    ├── visualizer.py           # loss/depth 可视化工具
    ├── vis.py                  # Mayavi 3D 可视化（可选）
    └── logging.py              # 日志工具
```

### 训练产出物目录结构

```
{output}/
├── train.log                   # 训练日志
├── final.pth                   # 高斯模型 checkpoint
├── exposure.pth                # 曝光模型权重（可选）
├── affine_transform.pth        # 仿射模型权重（可选）
├── ply/
│   └── final.ply               # 高斯模型 PLY 文件
└── images/
    ├── EPOCH-{n}_IDX-{idx}/    # 每个 epoch 的可视化
    │   └── {image_name}/
    │       ├── gt_image.png
    │       ├── render_image.png
    │       ├── render_depth_vis.png
    │       ├── bev_image.png
    │       ├── bev_label_vis.png
    │       ├── bev_height_vis.png
    │       └── ...
    └── final/                  # 最终 epoch 的完整输出
```

---

## 7. 参考资料

### 7.1 核心依赖

| 库 | 用途 |
|----|------|
| `diff_gaussian_rasterization_depthalpha` | CUDA 可微分高斯光栅化（支持深度和 alpha） |
| `diff_gaussian_rasterization_nusc` | 多通道光栅化（用于语义渲染） |
| `pytorch3d` | KNN、ball_query、四元数运算、点云操作 |
| `plyfile` | PLY 文件读写 |
| `pyquaternion` | 四元数工具（数据集中使用） |

### 7.2 关键算法

- **3D Gaussian Splatting**: Kerbl et al., "3D Gaussian Splatting for Real-Time Radiance Field Rendering", SIGGRAPH 2023
- **2D Gaussian 退化**: z-scale 强制为 0，将 3D 椭球退化为 2D 椭圆盘，适合路面等平面结构
- **自适应密度控制**: 基于视空间梯度的 clone/split/prune 策略（源自原始 3DGS）
- **球谐函数 (SH)**: 用于视角相关的颜色表示（可选，默认使用直接 RGB）
- **边缘感知平滑**: 深度梯度加权 `exp(-图像梯度)`，在纹理边缘处放松平滑约束

### 7.3 XPeng 数据格式

| 文件 | 格式 | 说明 |
|------|------|------|
| `transform.json` | JSON | 每帧的相机内外参、文件路径 |
| `localpose.json` | JSON | 时间戳 → 4×4 全局位姿 |
| `anchorpose.json` | JSON | 4×4 锚点位姿（世界坐标系原点） |
| `images/` | PNG/JPG | 多相机图像 |
| `segs/` | PNG | 语义分割标签（Mapillary 65 类） |
| `depth/` | NPY | 稀疏深度图（mask + value 格式） |
| `*.ply` | PLY | 路面点云（可选，用于 z 监督） |
