# OmniRe/Reconic 模块技术分析文档

## 1. 概述

Reconic 是 SimWorld 项目的核心 3D Gaussian Splatting (3DGS) 联合训练框架，位于 `omnire_joint_trainning/src/reconic/`。该框架实现了基于场景图（Scene Graph）的多类高斯模型联合优化，支持背景、地面、刚体车辆、可变形物体、SMPL 人体、交通灯等多种场景元素的分离建模与联合渲染。

### 核心能力

- **多类高斯场景图**：将驾驶场景分解为 Background / Ground / RigidNodes / DeformableNodes / SMPLNodes / Trafficlight / RigidNodesLight 等独立高斯模型
- **联合训练**：通过 `GenerativeReconTrainingLoop` 集成 Difix 生成式模型进行联合训练
- **仿真渲染**：通过 `ReconicSimulator` 支持任意视角、任意时刻的场景渲染
- **多后端光栅化**：同时支持 gsplat 和 xpeng_raster 两种光栅化后端

### 训练入口

```
train_cli.py → main()
  → OmegaConf.load(config_file)
  → 根据配置选择:
      ├─ GenerativeReconTrainingLoop(args)  # 含 Difix 联合训练
      ├─ XpengTrainingLoop(args)            # 小鹏定制训练
      └─ ReconTrainingLoop(args)            # 标准重建训练
  → trainer.train()
```

## 2. 模型结构

### 2.1 高斯模型类型枚举

```python
class GSModelType(IntEnum):
    Background = 0       # 背景静态场景
    RigidNodes = 1       # 刚体节点（车辆等）
    SMPLNodes = 2        # SMPL 人体模型
    DeformableNodes = 3  # 可变形节点
    Ground = 4           # 地面
    Trafficlight = 5     # 交通灯
    DynamicAssets = 6    # 动态资产（从 RigidNodes 中分离）
    RigidNodesLight = 7  # 带灯光的刚体节点
```

### 2.2 Trainer 继承体系

```
nn.Module
  └─ BasicTrainer_render (base_render.py)
       ├─ 场景初始化、相机处理、高斯收集、光栅化渲染
       ├─ 优化器初始化、checkpoint 管理
       └─ 仿射变换、动态资产高度对齐
           └─ BasicTrainer (base.py)
                ├─ 损失函数初始化、前向传播、反向传播
                ├─ 训练前/后处理、指标计算
                └─ Viewer 集成
                    └─ MultiTrainer (scene_graph.py)
                         ├─ 多类高斯模型初始化
                         ├─ 从数据集初始化高斯点云
                         ├─ 场景图前向渲染
                         └─ xpeng_raster 高性能渲染
```

### 2.3 BasicTrainer_render — 渲染基础层

核心职责：

**场景管理**：
- `_init_scene(scene_aabb)`: 从 AABB 计算场景原点和半径
- `collect_gaussians(cam, image_ids)`: 遍历所有高斯类，收集并拼接高斯属性（means/scales/quats/rgbs/opacities），生成 `pts_labels` 类别标签
- `move_dynamic_assets_height_to_ground(gs_dict, class_labels)`: 使用 KDTree 将动态资产的 z 坐标对齐到地面，带 EMA 平滑

**光栅化渲染**：
- `render_gaussians(gs, cam, ...)`: 核心渲染函数，内部定义 `render_fn` 和 `render_xpeng_raster` 两个闭包
  - gsplat 后端：调用 `gsplat.rendering.rasterization`
  - xpeng_raster 后端：调用 `xpeng_raster.rasterization`
  - 输出：`rgb_gaussians` [H,W,3]、`depth` [H,W,1]、`opacity` [H,W,1]
  - 返回 `render_fn` 闭包供后续按类别分离渲染

**仿射变换**：
- `affine_transformation(rgb, image_info, camera_info)`: 通过 `AffineTransform` 模型对渲染结果进行逐像素颜色校正，支持按相机名/ID 过滤

### 2.4 BasicTrainer — 训练核心层

在渲染层基础上增加：

**损失函数初始化** (`_init_losses`):
- Sky opacity loss: BCE 或 SafeBCE
- Depth loss: `DepthLoss` 类，支持 L1/L2/SmoothL1，可选归一化和逆深度

**前向传播** (`forward`):
```
process_camera → collect_gaussians → render_gaussians
  → Sky model 渲染天空
  → rgb = affine(rgb_gaussians + rgb_sky * (1-opacity))
```

当前实现里，`BasicTrainer` / `SingleTrainer` / `MultiTrainer` 在进入渲染前还会把当前 batch 的 `image_info` 和 `camera_info` 通过 `set_training_context()` 下发给各模型。这个上下文现在被 `RigidNodes` 用来计算对象级 regularization，例如 3D box 到 2D 图像平面的 reprojection 约束；因此训练侧 loss 已经不再只依赖内部状态，也会显式消费当前相机观测信息。

**反向传播** (`backward`):
- GradScaler 混合精度
- 固定参数梯度清零（`fix_params_dict` 控制静止物体不优化位姿）
- 学习率调度器更新

**训练步骤处理**:
- `preprocess_per_train_step`: 更新各高斯模型状态，处理 viewer 同步
- `postprocess_per_train_step`: 计算梯度统计，触发高斯自适应密度控制（densification/pruning）

### 2.5 MultiTrainer — 场景图训练器

`MultiTrainer`（`scene_graph.py`）是最终使用的训练器，负责多类高斯模型的编排。

**模型初始化** (`_init_models`):
- 根据 `model_config` 中的键名注册高斯类别
- 每个高斯模型通过 `import_str(model_cfg.type)(...)` 动态实例化
- 辅助模型（Sky/Affine/CamPose/CamPosePerturb）单独初始化
- 注册归一化时间戳 `normalized_timestamps = linspace(0, 1, num_timesteps)`

**从数据集初始化** (`init_gaussians_from_dataset`):
```
dataset.get_init_objects("RigidNodes")     → rigidnode_pts_dict
dataset.get_init_objects("RigidNodesLight") → rigidnode_light_pts_dict
dataset.get_init_objects("DeformableNodes") → deformnode_pts_dict
dataset.get_init_smpl_objects()             → smplnode_pts_dict

Background/Ground/Trafficlight:
  ├─ from_lidar: 从 LiDAR 点云采样
  ├─ near_randoms: 场景球内均匀采样
  ├─ far_randoms: 逆距离采样（远处点）
  ├─ filter_pts_in_boxes: 过滤掉落在物体框内的点
  └─ 特殊初始化:
       ├─ Ground + 2dgs_init → create_from_2dgs_ply
       ├─ Ground + g3r_ground → create_from_feedforward
       └─ Background + evolsplat → create_from_feedforward

RigidNodes/RigidNodesLight:
  ├─ 记录 moving_status → fix_params_dict（静止物体不优化位姿）
  └─ create_from_pcd(instance_pts_dict)

空类自动删除
```

**场景图前向渲染** (`forward`):
```python
# 1. 设置当前帧
for model in gaussian_classes: model.set_cur_frame(cur_frame)

# 2. 处理相机
processed_cam = process_camera(camera_info, image_info, novel_view)

# 3. 收集所有高斯
gs = collect_gaussians(cam, image_ids)

# 4. 渲染
outputs, render_fn = render_gaussians(gs, cam, ...)

# 5. 天空模型
outputs["rgb_sky"] = Sky(image_info, opacity=outputs["opacity"])

# 6. 仿射变换
outputs["rgb"] = affine(rgb_gaussians + rgb_sky * (1-opacity))

# 7. 评估时按类别分离渲染
for class_name in gaussian_classes:
    sep_rgb, sep_depth, sep_opacity = render_fn(gaussian_mask)

# 8. 动态掩膜渲染（排除 Background 和 Ground）
Dynamic_rgb, Dynamic_opacity, Dynamic_depth = render_fn(dynamic_mask)
```

**xpeng_raster 高性能渲染** (`render_xpeng_raster`):
- 用于仿真场景的高性能渲染路径
- `precompute_gaussians("Ground")`: 预计算 Ground 高斯属性缓存
- `collect_hil_dynamic_gaussians`: 支持区域掩膜过滤，只渲染可见区域
- 直接调用 `xpeng_raster_rasterization`，tile_size=6

### 2.6 辅助模型（modules.py）

| 模型 | 类名 | 功能 |
|------|------|------|
| 天空模型 | `SkyModel` | 方向编码 + MLP 预测天空颜色，支持外观嵌入 |
| 环境光 | `EnvLight` | 6面 CubeMap 参数化环境光照 |
| 仿射变换 | `AffineTransform` | 逐图像/逐像素颜色校正（3×4 仿射矩阵） |
| 相机优化 | `CameraOptModule` | 学习相机位姿残差（3D平移 + 6D旋转） |
| 变形网络 | `DeformNetwork` | 8层 MLP，输入 xyz+t，输出位移/旋转/缩放 |
| 条件变形 | `ConditionalDeformNetwork` | 带条件嵌入的变形网络 |
| 体素变形 | `VoxelDeformer` | 基于体素网格的 LBS 权重查询（用于 SMPL） |

### 2.7 外观嵌入模型（appearance_embedding.py）

`AppearanceEmbeddingModel` 用于建模不同相机/时间步的外观差异：

```
输入特征 (16D)
  + Camera Embedding (可选, 16D)
  + Timestep Embedding (可选, 16D)
  + Novel View Embedding (可选, 16D)
  + View Direction PE (可选)
  → Conv1D MLP [64, 32] → tanh → 3D 颜色偏移
```

- 所有嵌入初始化为零（从恒等变换开始学习）
- 测试时缓存计算结果（`use_cache`）

## 3. 训练流程

### 3.1 训练循环入口

```
train_cli.py
  → GenerativeReconTrainingLoop(args)  # 含 Difix 的联合训练
  → ReconTrainingLoop(args)            # 纯重建训练
  → XpengTrainingLoop(args)            # 小鹏定制训练
```

配置文件通过 `joint_training_cfg` 字段区分是否启用生成式联合训练。

### 3.2 训练步骤

每个训练步骤的执行流程：

```
Step N:
  1. preprocess_per_train_step(step)
     ├─ 更新各高斯模型内部状态
     └─ Viewer 同步（如启用）

  2. forward(image_info, camera_info)
     ├─ process_camera → collect_gaussians → render_gaussians
     ├─ Sky 渲染 → 仿射变换
     └─ 返回 outputs dict

  3. compute_losses(outputs, image_info, cam_info)
     └─ 计算所有损失项（见 3.3）

  4. backward(loss_dict)
     ├─ total_loss = sum(all losses)
     ├─ grad_scaler.scale(total_loss).backward()
     ├─ 固定参数梯度清零
     ├─ optimizer.step()
     └─ lr_scheduler 更新

  5. postprocess_per_train_step(step)
     ├─ 收集 radii 和 means2d 梯度
     ├─ 各高斯模型自适应密度控制
     └─ Viewer 更新
```

### 3.3 损失函数体系（losses.py + base.py）

#### RGB 损失
- **L1 Loss**: `|gt_rgb - predicted_rgb|.mean()`，权重 `losses_dict.rgb.w`
- **SSIM Loss**: `1 - SSIM(gt, pred)`，权重 `losses_dict.ssim.w`
- 交通灯区域额外加权：`tfl_mask` 区域的 `rgb_weight` 默认为 5.0
- 合成数据（`from_synthesis=True`）时 L1 权重降为 0.2×

#### 天空/不透明度损失
- **Sky Opacity Loss**: BCE/SafeBCE，约束天空区域不透明度接近 0
- **Background Opacity Loss**: 可选，约束背景不透明度排除地面
- `SafeBCE`: 自定义 autograd Function，梯度安全裁剪避免数值爆炸

#### 深度损失（DepthLoss 类）
- 支持 L1/L2/SmoothL1
- 可选归一化到 [0,1]（max_depth=80m）
- 可选逆深度模式
- 可选百分位裁剪（`depth_error_percentile`）
- 有效掩膜：`gt_depth > 0.01 & gt_depth < max_depth & pred_depth > 0.0001`
- 可选 `ground_depth_only`：仅在地面非动态区域计算
- 可选 `exclude_dyn_sky`：排除动态物体和天空
- 可选 `lidar_w_decay`：指数衰减权重

#### 正则化损失
- **Opacity Entropy**: `-p*log(p)` 鼓励不透明度趋向 0 或 1
- **Affine Reg**: 仿射矩阵趋向单位矩阵
- **Dynamic Region Loss**: 动态区域额外 L1 监督
- **Dynamic Opacity Loss**: 动态物体不透明度熵损失
- **Fake Downwards Cam**: 虚拟俯视相机约束地面不透明度接近 1
- **各高斯模型自身正则化**: `model.compute_reg_loss()`

### 3.4 学习率调度

```python
def lr_scheduler_fn(cfg, lr_init):
    # 阶段1: opt_after 之前 lr=0（延迟启动）
    # 阶段2: warmup_steps 内线性/余弦升温
    # 阶段3: 指数衰减到 lr_final
    # 支持 scene_radius 缩放空间学习率
```

### 3.5 优化器配置

- 全局 Adam 优化器，eps=1e-15
- 每个模型组件独立学习率和调度器
- 通过 `gaussian_optim_general_cfg` 提供默认值，模型级配置可覆盖
- GradScaler 可选混合精度训练

## 4. 推理与渲染

### 4.1 ReconicSimulator（reconic_simulator.py）

`ReconicSimulator` 继承 `BaseSimulator`，是仿真渲染的核心类。

**初始化流程**：
```
ReconicSimulator.__init__(args, device, cp_simulation, iter, state_dict)
  → super().__init__(config_path)  # 加载配置
  → init_models(config)            # 创建 MultiTrainer
  → setup_models(config, iter)     # 加载 checkpoint
  → load_calibrations()            # 加载相机标定
  → 如果 cp_simulation:
       ├─ 禁用 render_each_class（性能优化）
       ├─ 构建 Ground KDTree（地面高度查询）
       └─ 构建 dds_localpose KDTree（位姿查询）
  → 如果配置了 Difix:
       └─ init_difix_model()       # 初始化 DifixFixer
```

**模型创建** (`init_models`):
```python
self.gaussian = import_str(cfg.recon_trainer.type)(
    num_timesteps=num_frames,
    model_config=cfg.model,
    num_train_images=num_frames * num_cams,
    scene_aabb=torch.tensor(cfg.data.lidar_source.aabb),
    device=device,
    disable_metric=True,
)
```

**模型加载** (`setup_models`):
- 从 `checkpoint_final.pth` 或指定迭代的 checkpoint 加载
- 支持从 `state_dict` 直接加载（避免磁盘 I/O）
- 加载后设置 eval 模式
- 支持 `modified_obj.json` 场景编辑（修改/删除物体）

**前馈初始化** (`setup_feedforward_models`):
- Ground: 从 `misc/ground_final.ply` 加载 2DGS
- Background: 从 `evolsplat_bkgd/evolsplat_init.ply` 加载
- RigidNodes: 从 `instance_dict.pt` 加载
- Affine: 从 `misc/affine_transform.pth` 加载

**相机映射**：
```python
_label2camera = {0:'cam0', 2:'cam2', 3:'cam3', 4:'cam4', 5:'cam5', 6:'cam6', 7:'cam7'}
```

### 4.2 render_sim.py — 渲染脚本

提供多种渲染模式：

**`render_sim_origin`**: 原始轨迹渲染
- 从 `LocalPoseTopic.json` 读取位姿序列
- 支持 `mode="novel"` 使用正弦波横向偏移生成新视角
- 支持 Difix 后处理模式（`USE_DIFIX_MODE`）
- 渲染结果经 `redistort_gpu` 重新畸变回原始图像空间

**`render_sim`**: 通用渲染接口
- 支持 `hil_mode`（Hardware-in-the-Loop）高性能渲染
- 支持 `full_mode` 分类渲染（Background/Ground/Dynamic 分离）
- 使用 `XpengVisualizer` 保存图像和视频

**`render_profile`**: 性能分析
- 预计算 Ground 高斯（`precompute_gaussians`）
- 逐帧计时统计

**渲染结果重畸变流程**：
```
render() → result["rgb"] (去畸变空间)
  → torch.clamp(rgb * 255, 0, 255).permute(2,0,1).to(uint8)
  → redistort_gpu(cam_name, result)  # GPU 重畸变
  → permute(1,2,0).cpu().numpy()     # 回到 HWC numpy
```

### 4.3 数据集（driving_dataset.py）

`DrivingDataset` 继承 `SceneDataset`，支持多种数据集格式：

- 支持：Waymo / KITTI / NuScenes / ArgoVerse / PandaSet / NuPlan / XPeng
- 数据源：`pixel_source`（图像）+ `lidar_source`（点云）
- 帧范围：`start_timestep` 到 `end_timestep`
- 提供 `get_init_objects` / `get_lidar_samples` / `check_pts_visibility` / `filter_pts_in_boxes` 等初始化接口

## 5. Difix 集成

### 5.1 集成方式

Difix 作为后处理器集成到 Reconic 中，有两种使用路径：

**训练时（GenerativeReconTrainingLoop）**：
- 通过 `SerialScheduler` 调度 Difix 的训练和推理
- 3DGS 渲染结果作为 Difix 的输入
- Difix 生成的增强图像反馈给 3DGS 训练

**仿真时（ReconicSimulator）**：
- 通过 `init_difix_model()` 初始化 `DifixFixer`
- 配置来自 `simulator_config_manager.get_difix_config()`
- 渲染后对图像进行质量增强

### 5.2 SerialScheduler（serial_scheduler.py）

`SerialScheduler` 是 Difix 与 3DGS 训练之间的同步调度器：

**训练数据推送** (`push_training_pairs`):
```
(render_image, gt_image, mask, prompt) → 累积到 training_pairs
  → 达到 training_batch_size 时:
       → generative_engine.get_batch(batch_list)
       → generative_engine.training_forward(batch_data)
```

**推理数据推送** (`push_inference_image`):
```
(image, mask, info, index, ref_image, prompt) → 累积到 inference_images
  → 达到 inference_batch_size 或 infer_now=True 时:
       → generative_engine.get_infer_batch(batch_list)
       → generative_engine.inference_forward(...)
       → 结果放入 novel_data Queue
```

**数据消费** (`get_novel_data`):
```
→ 从 novel_data Queue 取出 (degrad_data, novel_data, sky_mask, info, index)
→ 供 3DGS 训练使用增强后的图像
```

**关键特性**：
- 支持动态 batch size 和尺寸不一致时的降级处理
- 训练/推理模式切换：`set_train()` / `set_eval()`
- Checkpoint 管理：`save_checkpoint()` / `resume_from_checkpoint()`

### 5.3 GenerativeScheduler（generative_scheduler.py）

该文件被 Pyarmor 加密保护，无法直接读取源码。根据 `SerialScheduler` 的接口推断，`GenerativeScheduler` 可能是异步版本的调度器，支持多线程/多进程并行的 Difix 训练和推理。

## 6. 目录结构速查

```
omnire_joint_trainning/src/reconic/
├── cli/
│   └── train_cli.py              # 训练入口 CLI
├── trainers/
│   ├── base_render.py            # BasicTrainer_render - 渲染基础层
│   ├── base.py                   # BasicTrainer - 训练核心层
│   └── scene_graph.py            # MultiTrainer - 场景图训练器
├── models/
│   ├── losses.py                 # 损失函数 (DepthLoss, SafeBCE, BCE)
│   ├── appearance_embedding.py   # 外观嵌入模型
│   ├── modules.py                # 辅助模型 (Sky, Affine, CamOpt, Deform, VoxelDeformer)
│   └── gaussians/
│       └── basics.py             # dataclass_camera, dataclass_gs
├── engines/
│   ├── serial_scheduler.py       # Difix 同步调度器
│   └── generative_scheduler.py   # Difix 异步调度器（加密）
├── simulator/
│   ├── reconic_simulator.py      # 仿真渲染器
│   └── render_strategy/
│       ├── strategies_factory.py # 渲染策略工厂
│       ├── render_strategy.py    # 策略抽象基类
│       ├── default_render_strategy.py
│       ├── difix_render_strategy.py
│       └── original_png_render_strategy.py
├── datasets/
│   ├── driving_dataset.py        # 驾驶数据集
│   ├── base/
│   │   ├── data_proto.py         # CameraInfo, ImageInfo, ImageMasks, Rays
│   │   ├── scene_dataset.py      # SceneDataset 基类
│   │   └── split_wrapper.py      # 数据集分割
│   └── xpeng/
│       ├── constants.py          # SemanticType, DATASET_CLASSES_IN_SEMANTIC
│       └── xpeng_utils.py        # 语义分割工具函数
├── render_sim.py                 # 渲染仿真脚本
├── evaluate_model.py             # 评估指标 (PSNR)
├── training_loop.py              # 训练循环实现
└── utils/
    ├── camera.py                 # 相机工具函数
    ├── geometry.py               # 几何变换工具
    ├── misc.py                   # import_str 等工具
    └── visualization.py          # 可视化布局
```

当前 simulator 渲染链路已经做成策略模式：`RenderStrategyFactory` 会从 `SimulatorConfigManager` 读取策略配置，按条件动态选择 `DefaultRenderStrategy`、`DifixRenderStrategy` 或其他策略类；每个策略同时提供 `render()` 和 `render_batch()` 两套接口，用于统一管理单相机渲染、批量多相机渲染、参考图获取和后处理流程。

## 7. 参考资料

- **3D Gaussian Splatting**: Kerbl et al., "3D Gaussian Splatting for Real-Time Radiance Field Rendering", SIGGRAPH 2023
- **gsplat**: 高性能 3DGS 光栅化库
- **OmniRe**: 基于场景图的驾驶场景重建框架
- **SMPL**: Loper et al., "SMPL: A Skinned Multi-Person Linear Model"
- **Mask2Former**: 用于语义/实例分割的 Transformer 架构
- **Difix**: 生成式图像修复/增强模型，用于 3DGS 渲染质量提升
- **detectron2**: Facebook AI Research 检测/分割框架
