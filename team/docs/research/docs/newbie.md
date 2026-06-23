# SimWorld 新人指南 (Newbie Guide)

> 本文档面向新加入三维重建团队的开发者，系统梳理 SimWorld 项目的整体架构、各模块设计原理、数据流和算法结构，帮助快速上手。

---

## 一、项目总览

SimWorld 是一个面向自动驾驶仿真场景的**三维重建与新视角合成**系统。核心目标是：从车载传感器（相机 + LiDAR）采集的真实道路数据出发，通过 3D Gaussian Splatting (3DGS) 技术重建高保真三维场景，并支持新视角渲染，为自动驾驶仿真提供逼真的视觉输入。

### 1.1 核心技术栈

| 技术 | 用途 |
|------|------|
| 3D Gaussian Splatting (3DGS) | 场景表示与可微渲染 |
| COLMAP | 稀疏重建 / SfM 位姿估计 |
| MVSNet (MVSA/CLMVSNet) | 多视角立体匹配，生成稠密深度 |
| Difix3D+ / NVFixer | 单步扩散模型，修复渲染伪影 |
| G3R (Neural Gaussians) | 稀疏 UNet 编码 + 高斯解码，前馈式重建 |
| EvoSplat | 前馈式高斯预测模型 |
| SAM3D | 3D 语义分割 |
| SMPL | 行人人体建模 |
| DCCF | 动态资产相机滤波与平滑 |

### 1.2 整体流程概览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        SimWorld 端到端流程                               │
│                                                                         │
│  ┌──────────┐   ┌──────────────┐   ┌──────────────┐   ┌─────────────┐  │
│  │ 数据拉取  │──▶│  数据预处理   │──▶│  模型训练     │──▶│ 渲染 & 部署  │  │
│  │          │   │              │   │              │   │             │  │
│  │ XMiner/  │   │ JSON解析     │   │ 3DGS训练     │   │ 新视角渲染   │  │
│  │ DataLoader│   │ 图像去畸变   │   │ (Reconic)    │   │ Difix后处理  │  │
│  │          │   │ 位姿优化     │   │              │   │ IPS生产部署  │  │
│  │          │   │ COLMAP/MVS   │   │ 场景图训练    │   │ 仿真接口     │  │
│  │          │   │ 点云生成     │   │ Difix联合训练 │   │             │  │
│  │          │   │ 深度图生成   │   │              │   │             │  │
│  │          │   │ 语义分割     │   │              │   │             │  │
│  └──────────┘   └──────────────┘   └──────────────┘   └─────────────┘  │
│                                                                         │
│  xpeng_data_process/   omnire_joint_trainning/   ips_deploy/            │
│  generate_dataset_data  street_gaussians/         sim_interface/         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 二、目录结构

```
simworld/
├── xpeng_data_process/      # 【数据预处理】核心模块，从原始传感器数据到训练数据
│   ├── main.py              # 预处理主入口
│   ├── pipelines.py         # Pipeline 编排（Lidar/Vision 两条线）
│   ├── generate_dataset_data.py  # 数据拉取（从大数据平台）
│   ├── settings/            # 配置管理（YACS）
│   ├── configs/             # YAML 配置文件
│   ├── img_processor.py     # 图像去畸变、语义分割
│   ├── lidar_processor.py   # LiDAR 点云处理
│   ├── colmap_processor.py  # COLMAP SfM
│   ├── point_processor.py   # 训练点云生成
│   ├── depth_processor.py   # 深度图生成
│   ├── opt_processor.py     # 相机位姿优化（DPVO）
│   ├── pose_processor.py    # 位姿平滑
│   ├── ground_processor.py  # 地面点云处理（ROGS/ROME）
│   ├── mvsnet_processor.py  # MVSNet 深度估计
│   ├── sam3d_processor.py   # SAM3D 语义分割
│   ├── seg_generator.py     # 语义分割生成
│   ├── mask_generator.py    # Mask 生成
│   ├── point_densifier.py   # 点云稠密化
│   ├── pcd_fusion_processor.py  # 点云融合
│   ├── trafficlight_processor.py # 交通灯点云提取
│   ├── mvsnet/              # MVSNet 模型（MVSA/CLMVSNet）
│   ├── optimization/        # 位姿优化（camopt/lidaropt/posemapping）
│   ├── sam3d/               # SAM3D 模型
│   ├── ground_processing/   # 地面处理（ROGS/ROME）
│   ├── data_mining/         # 数据挖掘（LOMM/Mask2Former）
│   └── utils/               # 工具函数
│
├── omnire_joint_trainning/  # 【模型训练】Reconic 训练框架
│   └── src/reconic/
│       ├── cli/             # 命令行入口（train/eval）
│       ├── datasets/        # 数据集加载
│       ├── models/          # 高斯模型定义
│       │   ├── gaussians/   # VanillaGaussians 等
│       │   ├── nodes/       # RigidNodes, SMPLNodes
│       │   ├── modules/     # Sky, Affine, CamPose 模块
│       │   └── losses.py    # 损失函数
│       ├── trainers/        # 训练器（MultiTrainer, SceneGraph）
│       ├── training_loop/   # 训练循环
│       ├── engines/         # 生成式引擎（Difix 联合训练）
│       ├── pipelines/       # Difix pipeline
│       └── render_sim.py    # 仿真渲染入口
│
├── street_gaussians/        # 【3DGS 训练】Street Gaussian 模型
│   ├── train.py             # 训练入口
│   ├── train_xpeng.py       # 小鹏定制训练
│   ├── train_2stages.py     # 两阶段训练
│   └── submodules/          # 子模块（simple-knn 等）
│
├── g3r/                     # 【前馈重建】G3R 神经高斯模型
│   ├── g3r_net.py           # 网络定义（SparseUNet + 高斯解码器）
│   ├── train_g3r.py         # 训练脚本
│   ├── inference.py         # 推理脚本
│   └── dataset.py           # 数据集
│
├── nail_evolsplat/          # 【前馈重建】EvoSplat 模型
│   ├── model/               # 模型定义
│   ├── train/               # 训练代码
│   ├── infer_evolsplat.py   # 推理入口
│   └── dataset.py           # 数据集
│
├── difix/                   # 【后处理】Difix3D+ 渲染修复
│   ├── fixer.py             # 修复主逻辑
│   └── src/                 # 模型源码
│
├── nvfixer/                 # 【后处理】NVFixer（基于 Cosmos Tokenizer）
│   ├── src/                 # 模型源码
│   └── fuyao_deploy_fixer/  # 扶摇部署脚本
│
├── dynamic_assets/          # 【动态资产】车辆等动态物体重建
│   ├── DCCF/                # 相机滤波平滑
│   ├── agent_service/       # 资产编辑服务
│   ├── gaussians_splatting/ # 资产高斯训练
│   ├── scenario_edit/       # 场景编辑
│   └── three_D_real_car_*   # 3D 真实车辆数据处理与训练
│
├── xpeng_raster/            # 【CUDA 渲染】自研高斯光栅化器
│   └── xpeng_raster/
│       ├── rendering.py     # Python 渲染接口
│       └── cuda/            # CUDA 核函数
│
├── sim_interface/           # 【仿真接口】仿真器基类与可视化
│   ├── simulator_base.py    # BaseSimulator 抽象类
│   └── visualizers/         # 可视化工具
│
├── ips_deploy/              # 【生产部署】IPS 平台部署
│   ├── deploy_ips.bash      # 部署脚本
│   ├── ips_xpeng_vision.py  # 纯视觉 IPS 主程序
│   ├── ips_main.py          # IPS 主入口
│   └── post_process.py      # 后处理
│
├── fuyao_deploy/            # 【扶摇部署】训练任务提交
│   ├── deploy_reconic.sh    # Reconic 训练部署
│   └── run_reconic.sh       # 训练运行脚本
│
├── tools/                   # 【工具脚本】分析与可视化
│   ├── scripts/             # IPS 分析、视频合并等
│   └── dynamic_check/       # 动态物体检查
│
├── dockerfile/              # Docker 镜像定义
│   ├── latest_a100/         # A100 镜像
│   └── latest_ppu/          # PPU 镜像
│
└── oss_defaults/            # OSS 默认配置
```

---

## 三、模块详解

### 3.1 数据预处理模块 (`xpeng_data_process/`)

#### 设计原理

数据预处理是整个 pipeline 的基础，负责将车载传感器的原始数据转换为 3DGS 训练所需的标准格式。系统支持两条并行的处理路线：

- **LiDAR 路线**：以 LiDAR 点云为主要几何信息来源
- **Vision 路线**：纯视觉方案，通过 MVSNet 获取深度信息

#### 数据流图

```
                        ┌─────────────────────────────────────────┐
                        │           数据拉取 (XMiner/DataLoader)    │
                        │  generate_dataset_data.py                │
                        └──────────────┬──────────────────────────┘
                                       │
                        ┌──────────────▼──────────────────────────┐
                        │           JSON 解析 (JsonProcessor)       │
                        │  解析标定、位姿、标注等元数据               │
                        └──────────────┬──────────────────────────┘
                                       │
                    ┌──────────────────┴──────────────────┐
                    │                                      │
           ┌────────▼────────┐                   ┌────────▼────────┐
           │   LiDAR 路线     │                   │   Vision 路线    │
           │                  │                   │                  │
           │ 1.位姿平滑       │                   │ 1.Vision数据拉取 │
           │ 2.Range生成      │                   │ 2.JSON解析       │
           │ 3.图像去畸变+分割│                   │ 3.Range生成      │
           │ 4.位姿优化(DPVO) │                   │ 4.图像去畸变+分割│
           │ 5.LiDAR点云处理  │                   │ 5.位姿优化       │
           │ 6.COLMAP SfM     │                   │ 6.SAM3D分割      │
           │ 7.训练点云生成   │                   │ 7.MVSNet深度估计 │
           │ 8.点云稠密化     │                   │ 8.点云融合       │
           │ 9.地面Surfel     │                   │ 9.地面点云       │
           │ 10.深度图生成    │                   │ 10.位姿平滑      │
           │ 11.G3R前馈重建   │                   │ 11.COLMAP SfM    │
           │ 12.交通灯提取    │                   │ 12.训练点云生成  │
           └────────┬────────┘                   │ 13.点云稠密化    │
                    │                             │ 14.深度图生成    │
                    │                             │ 15.EvoSplat前馈  │
                    │                             │ 16.交通灯提取    │
                    │                             └────────┬────────┘
                    │                                      │
                    └──────────────────┬───────────────────┘
                                       │
                        ┌──────────────▼──────────────────────────┐
                        │           训练数据输出                     │
                        │  images/ points3D.ply depth/ segs/ ...   │
                        └─────────────────────────────────────────┘
```

#### 输入输出

| 项目 | 说明 |
|------|------|
| **输入** | 车载传感器原始数据（7 路相机图像 + 2 路 LiDAR 点云 + 标定参数 + 位姿 + 标注） |
| **输出** | 去畸变图像、语义分割 mask、稀疏/稠密点云 (PLY)、深度图、COLMAP 模型、位姿文件 |
| **配置** | `configs/config_vision.yaml` 或 `configs/config_lidar.yaml` |

#### 关键处理器说明

| 处理器 | 功能 | 核心算法 |
|--------|------|----------|
| `ImgProcessor` | 图像去畸变、语义分割、实例分割 | OpenCV undistort + Mask2Former/LOMM |
| `OptProcessor` | 相机位姿优化 | DPVO (Deep Patch Visual Odometry) |
| `PoseProcessor` | 位姿平滑 | 滑动窗口平滑 |
| `ColmapProcessor` | 稀疏重建 | COLMAP SfM pipeline |
| `LidarProcessor` | LiDAR 点云处理与投影 | 体素下采样 + 坐标变换 |
| `PointProcessor` | 训练点云生成 | 多源点云融合 + 体素下采样 |
| `PointDensifier` | 点云稠密化 | 线特征点云加密 |
| `DepthProcessor` | 深度图生成 | 点云投影 + 遮挡处理 |
| `MvsnetProcessor` | 多视角深度估计 | MVSA / CLMVSNet |
| `GroundProcessor` | 地面点云处理 | ROGS / ROME 地面拟合 |
| `SAM3DProcessor` | 3D 语义分割 | SAM3D |
| `TrafficLightExtractor` | 交通灯点云提取 | 语义过滤 + 几何聚类 |


---

### 3.2 模型训练模块 (`omnire_joint_trainning/` + `street_gaussians/`)

#### 设计原理

训练模块基于 **3D Gaussian Splatting** 技术，将场景表示为一组三维高斯椭球体。每个高斯具有位置 (xyz)、协方差 (rotation + scale)、不透明度 (opacity) 和球谐系数 (SH) 等属性。通过可微光栅化渲染到图像平面，与真实图像计算损失进行端到端优化。

核心创新点在于**场景图 (Scene Graph)** 架构，将场景分解为多个语义类别分别建模：

```
                    ┌─────────────────────────────────┐
                    │         Scene Graph 场景图        │
                    │                                   │
                    │  ┌───────────┐  ┌──────────────┐ │
                    │  │ Background│  │    Ground     │ │
                    │  │ 背景高斯   │  │  地面高斯     │ │
                    │  │ (3DGS)    │  │  (2DGS init) │ │
                    │  └───────────┘  └──────────────┘ │
                    │  ┌───────────┐  ┌──────────────┐ │
                    │  │RigidNodes │  │  SMPLNodes   │ │
                    │  │ 刚体车辆   │  │  行人(SMPL)  │ │
                    │  └───────────┘  └──────────────┘ │
                    │  ┌───────────┐  ┌──────────────┐ │
                    │  │    Sky    │  │   Affine     │ │
                    │  │ 天空模型   │  │  仿射变换     │ │
                    │  │ (MLP)     │  │  (外观补偿)   │ │
                    │  └───────────┘  └──────────────┘ │
                    │  ┌───────────┐  ┌──────────────┐ │
                    │  │  CamPose  │  │ Trafficlight │ │
                    │  │ 相机优化   │  │  交通灯       │ │
                    │  └───────────┘  └──────────────┘ │
                    └─────────────────────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────────┐
                    │      可微光栅化渲染 (gsplat)       │
                    │  xpeng_raster (自研 CUDA 核函数)   │
                    └──────────────┬──────────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────────┐
                    │         损失函数计算               │
                    │  L = L_rgb + L_ssim + L_mask     │
                    │    + L_depth + L_affine           │
                    │    + L_dynamic_opacity            │
                    └─────────────────────────────────┘
```

#### 训练 Pipeline

```
输入数据 ──▶ DrivingDataset 加载
              │
              ▼
         MultiTrainer 初始化各子模型
              │
              ▼
         XpengTrainingLoop 训练循环
              │
              ├──▶ forward_step: 采样视角 → 渲染 → 计算损失
              ├──▶ backward_step: 反向传播
              ├──▶ 自适应密度控制 (densify/prune)
              └──▶ Difix 联合训练 (可选, 25k iter 后启动)
                    │
                    ▼
              生成式引擎 (DifixModel)
              对渲染结果进行扩散修复
              修复后的图像作为额外监督信号
```

#### 模型结构

| 子模型 | 类型 | 说明 |
|--------|------|------|
| `Background` | VanillaGaussians | 静态背景，从 LiDAR 点云初始化，支持前馈初始化 |
| `Ground` | VanillaGaussians | 地面，2DGS 初始化（扁平高斯），限制 xyz 学习率 |
| `RigidNodes` | RigidNodes | 刚体动态物体（车辆），带实例级旋转/平移优化 |
| `SMPLNodes` | SMPLNodes | 行人，基于 SMPL 人体模型 + 体素变形器 |
| `Sky` | SkyModel (MLP) | 天空模型，MLP 预测天空颜色 |
| `Affine` | AffineTransform | 逐帧仿射变换，补偿曝光/白平衡差异 |
| `CamPose` | CameraOptModule | 相机位姿微调 |
| `Trafficlight` | VanillaGaussians | 交通灯专用高斯 |

#### 损失函数

| 损失 | 权重 | 说明 |
|------|------|------|
| `L_rgb` | 1.2 | L1 像素损失 |
| `L_ssim` | 1.0 | 结构相似性损失 |
| `L_mask` | 0.2 | 动态物体 mask BCE 损失 |
| `L_depth` | 0.1 | 深度监督损失 |
| `L_affine` | 0.00001 | 仿射正则化 |
| `L_dynamic_opacity` | 0.1 | 动态物体不透明度正则 (20k iter 后) |
| `L_trafficlight` | 5.0 | 交通灯 RGB 加权损失 |

#### 输入输出

| 项目 | 说明 |
|------|------|
| **输入** | 预处理后的数据：去畸变图像、点云 PLY、深度图、语义 mask、COLMAP 模型、位姿 |
| **输出** | 训练好的高斯模型 checkpoint (.pth)、渲染视频、评估指标 (PSNR/SSIM/LPIPS/FID) |
| **配置** | `src/configs/version_control/sim3dgs_v410.yaml` |
| **部署** | 通过 `fuyao_deploy/deploy_reconic.sh` 提交到扶摇平台 |


---

### 3.3 前馈重建模块 (`g3r/` + `nail_evolsplat/`)

#### G3R — Neural Gaussians Decoder

**设计原理**：传统 3DGS 需要逐场景优化（per-scene optimization），耗时较长。G3R 采用前馈方式，通过 Sparse UNet 对点云进行特征编码，再用 MLP 解码器预测每个点的高斯属性，实现快速初始化。

```
输入点云 (N, 3+C)
      │
      ▼
┌─────────────┐
│ SparseResUNet│  ← 稀疏 3D 卷积，提取多尺度特征
│ (TorchSparse)│
└──────┬──────┘
       │ 特征向量 (N, D)
       ▼
┌─────────────┐
│ NeuralGaussians│  ← MLP 解码高斯属性
│ Decoder      │
│  ├─ mlp → Δ(opacity, scale, sh)
│  ├─ mlp_color → RGB 颜色
│  └─ mlp_rotations → 旋转四元数
└──────┬──────┘
       │
       ▼
  高斯属性 (xyz, rotation, scale, opacity, color)
```

| 项目 | 说明 |
|------|------|
| **输入** | 稀疏点云 + 颜色 |
| **输出** | 每个点的高斯属性（位置、旋转、缩放、不透明度、颜色） |
| **优势** | 单次前向传播即可获得初始高斯，大幅加速训练收敛 |

#### EvoSplat — 前馈高斯预测

**设计原理**：类似 G3R 的前馈思路，但基于图像输入而非点云。从多视角图像直接预测高斯参数，用于快速初始化或独立推理。

| 项目 | 说明 |
|------|------|
| **输入** | 多视角图像 + 种子点 |
| **输出** | 高斯场景表示 |
| **用途** | Vision 路线的前馈初始化 |

---

### 3.4 渲染后处理模块 (`difix/` + `nvfixer/`)

#### 设计原理

3DGS 渲染在欠约束区域（如遮挡区域、远处、天空边缘）会产生伪影。Difix3D+ 和 NVFixer 使用**单步扩散模型**对渲染图像进行修复：

```
3DGS 渲染图像 (含伪影)
      │
      ▼
┌─────────────────┐
│  Difix3D+ /     │  ← 单步去噪 (timestep=199/250)
│  NVFixer        │     条件：渲染图像 + 参考图像(可选)
│  (Diffusion)    │     提示词："remove degradation"
└──────┬──────────┘
       │
       ▼
  修复后的高质量图像
```

**联合训练模式**：在 Reconic 训练框架中，Difix 可作为生成式引擎参与联合训练（25k iter 后启动），将修复后的图像作为额外监督信号，提升重建质量。

| 模块 | 基础模型 | 特点 |
|------|----------|------|
| `difix/` | Difix3D+ (diffusers) | 轻量，支持参考图像引导 |
| `nvfixer/` | Cosmos Tokenizer + Fixer | 更强的修复能力，需要 Cosmos 环境 |

---

### 3.5 动态资产模块 (`dynamic_assets/`)

#### 设计原理

自动驾驶场景中的动态物体（车辆、行人）需要单独建模，以支持场景编辑（如车辆替换、轨迹修改）。

```
3D Real Car 数据
      │
      ▼
┌─────────────────┐
│ 数据预处理       │  COLMAP + 分割 + 清洗 + 标准化 + 缩放
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 高斯训练         │  单物体 3DGS 训练 → PLY 资产
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ 场景编辑         │  DCCF 相机滤波 + 场景插入/替换
└─────────────────┘
```

| 子模块 | 功能 |
|--------|------|
| `three_D_real_car_preprocess/` | 3D Real Car 数据集预处理 |
| `gaussians_splatting/` | 资产高斯训练 |
| `DCCF/` | 动态资产相机滤波与平滑 |
| `scenario_edit/` | 场景编辑工具 |
| `agent_service/` | 资产编辑服务 (TBD) |

---

### 3.6 自研渲染器 (`xpeng_raster/`)

#### 设计原理

基于 gsplat 的自研 CUDA 高斯光栅化器，针对小鹏场景优化。核心流程：

```
3D 高斯参数 (means, quats, scales, opacities, colors)
      │
      ▼
┌─────────────────┐
│ EWA 投影         │  3D 高斯 → 2D 椭圆 (CUDA)
│ projection_ewa   │  计算 radii, means2d, depths, conics
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ Tile 排序 & 渲染 │  按 tile 分组，前后排序，alpha blending
│ rasterize_fwd    │
└──────┬──────────┘
       │
       ▼
  渲染图像 (H, W, 3) + Alpha (H, W, 1)
```

---

### 3.7 生产部署模块 (`ips_deploy/`)

#### 设计原理

IPS (Intelligent Production System) 是生产环境的部署平台。整个流程在 IPS 上以 streaming 或 batch 方式运行：

```
IPS 任务触发
      │
      ▼
┌─────────────────┐
│ pre_processor    │  数据拉取 + 预处理 (复用 xpeng_data_process)
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ processor        │  3DGS 训练 (复用 omnire_joint_trainning)
└──────┬──────────┘
       │
       ▼
┌─────────────────┐
│ post_processor   │  渲染 + Difix 修复 + 评估 + 上传 OSS
└─────────────────┘
```

| 项目 | 说明 |
|------|------|
| **输入** | clip_id + 配置参数 |
| **输出** | 训练模型 + 渲染视频 + 评估指标，上传至 OSS |
| **部署方式** | `deploy_ips.bash` 提交 IPS 任务 |

---

### 3.8 仿真接口 (`sim_interface/`)

#### 设计原理

提供统一的仿真器接口 `BaseSimulator`，支持：
- 加载训练好的 3DGS 模型
- 接收新的 ego pose（位姿偏移、车道变换等）
- 渲染新视角图像
- 支持重畸变（redistort）还原到原始相机模型
- 集成 DCCF 相机滤波平滑

```
仿真控制信号 (ego_pose, 车道偏移等)
      │
      ▼
┌─────────────────┐
│ BaseSimulator    │
│  ├─ init_models  │  加载 3DGS 模型
│  ├─ render       │  渲染新视角
│  └─ redistort    │  重畸变到原始相机
└──────┬──────────┘
       │
       ▼
  仿真图像 (供自动驾驶算法消费)
```

---

## 四、训练与推理 Pipeline 汇总

### 4.1 训练 Pipeline

```
原始数据 ──▶ 数据拉取 ──▶ 预处理 ──▶ 3DGS 训练 ──▶ (可选) Difix 联合训练 ──▶ 模型输出
                │              │            │                │
                │              │            │                │
          generate_dataset  pipelines   train_cli.py    DifixModel
          _data.py          .py         XpengTrainingLoop  (25k iter后)
```

### 4.2 推理/渲染 Pipeline

```
训练模型 + 新视角位姿 ──▶ 高斯渲染 ──▶ Difix/NVFixer 修复 ──▶ 重畸变 ──▶ 输出图像
                              │              │                    │
                        xpeng_raster    difix/nvfixer      redistort
                        (CUDA)          (Diffusion)        (OpenCV)
```

### 4.3 生产 Pipeline (IPS)

```
IPS 触发 ──▶ pre_processor ──▶ processor ──▶ post_processor ──▶ OSS 上传
              (数据预处理)      (3DGS训练)    (渲染+修复+评估)
```

---

## 五、设计原理与核心思路

### 5.1 为什么选择 3D Gaussian Splatting？

相比 NeRF（隐式表示 + 体渲染），3DGS 具有：
- **显式表示**：每个高斯有明确的空间位置和属性，便于编辑和组合
- **实时渲染**：基于光栅化而非光线追踪，渲染速度快 100-1000x
- **可微优化**：支持端到端梯度优化
- **适合驾驶场景**：大规模户外场景、动态物体、多相机系统

### 5.2 场景图分解的设计思路

将场景分解为 Background / Ground / RigidNodes / SMPLNodes / Sky 等子模型：
- **物理合理性**：不同类别有不同的运动模式（静态/刚体/非刚体）
- **独立优化**：各子模型可以有不同的学习率、密度控制策略
- **场景编辑**：支持单独替换/移除某类物体
- **地面特殊处理**：2DGS 初始化（扁平高斯）+ 限制 xyz 学习率，保证地面平整

### 5.3 双路线设计（LiDAR vs Vision）

| 维度 | LiDAR 路线 | Vision 路线 |
|------|-----------|-------------|
| 几何来源 | LiDAR 点云 | MVSNet 深度估计 |
| 精度 | 高（直接测量） | 中（估计值） |
| 成本 | 需要 LiDAR 硬件 | 仅需相机 |
| 适用场景 | 高精度需求 | 纯视觉车型 |
| 额外步骤 | G3R 前馈 | EvoSplat 前馈 + SAM3D |

### 5.4 Difix 联合训练的设计思路

传统流程是先训练 3DGS，再用 Difix 后处理。联合训练的创新在于：
- 训练到 25k iter 后启动 Difix 生成式引擎
- 对当前渲染结果进行扩散修复
- 修复后的图像作为额外监督信号反馈给 3DGS
- 形成"渲染 → 修复 → 监督"的闭环，提升欠约束区域质量

---

## 六、后续优化建议

### 6.1 精度提升

| 方向 | 具体建议 | 预期收益 |
|------|----------|----------|
| **深度监督增强** | 引入单目深度估计模型 (如 Depth Anything V2) 作为额外深度先验 | 提升远处和遮挡区域的几何精度 |
| **法线监督** | 增加法线一致性损失，约束高斯朝向 | 减少地面和墙面的浮动伪影 |
| **多分辨率训练** | 从低分辨率逐步提升到高分辨率 | 加速收敛 + 避免局部最优 |
| **更好的天空模型** | 用全景天空 HDR 替代 MLP 天空模型 | 提升天空区域真实感 |
| **动态物体重建** | 引入时序一致性约束（光流监督） | 减少动态物体的闪烁和模糊 |

### 6.2 效率提升

| 方向 | 具体建议 | 预期收益 |
|------|----------|----------|
| **前馈初始化** | 扩展 G3R/EvoSplat 覆盖更多场景类型 | 减少 per-scene 优化迭代次数 |
| **高斯压缩** | 引入高斯剪枝 + 量化 (如 Mini-Splatting) | 减少内存占用和渲染时间 |
| **并行预处理** | 将 CPU/GPU 步骤进一步解耦，流水线并行 | 缩短预处理时间 |
| **增量训练** | 支持在已有模型基础上增量更新 | 避免从头训练 |
| **渲染器优化** | 优化 tile 排序和 alpha blending 的 CUDA 实现 | 提升渲染帧率 |

### 6.3 创新点方向

| 方向 | 具体建议 |
|------|----------|
| **4D Gaussian Splatting** | 引入时间维度，统一建模动态场景，替代当前的场景图分解方案 |
| **生成式场景补全** | 利用大规模预训练扩散模型，对未观测区域进行合理补全 |
| **语义感知渲染** | 在高斯属性中嵌入语义特征，支持语义级别的场景编辑 |
| **自监督深度估计** | 用渲染一致性替代 MVSNet，减少对外部深度模型的依赖 |
| **端到端可微仿真** | 将渲染器梯度传递到自动驾驶模型，实现闭环优化 |

### 6.4 工程迭代建议

| 方向 | 具体建议 |
|------|----------|
| **统一配置系统** | 将 YACS + OmegaConf + argparse 统一为一套配置方案 |
| **自动化测试** | 增加单元测试和集成测试，覆盖核心 pipeline |
| **监控与告警** | IPS 部署增加训练指标监控（loss 曲线、渲染质量） |
| **数据版本管理** | 引入数据版本控制，追踪预处理配置与训练数据的对应关系 |
| **模型注册中心** | 统一管理不同版本的训练模型和配置 |

---

## 七、快速上手指南

### 7.1 环境准备

```bash
# A100 镜像
docker pull infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:yangxh7-251209-0220

# PPU 镜像
docker pull infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wangyd13-251218-0102
```

### 7.2 数据预处理

```bash
cd xpeng_data_process
python main.py --config configs/config_vision.yaml
```

### 7.3 模型训练（扶摇平台）

```bash
cd fuyao_deploy
bash deploy_reconic.sh <config> <clip_id> <cameras_id> <output_path> [priority]
```

### 7.4 IPS 生产部署

```bash
cd ips_deploy
bash deploy_ips.bash
```

### 7.5 关键文档

| 文档 | 链接 |
|------|------|
| 3DGS 跑通 + 生产部署指南 | [飞书文档](https://xiaopeng.feishu.cn/docx/VYimdbtakoTbetxTGS9cDYDYnjh) |
| IPS V2 跑通教学 | [飞书文档](https://xiaopeng.feishu.cn/docx/QlZbdfmGpoe39gxFkrkc02hbnQc) |
| IPS V2 深度迁移后提交 job | [飞书文档](https://xiaopeng.feishu.cn/wiki/Tpnow2u5Wi1VqTkaoqHcpSzznhU) |
| 纯视觉生产/扶摇任务执行流程 | [飞书文档](https://xiaopeng.feishu.cn/wiki/S3fBw5Z83inSQGksaV4cVbennvc) |
