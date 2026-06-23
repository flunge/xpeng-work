# SimWorld 新人上手指南

> 本文档面向新加入三维重建团队的开发者，帮助你快速理解项目全貌并跑通核心流程。

---

## 目录

1. [项目概览](#1-项目概览)
2. [核心 Pipeline 与模型体系](#2-核心-pipeline-与模型体系)
3. [各模式下的输入输出与数据流转](#3-各模式下的输入输出与数据流转)
4. [快速跑通小范围验证](#4-快速跑通小范围验证)
5. [核心代码注释与规范建议](#5-核心代码注释与规范建议)
6. [开发状态与团队分工](#6-开发状态与团队分工)

---

## 1. 项目概览

SimWorld 是一个面向自动驾驶仿真的三维重建系统，核心能力是：**从车载传感器数据（相机 + LiDAR）重建街景 3D Gaussian Splatting 模型，并部署到仿真平台用于闭环测试**。

### 1.1 目录结构总览

```
simworld/
├── xpeng_data_process/    # 数据预处理 Pipeline（核心入口）
│   ├── main.py            # 本地/扶摇预处理主入口
│   ├── pipelines.py       # Pipeline 编排（lidar/vision 两条线）
│   ├── settings/           # 配置管理
│   ├── generate_dataset_data.py  # 从大数据平台拉取原始数据
│   └── *_processor.py     # 各步骤处理器（img/lidar/colmap/depth/...）
│
├── street_gaussians/      # 3D Gaussian Splatting 训练 & 渲染（Street Gaussians）
│   ├── train_xpeng.py     # 小鹏定制训练入口
│   ├── render_sim.py      # 仿真渲染入口
│   ├── lib/               # 模型核心（gaussian_model, renderer, datasets, utils）
│   └── configs/           # 训练配置
│
├── omnire_joint_trainning/ # OmniRe/Reconic 联合训练框架
│   ├── src/reconic/       # 训练器、模型、数据集、渲染
│   ├── deploy_cmd/        # 扶摇部署脚本（train/render/eval）
│   └── configs/           # 配置生成脚本
│
├── g3r/                   # G3R 网络（Ground Gaussian Reconstruction）
│   ├── train_g3r.py       # G3R 训练
│   ├── inference.py       # G3R 推理
│   └── g3r_net.py         # 网络结构（Sparse UNet）
│
├── nail_evolsplat/        # EvoSplat 前馈式 3DGS（Feed-Forward）
│   ├── infer_evolsplat.py # 推理入口
│   ├── dataset.py         # 数据加载
│   └── model/             # 模型定义
│
├── dynamic_assets/        # 动态物体资产（车辆 3DGS、场景编辑、色彩协调 DCCF）
├── difix/                 # 图像修复工具（DiFix）
├── nvfixer/               # NV 修复工具
├── sim_interface/         # 仿真接口层（Simulator Base + Visualizer）
├── xpeng_raster/          # 自研光栅化器
│
├── ips_deploy/            # IPS 生产部署（核心）
│   ├── ips_main.py        # IPS 标准部署入口（lidar 模式）
│   ├── ips_xpeng_vision.py # IPS vision 模式部署入口
│   ├── deploy_ips.bash    # 打包上传脚本
│   └── post_process.py    # 后处理（上传 OSS 等）
│
├── fuyao_deploy/          # 扶摇平台部署脚本
│   ├── deploy_reconic.sh  # Reconic 训练部署
│   └── run_reconic.sh     # 训练执行脚本
│
├── oss_defaults/          # OSS 上的默认配置文件集合
├── docker/                # Docker 构建相关
├── dockerfile/            # Dockerfile 定义
└── tools/                 # 辅助工具脚本
```

### 1.2 使用镜像

| 用途 | 镜像 |
|------|------|
| A100 训练/预处理 | `infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:yangxh7-251209-0220` |
| PPU 部署 | `infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:wangyd13-251218-0102` |

---

## 2. 核心 Pipeline 与模型体系

项目包含 **两条数据预处理 Pipeline** 和 **三种训练模型**。

### 2.1 两条预处理 Pipeline

#### Pipeline A：LiDAR 模式（`source=lidar`）

适用于有 LiDAR 数据的场景，点云质量高，是主力生产模式。

```
CPU 阶段 (pipeline_m1_lidar_cpu):
  JsonProcessor → PoseProcessor → RangeProcessor

GPU 阶段 (pipeline_m1_lidar_gpu):
  ImgProcessor → OptProcessor → LidarProcessor → ColmapProcessor
  → PointProcessor → PointDensifier → GrdSurfelProcessor
  → DepthProcessor → G3RProcessor → TrafficLightExtractor
```

#### Pipeline B：Vision 模式（`source=vision`）

纯视觉方案，无需 LiDAR，通过 MVSNet 生成深度/点云。

```
CPU 阶段 (pipeline_vision_cpu):
  VisionDataFetcher → JsonProcessor → RangeProcessor

GPU 阶段 (pipeline_vision_gpu):
  ImgProcessor → OptProcessor → SAM3DProcessor → MvsnetProcessor
  → PcdFusionProcessor → GroundProcessor → PoseProcessor
  → ColmapProcessor → PointProcessor → PointDensifier
  → DepthProcessor → EvoSplatProcessor → TrafficLightExtractor
```

### 2.2 三种训练模型

| 模型 | 目录 | 特点 | 部署方式 |
|------|------|------|---------|
| **Street Gaussians** | `street_gaussians/` | 经典 3DGS 优化式训练，分静态/动态/天空/地面多组件 | IPS `ips_main.py` (lidar) |
| **Reconic (OmniRe)** | `omnire_joint_trainning/` | 联合训练框架，支持生成式模型，更先进 | 扶摇 `deploy_reconic.sh` |
| **EvoSplat** | `nail_evolsplat/` | 前馈式 3DGS，无需逐场景优化，速度快 | Vision Pipeline 内嵌调用 |

辅助模型：
- **G3R**（`g3r/`）：地面高斯重建网络，在 LiDAR Pipeline 中作为一个步骤调用
- **DCCF**（`dynamic_assets/DCCF/`）：色彩协调网络，用于动态物体合成后的颜色一致性

---

## 3. 各模式下的输入输出与数据流转

### 3.1 LiDAR 模式全流程

```
┌─────────────────────────────────────────────────────────────────┐
│                        输入                                      │
│  大数据平台 clip 数据（图像 + LiDAR 点云 + 标定 + 位姿）          │
└──────────────────────────┬──────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 0: generate_dataset_data.py                                │
│  从 DataLoader 拉取原始数据 → 写入 {root}/{clip_id}/             │
│  输出: images/, lidars/, calibs.json, poses.json                 │
└──────────────────────────┬───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 1: JsonProcessor                                           │
│  解析标定/位姿 JSON → 生成统一格式的 transforms.json              │
│  输出: transforms.json, metadata.json                            │
└──────────────────────────┬───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 2: PoseProcessor                                           │
│  位姿平滑优化                                                     │
│  输出: smoothed_poses.json                                       │
└──────────────────────────┬───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 3: ImgProcessor                                            │
│  图像去畸变 + 语义分割 + Mask 生成                                │
│  输出: images_undistorted/, segs/, masks/                        │
└──────────────────────────┬───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 4: OptProcessor                                            │
│  相机标定优化（外参精调）                                         │
│  输出: optimized_calibs.json                                     │
└──────────────────────────┬───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 5: LidarProcessor                                          │
│  LiDAR 点云拼接/投影                                              │
│  输出: merged_pcd.ply                                            │
└──────────────────────────┬───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 6: ColmapProcessor                                         │
│  运行 COLMAP SfM → 生成稀疏重建                                  │
│  输出: colmap/sparse/                                            │
└──────────────────────────┬───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 7-9: PointProcessor → PointDensifier → GrdSurfelProcessor  │
│  生成训练用点云 → 加密 → 地面 Surfel                              │
│  输出: points3d.ply, dense_points.ply, ground_surfel.ply         │
└──────────────────────────┬───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 10: DepthProcessor                                         │
│  生成增强深度图（稠密、遮挡感知）                                  │
│  输出: depth/                                                    │
└──────────────────────────┬───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Step 11: G3RProcessor (可选)                                    │
│  地面高斯重建网络推理                                             │
│  输出: g3r_output/                                               │
└──────────────────────────┬───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  训练: street_gaussians/train_xpeng.py                           │
│  输入: 上述所有预处理产物                                         │
│  输出: trained_model/ (checkpoint + ply)                         │
└──────────────────────────┬───────────────────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  渲染: street_gaussians/render_sim.py                            │
│  输入: trained_model + 新视角位姿                                 │
│  输出: 渲染图像/视频 (simulator_render/)                          │
└──────────────────────────────────────────────────────────────────┘
```

### 3.2 Vision 模式差异

与 LiDAR 模式的主要区别：
- 无 LiDAR 数据，通过 **MVSNet** 从多视角图像估计深度
- 通过 **PcdFusionProcessor** 融合多视角深度为点云
- 通过 **GroundProcessor** 单独处理地面点
- 可选调用 **EvoSplat** 做前馈式初始化

### 3.3 Reconic 训练模式

```
预处理（同上） → omnire_joint_trainning/src/reconic/cli/train_cli.py
  → 训练完成 → convert_model_to_ply.py → render_sim.py
```

部署通过扶摇平台：`fuyao_deploy/deploy_reconic.sh` → `run_reconic.sh`

### 3.4 IPS 生产部署模式

IPS 是生产环境的自动化部署平台，入口函数遵循固定接口：

```python
def pre_processor(context: dict, **kwargs):   # CPU 预处理
def gpu_processor(context: dict, **kwargs):   # GPU 预处理 + 训练 + 渲染 + 上传
```

`context` 由 IPS 平台注入，包含 `id`（clip_id）、`root_path`、`data_loader`、`data_record`、`logger` 等。

| IPS 入口 | 模式 | 说明 |
|----------|------|------|
| `ips_main.py` | LiDAR | 标准 Street Gaussians 训练 |
| `ips_xpeng_vision.py` | Vision | 纯视觉 Pipeline + 训练 |
| `ips_main_2models.py` | 双模型 | 同时训练两个模型 |
| `ips_xpeng_feedforward.py` | 前馈 | EvoSplat 前馈推理 |

### 3.5 核心函数调用关系

```
main.py
  ├── get_config_list()                    # 读取配置
  ├── make_case_specific_settings(cfg)     # 生成 clip 级配置
  ├── dump_source_data(cfg)                # 拉取数据
  └── pipelines.pipeline_m1_lidar_cpu(cfg) # CPU 预处理
      pipelines.pipeline_m1_lidar_gpu(cfg) # GPU 预处理
          ├── ImgProcessor(cfg).process_undistort_parallel()
          ├── OptProcessor(cfg).process_optimization()
          ├── LidarProcessor(cfg).process_lidar()
          ├── ColmapProcessor(cfg).run_colmap()
          ├── PointProcessor(cfg).process_training_points()
          ├── PointDensifier(cfg).process_densify()
          ├── GrdSurfelProcessor(cfg).process_surfel()
          ├── DepthProcessor(cfg).process_enhanced_depth()
          ├── G3RProcessor(cfg).process_g3r()
          └── TrafficLightExtractor(cfg).process_all_frames()
```

---

## 4. 快速跑通小范围验证

### 4.1 本地预处理验证

1. **准备环境**：使用 A100 镜像启动容器
2. **准备配置**：修改 `oss_defaults/run_preprocess.yaml`，填入真实的 `clip_id` 和 `root` 路径
3. **运行**：
   ```bash
   cd xpeng_data_process
   python main.py
   ```
4. **验证产物**：检查 `{root}/{clip_id}/` 下是否生成了 `images_undistorted/`、`colmap/`、`points3d.ply` 等

> **Tips**：可通过 `settings/config.py` 中的 `steps_controller` 开关跳过耗时步骤，只跑你关心的阶段。

### 4.2 Street Gaussians 训练验证

```bash
cd street_gaussians
python train_xpeng.py --config configs/example/waymo_train_002.yaml
```

训练完成后渲染验证：
```bash
python render_sim.py --config <output_dir>/configs/config_sim.yaml \
    --save_path <output_dir>/simulator_render
```

### 4.3 Reconic 训练验证

```bash
cd omnire_joint_trainning/src
export PYTHONPATH=$(pwd)
python reconic/cli/train_cli.py \
    --config_file <config_path> \
    --output_root <output_path> \
    --project <clip_id> \
    --run_name <cameras_id>
```

### 4.4 扶摇平台提交任务

```bash
cd fuyao_deploy
bash deploy_reconic.sh <config> <clip_id> <cameras_id> <output_path> [priority]
```

### 4.5 IPS 部署包制作

```bash
cd ips_deploy
bash deploy_ips.bash ips_main.py
# 输出 OSS 路径，用于 IPS 平台配置
```

### 4.6 最小验证清单

| 验证项 | 命令/检查 | 预期结果 |
|--------|----------|---------|
| 数据拉取 | `python generate_dataset_data.py` | `{clip_path}/` 下有图像和点云 |
| 预处理 CPU | `pipeline_m1_lidar_cpu` 无报错 | `transforms.json` 生成 |
| 预处理 GPU | `pipeline_m1_lidar_gpu` 无报错 | `points3d.ply` 生成 |
| 训练 | `train_xpeng.py` 跑 1000 iter | loss 下降，checkpoint 保存 |
| 渲染 | `render_sim.py` | `simulator_render/` 下有视频 |

---

## 5. 核心代码注释与规范建议

### 5.1 关键文件速查

| 文件 | 职责 | 阅读优先级 |
|------|------|-----------|
| `xpeng_data_process/main.py` | 预处理总入口 | ⭐⭐⭐ |
| `xpeng_data_process/pipelines.py` | Pipeline 编排，理解全流程必读 | ⭐⭐⭐ |
| `xpeng_data_process/settings/config.py` | 配置体系，理解所有开关 | ⭐⭐⭐ |
| `street_gaussians/train_xpeng.py` | 训练主循环 | ⭐⭐⭐ |
| `street_gaussians/lib/models/street_gaussian_model.py` | 核心模型定义 | ⭐⭐ |
| `street_gaussians/lib/models/street_gaussian_renderer.py` | 渲染器 | ⭐⭐ |
| `street_gaussians/render_sim.py` | 仿真渲染 | ⭐⭐ |
| `ips_deploy/ips_main.py` | IPS 部署入口 | ⭐⭐ |
| `omnire_joint_trainning/deploy_cmd/train_cmd.sh` | Reconic 训练脚本 | ⭐⭐ |

### 5.2 配置体系说明

配置通过 `yacs.CfgNode` 管理，核心开关在 `steps_controller`：

```python
cfg.steps_controller.source = "lidar"       # "lidar" 或 "vision"，决定走哪条 Pipeline
cfg.steps_controller.json_processor = True   # 是否执行 JSON 解析
cfg.steps_controller.img_processor = True    # 是否执行图像处理
cfg.steps_controller.colmap_processor = False # 是否运行 COLMAP
cfg.steps_controller.point_processor = True  # 是否生成训练点云
cfg.steps_controller.depth_processor = True  # 是否生成深度图
cfg.steps_controller.g3r_processor = False   # 是否运行 G3R
# ... 更多开关见 settings/config.py
```

### 5.3 编码规范建议

1. **Processor 模式**：每个处理步骤封装为独立的 `XxxProcessor` 类，构造函数接收 `cfg`，核心方法为 `process_xxx()`
2. **配置驱动**：所有行为通过 `cfg.steps_controller` 开关控制，不要硬编码跳过逻辑
3. **日志规范**：使用 `print(f"######### [INFO] ...")` 格式，便于日志过滤
4. **路径管理**：所有路径基于 `cfg.clip_path` 拼接，不要使用绝对路径
5. **IPS 接口**：生产部署入口必须遵循 `pre_processor(context, **kwargs)` / `gpu_processor(context, **kwargs)` 签名
6. **异常处理**：IPS 模式下需捕获异常并通过 `context["data_record"].notify_cloudsim_3dgs()` 上报

---

## 6. 开发状态与团队分工

### 6.1 仓库状态

- **主分支**：`dev`
- **当前提交数**：仓库为从 CPFS 拷贝初始化（单次提交），历史提交在内部 Git 服务器
- **初始提交者**：peijh (peijh@xiaopeng.com)

### 6.2 模块负责人（根据代码路径和注释推断）

| 模块 | 推断负责人 | 核心贡献 |
|------|-----------|---------|
| 数据预处理 (`xpeng_data_process/`) | yangxh7 | Pipeline 架构、各 Processor 实现、IPS 集成 |
| Street Gaussians (`street_gaussians/`) | 团队共建 | 3DGS 训练/渲染、小鹏定制化适配 |
| Reconic (`omnire_joint_trainning/`) | 团队共建 | OmniRe 联合训练框架集成 |
| G3R (`g3r/`) | 专项开发 | 地面高斯重建网络 |
| EvoSplat (`nail_evolsplat/`) | lvy10 | 前馈式 3DGS 推理 |
| 动态资产 (`dynamic_assets/`) | 专项开发 | 车辆 3DGS、场景编辑、色彩协调 |
| IPS 部署 (`ips_deploy/`) | yangxh7 | 生产部署脚本、OSS 上传 |
| 扶摇部署 (`fuyao_deploy/`) | yangxh7 | 扶摇平台训练任务提交 |
| DiFix (`difix/`) | 专项开发 | 图像修复 |
| 仿真接口 (`sim_interface/`) | 团队共建 | Simulator 基类、可视化 |

> **注意**：以上负责人信息基于代码中的路径引用和用户名推断，具体分工请向团队 lead 确认。

### 6.3 版本演进

从 `oss_defaults/` 中的配置文件可以看出版本演进：
- `default_2.3.2` → `default_2.4.0` → `default_2.5.0` → `latest_static_*`
- 最新版本支持多种变体：`v1_plus`、`v2`、`v2_plus`、`v2_light`、`v2_g3r`、`v2_vision`

---

## 附录：常用参考文档

| 文档 | 链接 |
|------|------|
| 3D Gaussian Splatting 跑通 + 生产部署指南 | [飞书文档](https://xiaopeng.feishu.cn/docx/VYimdbtakoTbetxTGS9cDYDYnjh) |
| IPS V2 跑通手把手教学 | [飞书文档](https://xiaopeng.feishu.cn/docx/QlZbdfmGpoe39gxFkrkc02hbnQc) |
| IPS V2 深度迁移后如何提交 job | [飞书 Wiki](https://xiaopeng.feishu.cn/wiki/Tpnow2u5Wi1VqTkaoqHcpSzznhU) |
| 纯视觉生产/扶摇任务执行流程 | [飞书 Wiki](https://xiaopeng.feishu.cn/wiki/S3fBw5Z83inSQGksaV4cVbennvc) |
