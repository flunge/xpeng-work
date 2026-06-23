# G3R 模块技术分析文档

> G3R (Gaussian 3D Reconstruction) — 基于稀疏视角输入的 3D Gaussian 重建系统

---

## 1. 概述

G3R 是一个从稀疏输入视角重建 3D Gaussian 表示的深度学习模块。其核心思想是：给定一组稀疏的多视角图像及对应的相机参数和初始 3D 点云，通过**稀疏卷积 UNet** 网络对 3D 点的隐式特征进行迭代优化，最终输出高质量的 3D Gaussian Splatting 表示，用于新视角合成。

### 1.1 核心设计理念

- **迭代式梯度反馈优化**：采用类似扩散模型的多步迭代策略（默认 `T=5` 步），每一步通过渲染损失的梯度反馈来引导特征更新方向
- **稀疏 3D 卷积**：利用 `torchsparse` 库的稀疏卷积操作，在体素化的 3D 空间中高效处理大规模点云（百万级别）
- **区域分治**：将场景分为 `ground`（地面）和 `bkgd`（背景）两个区域，分别训练独立模型，针对不同区域特性采用不同的参数化策略
- **多相机融合**：支持多相机（cam0~cam6）数据输入，推理时通过加权平均策略融合不同相机视角的重建结果

### 1.2 技术栈

| 组件 | 技术选型 | 用途 |
|------|---------|------|
| 3D 稀疏卷积 | `torchsparse` | 稀疏 UNet 骨干网络 |
| Gaussian 渲染 | `gsplat` | 可微分 Gaussian Splatting 光栅化 |
| 感知损失 | LPIPS (AlexNet) | 感知质量评估 |
| 点云量化 | `torchsparse.utils.quantize` | 体素化稀疏点云 |
| 点云 I/O | `plyfile` | PLY 格式读写 |

### 1.3 输入/输出规格

**输入**：
- 初始 3D 点云（PLY 格式，含位置、旋转四元数、颜色）
- 多视角图像（PNG 格式）
- 相机内外参（`transform.json`）
- 语义分割图（用于区域掩码）

**输出**：
- 优化后的 3D Gaussian 属性字典：`means`（位置）、`scales`（尺度）、`rotations`（旋转）、`opacities`（不透明度）、`colors`（颜色）
- PLY 格式的 Gaussian 点云文件

---

## 2. 模型结构

### 2.1 整体架构

G3R 的网络架构由三个核心组件构成：

```
输入点云 → 初始化 Neural Gaussians → [迭代 T 步]:
  ├─ 1. 渲染当前 Gaussians → 计算损失 → 反向传播获取梯度反馈
  ├─ 2. 拼接 [当前特征, 梯度反馈] → 构建稀疏张量
  ├─ 3. SparseResUNet 处理 → 输出特征更新量
  ├─ 4. 加权更新: S_{t+1} = S_t + γ_t * ΔS
  └─ 5. NeuralGaussiansDecoder 解码 → 新的 Gaussian 属性
```

### 2.2 G3RReconstructor（主网络）

**文件**：`g3r_net.py` — 类 `G3RReconstructor(nn.Module)`

这是 G3R 的顶层模块，负责编排整个迭代优化流程。

#### 2.2.1 初始化参数

```python
G3RReconstructor(cfg, log_folder)
```

- `cfg`：配置字典（来自 `config.py`）
- `log_folder`：日志/调试图像保存路径

内部创建：
- `self.decoder`：`NeuralGaussiansDecoder` — 特征→Gaussian 属性解码器
- `self.g3r_net`：`SparseResUNet` — 稀疏卷积 UNet 骨干
- `self.optimizer`：Adam 优化器，学习率 `1e-4`
- `self.scheduler`：指数衰减调度器，`gamma=0.99998`
- `self.ssim_metric`：SSIM 评估指标

#### 2.2.2 Neural Gaussians 初始化

`initialize_neural_gaussians(points)` 方法将原始点云属性拆分并构建初始特征向量：

| 属性 | 维度 | 来源 |
|------|------|------|
| `priori_xyz` | 3 | 点云位置 `[:, :3]` |
| `priori_rotations` | 4 | 点云旋转四元数 `[:, 3:7]` |
| `priori_colors` | 3 | 点云颜色 `[:, 7:10]` |
| `priori_scales` | 3 | 点云尺度 `[:, 10:13]` |
| `input_opacities` | 1 | 点云不透明度 `[:, 13]` |

初始特征向量 `other_dims` 的构成（ground 区域）：

```
[delta_scales(3), opacity(1), delta_colors(3), latent(16)] → 总维度 23
```

初始特征向量 `other_dims` 的构成（bkgd 区域）：

```
[delta_scales(3), opacity(1), delta_colors(3), delta_rotations(4), latent(24)] → 总维度 35
```

#### 2.2.3 梯度反馈机制

`compute_gradient_feedback()` 是 G3R 的核心创新点：

1. 克隆当前特征并开启梯度追踪
2. 通过 Decoder 解码为 Gaussian 属性
3. 渲染图像并计算损失
4. 对特征求梯度 `∂L/∂S`
5. 对梯度做逐样本归一化（除以每个点的最大绝对梯度值）

```python
grad = torch.autograd.grad(outputs=step_loss, inputs=features_for_grad)[0]
max_abs = torch.max(torch.abs(grad), dim=1, keepdim=True)[0] + 1e-8
grad_norm = grad / max_abs
```

这个归一化梯度作为"方向信号"拼接到当前特征上，指导 UNet 的更新方向。

#### 2.2.4 前向传播（训练）

`forward()` 方法执行完整的 T 步迭代：

```
for t_step in range(T_iterations):  # 默认 T=5
    1. optimizer.zero_grad()
    2. grad_S_t = compute_gradient_feedback(S_t, ...)  # 梯度反馈
    3. x_in = cat([S_t, grad_S_t])                     # 拼接输入 (dim × 2)
    4. sparse_in = SparseTensor(feats=x_in, coords=coords)
    5. update = g3r_net(sparse_in, t_step)[-1]          # UNet 输出
    6. S_{t+1} = S_t + γ_t * update.feats              # 加权更新
    7. gaussians = decoder(S_{t+1}, ...)                # 解码
    8. loss = compute_loss(gaussians, all_views)        # 全视角损失
    9. loss.backward() → optimizer.step()
    10. S_t = S_{t+1}.detach()                          # 截断梯度
```

关键点：
- 每步使用**随机子集视角**计算梯度反馈（`num_src_views_train=15`），但用**全部视角**计算训练损失
- 更新权重 `γ_t` 来自余弦调度（cosine schedule），随步数递减
- 每步之间通过 `.detach()` 截断梯度，避免跨步反向传播

### 2.3 NeuralGaussiansDecoder（Gaussian 解码器）

**文件**：`g3r_net.py` — 类 `NeuralGaussiansDecoder(nn.Module)`

将 UNet 输出的隐式特征解码为显式的 Gaussian 属性。

#### 2.3.1 网络结构

```
features (total_latent_dim)
    │
    ├─ mlp: Linear(total_latent_dim → explicit_dim) + Tanh
    │   → delta_attributes（残差属性）
    │
    ├─ mlp_color: Linear(3→3) → ReLU → Linear(3→3) → Sigmoid
    │   → 颜色修正（加到 priori_colors 上）
    │
    └─ [仅 bkgd] mlp_rotations: Linear(4→4)
        → 旋转增量（四元数乘法叠加到 priori_rotations）
```

#### 2.3.2 区域差异化解码策略

**Ground 区域**（`explicit_dim=7`）：

| 输出属性 | 计算方式 | 值域约束 |
|---------|---------|---------|
| scales_xy | `0.02 * sigmoid(delta[:, 0:2]) + priori_scales_xy` | 在先验基础上微调 |
| scales_z | `0.01 * sigmoid(delta[:, 2]) + priori_scales_z` | z 方向尺度更小（地面薄片） |
| opacities | `sigmoid(delta[:, 3])` | [0, 1] |
| colors | `mlp_color(delta[:, 4:7]) + priori_colors` | 残差颜色 |

**Bkgd 区域**（`explicit_dim=11`）：

| 输出属性 | 计算方式 | 值域约束 |
|---------|---------|---------|
| scales | `sigmoid(delta[:, 0:3]) * 0.1` | 最大 0.1 |
| opacities | `sigmoid(delta[:, 3])` | [0, 1] |
| colors | `mlp_color(delta[:, 4:7]) + priori_colors` | 残差颜色 |
| rotations | `normalize(mlp_rot(delta[:, 7:11])) ⊗ priori_rot` | 四元数乘法组合 |

关键设计：
- Ground 区域**保留先验旋转不变**（地面法线方向固定），仅微调尺度
- Bkgd 区域**允许旋转自由度**，通过四元数乘法叠加增量旋转
- 颜色使用**残差学习**：`mlp_color` 的 bias 初始化为负值（-0.1 和 -2.0），使初始输出接近零

### 2.4 SparseResUNet（稀疏卷积 UNet）

**文件**：`sparse_unet.py` — 类 `SparseResUNet(nn.Module)`

基于 `torchsparse` 实现的 3D 稀疏卷积 U-Net，是 G3R 的特征提取骨干网络。

#### 2.4.1 网络配置

```python
SparseResUNet(
    stem_channels=32,
    time_embedding_channels=32,
    encoder_channels=[64, 128, 256, 512],
    decoder_channels=[256, 128, 64, total_latent_dim],
    in_channels=total_latent_dim * 2,  # 特征 + 梯度反馈
    width_multiplier=1.0
)
```

#### 2.4.2 架构详解

**Stem 层**：
```
Input(total_latent_dim×2) → Conv3d(3) → BN → ReLU → Conv3d(3) → BN → ReLU → 32ch
```

**Encoder（4 层下采样）**：
```
每层: SparseConvBlock(stride=2 下采样) → SparseResBlock × 2
通道变化: 32 → 64 → 128 → 256 → 512
```

**Bottleneck**：
- 在最深层注入**时间步嵌入**（正弦位置编码，维度 32）
- 时间嵌入通过 `torchsparse.cat` 拼接到特征上

**Decoder（4 层上采样）**：
```
每层: ConvTranspose3d(stride=2 上采样) → cat(skip_connection) → SparseResBlock × 2
通道变化: 512+32 → 256 → 128 → 64 → total_latent_dim
```

#### 2.4.3 递归式 U-Net 前向传播

`_unet_forward` 使用**递归**实现 U-Net 的编码-解码结构：

```python
def _unet_forward(self, x, encoders, decoders, t_step):
    if not encoders and not decoders:
        # 到达 bottleneck：注入时间嵌入
        time_emb = self.time_embed(t_step).expand(x.feats.shape[0], -1)
        return [torchsparse.cat([x, time_emb_sp])]

    xd = encoders[0](x)                                    # 下采样
    outputs = self._unet_forward(xd, encoders[1:], decoders[:-1], t_step)  # 递归
    u = decoders[-1]["upsample"](outputs[-1])               # 上采样
    y = decoders[-1]["fuse"](torchsparse.cat([u, x]))       # 跳跃连接 + 融合
    return [x] + outputs + [y]
```

返回值是所有中间层输出的列表，训练时取 `[-1]`（最终输出）。

#### 2.4.4 基础构建块

| 模块 | 结构 | 用途 |
|------|------|------|
| `SparseConvBlock` | Conv3d → BN → ReLU | 基础卷积块 |
| `SparseConvTransposeBlock` | ConvTranspose3d → BN → ReLU | 上采样块 |
| `SparseResBlock` | Conv3d → BN → ReLU → Conv3d → BN + Shortcut → ReLU | 残差块（含 1×1 shortcut） |
| `TimeEmbedding` | 正弦/余弦位置编码 | 时间步编码（dim=32） |

#### 2.4.5 时间步嵌入

```python
class TimeEmbedding(nn.Module):
    # 正弦位置编码，与 Transformer / 扩散模型中的时间嵌入一致
    freqs = exp(arange(half_dim) * -(log(10000) / (half_dim - 1)))
    # 输出: [cos(t*f_0), ..., cos(t*f_n), sin(t*f_0), ..., sin(t*f_n)]
```

时间步 `t_step ∈ {0, 1, ..., T-1}` 被编码为 32 维向量，在 bottleneck 层拼接到每个体素的特征上，使网络感知当前迭代步数。

---

## 3. 训练流程

### 3.1 训练入口

**文件**：`train_g3r.py` — 函数 `train_g3r(log_folder, config, checkpoint)`

```bash
python train_g3r.py --job_name <实验名> --region <ground|bkgd> [--checkpoint <pth路径>]
```

### 3.2 训练数据流

```
epoch 循环:
  └─ case 循环 (training_cases):
      ├─ 下载数据（如不存在）
      ├─ XpengDataset 加载点云 + 体素化
      └─ camera 循环 (cam0~cam6):
          ├─ dataset.get_xpeng_scene(cam_name) 加载图像/相机参数
          └─ batch 循环 (DataLoader):
              ├─ 按 valid_ids 筛选可见点
              ├─ G3RReconstructor.forward() → T 步迭代优化
              ├─ 记录 loss/psnr/lpips
              └─ 定期评估 + 保存 checkpoint
```

### 3.3 数据集（XpengDataset）

**文件**：`dataset.py` — 类 `XpengDataset(Dataset)`

#### 3.3.1 点云加载与体素化

1. **加载原始点云**：
   - Ground：从 `surfel_ground/ground_surfel.ply` 读取（含法线→四元数）
   - Bkgd：从 `input_ply/points3D_bkgd.ply` 读取，用 `ground_mask.npy` 排除地面点

2. **体素化量化**（`process_points`）：
   - 点云坐标减去最小值归零
   - 使用 `sparse_quantize(voxel_size=0.04)` 进行体素化
   - 返回量化后的稀疏坐标 `coords` 和对应索引 `indices`
   - 未被量化选中的点保存为 `unquantized_points_info`（推理时用于修复）

3. **尺度估计**：通过 KD-Tree 计算每个点到最近邻的 2D 距离作为初始 `scales_xy`

#### 3.3.2 场景图像加载

`get_xpeng_scene(cam_name)` 流程：

1. 从 `transform.json` 读取相机元数据，按时间戳排序
2. 如果帧数超过 `sample_camera_num`（默认 300），均匀采样
3. 多线程并行处理每帧（`process_frame`）：
   - 加载图像，应用语义掩码（ground/bkgd/sky/vehicle 分离）
   - 计算世界→相机变换矩阵
   - 将 3D 点投影到图像平面，筛选可见点（`valid_columns`）
   - 训练时对 cam0/cam2 图像做 0.5× 降采样（节省显存）
4. 按 `num_batch_views`（默认 30）分批

#### 3.3.3 可见性检查

`process_frame` 中的可见性判断包含多重过滤：

| 检查项 | 条件 |
|--------|------|
| 深度正值 | `cam_points[-1] > 0` |
| 最大距离 | `cam_points[-1] < max_distance`（推理时按相机调整） |
| 水平范围 | `left_bound < proj_x < right_bound`（推理时裁剪边缘） |
| 垂直范围 | `0 < proj_y < image_height` |
| 语义掩码 | 投影点落在对应区域掩码内 |

#### 3.3.4 Collate 函数

`sparse_scenes_collate` 将单个 batch 的数据整理为：

```python
cameras_info = {
    "timestamps": List[str],
    "extrinsics": Tensor[N, 4, 4],   # 世界→相机矩阵
    "intrinsics": Tensor[N, 3, 3],   # 相机内参
    "images": Tensor[N, 3, H, W]     # GT 图像
}
```

### 3.4 损失函数

**文件**：`g3r_net.py` — `compute_loss()` 方法，`utils/loss_utils.py`

#### 3.4.1 渲染

使用 `gsplat.rasterization` 进行可微分 Gaussian Splatting 渲染：

```python
gsplat.rasterization(
    means, quats, scales, opacities, colors,
    viewmats, Ks, width, height,
    near_plane=0.01, far_plane=1e10,
    sparse_grad=True,          # 训练时启用稀疏梯度
    rasterize_mode="antialiased",
    absgrad=True,
    packed=True                # 训练时启用 packed 模式
)
```

渲染后对 GT 图像中全黑区域（`== 0`）进行掩码处理，将对应渲染像素置零。

#### 3.4.2 损失组成

总损失公式：

```
L_total = N × (λ_mse × L_mse) + λ_lpips × L_lpips + λ_reg × L_reg
```

| 损失项 | 权重 | 计算方式 |
|--------|------|---------|
| MSE Loss | `λ_mse = 1.0` | `F.mse_loss(rendered, gt)` |
| LPIPS Loss | `λ_lpips = 0.01` | `lpips(rendered, gt, net='alex')` |
| Scale Regularization | `λ_reg = 0.01` | `ReLU(max_scale - ε).mean()`，`ε=0.1` |

其中 `N` 为当前 batch 的图像数量，Scale Regularization 惩罚过大的 Gaussian 尺度。

#### 3.4.3 评估指标

| 指标 | 实现 | 说明 |
|------|------|------|
| PSNR | `loss_utils.psnr_metric` | 支持掩码，`20 * log10(1/√MSE)` |
| SSIM | `loss_utils.ssim` | 高斯窗口卷积实现，`window_size=11` |
| LPIPS | `lpips(net='alex')` | AlexNet 感知距离 |

### 3.5 训练配置详解

**文件**：`config.py` — `obtain_config(region_type)`

| 参数 | 值 | 说明 |
|------|-----|------|
| `lr` | 1e-4 | Adam 学习率 |
| `scheduler_gamma` | 0.99998 | 指数衰减因子 |
| `epochs` | 1000 | 训练轮数 |
| `T_iterations` | 5 | 每个样本的迭代优化步数 |
| `num_src_views_train` | 15 | 梯度反馈使用的视角数 |
| `num_batch_views` | 30 | 每 batch 的视角数 |
| `sample_camera_num` | 300 | 每相机最大采样帧数 |
| `voxel_size` | 0.04 | 体素化分辨率（米） |
| `num_points_train` | 3,000,000 | 训练点数上限 |
| `save_img_step` | 500 | 调试图像保存间隔 |
| `evaluation_step` | 2000 | 评估间隔 |

#### 3.5.1 区域特定维度

| 参数 | Ground | Bkgd |
|------|--------|------|
| `explicit_dim` | 7 | 11 |
| `latent_dim_only` | 16 | 24 |
| `total_latent_dim` | 23 | 35 |

`explicit_dim` 差异原因：Bkgd 额外包含 4 维旋转增量。

### 3.6 更新调度（Gamma Schedule）

```python
def get_cosine_schedule(T, beta_start=0.0001, beta_end=0.02, s=0.008):
    timesteps = torch.arange(T)
    return cos((timesteps/T + s) / (1+s) * π/2) ** 2
```

生成 T 个递减的权重 `γ_t`，早期步骤更新幅度大，后期步骤精细调整。这与扩散模型的噪声调度类似。

### 3.7 训练循环特点

1. **数据按需下载**：训练 case 不在本地时自动下载（`down_training_data`）
2. **用后即删**：每个 case 训练完后删除本地数据（`rm -rf`），节省磁盘
3. **逐相机处理**：同一 case 的不同相机依次处理，避免显存溢出
4. **积极的显存管理**：每个 batch 后 `gc.collect()` + `torch.cuda.empty_cache()`
5. **定期评估**：每 2000 步在验证集上运行推理并保存 checkpoint
6. **随机种子固定**：`seed=42`，保证可复现性

---

## 4. 推理流程

### 4.1 推理入口

**文件**：`inference.py`

```python
# 命令行方式
python inference.py --clip_id <clip_id>

# 编程接口
inference_g3r_interface(region_type, model_pth, source_data, log_folder)
```

### 4.2 推理配置调整

`modify_inference_config` 对训练配置做以下修改：

| 参数 | 训练值 | 推理值 | 原因 |
|------|--------|--------|------|
| `cam_names` | 6 个相机 | `[cam3, cam4, cam2, cam0]` | 仅用关键视角 |
| `num_points_train` | 3M | 15M | 推理不受显存限制 |
| `voxel_size` | 0.04 | 0.02 | 更精细的体素分辨率 |
| `sample_camera_num` | 300 | 50 | 减少采样帧数 |
| `num_batch_views` | 30 | 50 | 增大 batch 视角数 |

### 4.3 推理流程详解

```
inference_g3r(g3r_reconstructor, net_mode, cfg, source_data, log_folder):
  │
  ├─ 1. 加载数据集，获取点云 + 体素坐标
  │
  ├─ 2. 逐相机处理:
  │     for cam_name in [cam3, cam4, cam2, cam0]:
  │       for batch in eval_loader:
  │         ├─ 筛选当前 batch 可见的点 (curr_update_id)
  │         ├─ 限制最大点数 700,000（随机采样）
  │         ├─ 初始化 Neural Gaussians
  │         ├─ T 步迭代优化（与训练相同，但无梯度更新）
  │         └─ 加权累积到全局 Gaussians
  │
  ├─ 3. 多相机加权平均融合
  │
  ├─ 4. 修复未覆盖的点（repair_gaussians）
  │
  ├─ 5. 全视角指标评估
  │
  └─ 6. 保存 PLY 文件
```

### 4.4 多相机加权融合策略

推理时采用 `use_g3r_avg=True` 模式，不同相机对同一点的贡献有不同权重：

| 相机 | 权重 | 说明 |
|------|------|------|
| cam3 | 2.0 | 前向主相机，高权重 |
| cam4 | 2.0 | 前向主相机，高权重 |
| cam5 | 2.0 | 侧向相机 |
| cam6 | 2.0 | 侧向相机 |
| cam0 | 1.5 | 后向相机 |
| cam2 | 0.6 | 后向相机，低权重 |

融合过程（`ply_utils.py`）：

1. **累积阶段**（`update_g3r_gaussians_with_count`）：
   - `means` 和 `rotations`：直接覆盖（取最后一个相机的值）
   - `scales`、`colors`、`opacities`：加权累加
   - 记录每个点的累积权重 `update_id_counts`

2. **平均阶段**（`average_g3r_gaussians`）：
   - 对累加的属性除以总权重
   - 过滤掉权重为 0 的点（未被任何相机覆盖）

### 4.5 点云修复

`repair_gaussians` 处理两类未被 UNet 优化的点：

1. **未被任何相机覆盖的量化点**：使用原始初始属性填充
2. **体素化时被丢弃的非量化点**（`unquantized_points_info`）：直接追加

这确保最终输出的 Gaussian 点云覆盖完整场景。

### 4.6 推理时的视角裁剪

推理时对不同相机应用不同的投影范围限制：

| 相机 | 水平裁剪 | 最大距离（ground） |
|------|---------|-------------------|
| cam3/cam6 | 右侧 66% | 30m |
| cam4/cam5 | 左侧 33% 起 | 30m |
| cam0 | 全幅 | shift_distance + 60m |
| cam2 | 中间 33%~66% | shift_distance + 30m |

这避免了边缘畸变区域和过远点对重建质量的影响。

### 4.7 输出文件

| 文件 | 格式 | 内容 |
|------|------|------|
| `g3r_ground.ply` | 自定义 PLY | 原始 Gaussian 属性（px/py/pz/sx/sy/sz/opacity/rgb/qwxyz） |
| `g3r_ground_vis.ply` | 标准 GS PLY | 兼容 3DGS 查看器的格式（含 SH 系数） |
| `eval_metrics.txt` | 文本 | PSNR/LPIPS 指标记录 |

---

## 5. 目录结构速查

```
g3r/
├── g3r_net.py              # 主网络：G3RReconstructor + NeuralGaussiansDecoder
├── sparse_unet.py          # 稀疏卷积 UNet：SparseResUNet + 构建块
├── train_g3r.py            # 训练入口脚本
├── inference.py            # 推理入口脚本 + inference_g3r_interface API
├── dataset.py              # XpengDataset 数据集 + collate 函数
├── config.py               # 配置管理：obtain_config / modify_inference_config
├── utils/
│   ├── loss_utils.py       # 损失函数：SSIM / PSNR
│   ├── general_utils.py    # 通用工具：语义解析、调度器、图像保存、指标评估
│   ├── math_utils.py       # 数学工具：四元数运算、法线计算、KD-Tree 最近邻
│   ├── ply_utils.py        # PLY 工具：Gaussian 读写/合并/平均/修复/格式转换
│   ├── training_cases.py   # 训练 case ID 列表
│   └── downclip_utils.py   # 数据下载工具
└── fuyao/
    ├── run_g3r_train.bash  # 扶摇平台训练启动脚本
    └── deploy_g3r.bash     # 扶摇平台部署脚本
```

### 5.1 核心类/函数速查

| 类/函数 | 文件 | 职责 |
|---------|------|------|
| `G3RReconstructor` | g3r_net.py | 顶层模块，编排迭代优化 |
| `NeuralGaussiansDecoder` | g3r_net.py | 特征→Gaussian 属性解码 |
| `SparseResUNet` | sparse_unet.py | 3D 稀疏卷积 UNet 骨干 |
| `TimeEmbedding` | sparse_unet.py | 时间步正弦编码 |
| `XpengDataset` | dataset.py | 数据加载、体素化、可见性检查 |
| `train_g3r` | train_g3r.py | 训练主循环 |
| `inference_g3r` | inference.py | 推理主流程 |
| `inference_g3r_interface` | inference.py | 推理编程接口 |
| `obtain_config` | config.py | 获取区域配置 |
| `get_cosine_schedule` | general_utils.py | 余弦更新调度 |
| `psnr_metric` | loss_utils.py | PSNR 计算（支持掩码） |
| `ssim` | loss_utils.py | SSIM 计算（支持掩码和权重） |
| `update_g3r_gaussians_with_count` | ply_utils.py | 加权累积 Gaussians |
| `average_g3r_gaussians` | ply_utils.py | 加权平均融合 |
| `repair_gaussians` | ply_utils.py | 修复未覆盖点 |
| `quaternion_multiply_torch` | math_utils.py | 批量四元数乘法 |
| `nearest_distances_kdtree` | math_utils.py | KD-Tree 最近邻距离 |

---

## 6. 参考资料

### 6.1 相关论文与技术

| 技术 | 参考 | 在 G3R 中的应用 |
|------|------|----------------|
| 3D Gaussian Splatting | Kerbl et al., 2023 | 场景表示与可微渲染 |
| Sparse Convolution | Choy et al., 2019 (MinkowskiEngine) | 3D 特征提取骨干 |
| Diffusion-style Iterative Refinement | Ho et al., 2020 (DDPM) | 迭代优化策略与时间步嵌入 |
| LPIPS | Zhang et al., 2018 | 感知质量损失 |
| gsplat | Ye et al., 2024 | 高效 Gaussian 光栅化 |

### 6.2 关键依赖版本

| 包 | 用途 |
|----|------|
| `torch` | 深度学习框架 |
| `torchsparse` | 3D 稀疏卷积 |
| `gsplat` | Gaussian Splatting 渲染 |
| `plyfile` | PLY 文件读写 |
| `torchmetrics` | SSIM 指标 |
| `scipy` / `sklearn` | KD-Tree / 最近邻 |

### 6.3 数据格式

**transform.json 结构**：
```json
{
  "frames": [
    {
      "camera": "cam3",
      "timestamp": "1234567890",
      "transform_matrix": [[4x4 矩阵]],
      "fl_x": 1000.0, "fl_y": 1000.0,
      "cx": 960.0, "cy": 540.0
    }
  ]
}
```

**语义类别映射**（`general_utils.py`）：

| 类别 | 语义 ID 列表 | 用途 |
|------|-------------|------|
| GROUND | 7,8,13,14,23,24,41,10,36,43 | 地面区域掩码 |
| SKY | 27 | 天空掩码（bkgd 中排除） |
| VEHICLE | 52-65 | 车辆掩码 |
| HUMAN | 0,1,19-22 | 行人掩码 |
| ROADSIDE | 2-6,9,11,12,15,16,18,26,28 | 路侧掩码 |
