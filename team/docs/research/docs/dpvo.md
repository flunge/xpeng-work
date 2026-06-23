# DPVO 模块技术分析文档

> Deep Patch Visual Odometry — 基于深度学习的 Patch 级视觉里程计
>
> 模块路径：`xpeng_data_process/optimization/camopt/dpvo/`

---

## 1. 概述

### 1.1 模块定位

DPVO（Deep Patch Visual Odometry）是 SimWorld 三维重建数据处理流水线中的**相机位姿优化**模块，位于 `xpeng_data_process/optimization/camopt/` 子系统下。其核心职责是：

- 从单目图像序列中**在线估计相机 6-DoF 位姿**（平移 + 旋转，SE3 表示）
- 输出稀疏三维点云，供下游 3D Gaussian Splatting 等重建模块使用
- 支持**流式推理**（逐帧输入）和**回环检测**（Loop Closure）

### 1.2 核心思想

与传统稠密光流 VO 不同，DPVO 采用 **Patch-based** 策略：

1. 每帧图像提取 `M` 个稀疏 Patch（默认 `M=160`，大小 `3×3`）
2. 在 Patch 之间建立**因子图**（Factor Graph），边连接不同帧的 Patch 观测
3. 通过**可学习的更新算子**（Update Operator）迭代预测光流残差和置信度权重
4. 使用**可微分 Bundle Adjustment**（BA）联合优化位姿和 Patch 逆深度

### 1.3 在流水线中的调用方式

入口文件 `run_campose_est.py` 提供两个主要函数：

| 函数 | 输入 | 用途 |
|------|------|------|
| `run(cfg, network, imagedir, calib, ...)` | 图像目录 + 标定文件 | 通用图像序列位姿估计 |
| `run_vslam(user_cfg, network, clip_path, transform_name, ...)` | clip 路径 + transform JSON | 车端数据（含动态 mask）位姿估计 |

两者均返回 `(poses, tstamps), (points, colors, calib)`，其中 `poses` 为 `[N, 7]`（x y z qx qy qz qw）。

---

## 2. 模型结构

### 2.1 整体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         VONet (net.py)                          │
│                                                                 │
│  ┌──────────────────────┐    ┌──────────────────────────────┐   │
│  │   Patchifier          │    │   Update Operator             │   │
│  │                        │    │                                │   │
│  │  fnet (BasicEncoder4) │    │  corr MLP (2×49×P²→DIM→DIM)  │   │
│  │    → fmap [128,H/4,W/4]│    │  c1, c2 (邻域消息传递)        │   │
│  │                        │    │  agg_kk (Patch 内聚合)        │   │
│  │  inet (BasicEncoder4) │    │  agg_ij (帧间聚合)             │   │
│  │    → imap [384,H/4,W/4]│    │  GRU (GatedResidual ×2)      │   │
│  │                        │    │  d → delta [2] (光流残差)      │   │
│  │  Patch 采样 + patchify │    │  w → weight [2] (置信度)       │   │
│  └──────────────────────┘    └──────────────────────────────┘   │
│                                                                 │
│  属性: DIM=384, RES=4, P=3                                      │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 特征提取器 — BasicEncoder4 (`extractor.py`)

DPVO 使用两个独立的 `BasicEncoder4` 实例，分别提取**匹配特征**和**上下文特征**。

**网络结构（BasicEncoder4）：**

```
输入: [B×N, 3, H, W]
  │
  ├─ Conv2d(3→32, k=7, s=2, p=3) + InstanceNorm/None + ReLU
  │    → [B×N, 32, H/2, W/2]
  │
  ├─ layer1: ResidualBlock(32→32) × 2, stride=1
  │    → [B×N, 32, H/2, W/2]
  │
  ├─ layer2: ResidualBlock(32→64) × 2, stride=2
  │    → [B×N, 64, H/4, W/4]
  │
  └─ Conv2d(64→output_dim, k=1)
       → [B×N, output_dim, H/4, W/4]

输出 reshape: [B, N, output_dim, H/4, W/4]
```

| 实例 | output_dim | norm_fn | 输出符号 | 用途 |
|------|-----------|---------|---------|------|
| `fnet` | 128 | `instance` | `fmap` | 匹配特征，用于构建相关性体积 |
| `inet` | 384 (=DIM) | `none` | `imap` | 上下文特征，注入 Update Operator |

**ResidualBlock 结构：**

```
x → Conv2d(k=3,s=stride) → Norm → ReLU → Conv2d(k=3,s=1) → Norm → (+x) → ReLU
    (若 stride≠1，x 经 Conv2d(k=1,s=stride)+Norm 下采样)
```

### 2.3 Patch 提取 — Patchifier (`net.py`)

`Patchifier.forward()` 从每帧图像中采样稀疏 Patch：

**输入：**
- `images`: `[B, N, 3, H, W]` — 归一化后的图像（`2*(img/255)-0.5`）
- `patches_per_image`: `int` — 每帧采样 Patch 数（默认 160）
- `mask`: 可选，动态物体 mask

**处理流程：**

```
1. fmap = fnet(images) / 4.0   → [B, N, 128, H/4, W/4]
2. imap = inet(images) / 4.0   → [B, N, 384, H/4, W/4]

3. Patch 中心采样（在 H/4 × W/4 特征图上）:
   ├─ GRADIENT_BIAS: 采样 3×M 个候选点 → 计算梯度 → 取梯度最大的 M 个
   └─ RANDOM: 直接随机采样 M 个点（支持 mask 约束）

4. 坐标 coords: [N, M, 2] (x, y)

5. Patchify（CUDA 双线性插值）:
   ├─ imap_patches = patchify(imap, coords, r=0)  → [B, N×M, 384, 1, 1]
   ├─ gmap_patches = patchify(fmap, coords, r=1)  → [B, N×M, 128, 3, 3]
   └─ patches      = patchify(grid,  coords, r=1) → [B, N×M, 3, 3, 3]
      (grid 包含 x, y, disparity 三个通道)
```

**输出张量维度汇总：**

| 输出 | 维度 | 说明 |
|------|------|------|
| `fmap` | `[B, N, 128, H/4, W/4]` | 全图匹配特征（存入金字塔） |
| `gmap` | `[B, N×M, 128, 3, 3]` | Patch 级匹配特征模板 |
| `imap` | `[B, N×M, 384, 1, 1]` | Patch 级上下文特征 |
| `patches` | `[B, N×M, 3, 3, 3]` | Patch 几何信息 (x, y, inv_depth) |
| `index` | `[N×M]` | 每个 Patch 所属帧索引 |

### 2.4 相关性计算 — AltCorr (`altcorr/correlation.py`)

相关性体积通过 CUDA 自定义算子高效计算，核心是 `CorrLayer`：

```python
corr = CorrLayer.apply(fmap1, fmap2, coords, ii, jj, radius, dropout)
```

**计算逻辑：**
- `fmap1` = `gmap`：Patch 模板特征 `[1, pmem×M, 128, P, P]`
- `fmap2` = 金字塔层特征 `[1, mem, 128, H', W']`
- `coords`：Patch 重投影坐标 `[1, E, 2, P, P]`
- 在 `coords` 周围 `radius=3` 的邻域内计算点积相关性

**双层金字塔：**

```python
corr1 = altcorr.corr(gmap, pyramid[0], coords/1, ...)  # 原始分辨率 H/4×W/4
corr2 = altcorr.corr(gmap, pyramid[1], coords/4, ...)  # 1/4 分辨率 H/16×W/16
corr = torch.stack([corr1, corr2], -1)  # → [1, E, 2×49×P²]
```

其中 `49 = (2×3+1)²` 为搜索窗口大小，`P²=9`。最终相关性向量维度：`2 × 49 × 9 = 882`。

### 2.5 更新算子 — Update (`net.py`)

Update Operator 是 DPVO 的核心可学习模块，迭代更新隐状态并预测光流残差。

**输入：**

| 参数 | 维度 | 说明 |
|------|------|------|
| `net` | `[1, E, 384]` | 边的隐状态 |
| `inp` | `[1, E, 384]` | 上下文特征（imap 按 kk 索引） |
| `corr` | `[1, E, 882]` | 相关性向量 |
| `ii, jj, kk` | `[E]` | 边的源帧、目标帧、Patch 索引 |

**前向传播：**

```
1. 特征融合:
   net = net + inp + corr_mlp(corr)     # corr_mlp: 882→384→384 (LayerNorm+ReLU)
   net = LayerNorm(net)                  # → [1, E, 384]

2. 邻域消息传递:
   ix, jx = neighbors(kk, jj)           # CUDA 查找同 Patch / 同帧对的邻居
   net = net + c1(net[:, ix] * mask_ix)  # 同 Patch 不同帧的消息
   net = net + c2(net[:, jx] * mask_jx)  # 同帧不同 Patch 的消息

3. 软聚合:
   net = net + agg_kk(net, kk)           # 按 Patch ID 聚合（SoftAgg）
   net = net + agg_ij(net, ii*12345+jj)  # 按帧对 (i,j) 聚合（SoftAgg）

4. GRU 更新:
   net = GRU(net)                        # LayerNorm → GatedResidual → LayerNorm → GatedResidual

5. 输出头:
   delta  = d(net)  → [1, E, 2]         # 光流残差 (dx, dy)，经 GradientClip
   weight = w(net)  → [1, E, 2]         # 置信度权重 (0,1)，经 Sigmoid + GradientClip
```

### 2.6 SoftAgg 聚合机制 (`blocks.py`)

```python
class SoftAgg:
    f: Linear(DIM→DIM)   # 值变换
    g: Linear(DIM→DIM)   # 注意力得分
    h: Linear(DIM→DIM)   # 输出变换

    forward(x, ix):
        w = scatter_softmax(g(x), ix)     # 组内 softmax 注意力
        y = scatter_sum(f(x) * w, ix)     # 加权聚合
        return h(y)[:, jx]                # 广播回原始维度
```

### 2.7 GatedResidual (`blocks.py`)

```python
class GatedResidual:
    gate: Linear(DIM→DIM) → Sigmoid
    res:  Linear(DIM→DIM) → ReLU → Linear(DIM→DIM)

    forward(x):
        return x + gate(x) * res(x)      # 门控残差连接
```

---

## 3. 训练流程

### 3.1 训练数据

训练数据通过 `data_readers/` 加载，支持 TartanAir 等带有 GT 深度和位姿的数据集。

**数据增强（`data_readers/augmentation.py`）：**
- 随机裁剪、颜色抖动
- 随机水平翻转

**数据格式：**

| 字段 | 维度 | 说明 |
|------|------|------|
| `images` | `[B, N, 3, H, W]` | RGB 图像序列（0-255） |
| `poses` | `[B, N, 7]` | GT 位姿（SE3，tx ty tz qx qy qz qw） |
| `disps` | `[B, N, H, W]` | GT 逆深度图 |
| `intrinsics` | `[B, N, 4]` | 相机内参 (fx, fy, cx, cy) |

### 3.2 训练前向传播 (`VONet.forward`)

训练时 `VONet.forward()` 执行完整的多步迭代优化，模拟在线推理过程：

```
1. 预处理:
   images = 2*(images/255) - 0.5
   intrinsics = intrinsics / 4.0          # 适配 1/4 分辨率特征图
   disps = disps[:,:,1::4,1::4]           # 下采样到特征图分辨率

2. 特征提取:
   fmap, gmap, imap, patches, ix = patchify(images, disps=disps)

3. 构建相关性函数:
   corr_fn = CorrBlock(fmap, gmap)        # 金字塔级别 [1, 4]

4. 深度初始化:
   patches 的深度通道用随机值替换（模拟未知深度）

5. 迭代优化 (STEPS=12 步):
   for step in range(STEPS):
     ├─ 逐步扩展帧（step≥8 时加入新帧）
     ├─ coords = transform(Gs, patches, intrinsics, ii, jj, kk)  # 重投影
     ├─ corr = corr_fn(kk, jj, coords)                           # 相关性
     ├─ net, (delta, weight, _) = update(net, imap[:,kk], corr, ...)
     ├─ target = coords[...,P//2,P//2,:] + delta                  # 目标坐标
     └─ Gs, patches = BA(Gs, patches, intrinsics, target, weight, ...)
        # 可微分 Bundle Adjustment

6. 收集轨迹:
   traj.append((valid, coords, coords_gt, Gs[:,:n], Ps[:,:n], kl))
```

### 3.3 损失函数

训练损失在 `VONet.forward()` 返回的 `traj` 列表上计算（外部训练脚本中）：

**核心损失 — 加权重投影误差：**

$$L = \sum_{t=0}^{T-1} \gamma^t \sum_{(i,j) \in \mathcal{E}_t} \mathbb{1}[|i-j| \in (0,2]] \cdot \text{valid}_{ij} \cdot \| \hat{\pi}_{ij}^{(t)} - \pi_{ij}^{*} \|_2$$

其中：
- $\hat{\pi}_{ij}^{(t)}$：第 $t$ 步迭代中，当前估计位姿下 Patch 中心的重投影坐标 `[1, E, 2, P, P]`
- $\pi_{ij}^{*}$：GT 位姿下 Patch 中心的重投影坐标 `[1, E, 2, P, P]`
- $\text{valid}_{ij}$：深度有效性掩码（$Z > 0.2$），`[1, E]`
- $\gamma^t$：指数递增权重（$\gamma > 1$），后期迭代步权重更大
- $\mathcal{E}_t$：第 $t$ 步的活跃边集合
- 只计算时间距离 $|i-j| \in (0, 2]$ 的边

**设计思想：**

| 设计点 | 原理 |
|--------|------|
| 重投影误差 | 直接度量几何一致性——如果位姿和深度估计正确，同一 3D 点在不同帧的投影应精确对应。这是 Bundle Adjustment 的经典目标函数 |
| 指数递增权重 | 早期迭代步的估计不准确，给予较低权重避免误导梯度方向；后期迭代步接近收敛，给予高权重鼓励精细调整 |
| 时间距离过滤 | 只计算相邻 1-2 帧的边，避免远距离帧间的大视差导致梯度不稳定 |
| 有效性掩码 | 排除深度过小（$Z < 0.2$m）的退化点，这些点通常是噪声或遮挡区域 |

### 3.4 可微分 Bundle Adjustment (`ba.py`)

训练时使用纯 PyTorch 实现的 BA（非 CUDA 加速版），支持自动微分：

**优化变量：**
- 位姿 `Gs`：SE3 李群表示，`[B, N, 7]`
- Patch 逆深度 `patches[..., 2, :, :]`：`[B, N×M, 1, P, P]`

**BA 求解过程（Schur Complement）：**

```
1. 计算雅可比矩阵:
   coords, valid, (Ji, Jj, Jz) = transform(..., jacobian=True)
   ├─ Ji: 对源帧位姿的雅可比 [1, E, 2, 6]
   ├─ Jj: 对目标帧位姿的雅可比 [1, E, 2, 6]
   └─ Jz: 对逆深度的雅可比 [1, E, 2, 1]

2. 构建法方程 (H·δ = b):
   ├─ B (位姿-位姿块):  scatter_add(JᵀWJ) → [B, n, n, 6, 6]
   ├─ E (位姿-深度块):  scatter_add(JᵀWJz) → [B, n, m, 6, 1]
   ├─ C (深度-深度块):  scatter_add(JzᵀWJz) → [B, m, 1]
   ├─ v (位姿残差):     scatter_add(JᵀWr) → [B, n, 1, 6, 1]
   └─ w (深度残差):     scatter_add(JzᵀWr) → [B, m, 1]

3. Schur Complement 消元:
   Q = 1/(C + λ)
   S = B - E·Q·Eᵀ                        # Schur 补矩阵
   y = v - E·Q·w
   dX = CholeskySolver(S, y)              # 位姿增量 [B, n, 6]
   dZ = Q·(w - Eᵀ·dX)                    # 深度增量 [B, m, 1]

4. 更新:
   poses = pose_retr(poses, dX)           # SE3 retraction
   disps = disp_retr(disps, dZ)           # 逆深度加法更新，clamp [1e-3, 10.0]
```

**CholeskySolver** 使用 `torch.linalg.cholesky_ex` 求解，支持反向传播。Cholesky 分解失败时返回零向量，避免训练崩溃。

### 3.5 关键训练配置 (`config.py`)

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `PATCHES_PER_FRAME` | 160 | 每帧采样 Patch 数 |
| `BUFFER_SIZE` | 4096 | 最大关键帧数 |
| `OPTIMIZATION_WINDOW` | 12 | 局部 BA 优化窗口 |
| `REMOVAL_WINDOW` | 20 | 边移除窗口 |
| `PATCH_LIFETIME` | 12 | Patch 存活帧数 |
| `MIXED_PRECISION` | False | 是否使用混合精度 |
| `MOTION_MODEL` | `DAMPED_LINEAR` | 运动模型（阻尼线性） |
| `MOTION_DAMPING` | 0.5 | 运动阻尼系数 |
| `network` | `dpvo.pth` | 预训练权重路径 |

---

## 4. 推理流程

### 4.1 整体推理管线

```
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
│ 图像流    │───▶│ DPVO     │───▶│ 终止 &   │───▶│ 输出     │
│ (Stream) │    │ __call__ │    │ 插值     │    │ 位姿+点云│
│          │    │ (逐帧)   │    │ terminate│    │          │
└──────────┘    └──────────┘    └──────────┘    └──────────┘
```

### 4.2 数据流入 — Stream (`stream.py`)

提供三种数据流生成器，均通过 `multiprocessing.Queue` 异步加载：

| 函数 | 输入 | 输出元组 | 特点 |
|------|------|---------|------|
| `image_stream` | 图像目录 + 标定文件 | `(t, image, intrinsics)` | 支持畸变校正 |
| `video_stream` | 视频文件 + 标定文件 | `(t, image, intrinsics)` | 0.5× 降采样 |
| `cam0_stream` | clip 路径 + transform JSON | `(t, image, intrinsics, mask)` | 车端数据，含动态 mask |

**图像预处理：**
- 尺寸对齐到 16 的倍数：`image = image[:h-h%16, :w-w%16]`
- 标定参数从 transform JSON 或 calib 文件读取

### 4.3 逐帧处理 — `DPVO.__call__`

每帧调用 `slam(t, image, intrinsics, mask)` 执行以下步骤：

```
输入: tstamp, image [3, H, W], intrinsics [4], mask [H, W]

Step 1 — 图像归一化:
  image = 2*(image/255) - 0.5  → [1, 1, 3, H, W]

Step 2 — 特征提取 + Patch 采样:
  fmap, gmap, imap, patches, _, clr = network.patchify(image, M=160, mask=mask)
  ├─ fmap:    [1, 1, 128, H/4, W/4]
  ├─ gmap:    [1, M, 128, 3, 3]
  ├─ imap:    [1, M, 384, 1, 1]
  ├─ patches: [1, M, 3, 3, 3]     (x, y, inv_depth 各 3×3)
  └─ clr:     [1, M, 3]           (颜色，用于可视化)

Step 3 — 状态更新:
  ├─ 记录时间戳、内参（缩放 1/RES=1/4）
  ├─ 存储特征到环形缓冲区:
  │   imap_[n % pmem] = imap       # Patch 上下文特征
  │   gmap_[n % pmem] = gmap       # Patch 匹配模板
  │   fmap1_[n % mem] = fmap       # 全图特征（原始分辨率）
  │   fmap2_[n % mem] = avg_pool(fmap, 4)  # 全图特征（1/4 分辨率）
  │
  ├─ 运动模型初始化位姿:
  │   DAMPED_LINEAR: P_n = exp(damping × fac × log(P_{n-1} × P_{n-2}⁻¹)) × P_{n-1}
  │   (fac 根据时间戳间隔自适应调整)
  │
  └─ 深度初始化:
      patches[:,:,2] = rand()      # 随机初始化
      if initialized:
          patches[:,:,2] = median(patches[n-3:n])  # 用近邻帧中位数

Step 4 — 运动检测（初始化阶段）:
  if not initialized:
      motion = motion_probe()       # 计算光流中位数
      if motion < 2.0:
          记录为静止帧（delta），跳过
          return

Step 5 — 构建因子图边:
  ├─ edges_forw(): 旧 Patch → 新帧 (t0..t1 × n-1..n)
  ├─ edges_back(): 新 Patch → 旧帧 (t0..t1 × n-r..n)
  └─ edges_loop(): 回环边（若启用 LOOP_CLOSURE）
  append_factors(ii, jj) 将边加入图中

Step 6 — 初始化 / 更新:
  if n == 8 (首次初始化):
      for _ in range(12): update()  # 12 次迭代优化
  elif initialized:
      update()                      # 单次更新
      keyframe()                    # 关键帧管理
```

### 4.4 更新步骤 — `DPVO.update`

```
1. 重投影:
   coords = reproject()
   # transform(SE3(poses), patches, intrinsics, ii, jj, kk)
   # → [1, E, 2, P, P]  (P=3)

2. 相关性计算:
   corr = self.corr(coords)
   # 双层金字塔相关性 → [1, E, 882]

3. 网络更新:
   net, (delta, weight, _) = network.update(net, ctx, corr, None, ii, jj, kk)
   # delta: [1, E, 2]   光流残差
   # weight: [1, E, 2]  置信度

4. 计算目标坐标:
   target = coords[..., P//2, P//2] + delta   # Patch 中心 + 残差

5. Bundle Adjustment:
   ├─ 若存在长程边且未执行过全局 BA → __run_global_BA()
   │   (合并 active + inactive 边，iterations=2, eff_impl=True)
   └─ 否则 → 局部 BA
       fastba.BA(..., t0=n-OPTIMIZATION_WINDOW, t1=n, iterations=2)

6. 更新点云:
   points = point_cloud(poses, patches, intrinsics, ix)
```

### 4.5 关键帧管理 — `DPVO.keyframe`

```
1. 计算运动幅度:
   m = motionmag(i, j) + motionmag(j, i)
   (i = n-KEYFRAME_INDEX-1, j = n-KEYFRAME_INDEX+1)

2. 若 m/2 < KEYFRAME_THRESH (运动不足):
   ├─ 记录被移除帧的相对位姿 delta[t1] = (t0, dP)
   ├─ 移除该帧相关的所有边
   ├─ 将后续帧的索引前移（ii, jj, kk 调整）
   ├─ 将后续帧的数据前移（poses, patches, features 等）
   └─ n -= 1, m -= M

3. 移除超出 REMOVAL_WINDOW 的旧边:
   to_remove = ix[kk] < n - REMOVAL_WINDOW
   (回环边豁免)
   remove_factors(to_remove, store=True)  # 存入 inactive 集合
```

### 4.6 终止与位姿输出 — `DPVO.terminate`

```
1. 若启用回环: 添加回环边
2. 执行 12 次最终优化 (update)
3. 构建完整轨迹:
   ├─ 已有关键帧: traj[tstamp] = pose
   └─ 被移除帧: 通过 delta 链递归恢复
       get_pose(t) = delta[t].dP × get_pose(delta[t].t0)
4. 输出:
   poses = SE3.inv().data  → [N, 7] (x y z qx qy qz qw)
   tstamps → [N] (float64)
```

### 4.7 PatchGraph 数据结构 (`patchgraph.py`)

`PatchGraph` 是 DPVO 的核心状态容器：

| 属性 | 维度 | 说明 |
|------|------|------|
| `poses_` | `[N, 7]` | 关键帧位姿 (tx ty tz qx qy qz qw) |
| `patches_` | `[N, M, 3, P, P]` | Patch 几何 (x, y, inv_depth) |
| `intrinsics_` | `[N, 4]` | 每帧内参 (fx, fy, cx, cy) |
| `points_` | `[N×M, 3]` | 三维点云 |
| `colors_` | `[N, M, 3]` | 点云颜色 |
| `tstamps_` | `[N]` | 时间戳 |
| `ii, jj, kk` | `[E]` | 活跃边：源帧、目标帧、Patch 索引 |
| `net` | `[1, E, 384]` | 边的隐状态 |
| `target` | `[1, E, 2]` | 目标重投影坐标 |
| `weight` | `[1, E, 2]` | 置信度权重 |
| `ii_inac, jj_inac, ...` | 变长 | 非活跃边（用于全局 BA） |
| `delta` | `dict` | 被移除帧的相对位姿 {t: (t0, dP)} |

---

## 5. 工程优化

### 5.1 CUDA 加速

| 模块 | 文件 | 加速内容 |
|------|------|---------|
| `altcorr` | `correlation_kernel.cu` | Patch 相关性计算（前向+反向）、双线性 Patchify |
| `fastba` | `ba_cuda.cu`, `block_e.cu` | 高效 BA 求解（Schur Complement、稀疏矩阵运算） |
| `lietorch` | `lietorch_gpu.cu` | SE3/Sim3 李群运算（指数映射、伴随、retraction） |

**fastba 的两种实现：**
- `eff_impl=False`：标准局部 BA，优化窗口 `[t0, t1]` 内的位姿和深度
- `eff_impl=True`：全局 BA 高效实现，用于包含非活跃边的全局优化

### 5.2 内存管理

**环形缓冲区设计：**

```python
self.mem = 36                          # 特征图缓冲区大小
self.pmem = 36 (或 MAX_EDGE_AGE)       # Patch 特征缓冲区大小

# 写入时取模
self.imap_[n % pmem] = imap
self.fmap1_[0, n % mem] = fmap
```

- 特征图缓冲区 `fmap1_`, `fmap2_`：`[1, mem, 128, H', W']`，存储最近 `mem` 帧的全图特征
- Patch 特征缓冲区 `imap_`, `gmap_`：`[pmem, M, DIM/128, ...]`，存储最近 `pmem` 帧的 Patch 特征
- 当启用回环检测时，`pmem` 扩大到 `MAX_EDGE_AGE`（默认 1000）以保留更多历史

### 5.3 混合精度

```python
if cfg.MIXED_PRECISION:
    kwargs = {"device": "cuda", "dtype": torch.half}
```

特征存储使用 FP16 减少显存占用（约节省 50%），BA 求解仍使用 FP32 保证数值稳定性。

### 5.4 梯度裁剪

`GradientClip` 模块在反向传播时将梯度裁剪到 `[-0.01, 0.01]`，并将 NaN 梯度置零：

```python
class GradClip(torch.autograd.Function):
    @staticmethod
    def backward(ctx, grad_x):
        grad_x = torch.where(torch.isnan(grad_x), torch.zeros_like(grad_x), grad_x)
        return grad_x.clamp(min=-0.01, max=0.01)
```

应用于 Update Operator 的 `delta` 和 `weight` 输出头，防止 BA 反传的大梯度破坏网络训练。

### 5.5 多进程数据加载

```python
queue = Queue(maxsize=8)
reader = Process(target=image_stream, args=(queue, ...))
reader.start()
# 主进程消费
while True:
    (t, image, intrinsics) = queue.get()
```

图像读取在独立进程中执行，通过 `maxsize=8` 的队列与推理进程解耦，避免 I/O 阻塞。

### 5.6 动态 Mask 支持

车端数据通过 `cam0_stream` 提供动态物体 mask，Patchifier 中：

1. Mask 从原图分辨率下采样到特征图分辨率（`max_pool2d`）
2. 采样时只在 `mask=True` 的区域选取 Patch 中心
3. 若某帧 mask 全为 False，退化为全图随机采样

### 5.7 回环检测

**短程回环（`LOOP_CLOSURE`）：**
- `PatchGraph.edges_loop()` 在旧 Patch 和新帧之间建立长程边
- 通过光流幅度阈值 `BACKEND_THRESH` 过滤无效边
- 使用 `reduce_edges` 进行非极大值抑制，限制最大边数

**长程回环（`CLASSIC_LOOP_CLOSURE`）：**
- 基于图像检索（DBoW）的传统回环检测
- 通过 `loop_closure/retrieval/` 模块实现
- 检测到回环后添加约束边并触发全局 BA

### 5.8 运动模型

**阻尼线性模型（`DAMPED_LINEAR`）：**

```python
# 自适应时间间隔
fac = (t_n - t_{n-1}) / (t_{n-1} - t_{n-2})

# 阻尼外推
xi = MOTION_DAMPING × fac × log(P_{n-1} × P_{n-2}⁻¹)
P_n = exp(xi) × P_{n-1}
```

在变频相机（如车端数据帧率不稳定）场景下，通过 `fac` 因子自适应调整外推幅度。

---

## 6. 目录结构速查

```
dpvo/
├── __init__.py
├── config.py                 # YACS 配置定义（所有超参数）
├── dpvo.py                   # DPVO 主类（在线推理状态机）
├── net.py                    # VONet 网络（Patchifier + Update + 训练 forward）
├── extractor.py              # BasicEncoder / BasicEncoder4 特征提取器
├── blocks.py                 # 网络构建块（GatedResidual, SoftAgg, GradientClip）
├── ba.py                     # 可微分 Bundle Adjustment（训练用，纯 PyTorch）
├── projective_ops.py         # 投影/反投影/重投影/雅可比计算
├── patchgraph.py             # PatchGraph 数据结构（状态容器）
├── stream.py                 # 数据流生成器（图像/视频/车端）
├── utils.py                  # 工具函数（坐标网格、金字塔、Timer）
├── plot_utils.py             # 可视化工具（PLY 导出、COLMAP 格式）
├── logger.py                 # 训练日志
│
├── altcorr/                  # CUDA 相关性计算
│   ├── __init__.py
│   ├── correlation.py        # Python 接口（CorrLayer, PatchLayer）
│   ├── correlation.cpp       # C++ 绑定
│   └── correlation_kernel.cu # CUDA 核函数
│
├── fastba/                   # CUDA 加速 Bundle Adjustment
│   ├── __init__.py
│   ├── ba.py                 # Python 接口（BA, neighbors）
│   ├── ba.cpp                # C++ 绑定
│   ├── ba_cuda.cu            # CUDA BA 求解器
│   ├── block_e.cu            # 块矩阵运算核函数
│   └── block_e.cuh           # 头文件
│
├── lietorch/                 # 李群运算库
│   ├── __init__.py
│   ├── groups.py             # SE3, Sim3, SO3 Python 封装
│   ├── group_ops.py          # 群运算接口
│   ├── broadcasting.py       # 广播规则
│   ├── src/                  # C++/CUDA 实现
│   └── include/              # 头文件（se3.h, so3.h, sim3.h 等）
│
├── data_readers/             # 训练数据加载
│   ├── base.py               # 基础数据集类
│   ├── tartan.py             # TartanAir 数据集
│   ├── augmentation.py       # 数据增强
│   ├── frame_utils.py        # 帧处理工具
│   └── rgbd_utils.py         # RGBD 工具
│
└── loop_closure/             # 回环检测
    ├── long_term.py          # 长程回环检测
    ├── optim_utils.py        # 优化工具（边过滤、NMS）
    └── retrieval/            # 图像检索
        ├── retrieval_dbow.py # DBoW 检索
        └── image_cache.py    # 图像缓存
```

---

## 7. 参考资料

### 7.1 论文

- **DPVO: Deep Patch Visual Odometry** — Teed et al., 2023
  - 核心贡献：Patch-based 视觉里程计，用稀疏 Patch 替代稠密光流
  - 关键创新：可学习的 Update Operator + 可微分 BA

- **DROID-SLAM** — Teed & Deng, 2021
  - DPVO 的前身，使用稠密光流；DPVO 将其简化为 Patch 级别

### 7.2 关键依赖

| 库 | 用途 |
|----|------|
| `lietorch` | SE3/Sim3 李群运算（指数映射、对数映射、伴随表示） |
| `torch_scatter` | 高效 scatter 操作（scatter_sum, scatter_softmax） |
| `cuda_ba` | CUDA 加速 BA（自定义编译） |
| `cuda_corr` | CUDA 加速相关性计算（自定义编译） |
| `yacs` | 配置管理 |
| `evo` | 轨迹评估工具（PoseTrajectory3D） |
| `einops` | 张量重排 |

### 7.3 关键数值常量

| 常量 | 值 | 位置 | 说明 |
|------|-----|------|------|
| `DIM` | 384 | `net.py` | 隐状态维度 |
| `RES` | 4 | `VONet` | 特征图下采样倍率 |
| `P` | 3 | `VONet` | Patch 大小 |
| `MIN_DEPTH` | 0.2 | `projective_ops.py` | 最小有效深度 |
| `GRAD_CLIP` | 0.01 | `blocks.py` | 梯度裁剪阈值 |
| `lmbda` | 1e-4 | `dpvo.py` | BA 正则化系数 |
| 初始化帧数 | 8 | `dpvo.py` | 累积 8 帧后触发初始化 |
| 初始化迭代 | 12 | `dpvo.py` | 初始化时执行 12 次 update |
| 终止迭代 | 12 | `dpvo.py` | 终止时执行 12 次 update |
