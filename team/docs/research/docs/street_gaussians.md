# Street Gaussians 技术分析文档

## 1. 概述

Street Gaussians 是一个面向城市驾驶场景的动态三维重建框架，基于 3D Gaussian Splatting (3DGS) 技术，通过将场景分解为多个语义组件（背景、动态物体、天空、地面）来实现高质量的新视角合成。

### 1.1 核心思想

传统 3DGS 假设场景为静态，无法处理城市驾驶中大量存在的动态物体（车辆、行人等）。Street Gaussians 采用 **Neural Scene Graph (NSG)** 的思路，将场景分解为：

- **Background（背景）**：静态建筑、植被、路灯等
- **Ground（地面）**：道路平面，使用独立高斯模型并施加平坦性约束
- **Actor（动态物体）**：车辆、行人等，每个物体在局部坐标系下建模，通过 tracklet 位姿变换到世界坐标系
- **Sky（天空）**：使用 CubeMap 或高斯模型表示远处天空

每个组件独立维护一组 3D Gaussian 参数，渲染时按场景图（Scene Graph）组合后统一光栅化。

### 1.2 技术栈

| 组件 | 技术 |
|------|------|
| 核心框架 | PyTorch + CUDA |
| 光栅化后端 | `diff-gaussian-rasterization`（默认）/ `gsplat`（可选） |
| 球谐函数 | 最高 3 阶 SH（可配置） |
| 天空模型 | `nvdiffrast` CubeMap |
| 点云处理 | `simple_knn`、`plyfile` |
| 数据集 | Waymo、XPeng 自采数据、Colmap |

---

## 2. 模型结构

### 2.1 整体架构

```
StreetGaussianModel (nn.Module)
├── GaussianModelBkgd        # 背景高斯模型
├── GaussianModelGround       # 地面高斯模型
├── GaussianModelActor × N    # N 个动态物体高斯模型（obj_000000001, obj_000000002, ...）
├── ActorPose                 # 物体位姿管理（tracklet 插值 + 可优化残差）
├── SkyCubeMap                # 天空立方体贴图（可选）
├── ColorCorrection           # 颜色校正（可选，per-image 或 per-sensor 仿射变换）
└── PoseCorrection            # 相机位姿校正（可选）
```

### 2.2 基础高斯模型 `GaussianModel`

所有组件的基类，定义了单个 3D Gaussian 的完整参数集。

#### 2.2.1 核心参数（可学习）

| 参数 | 变量名 | 形状 | 说明 |
|------|--------|------|------|
| 位置 | `_xyz` | `[N, 3]` | 高斯中心坐标 |
| DC 球谐系数 | `_features_dc` | `[N, 1, 3]` | 0 阶 SH 系数（基础颜色） |
| 高阶球谐系数 | `_features_rest` | `[N, (L+1)²-1, 3]` | 1~L 阶 SH 系数（视角相关颜色） |
| 缩放 | `_scaling` | `[N, 3]` | 对数空间的各向异性缩放 |
| 旋转 | `_rotation` | `[N, 4]` | 四元数 `[w, x, y, z]` |
| 不透明度 | `_opacity` | `[N, 1]` | logit 空间的不透明度 |
| 语义标签 | `_semantic` | `[N, C]` | C 类语义 logits |
| 外观嵌入 | `_appearance_embeddings` | `[4096, 64]` | per-view 外观嵌入向量 |

#### 2.2.2 激活函数

```python
scaling   → torch.exp(_scaling)           # 保证正值
opacity   → torch.sigmoid(_opacity)       # 映射到 [0, 1]
rotation  → F.normalize(_rotation)        # 单位四元数
```

#### 2.2.3 协方差矩阵计算

3D 协方差矩阵由 scaling 和 rotation 构建：

```
Σ = R · S · Sᵀ · Rᵀ
```

其中 `R = quaternion_to_matrix(rotation)` 为 `[N, 3, 3]`，`S = diag(scaling)` 为 `[N, 3, 3]`。代码中通过 `build_scaling_rotation` 构建 `L = R·S`，然后 `Σ = L·Lᵀ`，最后取上三角 6 个独立元素（`strip_symmetric`）。

#### 2.2.4 法线计算

法线取自协方差矩阵最小特征值对应的特征向量方向：

```python
min_scales = torch.argmin(scales, dim=-1)       # 找最薄方向
normals = rotations_mat[indices, :, min_scales]  # 对应旋转矩阵列
# 翻转使法线朝向相机
dotprod = torch.sum(-dir_pp_normalized * normals, dim=1, keepdim=True)
normals = torch.where(dotprod >= 0, normals, -normals)
```

#### 2.2.5 外观网络 `AppearanceNetwork`

基于 GOF (Gaussian Opacity Fields) 的外观解耦网络，用于处理不同视角/时间的光照变化：

```
输入: 下采样图像 [1, 3, H/32, W/32] + 外观嵌入 [1, 64, H/32, W/32]
      ↓ concat → [1, 67, H/32, W/32]
      ↓ Conv2d(67→256) + ReLU
      ↓ PixelShuffle ×4 (256→128→64→32→16)
      ↓ Bilinear Upsample to [H, W]
      ↓ Conv2d(16→16) + ReLU
      ↓ Conv2d(16→3) + Sigmoid
输出: 乘性映射 [1, 3, H, W]，与原图逐像素相乘
```

### 2.3 背景模型 `GaussianModelBkgd`

继承 `GaussianModel`，增加场景范围感知：

- **场景中心/半径**：`scene_center [3]`、`scene_radius [1]`，用于密度化和剪枝的空间范围判断
- **球体中心/半径**：`sphere_center [3]`、`sphere_radius [1]`，用于远处点的剪枝
- **背景掩码**：`background_mask`，可选的布尔掩码，用于动态过滤可见高斯
- **LiDAR 约束密度化**：在 `densify_and_prune` 中，使用 FAISS KNN 索引 (`bkgd_index`) 限制只在 LiDAR 点附近进行 clone/split
- **Scaling 学习率调度**：密度化阶段结束后切换到更低的 `scaling_lr_final`
- **地面平坦性损失**：`ground_flatten_loss` 约束 z 方向缩放趋近 0，roll/pitch 趋近 0

### 2.4 地面模型 `GaussianModelGround`

继承 `GaussianModel`，专门建模道路平面：

- **初始化**：支持三种来源——G3R 地面重建、Surfel 地面、LiDAR 点云中的地面点
- **旋转初始化**：从点云中读取预计算的旋转（`pcd.rots`），而非默认单位四元数
- **Z 轴缩放约束**：初始化时 `scales[:, 2]` 被 clamp 到 `log(0.04)`，强制高斯在垂直方向极薄
- **不参与密度化**：`densify_and_prune` 直接返回空结果，地面高斯数量固定
- **独立剪枝**：通过 `prune` 方法单独执行不透明度和尺寸剪枝
- **正则化损失**：
  - `ground_flatten_loss`：约束 sz→0、roll→0、pitch→0
  - `ground_symmetry_loss`：约束 sx≈sy（各向同性）、xy 旋转≈单位矩阵
  - `ground_maxscale_loss`：约束 sx, sy 不超过阈值

### 2.5 动态物体模型 `GaussianModelActor`

继承 `GaussianModel`，每个被跟踪的物体实例化一个：

#### 2.5.1 物体元数据

```python
obj_meta = {
    'class': 'Car',              # 物体类别
    'class_label': 2,            # 语义标签 ID
    'deformable': False,         # 是否可变形（行人等）
    'track_id': 42,              # 跟踪 ID
    'start_frame': 0,            # 出现的起始帧
    'end_frame': 100,            # 消失的结束帧
    'start_timestamp': 0.0,      # 起始时间戳
    'end_timestamp': 3.33,       # 结束时间戳
    'length': 4.5, 'width': 1.8, 'height': 1.5,  # 3D 包围盒尺寸
}
```

#### 2.5.2 局部坐标系

所有高斯在物体局部坐标系下定义，包围盒为 `[-L/2, L/2] × [-W/2, W/2] × [-H/2, H/2]`。

#### 2.5.3 傅里叶球谐 (Fourier SH)

为处理动态物体的时变外观（如转向灯、刹车灯），DC 系数使用傅里叶基函数调制：

```python
# _features_dc 形状: [N, fourier_dim, 3]（而非标准的 [N, 1, 3]）
normalized_frame = (frame - start_frame) / (end_frame - start_frame)  # 归一化到 [0, 1]
time = fourier_scale * normalized_frame
idft_base = IDFT(time, fourier_dim)  # [fourier_dim] 傅里叶基函数值
features_dc = torch.sum(_features_dc * idft_base[..., None], dim=1, keepdim=True)  # [N, 1, 3]
```

最终 `features = cat([features_dc, _features_rest], dim=1)` 形状为 `[N, (L+1)², 3]`。

#### 2.5.4 对称性先验

对于刚性物体（非 deformable），训练时以 `flip_prob` 概率沿 Y 轴翻转高斯：

```python
# 翻转位置
xyzs_local[flip_mask, flip_axis] *= -1
# 翻转旋转
rotations_local[flip_mask] = quaternion_raw_multiply(flip_matrix, rotations_local[flip_mask])
```

#### 2.5.5 包围盒剪枝

密度化后，采样高斯覆盖范围并剪除超出包围盒的点：

```python
samples_xyz = R @ samples + origins  # [N, M, 3]，M=2 次采样
points_inside_box = (samples_xyz >= min_xyz) & (samples_xyz <= max_xyz)
points_outside_box = ~points_inside_box.all(dim=-1)
prune_mask |= points_outside_box
```

### 2.6 天空模型 `SkyCubeMap`

不使用高斯表示，而是用可学习的立方体贴图：

- **参数**：`sky_cube_map [6, R, R, 3]`，R 默认 1024
- **渲染**：通过 `nvdiffrast` 的 `dr.texture` 对立方体贴图采样
- **合成**：`rgb_final = rgb_foreground + sky_color * (1 - acc_foreground)`

### 2.7 物体位姿管理 `ActorPose`

管理所有动态物体的逐帧位姿，支持可优化残差：

#### 2.7.1 数据结构

```python
track_ids:        [num_frames, max_obj]           # 每帧每个槽位的 track_id
input_trans:      [num_frames, max_obj, 3]        # 输入平移（车辆坐标系）
input_rots:       [num_frames, max_obj, 4]        # 输入旋转四元数
input_trans_world:[num_frames, max_obj, 3]        # 输入平移（世界坐标系）
input_rots_world: [num_frames, max_obj, 4]        # 输入旋转四元数（世界坐标系）
opt_trans:        [num_frames, max_obj, 3]         # 可学习平移残差
opt_rots:         [num_frames, max_obj, 1]         # 可学习 yaw 角残差
```

#### 2.7.2 位姿插值

对于非关键帧时间戳，通过最近两帧线性插值平移、SLERP 插值旋转：

```python
trans = (trans1 * (t2 - t) + trans2 * (t - t1)) / (t2 - t1)
rots = quaternion_slerp(rots1, rots2, r)
```

### 2.8 颜色校正 `ColorCorrection`

处理多相机间的色彩不一致，学习 per-image 或 per-sensor 的 3×4 仿射变换矩阵：

```python
# 仿射变换
image_out = A[:3,:3] @ image + A[:3,3]  # A 初始化为单位矩阵
```

支持两种模式：
- **直接参数**：`affine_trans [num_corrections, 3, 4]`
- **MLP 回归**：从相机外参 (6D axis-angle) 回归仿射参数

### 2.9 场景图组装 `StreetGaussianModel.parse_camera`

每次渲染前，根据当前相机时间戳构建场景图：

1. **可见性过滤**：检查每个物体的时间范围是否覆盖当前帧
2. **位姿查询**：从 `ActorPose` 获取每个可见物体的旋转 `obj_rots [N_obj, 4]` 和平移 `obj_trans [N_obj, 3]`
3. **坐标变换**：将物体局部高斯变换到世界坐标系
   ```python
   # 位置变换
   obj_rots_mat = quaternion_to_matrix(obj_rots)  # [N_obj, 3, 3]
   xyzs_world = einsum('bij, bj -> bi', obj_rots_mat, xyzs_local) + obj_trans
   # 旋转变换
   rotations_world = quaternion_raw_multiply(obj_rots, rotations_local)
   ```
4. **索引范围记录**：`graph_gaussian_range` 记录每个模型在拼接后张量中的起止索引
5. **属性拼接**：所有组件的 xyz、rotation、scaling、opacity、features 按顺序 `torch.cat`

---

## 3. 训练流程

### 3.1 训练初始化

#### 3.1.1 点云初始化

| 组件 | 初始化来源 | 点数 |
|------|-----------|------|
| Background | LiDAR 点云（去除地面点） | 由数据决定 |
| Ground | G3R 地面重建 / Surfel / LiDAR 地面点 | 由数据决定 |
| Actor | 物体点云 PLY 文件（若不足 2000 点则随机初始化 20³=8000 点网格） | 8000 或由数据决定 |
| Sky | CubeMap 参数（非点云） | 6×1024×1024 |

背景点云初始化流程：
```python
fused_point_cloud = torch.tensor(pcd.points).float().cuda()     # [N, 3]
fused_color = RGB2SH(torch.tensor(pcd.colors).float().cuda())   # [N, 3] → SH DC
dist2 = distCUDA2(points)                                        # KNN 距离²
scales = torch.log(torch.sqrt(dist2))[..., None].repeat(1, 3)   # [N, 3]
rots = torch.zeros(N, 4); rots[:, 0] = 1                        # 单位四元数
opacities = inverse_sigmoid(0.1 * torch.ones(N, 1))             # logit(0.1)
```

#### 3.1.2 优化器配置

所有组件使用 Adam 优化器，关键学习率：

| 参数 | 初始 LR | 最终 LR | 调度策略 |
|------|---------|---------|---------|
| xyz (背景) | `position_lr_init × spatial_lr_scale` | `position_lr_final × spatial_lr_scale` | 指数衰减 |
| xyz (地面) | `position_lr_init_grd` (≈1e-15) | `position_lr_final_grd` (≈1e-16) | 指数衰减（几乎冻结） |
| features_dc | `feature_lr` (0.0025) | — | 固定 |
| features_rest | `feature_lr / 20` | — | 固定 |
| scaling | `scaling_lr` (0.005) | `scaling_lr_final` | 密度化后切换 |
| rotation | `rotation_lr` (0.001) | — | 固定 |
| opacity | `opacity_lr` (0.05) | — | 固定 |
| tracklet trans | `track_position_lr_init` | `track_position_lr_final` | 指数衰减 |
| tracklet rots | `track_rotation_lr_init` | `track_rotation_lr_final` | 指数衰减 |
| sky cubemap | `sky_cube_map_lr_init` (0.01) | `sky_cube_map_lr_final` (0.0001) | 指数衰减 |
| color correction | `color_correction_lr_init` (5e-4) | `color_correction_lr_final` (5e-5) | 指数衰减 |

### 3.2 XPeng 两阶段训练

配置中定义了两阶段训练策略 (`cfg.train_xpeng`)：

- **Phase 1**：地面训练，迭代 `iterations_ground` 次（默认 30000）
- **Phase 2**：完整 Street Gaussian 训练，迭代 `iterations_streetgaussian` 次（默认 50000）

Phase 2 中地面模型可选仅优化 opacity（`phase2_ground_only_opacity`），位置和旋转冻结。

### 3.3 损失函数

#### 3.3.1 主要重建损失

```
L_total = λ_l1 · L1(rgb_pred, rgb_gt) + λ_dssim · (1 - SSIM(rgb_pred, rgb_gt))
```

默认 `λ_l1 = 1.0`，`λ_dssim = 0.2`。

#### 3.3.2 可选正则化损失

| 损失 | 配置键 | 公式/说明 |
|------|--------|----------|
| 天空损失 | `lambda_sky` | 天空区域的 L1 损失 |
| 语义损失 | `lambda_semantic` | 交叉熵或 logits 损失 |
| LiDAR 深度 | `lambda_depth_lidar` | 渲染深度与 LiDAR 深度的 L1 |
| 单目深度 | `lambda_depth_mono` | 渲染深度与单目估计深度的损失 |
| LiDAR 法线 | `lambda_normal_lidar` | 渲染法线与 LiDAR 法线的一致性 |
| 单目法线 | `lambda_normal_mono` | 渲染法线与单目估计法线的一致性 |
| 颜色校正正则 | `lambda_color_correction` | 仿射矩阵偏离单位矩阵的惩罚 |
| 位姿校正正则 | `lambda_pose_correction` | 位姿校正偏离零的惩罚 |
| 缩放平坦化 | `lambda_scale_flatten` | 约束高斯趋向扁平 |
| 稀疏不透明度 | `lambda_opacity_sparse` | 鼓励不透明度稀疏 |
| 地面累积不透明度 | `lambda_ground_acc` | 地面区域的累积不透明度约束 |
| 地面平坦性 | `lambda_ground_flatten` | sz→0, roll→0, pitch→0 |
| 地面对称性 | `lambda_ground_symmetry` | sx≈sy, xy 旋转≈I |
| 背景最大缩放 | `lambda_background_maxscale` | 限制背景高斯最大尺寸 |
| 物体包围盒正则 | `lambda_object_box_reg` | 惩罚超出包围盒的高斯 |

#### 3.3.3 地面正则化损失详解

```python
# ground_flatten_loss
ground_flatten_loss = |sz|.mean() + |roll|.mean() + |pitch|.mean()

# ground_symmetry_loss
isotropy_loss = |sx - sy|.mean()
rotation_loss = mean((R_xy - I_2×2)²)
ground_symmetry_loss = isotropy_loss + rotation_loss

# ground_regularization_loss（综合版）
z_axis = R[:, :, 2]  # 局部 z 轴
flatten_loss = z_axis[:, :2].pow(2).sum(-1).mean()  # z 轴应指向 [0,0,1]
upward_loss = (1.0 - z_axis[:, 2]).abs().mean()
```

### 3.4 自适应密度控制

#### 3.4.1 梯度累积

每次前向传播后，累积屏幕空间梯度：

```python
# diff-gaussian-rasterization 模式
xyz_gradient_accum[vis, 0:1] += norm(grad[vis, :2])   # xy 梯度范数
xyz_gradient_accum[vis, 1:2] += norm(grad[vis, 2:])    # depth 梯度范数
denom[vis] += 1

# gsplat 模式（使用 absgrad）
xyz_gradient_accum[vis, 0] += sqrt((grad_x * W/2)² + (grad_y * H/2)²)
xyz_gradient_accum[vis, 1] += sqrt((absgrad_x * W/2)² + (absgrad_y * H/2)²)
```

#### 3.4.2 Clone（克隆）

梯度大但尺寸小的高斯被克隆：

```python
selected = (grads >= grad_threshold) & (max_scaling <= percent_dense * extent)
# 直接复制所有属性
```

#### 3.4.3 Split（分裂）

梯度大且尺寸大的高斯被分裂为 N=2 个：

```python
selected = (grads >= grad_threshold) & (max_scaling > percent_dense * extent)
# 在原始高斯范围内高斯采样 N 个新点
samples = Normal(mean=0, std=scaling)
new_xyz = R @ samples + xyz_original  # 旋转到世界坐标
new_scaling = scaling / (0.8 * N)      # 缩小尺寸
# 删除原始点，保留新点
```

#### 3.4.4 Prune（剪枝）

```python
prune_mask = (opacity < min_opacity)                    # 不透明度过低
prune_mask |= (max_radii2D > max_screen_size)           # 屏幕投影过大
prune_mask |= (max_scaling > extent * percent_big_ws)   # 世界空间过大
# Actor 额外：超出包围盒的点
```

#### 3.4.5 Opacity Reset

每 `opacity_reset_interval`（默认 3000）次迭代，将所有不透明度重置为 `sigmoid⁻¹(0.01)`：

```python
opacities_new = inverse_sigmoid(min(opacity, 0.01))
```

#### 3.4.6 密度化时间窗口

```
densify_from_iter = 500
densify_until_iter = 15000
densification_interval = 100
```

SH degree 逐步提升：从 0 阶开始，每 1000 次迭代提升一阶直到 `max_sh_degree`。

---

## 4. 推理与渲染

### 4.1 渲染器架构

`StreetGaussianRenderer` 支持两种光栅化后端：

| 后端 | 配置 | 特点 |
|------|------|------|
| `diff-gaussian-rasterization` | `use_gsplat=False`（默认） | 原始 3DGS 光栅化器 |
| `gsplat` | `use_gsplat=True` | 支持 antialiased 模式、absgrad |

### 4.2 完整渲染流程

```
render(camera, pc) 流程:
│
├─ Step 1: 设置可见性 → pc.set_visibility(include_list)
├─ Step 2: 解析相机 → pc.parse_camera(camera)
│   ├─ 构建场景图（确定可见物体）
│   ├─ 查询物体位姿（ActorPose 插值）
│   ├─ 局部→世界坐标变换
│   └─ 记录各组件索引范围
│
├─ Step 3: 属性拼接
│   ├─ means3D = pc.get_xyz          # [N_total, 3]
│   ├─ scales = pc.get_scaling       # [N_total, 3]
│   ├─ rotations = pc.get_rotation   # [N_total, 4]
│   ├─ opacity = pc.get_opacity      # [N_total, 1]
│   └─ shs = pc.get_features         # [N_total, (L+1)², 3]
│
├─ Step 4: 光栅化
│   └─ rasterizer(means3D, means2D, opacities, shs, scales, rotations, ...)
│       → rendered_color [3, H, W]
│       → rendered_acc   [1, H, W]
│       → rendered_depth [1, H, W]
│       → radii          [N_total] 或 [N_total, K]
│
├─ Step 5: 天空合成（如启用 SkyCubeMap）
│   ├─ sky_color = sky_cubemap(camera, acc.detach())  # [3, H, W]
│   └─ rgb = rgb + sky_color * (1 - acc)
│
├─ Step 6: 颜色校正（如启用）
│   └─ rgb = color_correction(camera, rgb)
│       # rgb = A[:3,:3] @ rgb + A[:3,3]
│
└─ Step 7: Clamp（推理时）
    └─ rgb = clamp(rgb, 0, 1)
```

### 4.3 diff-gaussian-rasterization 后端

```python
rasterizer = make_rasterizer(camera, max_sh_degree, bg_color, scaling_modifier)
rendered_color, radii, rendered_depth, rendered_acc, rendered_feature = rasterizer(
    means3D=means3D,       # [N, 3]
    means2D=means2D,       # [N, 3] (屏幕空间，用于梯度)
    opacities=opacity,     # [N, 1]
    shs=shs,               # [N, (L+1)², 3] 或 None
    colors_precomp=None,   # [N, 3] 或 None
    scales=scales,         # [N, 3]
    rotations=rotations,   # [N, 4]
    semantics=features,    # [N, D] 附加特征（法线、语义等）
)
# 输出:
# rendered_color:  [3, H, W]
# radii:           [N]
# rendered_depth:  [1, H, W]
# rendered_acc:    [1, H, W]
# rendered_feature:[D, H, W]
```

### 4.4 gsplat 后端

```python
render_colors, render_alphas, meta = gsplat.rasterization(
    means=means3D,                    # [P, 3]
    quats=rotations,                  # [P, 4]
    scales=scales,                    # [P, 3]
    opacities=opacity.squeeze(-1),    # [P]（注意：gsplat 要求 1D）
    colors=shs,                       # [P, M, 3] 或 [P, 3]
    viewmats=camera.RT.unsqueeze(0),  # [1, 4, 4]
    Ks=camera.K.unsqueeze(0),         # [1, 3, 3]
    width=W, height=H,
    sh_degree=max_sh_degree,
    near_plane=znear, far_plane=zfar,
    tile_size=8,
    backgrounds=bg_color.unsqueeze(0),
    render_mode='RGB+ED',             # 训练时含深度
    rasterize_mode='classic',         # 或 'antialiased'
    absgrad=True,                     # 训练时启用
)
# render_colors: [1, H, W, 4] (RGB+Depth)
# render_alphas: [1, H, W, 1]
# meta['means2d']: [1, P, 2] (屏幕空间坐标)
# meta['radii']:   [1, P, K]
```

### 4.5 分层渲染

`render_all` 方法支持分层渲染，用于可视化和调试：

```python
result = renderer.render_all(camera, pc)
# result['rgb']            → 完整合成图像 [3, H, W]
# result['acc']            → 累积不透明度 [1, H, W]
# result['rgb_background'] → 仅背景 [3, H, W]
# result['acc_background'] → 背景不透明度 [1, H, W]
# result['rgb_ground']     → 仅地面 [3, H, W]
# result['rgb_object']     → 仅动态物体 [3, H, W]
# result['depth']          → 深度图 [1, H, W]
# result['semantic']       → 语义图 [C, H, W]（如启用）
# result['normals']        → 法线图 [3, H, W]（如启用）
```

### 4.6 SH 颜色计算

当 `convert_SHs_python=True` 时，在 Python 端计算 SH→RGB：

```python
shs_view = features.transpose(1, 2).view(-1, 3, (L+1)²)  # [N, 3, (L+1)²]
dir_pp = xyz - camera_center                                # [N, 3]
dir_pp_normalized = dir_pp / dir_pp.norm(dim=1, keepdim=True)
sh2rgb = eval_sh(active_sh_degree, shs_view, dir_pp_normalized)  # [N, 3]
colors = clamp_min(sh2rgb + 0.5, 0.0)                            # [N, 3]
```

---

## 5. 数据处理

### 5.1 数据集支持

| 数据集 | Reader | 配置 `data.type` |
|--------|--------|-----------------|
| Colmap | `readColmapSceneInfo` | `"Colmap"` |
| Blender | `readNerfSyntheticInfo` | `"Blender"` |
| Waymo | `readWaymoFullInfo` | `"Waymo"` |
| XPeng | `readXpengFullInfo` | `"Xpeng"` |

### 5.2 XPeng 数据读取流程 (`readXpengFullInfo`)

#### 5.2.1 输入数据结构

```
source_path/
├── input_ply/
│   ├── points3D_bkgd.ply          # 背景点云
│   └── points3D_obj_XXXXXXXXX.ply # 各物体点云
├── surfel_ground/
│   └── ground_surfel.ply          # Surfel 地面点云
├── g3r_ground/
│   └── g3r_ground.ply             # G3R 地面重建
├── ground_mask.npy                # 地面掩码（布尔数组）
├── segs/                          # 语义分割掩码
│   └── cam{N}/{frame}.png
├── depth/                         # LiDAR 深度图
│   └── cam{N}/{frame}.npy
├── mono_normal/                   # 单目法线估计
│   └── cam{N}/{frame}.npy
├── normal_pcd/                    # LiDAR 法线
│   └── cam{N}/{frame}.npy
└── masks/                         # 自车遮挡掩码
    └── cam{N}/{frame}.png
```

#### 5.2.2 数据解析流程

```
1. generate_dataparser_outputs(datadir)
   → 解析标注文件，获取：
     - exts [N_img, 4, 4]     相机外参
     - ixts [N_img, 3, 3]     相机内参
     - poses [N_img, 4, 4]    自车位姿（ego pose）
     - c2ws [N_img, 4, 4]     camera-to-world
     - obj_tracklets [F, M, 8] 物体轨迹（track_id, x, y, z, qw, qx, qy, qz）
     - obj_info {track_id: meta} 物体元数据

2. 构建 CameraInfo 列表
   → 每张图像一个 CameraInfo，包含：
     - R, T: 旋转矩阵转置、平移向量
     - FovX, FovY: 视场角（从焦距计算）
     - K: 3×3 内参矩阵
     - metadata: 帧号、相机名、时间戳、ego_pose、外参等

3. 划分训练/测试集
   → get_val_frames(num_frames, test_every, train_every)

4. 构建场景元数据
   → scene_center, scene_radius: NeRF++ 归一化
   → sphere_center, sphere_radius: 点云包围球
   → 地面/背景点云分离（通过 ground_mask.npy）

5. 构建点云字典
   point_cloud_dict = {
       'background': pcd[~ground_mask],
       'ground': fetchG3RPly(...) 或 fetchGroundSurfelPly(...) 或 pcd[ground_mask]
   }
```

#### 5.2.3 相机模型

支持 7 个相机（`cameras: [1, 2, 3, 4, 5, 6, 7]`），每个相机的关键属性：

| 属性 | 说明 |
|------|------|
| `ego_pose` | 自车位姿 `[4, 4]` |
| `ego_pose_smoothed` | 平滑后的自车位姿 |
| `extrinsic` | 相机外参（相机→车辆） `[4, 4]` |
| `RT` | world-to-camera `[4, 4]` |
| `K` | 内参矩阵 `[3, 3]` |
| `FovX, FovY` | 水平/垂直视场角 |
| `camera_center` | 相机中心世界坐标 `[3]` |
| `timestamp` | 时间戳 |

### 5.3 场景归一化

```python
# NeRF++ 归一化
nerf_normalization = getNerfppNorm(train_cam_infos)
# center = 所有相机中心的均值
# radius = max(相机中心到 center 的距离) * 1.1
# radius = max(radius, 10)  # 下限 10 米

# 点云包围球
sphere_normalization = get_Sphere_Norm(points)
# center = 点云中心
# radius = max(点到 center 的距离)
```

### 5.4 `CameraDataset`

继承 `torch.utils.data.Dataset`，支持按需加载：

```python
class CameraDataset(TorchDataset):
    def __getitem__(self, idx) -> Camera:
        camera_info = self.camera_infos[idx]
        return load_camera_on_demand(camera_info, resolution_scale=1)
```

特殊处理：`cam7` 在位姿优化阶段前按 `cam7_sample_rate` 降采样。

### 5.5 Scene 管理

`Scene` 类协调数据集和模型：

```python
class Scene:
    def __init__(self, gaussians, dataset):
        if cfg.mode == 'train':
            # 从点云创建高斯模型
            gaussians.create_from_pcd(point_cloud_dict, scene_radius)
        else:
            # 加载 checkpoint
            state_dict = torch.load(checkpoint_path)
            gaussians.load_state_dict(state_dict)
    
    def save(self, iteration):
        # 保存 PLY 点云 + 可视化 PLY
        gaussians.save_ply(point_cloud_path)
        gaussians.save_ply_vis(vis_dir)
```

---

## 6. 目录结构速查

```
street_gaussians/
├── lib/
│   ├── config/
│   │   ├── config.py              # 全局配置定义（cfg 对象，所有超参数）
│   │   ├── globals.py             # 全局变量
│   │   └── yacs.py                # YACS 配置系统
│   │
│   ├── models/
│   │   ├── gaussian_model.py          # 基础高斯模型（所有组件的基类）
│   │   ├── gaussian_model_bkgd.py     # 背景高斯模型
│   │   ├── gaussian_model_grd.py      # 地面高斯模型
│   │   ├── gaussian_model_actor.py    # 动态物体高斯模型（傅里叶 SH）
│   │   ├── gaussian_model_sky.py      # 天空高斯模型
│   │   ├── street_gaussian_model.py   # 场景图组装（核心调度器）
│   │   ├── street_gaussian_renderer.py# 分层渲染器（diff-raster / gsplat）
│   │   ├── gaussian_renderer.py       # 基础渲染器
│   │   ├── scene.py                   # 场景管理（数据集↔模型桥梁）
│   │   ├── actor_pose.py             # 物体位姿管理（tracklet 插值+优化）
│   │   ├── sky_cubemap.py            # 天空立方体贴图
│   │   ├── appearance_network.py     # 外观解耦网络（GOF）
│   │   ├── color_correction.py       # 颜色校正（仿射变换 / MLP）
│   │   └── camera_pose.py           # 相机位姿校正
│   │
│   ├── datasets/
│   │   ├── dataset.py                # 数据集基类 + CameraDataset
│   │   ├── base_readers.py           # 基础数据读取工具
│   │   ├── xpeng_full_readers.py     # XPeng 数据读取器
│   │   ├── waymo_full_readers.py     # Waymo 数据读取器
│   │   ├── colmap_readers.py         # Colmap 数据读取器
│   │   └── blender_readers.py        # Blender 数据读取器
│   │
│   ├── utils/
│   │   ├── camera_utils.py           # 相机工具（Camera 类、光栅化器构建）
│   │   ├── general_utils.py          # 通用工具（四元数运算、LR 调度）
│   │   ├── sh_utils.py               # 球谐函数（eval_sh、RGB2SH、IDFT）
│   │   ├── graphics_utils.py         # 图形工具（BasicPointCloud、射线生成）
│   │   ├── loss_utils.py             # 损失函数（L1、SSIM）
│   │   ├── metric_utils.py           # 评估指标（PSNR、SSIM、LPIPS）
│   │   ├── xpeng_utils.py            # XPeng 数据解析工具
│   │   └── ...
│   │
│   └── visualizers/
│       ├── street_gaussian_visualizer.py  # 渲染可视化
│       └── xpeng_visualizer.py            # XPeng 专用可视化
```

---

## 7. 参考资料

### 7.1 核心论文

- **3D Gaussian Splatting for Real-Time Radiance Field Rendering** (Kerbl et al., SIGGRAPH 2023)
- **Street Gaussians for Modeling Dynamic Urban Scenes** (Yan et al., 2024)
- **Neural Scene Graphs for Dynamic Scenes** (Ost et al., CVPR 2021)

### 7.2 关键依赖

| 库 | 用途 |
|----|------|
| `diff-gaussian-rasterization` | 可微高斯光栅化（CUDA） |
| `gsplat` | 替代光栅化后端（支持 antialiased） |
| `simple_knn` | CUDA KNN 距离计算（初始化 scaling） |
| `nvdiffrast` | 可微渲染（天空 CubeMap 采样） |
| `plyfile` | PLY 点云读写 |
| `bidict` | 双向字典（模型名↔ID 映射） |

### 7.3 关键数据流总结

```
输入数据
  ├─ LiDAR 点云 → Background/Ground 初始化
  ├─ 物体点云 → Actor 初始化
  ├─ 相机参数 → Camera 对象
  ├─ 物体轨迹 → ActorPose
  └─ 语义/深度/法线 → 监督信号

训练循环
  ├─ parse_camera → 场景图构建
  ├─ render_kernel → 光栅化
  ├─ loss 计算 → 反向传播
  ├─ optimizer.step → 参数更新
  └─ densify_and_prune → 自适应密度控制

推理输出
  ├─ RGB 图像 [3, H, W]
  ├─ 深度图 [1, H, W]
  ├─ 累积不透明度 [1, H, W]
  ├─ 语义图 [C, H, W]（可选）
  └─ 法线图 [3, H, W]（可选）
```
