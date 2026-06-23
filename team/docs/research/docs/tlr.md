# 红绿灯（Traffic Light）链路流程分析

## 1. 总体架构概览

红绿灯在本工程中作为一个**独立的 Gaussian 类别**（`Trafficlight`），从数据预处理到模型训练、渲染形成完整链路。核心设计思路是：**将红绿灯从背景点云中分离出来，作为独立的 3D Gaussian Splatting 模型进行建模，并通过傅里叶时序特征捕捉红绿灯的颜色变化**。

```
数据预处理                    模型训练                      渲染
┌─────────────────┐     ┌──────────────────────┐     ┌─────────────────┐
│ trafficlight_   │     │ scene_graph.py        │     │ vanilla_render  │
│ processor.py    │────▶│   ├─ 初始化 Trafficlight│────▶│   ├─ 傅里叶颜色  │
│ ├─ 语义分割提取  │     │   │  Gaussian 模型     │     │   │  时序解码     │
│ ├─ 多视角投影    │     │ base.py               │     │   └─ 合成渲染    │
│ ├─ 体素投票融合  │     │   ├─ tfl_mask 加权损失  │     └─────────────────┘
│ ├─ 背景点云分离  │     │   └─ rgb_weight=5.0   │
│ └─ 输出 tfl.ply │     │ vanilla.py            │
└─────────────────┘     │   ├─ 傅里叶特征初始化   │
                        │   └─ 自适应密度控制     │
                        └──────────────────────┘
```

---

## 2. 数据预处理阶段

### 2.1 入口与触发

- **入口文件**：`xpeng_data_process/pipelines.py` → Step 11
- **处理器**：`xpeng_data_process/trafficlight_processor.py` → `TrafficLightExtractor`
- **开关配置**：`settings/config.py` → `cfg.steps_controller.trafficlight_processor = True`

### 2.2 处理流程

```
transform.json (帧信息)
        │
        ▼
┌─ 逐帧处理（每 28 帧一组，取前 7 帧）──────────────────────┐
│  1. 加载语义分割图 → 提取 TrafficLight mask (class_id=48) │
│  2. 加载点云（LiDAR 或 vision 模式）                      │
│  3. 相机内外参变换 → 3D 点投影到 2D 图像平面               │
│  4. 用 mask 筛选落在红绿灯区域的 3D 点                    │
│  5. 转换回全局坐标系                                      │
└──────────────────────────────────────────────────────────┘
        │ 每 7 帧一组
        ▼
┌─ 多视角融合 ─────────────────────────────────────────────┐
│  fuse_with_voxel_voting()                                │
│  - 体素量化（voxel_size=0.1m）                            │
│  - 投票过滤：至少 2 个不同视角观测到才保留                  │
└──────────────────────────────────────────────────────────┘
        │
        ▼
┌─ 后处理 ─────────────────────────────────────────────────┐
│  1. 合并所有组的点云                                      │
│  2. 体素下采样（voxel_size=0.005m）                       │
│  3. 点数 < 50 则跳过（认为红绿灯点不足）                   │
│  4. 保存 → input_ply/points3D_tfl.ply                    │
│  5. remove_traffic_light_from_background()                │
│     - 从 points3D_bkgd.ply 中移除与 tfl 重叠的点          │
│     - 同步更新 ground_mask.npy                            │
└──────────────────────────────────────────────────────────┘
```

### 2.3 数据源模式

| 模式 | 点云来源 | 说明 |
|------|---------|------|
| LiDAR 模式 | `LidarProcessor.background_pcds[timestamp]` | 按时间戳获取对应帧的 LiDAR 点云 |
| Vision 模式 | `input_ply/points3D_bkgd.ply` | 一次性加载全局背景点云 |

### 2.4 语义标签定义

```python
# settings/globals.py
SEMANTIC_CLASSES = { 48: 'TrafficLight' }
DATASET_CLASSES_IN_SEMANTIC = { 'TrafficLight': [48] }
SemanticType.TrafficLight = 7
```

### 2.5 输出产物

| 文件 | 路径 | 说明 |
|------|------|------|
| 红绿灯点云 | `input_ply/points3D_tfl.ply` | 分离后的红绿灯 3D 点云 |
| 更新后的背景 | `input_ply/points3D_bkgd.ply` | 移除红绿灯点后的背景点云 |
| 更新后的地面 mask | `ground_mask.npy` | 同步更新的地面掩码 |
| 调试可视化 | `mask_visualizations/` | 每帧的 tfl mask 和语义图 |

---

## 3. 模型训练阶段

### 3.1 模型注册与初始化

**配置文件**（以 `dev.yaml` 为例）：

```yaml
model:
  Trafficlight:
    type: reconic.models.gaussians.VanillaGaussians
    init:
      from_lidar:
        return_color: True
        model_type: Trafficlight
    ctrl:
      fourier_dim: 100      # 傅里叶级数维度
      fourier_scale: 1.0    # 傅里叶缩放因子
```

**初始化链路**：

1. `scene_graph.py` → 检测配置中是否有 `Trafficlight` 键 → 注册为 `GSModelType.Trafficlight`
2. `init_gaussians_from_dataset()` → 检查 `points3D_tfl.ply` 是否存在
   - 存在 → 加载点云初始化 Gaussian
   - 不存在 → 从 `gaussian_classes` 和 `models` 中移除该类别（优雅降级）
3. `xpeng_driving_dataset.py` → `trafficlight_points()` → 从 PLY 文件读取点和颜色

### 3.2 傅里叶时序特征（核心创新点）

#### 3.2.1 为什么需要傅里叶时序建模

红绿灯的颜色随时间呈**周期性变化**（红→绿→黄→红），这与 3D Gaussian Splatting 中其他物体有本质区别：

| 物体类型 | 颜色特性 | 标准 SH 能否建模 |
|---------|---------|-----------------|
| 建筑/道路 | 静态颜色，仅随视角变化 | ✅ 球谐函数擅长视角相关的颜色 |
| 车辆 | 静态颜色 + 运动位姿 | ✅ 颜色不变，位姿由刚体变换处理 |
| **红绿灯** | **同一空间位置，颜色随时间周期变化** | ❌ SH 只编码空间方向，无时间维度 |

球谐函数（Spherical Harmonics）将颜色表示为视角方向的函数 `c = f(θ, φ)`，本质上是**空间频域分解**。但红绿灯的颜色变化是 `c = f(t)`，是**时间域**上的变化，SH 完全无法表达。

如果强行用 SH 建模红绿灯，模型只能学到所有时刻颜色的"平均值"——一个混合了红、绿、黄的模糊颜色，无法还原任何时刻的真实状态。

#### 3.2.2 傅里叶级数的数学原理

**核心思想**：任何周期信号都可以分解为不同频率的正弦和余弦函数的叠加（傅里叶定理）。红绿灯的颜色变化本质上就是一个时间域上的周期信号，因此可以用傅里叶级数精确表示。

对于红绿灯每个 Gaussian 点的颜色 `c(t)`，将其表示为：

```
c(t) = Σ_{k=0}^{D/2-1} [ a_k · cos(πtk) + b_k · sin(πt(k+1)) ]
```

其中：
- `t` 是归一化时间（当前帧在整个 clip 中的相对位置，范围 [0, 1]）
- `D = fourier_dim = 100` 是傅里叶基函数总数（50 个余弦 + 50 个正弦）
- `a_k, b_k` 是**可学习的频域系数**，存储在 `_features_dc` 中，形状为 `[N, D, 3]`
- 每个 Gaussian 点有独立的 D×3 个系数（D 个频率分量 × RGB 3 通道）

**为什么这能捕捉红绿灯变化**：

1. **低频分量**（k 较小）：捕捉颜色的缓慢整体变化趋势，如从红到绿的渐变过渡
2. **中频分量**：捕捉红绿灯切换的主要周期，如一个完整的红→绿→黄→红循环
3. **高频分量**（k 较大）：捕捉快速变化的细节，如黄灯的短暂闪烁、切换瞬间的颜色跳变

通过训练，模型自动学习每个频率分量的系数，使得在任意时刻 `t` 通过上述公式重建出的颜色与真实观测一致。

#### 3.2.3 与标准 SH 的对比

```
标准 3DGS（背景/车辆）：
  _features_dc: [N, 3]          ← 每个点 3 个值（RGB 直流分量）
  颜色 = f(视角方向)             ← 空间域函数

红绿灯傅里叶模式：
  _features_dc: [N, fourier_dim, 3]  ← 每个点 100×3 个值（频域系数）
  颜色 = f(时间)                      ← 时间域函数
```

存储开销增加约 100 倍（每个点从 3 个参数变为 300 个），但红绿灯点云通常只有几百到几千个点，总参数量增加可忽略不计。

#### 3.2.4 代码实现

**IDFT 基函数构造**（`fourier_utils.py`）：

```python
def IDFT(time, dim):
    t = time.view(-1, 1).float()          # 归一化时间 → [1, 1]
    idft = torch.zeros(t.shape[0], dim)    # [1, D]
    indices = torch.arange(dim)
    even_indices = indices[::2]            # 0, 2, 4, ... → 余弦基
    odd_indices = indices[1::2]            # 1, 3, 5, ... → 正弦基
    idft[:, even_indices] = torch.cos(torch.pi * t * even_indices)
    idft[:, odd_indices]  = torch.sin(torch.pi * t * (odd_indices + 1))
    return idft  # [1, D] — 当前时刻的傅里叶基向量
```

**渲染时颜色解码**（`vanilla_render.py`）：

```python
def get_features_fourier(self, frame=0):
    # 1. 时间归一化：将帧号映射到 [0, 1]
    normalized_frame = (frame - self.start_frame) / (self.end_frame - self.start_frame)
    time = self.fourier_scale * normalized_frame

    # 2. 构造当前时刻的傅里叶基向量
    idft_base = IDFT(time, self.fourier_dim)[0]  # [D]

    # 3. 频域系数 × 基向量 → 求和得到当前时刻颜色
    features_dc = self._features_dc                                      # [N, D, 3]
    features_dc = torch.sum(features_dc * idft_base[..., None], dim=1,
                            keepdim=True)                                # [N, 1, 3]
    features_rest = self._features_rest                                  # [N, sh, 3]
    features = torch.cat([features_dc, features_rest], dim=1)
    return features
```

**计算过程可视化**：

```
输入：frame=42, start_frame=0, end_frame=100
  ↓
normalized_frame = 42/100 = 0.42
  ↓
IDFT(0.42, 100) → 基向量 [cos(0), sin(π·0.42·1), cos(π·0.42·2), sin(π·0.42·3), ...]
  ↓                        ↑ 100 个不同频率的三角函数值
_features_dc [N, 100, 3] × idft_base [100] → sum over dim=1 → [N, 1, 3]
  ↓                        ↑ 加权求和：每个频率系数 × 对应基函数值
输出：当前时刻每个 Gaussian 点的 RGB 颜色
```

#### 3.2.5 训练过程中的学习机制

训练时，`_features_dc`（形状 `[N, 100, 3]`）作为可学习参数参与梯度优化：

1. **前向传播**：给定训练帧 `t`，通过 IDFT 解码出预测颜色
2. **损失计算**：预测颜色与 GT 图像在红绿灯区域的 RGB 损失（权重 5.0）
3. **反向传播**：梯度回传到 100 个频域系数，调整各频率分量的幅值和相位

由于不同训练帧对应不同的 `t` 值，模型被迫学习一组频域系数，使得在**所有训练时刻**重建出的颜色都与 GT 一致。这等价于对红绿灯颜色的时间序列做了一次**隐式的傅里叶拟合**。

#### 3.2.6 为什么傅里叶级数特别适合红绿灯

1. **周期性天然匹配**：红绿灯状态循环（红→绿→黄→红）本身就是周期信号，傅里叶级数是表示周期信号的最自然工具
2. **频谱稀疏性**：红绿灯颜色变化的频谱集中在少数几个频率上（主周期 + 少量谐波），100 维的傅里叶空间足以高精度表示
3. **平滑插值**：三角函数天然连续可微，在训练帧之间的时刻也能给出平滑合理的颜色插值，不会出现跳变
4. **全局表示**：每个频域系数影响整个时间轴，模型可以用少量参数编码长时间跨度的变化模式，而非逐帧独立存储颜色

### 3.3 损失函数加权

```python
# base.py - compute_losses()
if tfl_mask is not None:
    valid_loss_mask_add_tfl_rgb_weight[valid_tfl_mask] = rgb_weight  # 默认 5.0
```

红绿灯区域的 RGB 损失权重为 **5.0**（相比背景的 1.0），强制模型更关注红绿灯区域的颜色还原精度。

### 3.4 Gaussian 自适应密度控制

```python
# vanilla.py - create_from_pcd()
if self.class_name == "Trafficlight":
    avg_dist = torch.clamp(avg_dist, min=1e-8)  # 防止尺度为零
```

红绿灯点云通常较稀疏，需要额外的数值稳定性保护。

### 3.5 Checkpoint 加载容错

```python
# base_render.py - load_state_dict()
if class_name == "Trafficlight":
    trafficlight_point_cloud = False  # 标记缺失
# ...
if not trafficlight_point_cloud:
    del self.models["Trafficlight"]  # 安全移除
```

支持从不含红绿灯模型的旧 checkpoint 加载，不会导致崩溃。

---

## 4. 渲染阶段

### 4.1 颜色计算

```python
# vanilla_render.py - get_gaussians()
if self.class_name == "Trafficlight":
    colors = self.get_features_fourier(cam.timestep_id)  # 时序傅里叶解码
else:
    colors = torch.cat((features_dc, features_rest), dim=1)  # 普通 SH
```

渲染时根据当前帧的时间戳，通过傅里叶逆变换计算出该时刻红绿灯的颜色，实现红绿灯状态的时序变化。

### 4.2 与其他 Gaussian 类别的合成

红绿灯作为独立的 Gaussian 类别，与 Background、Ground、RigidNodes 等一起参与最终的 alpha-blending 合成渲染。

---

## 5. 当前现状

### 5.1 已实现功能

| 功能 | 状态 | 说明 |
|------|------|------|
| 语义分割提取 | ✅ | 基于 class_id=48 的语义 mask |
| 多视角体素投票融合 | ✅ | 去除单视角噪声 |
| 背景点云分离 | ✅ | 双向 KD-Tree 清理 |
| 傅里叶时序颜色建模 | ✅ | 100 维傅里叶级数 |
| 损失加权 | ✅ | rgb_weight=5.0 |
| 优雅降级 | ✅ | 无 tfl 点云时自动跳过 |
| Checkpoint 兼容 | ✅ | 旧模型加载不崩溃 |

### 5.2 版本支持情况

| 配置版本 | load_tfl_mask | Trafficlight 模型 |
|---------|---------------|-------------------|
| v313, v314 | ❌ | ✅（无 mask 加权） |
| v409+ | ✅ | ✅ |
| v409b | ❌（显式关闭） | ✅ |

### 5.3 IPS 生产部署

当前 IPS 部署脚本（`ips_deploy/`）中**未发现红绿灯相关的特殊处理**，说明红绿灯在生产推理时作为标准 Gaussian 类别参与渲染，无需额外逻辑。

---

## 6. 可能问题

### 6.1 数据预处理

| 问题 | 严重程度 | 描述 |
|------|---------|------|
| **硬编码的帧分组逻辑** | 🟡 中 | `pos <= 6` 和 `i == 6` 硬编码了每 28 帧取前 7 帧的逻辑，与相机数量（7 个）强耦合，换相机配置会出错 |
| **KD-Tree 逐点遍历性能** | 🟡 中 | `remove_traffic_light_from_background()` 中对背景点云逐点查询 KD-Tree，大规模点云时性能较差 |
| **50 点阈值过于简单** | 🟠 低 | 仅用点数判断是否保留红绿灯，未考虑空间分布质量 |
| **注释掉的滤波器** | 🟠 低 | 统计滤波和半径滤波被注释掉，可能导致噪声点残留 |
| **Vision 模式下全局点云** | 🟡 中 | Vision 模式加载全局背景点云到 GPU，每帧都投影全量点，内存和计算开销大 |

### 6.2 模型训练

| 问题 | 严重程度 | 描述 |
|------|---------|------|
| **傅里叶维度固定** | 🟠 低 | `fourier_dim=100` 对所有场景统一，短 clip 可能过拟合，长 clip 可能欠拟合 |
| **时间归一化假设** | 🟡 中 | `start_frame=0, end_frame=num_images//7`，假设 7 个相机，与预处理的 28 帧分组逻辑存在隐式耦合 |
| **损失权重不可按场景调节** | 🟠 低 | `rgb_weight=5.0` 全局固定，不同场景红绿灯占比差异大 |
| **split 操作的特殊处理** | 🟠 低 | `_features_dc` 在 split 时需要 `repeat(samps, 1, 1)` 而非 `repeat(samps, 1)`，增加了维护复杂度 |

### 6.3 工程质量

| 问题 | 严重程度 | 描述 |
|------|---------|------|
| **SemanticType 枚举不一致** | 🟡 中 | 预处理用 `SemanticType.TrafficLight = 7`，训练用 `SemanticType.TRAFFICLIGHT = 5`，两套枚举定义 |
| **大量注释掉的调试代码** | 🟠 低 | `trafficlight_processor.py` 中有大量被注释的 print 语句 |
| **缺少单元测试** | 🟡 中 | 整个红绿灯链路无自动化测试覆盖 |

---

## 7. 改进建议

### 7.1 短期优化（低成本高收益）

1. **消除帧分组硬编码**：从 `transform.json` 中读取相机数量，动态计算分组大小，而非硬编码 `28` 和 `7`
2. **启用点云滤波**：恢复被注释的统计滤波 + 半径滤波，或用更轻量的体素滤波替代，减少噪声点
3. **统一 SemanticType 枚举**：预处理和训练使用同一份枚举定义，避免维护两套映射

### 7.2 中期优化

4. **KD-Tree 批量查询**：将逐点查询改为 Open3D 的 `compute_point_cloud_distance()` 批量操作，预计提速 10x+
5. **Vision 模式优化**：按相机视锥预筛选点云，避免全量投影
6. **自适应傅里叶维度**：根据 clip 时长自动调整 `fourier_dim`，短 clip 用较小维度

### 7.3 长期演进

7. **红绿灯状态感知**：结合检测模型输出红绿灯状态标签（红/绿/黄），作为额外监督信号
8. **IPS 部署验证**：在生产部署中增加红绿灯渲染质量的自动化评估指标
9. **端到端测试**：建立从预处理到渲染的集成测试，覆盖有/无红绿灯的场景
