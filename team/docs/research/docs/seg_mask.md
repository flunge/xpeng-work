# Seg Mask 模块技术分析文档

## 1. 概述

Seg Mask 模块是 SimWorld 数据预处理流水线中的语义分割与掩膜生成子系统，位于 `xpeng_data_process/` 目录下。该模块负责两个核心任务：

1. **语义分割（SegGenerator）**：使用 Mask2Former 和 LOMM 模型对驾驶场景图像进行像素级语义分割和视频实例分割，生成每帧的语义标签图和实例 ID 图。
2. **车辆掩膜生成（MaskGenerator）**：基于车型模板掩膜，为每个相机视角生成自车遮挡掩膜（ego-car mask），用于训练时排除自车区域。

两者的输出最终在 `ImgProcessor` 中被组合：语义分割结果用于识别车辆/行人/天空/地面等语义区域，车辆掩膜用于遮挡自车部分，二者与 3D 标注框投影掩膜相乘，生成最终的 `masks_obj` 训练掩膜。

### 在流水线中的位置

```
main.py
  └─ pipelines.pipeline_m1_lidar_gpu() / pipeline_vision_gpu()
       └─ ImgProcessor(cfg, load_seg=True)
            ├─ SegGenerator(cfg)     ← 语义分割模型
            ├─ MaskGenerator(cfg)    ← 车辆掩膜模板
            ├─ process_undistort_parallel()  ← 去畸变 + 生成 ego mask
            ├─ process_origin_imgs()         ← Mask2Former 语义分割
            ├─ process_segs_vision()         ← Vision 模式语义分割
            ├─ process_instance_seg_vision_lomm()  ← LOMM 视频实例分割
            └─ process_on_the_end()          ← 组合最终掩膜
```

## 2. 模型结构

### 2.1 SegGenerator — 语义分割模型管理器

`SegGenerator` 类（`seg_generator.py`）管理三个独立的分割模型，均基于 detectron2 框架构建，采用懒加载（lazy loading）策略：

| 模型 | 属性名 | 骨干网络 | 用途 | 预训练数据 |
|------|--------|---------|------|-----------|
| Mask2Former (图像) | `self.model` | Swin-L IN21k | 单帧语义分割 | Mapillary Vistas |
| Mask2Former (视频) | `self.video_model` | Swin-L IN21k | 视频实例分割 | YouTube-VIS |
| LOMM | `self.lomm_model` | ViT-Adapter-L | 视频实例分割（带跟踪） | YouTube-VIS 2019 |

#### 2.1.1 Mask2Former 图像模型

- 配置：`maskformer2_swin_large_IN21k_384_bs16_300k.yaml`
- 权重：`mask2former_mapillary_vistas_swin_L.pkl`
- 加载流程：`get_cfg() → add_deeplab_config → add_maskformer2_config → merge_from_file → build_model → DetectionCheckpointer.load`
- 输出：65 类 Mapillary Vistas 语义标签（包括 Car=55, Truck=61, Person=19, Sky=27 等）

#### 2.1.2 Mask2Former 视频模型

- 配置：`video_maskformer2_swin_large_IN21k_384_bs16_8ep.yaml`
- 额外添加 `add_maskformer2_video_config`
- 输入为多帧图像列表，输出包含 `pred_scores`、`pred_labels`、`pred_masks` 的实例分割结果
- 使用 `TrackVisualizer` 进行可视化

#### 2.1.3 LOMM 模型

- 配置：`LOMM_Online_ViTL.yaml`
- 加载链：`get_cfg() → add_deeplab_config → add_maskformer2_config → add_maskformer2_video_config → add_minvis_config → add_dvis_config → add_lomm_config`
- 关键特性：
  - 支持 `keep` 参数实现跨批次状态保持（长视频处理）
  - 输出 `pred_ids` 用于跨帧实例跟踪
  - 置信度阈值过滤：`score < 0.3` 的实例被丢弃
  - 对特定类别（person=0, sedan=5, motorbike=20, truck=28）生成 `instance_id_label`
  - 使用 `LOMMTrackVisualizer` 维护 `id_memories` 实现连续 ID 分配

### 2.2 MaskGenerator — 车辆掩膜生成器

`MaskGenerator` 类（`mask_generator.py`）基于预制的车型掩膜模板生成自车遮挡区域掩膜。

#### 车型掩膜映射表

```python
mask_folder_mapping = {
    50:  "assets/Vehicle_Mask/F30_Masks",
    43:  "assets/Vehicle_Mask/E38A_Masks",
    21:  "assets/Vehicle_Mask/E28A_Masks",
    40:  "assets/Vehicle_Mask/E38_Masks",
    60:  "assets/Vehicle_Mask/H93_Masks",
    70:  "assets/Vehicle_Mask/F57_Masks",
    201: "assets/Vehicle_Mask/XP5_201_Masks",
    205: "assets/Vehicle_Mask/XP5_269_Masks",
    203: "assets/Vehicle_Mask/E38B_Masks",
    206: "assets/Vehicle_Mask/F30B_Masks",
    231: "assets/Vehicle_Mask/H93AS_Masks",
    269: "assets/Vehicle_Mask/XP5_269_Masks",
    247: "assets/Vehicle_Mask/XP5_247_Masks",
    239: "assets/Vehicle_Mask/XP5_239_Masks",
    229: "assets/Vehicle_Mask/XP5_229_Masks",
}
```

#### 掩膜生成策略

- **前视/后视相机（cam0, cam7）**：基于 ROI 区域，将全黑像素（去畸变后的无效区域）标记为 0，其余为 255
- **侧视相机（cam2-cam6）**：从预制模板加载，支持两种模式：
  - `use_origin_mask=False`：直接加载已去畸变的掩膜模板，resize 到目标尺寸
  - `use_origin_mask=True`：加载原始畸变掩膜，通过 `undistorter` 进行去畸变处理
- 每个相机的掩膜被缓存在 `self.mask_dict` 中，避免重复加载

## 3. 推理流程

### 3.1 单帧语义分割流程

```
原始图像 (BGR)
  → torch.from_numpy().permute(2,0,1).to("cuda")
  → Mask2Former model forward
  → outputs["sem_seg"].argmax(dim=0)  # [H, W] 语义标签
  → undistort (cv2.INTER_NEAREST)     # 去畸变保持标签值
  → 保存到 segs/{cam_name}/{img_name}
```

### 3.2 LOMM 视频实例分割流程

```
批量图像 (30帧/批)
  → BGR→RGB 转换 (如需)
  → ResizeShortestEdge 预处理
  → LOMM model forward (keep=True 保持跟踪状态)
  → 置信度过滤 (score >= 0.3)
  → 逐帧生成:
      ├─ sem_label: 语义标签图 [H, W]
      ├─ instance_id_label: 实例 ID 图 [H, W] (仅 person/sedan/motorbike/truck)
      └─ frame_instance_ids: 当前帧实例 ID 列表
  → 保存 instance_id_label 为 .npy
  → 汇总 lomm_meta.json (timestamp → instance_ids 映射)
```

#### 跨批次跟踪机制

LOMM 处理长视频时采用分批处理 + 状态保持策略：
1. 首批（batch_idx=0）：`keep=False`，清空 tracker 内存
2. 后续批次：`keep=True`，恢复上一批次的 tracker 状态
3. 多相机并行处理时使用 `threading.Lock` 保护共享模型
4. 每个相机维护独立的 `camera_tracker_state` 和 `cam_id_memories`

### 3.3 最终掩膜组合流程

```
ego_mask (MaskGenerator)          # 自车遮挡区域 [0/255]
  × mask_veh (语义分割→车辆类)    # 排除其他车辆区域
  × mask_hum (语义分割→行人类)    # 排除行人区域
  × mask_obj (3D框投影→移动物体)  # 排除移动物体区域
  = combined_mask                  # 最终训练掩膜 → masks_obj/
```

其中：
- `get_semantics_from_path()` 从语义分割结果读取标签
- `get_mask_from_semantics(semantics, SemanticType.VEHICLE)` 提取特定语义类别的二值掩膜
- `get_mask_obj_bound()` 基于 3D 标注框和相机标定投影生成移动物体掩膜

## 4. 数据处理

### 4.1 输入数据

| 数据 | 路径 | 说明 |
|------|------|------|
| 原始图像 | `{clip_path}/images_origin/{cam_name}/` | 未去畸变的原始相机图像 |
| 标定信息 | `{clip_path}/calib.json` | 相机内外参 |
| 3D 标注 | `{clip_path}/annotation_for_train.json` | 自动标注的 3D 框 |
| 变换矩阵 | `{clip_path}/transform.json` | 帧级变换信息 |
| 车型信息 | `{clip_path}/metadata.json` | 包含 vehicle_model 字段 |

### 4.2 输出数据

| 数据 | 路径 | 格式 | 说明 |
|------|------|------|------|
| 去畸变图像 | `{clip_path}/images/{cam_name}/` | PNG | 去畸变后的训练图像 |
| 语义分割 | `{clip_path}/segs/{cam_name}/` | PNG (uint8) | Mapillary 65 类标签 |
| Vision 语义分割 | `{clip_path}/segs_vision/` | PNG | MVS 模式专用 |
| 实例分割 | `{clip_path}/instance_segs_vision/` | PNG | 视频实例分割结果 |
| 实例 ID 图 | `{clip_path}/instance_segs_id/` | NPY | LOMM 实例跟踪 ID |
| 自车掩膜 | `{clip_path}/masks/{cam_name}/` | PNG (灰度) | 自车遮挡掩膜 |
| 组合掩膜 | `{clip_path}/masks_obj/{cam_name}/` | PNG (灰度) | 最终训练掩膜 |
| 调试可视化 | `{clip_path}/masks_misc/{cam_name}/` | PNG | 地面/天空叠加可视化 |
| LOMM 元数据 | `{clip_path}/lomm_meta.json` | JSON | 实例跟踪元数据 |

### 4.3 相机配置

系统支持 7 个相机视角：`cam0`（前视）、`cam2-cam6`（环视）、`cam7`（后视）。LOMM 处理的默认相机列表为全部 7 个：`["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"]`。

### 4.4 并行处理策略

- **图像去畸变 + 掩膜生成**：`multiprocessing.Pool`（最多 10 进程）
- **最终掩膜组合**：`ThreadPoolExecutor`（最多 5 线程）
- **LOMM 多相机处理**：`ThreadPoolExecutor`（最多 6 线程），共享模型 + Lock
- **图像 I/O**：`ThreadPoolExecutor`（最多 10 线程）用于批量读写

## 5. 目录结构速查

```
xpeng_data_process/
├── seg_generator.py          # SegGenerator 类 - 管理 Mask2Former/LOMM 模型
├── mask_generator.py         # MaskGenerator 类 - 车型掩膜模板管理
├── img_processor.py          # ImgProcessor 类 - 整合去畸变/分割/掩膜流程
├── pipelines.py              # 流水线编排 - pipeline_m1_lidar_gpu / pipeline_vision_gpu
├── main.py                   # 主入口
├── undistorter.py            # 图像去畸变工具
├── assets/
│   └── Vehicle_Mask/         # 各车型掩膜模板
│       ├── F30_Masks/
│       ├── E38A_Masks/
│       ├── E28A_Masks/
│       └── ...
├── data_mining/
│   ├── Mask2Former/          # Mask2Former 模型代码
│   │   ├── mask2former/
│   │   ├── mask2former_video/
│   │   └── *.yaml            # 模型配置文件
│   └── LOMM/                 # LOMM 模型代码
│       ├── lomm/
│       ├── configs/
│       └── demo_video/
├── utils/
│   ├── file_utils.py         # get_semantics_from_path, get_mask_from_semantics
│   ├── misc.py               # get_global_object_moving_status, get_mask_obj_bound
│   └── calib_utils.py        # get_calibration
└── settings/
    ├── config.py             # 配置管理
    └── globals.py            # SemanticType 枚举定义
```

## 6. 参考资料

- **Mask2Former**: Cheng et al., "Masked-attention Mask Transformer for Universal Image Segmentation", CVPR 2022
- **LOMM**: 基于 DVIS/MinVIS 的在线视频实例分割框架，支持长视频跟踪
- **Detectron2**: Facebook AI Research 的目标检测/分割框架
- **Mapillary Vistas**: 65 类街景语义分割数据集，提供细粒度道路场景标注
- **YouTube-VIS 2019**: 40 类视频实例分割基准数据集
