# SAM3D 模块技术分析文档

## 1. 概述

SAM3D 是一个基于 **DiT（Diffusion Transformer）+ Flow Matching** 的三维物体重建模块，能够从单张或多张 2D 图像生成高质量的 3D 物体表示（Gaussian Splatting / Mesh）。

### 核心能力

| 能力 | 说明 |
|------|------|
| 单视角重建 | 从单张 RGBA 图像生成 3D 物体 |
| 多视角重建 | 融合多张不同视角图像，通过 MultiDiffusion 机制提升重建质量 |
| PointMap 条件生成 | 利用深度估计模型生成的点云图作为额外几何条件，提升空间精度 |
| 多格式输出 | 支持 Gaussian Splatting（PLY）和 Mesh（GLB）两种输出格式 |

### 技术路线

系统采用两阶段生成架构：

```
输入图像 (RGBA)
    │
    ├─→ DINO Embedder ──→ 图像条件 tokens
    ├─→ PointMap Embedder ──→ 几何条件 tokens（可选）
    │
    ▼
┌─────────────────────────────────────────┐
│  Stage 1: Sparse Structure Generation   │
│  (SparseStructureFlowModel + FlowMatch) │
│  输入: 噪声 (bs, 4096, 8)              │
│  输出: 稀疏体素坐标 coords              │
└─────────────────────────────────────────┘
    │ coords
    ▼
┌─────────────────────────────────────────┐
│  Stage 2: Structured Latent Generation  │
│  (SLatFlowModel + FlowMatching)         │
│  输入: 噪声 (bs, N_coords, 8)          │
│  输出: SparseTensor (coords + feats)    │
└─────────────────────────────────────────┘
    │ SparseTensor
    ▼
┌─────────────────────────────────────────┐
│  Decode: VAE Decoder                    │
│  (SLatGaussianDecoder)                  │
│  输出: Gaussian Splatting / Mesh        │
└─────────────────────────────────────────┘
```

---

### 当前项目中的动态障碍物重建链路

上面的内容描述的是通用 SAM3D 模型能力；在本仓库里，SAM3D 的实际职责更具体一些：它是 Vision 预处理流水线中的动态障碍物初始化模块，用来把时序图像中的动态目标重建成对象级 Gaussian PLY，供后续 Feedforward / Reconic 训练初始化使用。

当前链路的实际入口位于 `xpeng_data_process/main.py`，Vision 模式下调用顺序如下：

```text
main.py
  -> pipeline_vision_cpu()
      -> JsonProcessor.process_input_json()
          -> 可选：use_h265_png 时先做 h265/png 对齐、重命名和 timestamp2slice 重写
          -> 生成 transform.json / annotation_for_train.json / localpose.json
  -> pipeline_vision_gpu()
      -> ImgProcessor.process_undistort_parallel()
          -> 生成 images/、masks/、images_vision/
      -> ImgProcessor.process_segs_vision()
          -> 生成 segs/、segs_vision/、masks_obj/
      -> ImgProcessor.process_instance_seg_vision_lomm()
          -> 生成 instance_segs_id/、lomm_meta.json
      -> OptProcessor.process_optimization()  [可选，若未走 vision_data_fetcher]
          -> 更新 transform.json / annotation_for_train.json
      -> SAM3DProcessor.process()
          -> 生成 input_ply/{gid}.ply
```

如果下游训练启用了 feedforward 初始化，`omnire_joint_trainning/src/reconic/datasets/xpeng/xpeng_driving_dataset.py` 会优先读取 `input_ply/{gid}.ply` 作为动态目标的初始高斯；如果对应 PLY 不存在，才退回到随机点初始化。

### 当前链路里的前处理有哪些

从 `SAM3DProcessor` 的真实依赖看，动态障碍物重建前至少包含以下前处理阶段。

#### 1. JSON 结构化与时序有效性检查

- 若 `cfg.use_h265_png = True`，`JsonProcessor.process_input_json()` 会先调用 `match_pose_and_cam.py` 中的对齐逻辑，把 h265 抽帧图像与 localpose 时间戳重新匹配，并同步更新 `calib.json` / `timestamp2slice.json`。
- `JsonProcessor.check_timestamps()` 会校验各相机相邻帧时间间隔不超过 0.5 秒，避免时序断裂数据进入后续实例跟踪与多视图重建。
- `JsonProcessor.get_vision_scene_parameters()` 会生成 `transform.json`、`annotation_for_train.json`、`localpose.json`、`anchorpose.json` 等场景描述文件。
- 其中 `annotation_for_train.json` 提供 3D 框、`transform.json` 提供每帧相机位姿，两者都是后续 2D/3D 关联的直接输入。

这一步是当前 develop 新增的重要预处理前置条件，因为后续 `images_vision/`、`instance_segs_id/`、`lomm_meta.json`、`SAM3DProcessor` 全都依赖重写后的 `timestamp2slice.json` 保持统一 slice 编号。

#### 2. 图像去畸变与 Vision 视图整理

- `ImgProcessor.process_undistort_parallel()` 会把 `images_origin/` 中的原始图像去畸变后写入 `images/`。
- 同时基于 `timestamp2slice.json` 把 Vision 路径专用图像写入 `images_vision/`，命名为 `slice{slice_id}_{cam}.png`。
- 这一步还会生成 `masks/`，即自车遮挡掩码；虽然它不是 SAM3D 的直接输入，但属于同一视觉预处理阶段的基础产物。

#### 3. 语义分割与组合掩码生成

- `ImgProcessor.process_segs_vision()` 会对原图做语义分割，并分别输出到 `segs/` 和 `segs_vision/`。
- `process_on_the_end()` 随后调用 `save_combined_mask_img_parallel()`，把自车 mask、车辆/行人语义 mask、以及基于 3D 标注框投影的动态物体 mask 合成为 `masks_obj/`。
- 这部分结果主要服务于后续训练与可视化，但它也说明 SAM3D 前面的视觉预处理已经完成了“动态区域/静态区域”的第一次筛分。

#### 4. 视频实例分割与跨帧实例 ID 跟踪

- `ImgProcessor.process_instance_seg_vision_lomm()` 会对 `images_vision/` 做 LOMM 视频实例分割。
- 每一帧输出一个 `instance_segs_id/slice{slice_id}_{cam}.npy`，像素值是跨帧跟踪后的实例 ID。
- 同时输出 `lomm_meta.json`，记录 `cam -> timestamp -> [instance_ids]` 的映射。
- 这是 SAM3D 最关键的前处理之一，因为后续 2D/3D 对应关系并不是直接基于语义类别，而是基于这些稳定的实例 ID 进行匹配。

#### 5. 位姿/标注优化结果回写

- `pipeline_vision_gpu()` 中，若未走 `vision_data_fetcher`，会在 SAM3D 前执行 `OptProcessor.process_optimization()`。
- 该步骤会回写 `transform.json` 和 `annotation_for_train.json`。
- 因此，SAM3D 使用的是优化后的相机位姿和对象框，而不是 JSON 初始阶段的原始版本。

#### 6. 静态障碍物剔除

- `SAM3DProcessor.process()` 的第一步是调用 `gen_static_obj_segs()`。
- 这个函数会读取 `2d_3d_corr.json`、`annotation_for_train.json`、`timestamp2slice.json` 和 `instance_segs_id/`，生成 `static_obs_ids.json`。
- 判定逻辑不是简单看单帧 `is_moving`，而是结合 LOMM ID 与时序运动状态，过滤掉“长时间保持静止、但偶尔抖动”的障碍物。
- 后续 `extract_unique_ids()` 会据此跳过静态 gid，确保当前 SAM3D 只重建真正需要的动态障碍物。

### SAM3D 如何消费这些前处理产物

在真正进入多视图生成前，`SAM3DProcessor` 会把前处理产物组织成 2D/3D 对应关系，核心依赖如下：

| 前处理产物 | 作用 | 在 SAM3D 中的用途 |
|------|------|-------------------|
| `images/cam0/*.png` | 提供原始时间戳序列 | 构建 `timestamp -> slice_id` 映射 |
| `images_vision/slice*_cam*.png` | 多视角输入图像 | 作为 `run_multi_view()` 的 `view_images` |
| `instance_segs_id/*.npy` | 像素级实例 ID 图 | 提取布尔 mask，作为 `view_masks` |
| `lomm_meta.json` | 每帧候选实例 ID | 限定某个 `(gid, cam, timestamp)` 下需要比对的实例集合 |
| `annotation_for_train.json` | 3D 目标框 | 投影到图像平面，和实例 mask 计算 IoU |
| `transform.json` + `calib.json` | 相机内外参 | 计算 world 到 camera 的投影关系 |
| `timestamp2slice.json` | 时间戳到帧索引映射 | 拼接 `slice{n}_{cam}` 文件名 |
| `static_obs_ids.json` | 静态障碍物 gid 集 | 在 SAM3D 阶段直接跳过 |

`SAM3DProcessor` 会先用 3D 框投影与实例分割结果做 2D/3D 关联，再经过以下筛选：

- `min_valid_iou = 0.3`：低于该阈值的实例不参与粗匹配。
- `min_iou_for_sam3d = 0.5`：只有更高质量的匹配才会进入最终重建集合。
- `frame_interval = 3`：不是逐帧匹配，而是按时间间隔抽样，降低计算量。
- `consistent_instance_id = True`：要求同一 gid 在同一相机上的主实例 ID 足够稳定，否则不进入精确 mask 重建分支。
- `min_observation_for_sam3d = 2`、`max_observation_for_sam3d = 3`：最终每个目标至少需要 2 个观测，且最多保留 3 个视图给 SAM3D。

### 当前动态障碍物重建的两阶段执行策略

完成前处理和 2D/3D 关联后，当前实现并不是只走单一路径，而是分两阶段执行：

1. 精确实例 mask 重建
    - 输入来自 `corr_id_dict_key_frames`。
    - 对每个 gid，从 `instance_segs_id/*.npy` 中取出 `mask == ins_id` 的像素级布尔掩码。
    - 这是主路径，优先用于有稳定 LOMM 实例跟踪结果的动态目标。

2. 矩形框补救重建
    - 输入来自 `rect_id_dict`。
    - 若实例 ID 一致性不足，但 3D 投影矩形质量还可以，就直接用 `rect_info` 生成矩形 mask。
    - 对超大目标，还会走 `add_postprocess_rect()` 做额外补救。

最终，`_process_sam3d()` 调用 `run_multi_view(..., mode="multidiffusion")`，并把结果保存为 `input_ply/{gid}.ply`。

### 动态障碍物抖动问题：原因猜测与解决方案

当前链路里，动态障碍物最终出现“整体跳动、朝向摆动、局部高斯发颤”等现象时，不应只把问题归因到 SAM3D 本身。更常见的是上游 3D 框时序抖动、SAM3D 初始化不稳定、以及训练侧对刚体轨迹约束不足三者叠加。

#### 1. 高概率根因：3D 框时序抖动直接传进训练位姿

- `annotation_for_train.json` 中每帧对象的 `translation` 和 `rotation` 会被直接装配成 `instances_pose`，再初始化到训练阶段的 `instances_trans` / `instances_quats`。
- 因此，只要 3D 框中心或朝向逐帧抖动，训练初值就已经带抖，不需要等 SAM3D 出错也会表现为动态资产跳动。
- 过去的 `PoseProcessor.process_sliding_window_smooth()` 只对动态目标平移做滑窗平滑，没有同步平滑旋转，这会导致“车身中心相对稳，但车头方向和局部几何仍在摆”的现象。

本次代码已做的最小修复：

- 在 `xpeng_data_process/pose_processor.py` 中，为动态目标的滑窗平滑补上了四元数平均与符号对齐后的旋转平滑。
- 同时把静态段平均姿态的四元数平均改成了带符号对齐的稳健实现，避免四元数正负号翻转造成均值失真。

建议继续做的增强方案：

1. 用 Kalman / 常速度模型替换简单滑窗均值，对 `translation` 做轨迹级平滑。
2. 对 `rotation` 使用 slerp 或李代数空间平滑，而不是仅用窗口均值。
3. 把平滑触发条件从单帧 `is_moving` 扩展为“连续可见且轨迹有效”的目标段，降低低速目标频繁切窗的问题。

#### 2. 高概率根因：SAM3D 关键帧选取偏向了小目标视图

- `SAM3DProcessor.select_key_frames()` 在同相机观测过多时，会按 `seg_ratio` 选关键帧。
- 原实现实际是按 `seg_ratio` 升序排序，优先保留面积更小、质量更差的观测，这与代码注释“取前 max_observation_each_cam 个高质量观测”的意图相反。
- 这会让 SAM3D 更容易使用远距离、小投影、边缘视角的目标图像，造成对象初始化几何不稳。

本次代码已做的最小修复：

- 在 `xpeng_data_process/sam3d_processor.py` 中把该处改为按 `seg_ratio` 降序排序，优先保留投影面积更大的观测。

建议继续做的增强方案：

1. 用联合排序分数替换单一 `seg_ratio`：例如 `score = seg_ratio * IoU`。
2. 增加跨时间覆盖约束，避免 3 个视图都集中在相邻时刻。
3. 对疑似抖动目标增加“多于 3 个候选观测 -> RANSAC 式剔除异常帧”的机制。

#### 3. 中概率根因：训练阶段对刚体目标的时序约束偏弱

- 动态刚体的 `instances_trans` / `instances_quats` 会在训练时继续优化。
- 代码层面虽然支持 `RigidNodes` 的 `temporal_smooth_reg`，但是否生效取决于训练配置，不是预处理默认强制保证。
- 如果配置里没开或权重太低，训练会把 noisy pose 直接学进去，甚至进一步放大高频扰动。

建议继续做的增强方案：

1. 给 `RigidNodes` 显式打开 `temporal_smooth_reg.trans`，建议先从 `w = 0.005 ~ 0.02` 开始扫描。
2. 若朝向抖动更明显，再补一个旋转二阶差分正则。
3. 若是近距离车辆抖动明显，可先降低 `ins_translation` / `ins_rotation` 学习率，再观察是否收敛更稳。

#### 4. 中概率根因：低速目标的 moving 状态不稳定

- 当前 `is_moving` 的生成依赖速度阈值和相邻帧位移阈值，低速跟车、缓起步、缓停车目标容易在 moving / static 之间来回跳。
- 一旦单帧 `is_moving` 波动，平滑窗口会被频繁重置，静态剔除逻辑也可能把本该保留的目标误判为静态资产。

建议继续做的增强方案：

1. 把单帧 moving 判定改成短时间窗口投票，而不是直接使用单帧阈值。
2. 对低速目标引入滞回阈值：进入 moving 用高阈值，退出 moving 用低阈值。
3. 在 `static_obs_ids.json` 生成阶段增加“总位移”和“持续可见长度”联合判断，减少误删慢车。

#### 实际排查顺序建议

1. 先只可视化 3D 框中心和朝向轨迹，不渲染高斯，确认抖动是否已经存在于标注位姿。
2. 再关闭 SAM3D 初始化做对照实验：若整体抖动仍在，说明主因更偏向 3D 框 / 训练位姿，而不是 SAM3D 几何。
3. 打开或增强 `RigidNodes` 时序平滑正则，观察 jitter 是否明显下降。
4. 若仍有明显抖动，再检查 LOMM 实例 ID 稳定性和 SAM3D 关键帧候选是否混入异常小目标视图。

#### 更强化的手段：双向平滑与 2D 约束

如果单向滑窗只能压掉一部分高频噪声，还可以继续往两条线上加强。

1. 预处理侧做离线双向平滑
    - 思路不是只看“过去 -> 现在”，而是同时利用“过去 -> 现在”和“未来 -> 现在”两侧信息，再把两次结果融合。
    - 这类方法可以是双向 EMA、双向 Kalman、或更完整的 RTS smoother，本质都是让当前帧位姿同时受前后文约束。
    - 对动态车辆尤其有效，因为很多抖动是单帧框漂移，不是真实运动突变。

本次代码新增的最小实现：

- `xpeng_data_process/pose_processor.py` 里保留了原有局部滑窗，但在连续动态段上又追加了一次双向平滑。
- 平移使用双向 EMA，旋转使用带四元数符号对齐的双向平滑再融合，避免只看历史帧时把短时尖峰直接传下去。
- 进一步按目标类型切换动力学模型：`car/truck` 默认走车辆模型，`pedestrian` 走 CV，`cyclist/motorcycle` 走带加速度项的模型。
- 对低速车辆，不再只用单一车辆模型，而是用简化 IMM 在 `static / CV / CTRV` 三个候选之间做融合，减少排队、缓起步、跟车阶段的抖动和状态来回跳变。

2. 训练侧加入 2D box reprojection regularization
    - 动态刚体的最终问题经常表现为“3D 位置有点偏、投到图上抖得更明显”。
    - 因此可以把 3D 刚体姿态重新投影回当前相机，要求优化后的 2D 框不要偏离初始化来源太多。
    - 这类约束比直接压 3D 位移更贴近视觉观测，也更容易约束横摆和局部漂移。

本次代码新增的最小实现：

- 在 `RigidNodes` 中缓存初始化时的 `instances_trans / instances_quats`，把它们当作源 pose。
- 训练时使用当前 `camera_info` 将“当前优化 pose 的 3D 框”和“初始化 pose 的 3D 框”分别投影到图像平面。
- 对有效可见框施加 `bbox_reproj_reg`，约束优化结果不要在 2D 上偏离过大。

这不是最终形态，后面还可以继续增强成：

1. 把 2D 框升级成 `center + wh` 分解损失，减小长边目标对角点误差的放大效应。
2. 若数据侧能稳定提供对象级 mask，再把 box loss 升级为 silhouette / mask loss。
3. 若要进一步抑制“先抖后拉回”的轨迹，可把双向 EMA 换成固定运动模型的 RTS smoother。

## 2. 模型结构

### 2.1 整体架构：两阶段 Pipeline

SAM3D 的生成过程分为两个阶段，每个阶段都使用 **Flow Matching** 作为生成框架，以 **DiT** 作为去噪骨干网络。

#### Stage 1 — Sparse Structure DiT（稀疏结构生成）

- **模型类**: `SparseStructureFlowModel` / `SparseStructureFlowTdfyWrapper`
- **文件**: `model/backbone/tdfy_dit/models/sparse_structure_flow.py`
- **目标**: 从图像条件生成 3D 稀疏体素结构（哪些体素位置被占据）

**网络结构**:

```
输入 x: (bs, 4096, 8)  ← 展平的 16×16×16 体素网格，每个体素 8 维特征
    │
    ▼ reshape → (bs, 8, 16, 16, 16)
    ▼ patchify (patch_size=2) → (bs, 8*2³, 8, 8, 8) → flatten → (bs, 512, 64)
    ▼ input_layer: Linear(64, model_channels)
    ▼ + pos_emb (AbsolutePositionEmbedder, 512 个 3D 位置)
    │
    ▼ TimestepEmbedder(t) → t_emb
    │
    ├─→ ModulatedTransformerCrossBlock × num_blocks
    │     每个 block:
    │     - Self-Attention (full attention)
    │     - Cross-Attention (与 condition tokens 交互)
    │     - AdaLN 调制 (由 t_emb 控制)
    │     - MLP (mlp_ratio=4)
    │
    ▼ LayerNorm → out_layer: Linear(model_channels, 8*2³)
    ▼ unpatchify → (bs, 8, 16, 16, 16)
```

**关键参数**:
- `resolution`: 16（体素网格分辨率）
- `in_channels`: 8（每个体素的潜在特征维度）
- `patch_size`: 2（将 16³ 体素 patchify 为 8³ = 512 个 token）
- `pe_mode`: "ape"（绝对位置编码）
- `include_pose`: 支持可选的 pose token 拼接

**SS Decoder（稀疏结构解码器）**:
Stage 1 生成的 latent 经过 `ss_decoder` 解码为占据概率：
```python
ss = ss_decoder(shape_latent.permute(0,2,1).view(bs, 8, 16, 16, 16))
coords = torch.argwhere(ss > 0)[:, [0, 2, 3, 4]].int()  # 提取占据体素坐标
```

#### Stage 2 — Structured Latent DiT（结构化潜在生成）

- **模型类**: `SLatFlowModel` / `SLatFlowModelTdfyWrapper`
- **文件**: `model/backbone/tdfy_dit/models/structured_latent_flow.py`
- **目标**: 在 Stage 1 确定的稀疏坐标上生成每个体素的详细特征

**网络结构（U-Net 风格的 Sparse Transformer）**:

```
输入: SparseTensor(coords=Stage1坐标, feats=噪声(N, 8))
    │
    ▼ SparseLinear(8, io_block_channels[0])
    │
    ▼ ═══ Input Blocks (下采样路径) ═══
    │  SparseResBlock3d × num_io_res_blocks (每层)
    │  最后一个 block 带 downsample=True (SparseDownsample)
    │  逐层通道: io_block_channels[0] → [1] → ... → model_channels
    │  每层保存 skip connection
    │
    ▼ + AbsolutePositionEmbedder(coords)
    │
    ▼ ═══ Transformer Blocks (中间层) ═══
    │  ModulatedSparseTransformerCrossBlock × num_blocks
    │  - Sparse Self-Attention
    │  - Cross-Attention (与 condition tokens)
    │  - AdaLN 调制 (t_emb)
    │
    ▼ ═══ Output Blocks (上采样路径) ═══
    │  SparseResBlock3d × num_io_res_blocks (每层)
    │  第一个 block 带 upsample=True (SparseUpsample)
    │  使用 skip connection 拼接 (cat)
    │
    ▼ LayerNorm → SparseLinear(io_block_channels[0], out_channels)
    ▼ 输出: SparseTensor feats (N, 8)
```

**关键设计**:
- 使用 **SparseConv3d** 和 **SparseTensor** 进行稀疏 3D 卷积，仅在占据体素上计算
- **U-Net skip connections**: `use_skip_connection=True` 时，上采样路径拼接下采样路径的特征
- **SparseResBlock3d**: 包含两个 SparseConv3d + AdaLN 调制 + 残差连接
- 支持 `is_shortcut_model` 模式（蒸馏加速）

**输出反归一化**:
```python
slat = sp.SparseTensor(coords=coords, feats=slat[0])
slat = slat * slat_std + slat_mean  # 反归一化到原始分布
```

### 2.2 VAE 编码器 / 解码器

#### SLatEncoder（编码器）

- **文件**: `structured_latent_vae/encoder.py`
- **作用**: 将 3D 表示编码为结构化潜在空间（训练时使用）

```
输入: SparseTensor (coords, feats=in_channels)
    ▼ SparseTransformerBase (多层 Sparse Transformer)
    ▼ LayerNorm
    ▼ SparseLinear → 2 * latent_channels
    ▼ split → mean, logvar
    ▼ 重参数化: z = mean + std * ε
输出: SparseTensor (coords, feats=latent_channels)
```

#### SLatGaussianDecoder（Gaussian Splatting 解码器）

- **文件**: `structured_latent_vae/decoder_gs.py`
- **作用**: 将结构化潜在表示解码为 Gaussian Splatting 参数

```
输入: SparseTensor (coords, feats=latent_channels)
    ▼ SparseTransformerBase (多层 Sparse Transformer)
    ▼ LayerNorm
    ▼ SparseLinear → out_channels (所有 GS 参数总维度)
    ▼ to_representation() → List[Gaussian]
```

**Gaussian 参数布局** (`_calc_layout`):

| 参数 | 形状 (per voxel) | 说明 |
|------|------------------|------|
| `_xyz` | (num_gaussians, 3) | 位置偏移（相对于体素中心） |
| `_features_dc` | (num_gaussians, 1, 3) | 球谐系数（0 阶，即 RGB 颜色） |
| `_scaling` | (num_gaussians, 3) | 缩放参数 |
| `_rotation` | (num_gaussians, 4) | 旋转四元数 |
| `_opacity` | (num_gaussians, 1) | 不透明度 |

- 每个体素包含 `num_gaussians` 个高斯核
- 位置使用 **Hammersley 序列** 初始化扰动（`_build_perturbation`），确保均匀分布
- 位置偏移经过 `tanh` 激活限制在体素范围内

### 2.3 条件嵌入器

#### DINO Embedder（图像条件）

- **文件**: `model/backbone/dit/embedder/dino.py`
- **模型**: DINOv2 ViT-L/14（带 register tokens）

```
输入: RGB 图像 (bs, 3, H, W)
    ▼ 双线性插值 resize → (bs, 3, 224, 224)  [默认 input_size]
    ▼ ImageNet 归一化: (x - mean) / std
    ▼ DINOv2 backbone.forward_features()
    ▼ 拼接 [cls_token, patch_tokens] → (bs, 1+N_patches, embed_dim)
输出: condition tokens (bs, 257, 1024)  [ViT-L embed_dim=1024]
```

**关键配置**:
- `freeze_backbone=True`: 推理时冻结 DINO 权重
- `normalize_images=True`: 应用 ImageNet 均值/标准差归一化
- `prenorm_features=False`: 使用 post-norm 特征（`x_norm_clstoken` + `x_norm_patchtokens`）
- 权重从本地路径加载: `dinov2_vitl14_reg4_pretrain.pth`

#### PointMap Embedder（几何条件）

- **文件**: `model/backbone/dit/embedder/pointmap.py`
- **模型类**: `PointPatchEmbed`

```
输入: 点云图 (bs, 3, H, W) — 每个像素的 (x,y,z) 世界坐标
    ▼ resize → (bs, input_size, input_size, 3)
    ▼ PointRemapper: 坐标范围归一化 (exp 映射)
    ▼ point_proj: Linear(3, embed_dim) — 逐像素投影
    ▼ 无效点 → invalid_xyz_token (可学习)
    ▼ 分窗: (patch_size × patch_size) 个像素为一窗
    ▼ 拼接 cls_token + 窗内像素 tokens
    ▼ + pos_embed_window (窗内位置编码)
    ▼ Block (Self-Attention, 1层) — 窗内注意力
    ▼ 提取 cls_token → 每窗一个 token
    ▼ + pos_embed (窗间位置编码)
    ▼ [可选] pointmap dropout (训练时随机丢弃整个 pointmap)
输出: (bs, num_windows, embed_dim)
```

**关键设计**:
- `patch_size=8`: 将 256×256 的点云图分为 32×32 = 1024 个窗口
- 窗内使用 **单层 Transformer Block** 聚合局部几何信息
- `dropout_prob`: 训练时随机丢弃 pointmap 条件，增强鲁棒性
- `force_dropout_always`: 推理时强制丢弃（用于无 pointmap 的场景）

### 2.4 Flow Matching 生成器

- **文件**: `model/backbone/generator/flow_matching/model.py`
- **模型类**: `FlowMatching` / `ConditionalFlowMatching`

Flow Matching 是一种基于 ODE 的生成框架，将噪声分布 x₀ 通过学习的速度场 v(x_t, t) 传输到数据分布 x₁。

**核心公式**:
- 前向插值: `x_t = (1 - (1-σ_min)·t) · x₀ + t · x₁`
- 目标速度: `v = x₁ - (1-σ_min) · x₀`
- 损失函数: `L = MSE(v_predicted, v_target)`

**推理过程（ODE 求解）**:
```python
t_seq = linspace(0, 1, steps+1)  # 时间步序列
t_seq = t_seq / (1 + (rescale_t - 1) * (1 - t_seq))  # 时间重缩放
x_0 = randn(latent_shape)  # 初始噪声
for t0, t1 in zip(t_seq[:-1], t_seq[1:]):
    velocity = reverse_fn(x_t, t0 * time_scale, *conditions)
    x_t = x_t + velocity * (t1 - t0)  # Euler 步进
```

**ODE 求解器** (`solver.py`):

| 求解器 | 类 | 精度 | 每步函数评估次数 |
|--------|-----|------|-----------------|
| Euler | `Euler` | 1 阶 | 1 |
| Midpoint | `Midpoint` | 2 阶 | 2 |
| RK4 | `RungeKutta4` | 4 阶 | 4 |
| SDE | `SDE` | 随机 | 1 + 噪声注入 |

**时间重缩放** (`rescale_t`):
```python
t_seq = t_seq / (1 + (rescale_t - 1) * (1 - t_seq))
```
当 `rescale_t > 1` 时，在 t 接近 1（接近数据分布）时步长更密集，提升生成质量。

**训练时间采样**: 使用 **LogNorm 采样器**（`lognorm_sampler`），偏向中间时间步，提升训练效率。

**Classifier-Free Guidance (CFG)**:
通过 `reverse_fn` 中的 `strength` 参数控制，在推理时混合有条件和无条件预测：
```
v_guided = v_uncond + strength * (v_cond - v_uncond)
```

---

## 3. 推理流程

### 3.1 入口脚本 `run_inference.py`

入口脚本支持两种推理模式：

```bash
# 单视角推理
python run_inference.py --input_path ./data --image_names image1

# 多视角推理（使用所有图像）
python run_inference.py --input_path ./data/images_and_masks

# 多视角推理（指定 mask 子目录）
python run_inference.py --input_path ./data --mask_prompt stuffed_toy --image_names img1,img2
```

**参数说明**:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--input_path` | 必填 | 输入图像目录 |
| `--mask_prompt` | None | mask 子目录名；None 时图像和 mask 在同一目录 |
| `--image_names` | None | 逗号分隔的图像名（无扩展名）；None 使用全部 |
| `--seed` | 42 | 随机种子 |
| `--stage1_steps` | 50 | Stage 1 推理步数 |
| `--stage2_steps` | 25 | Stage 2 推理步数 |
| `--decode_formats` | gaussian,mesh | 输出格式 |

**判断逻辑**: 加载的视角数 `num_views == 1` 时走单视角路径，否则走多视角路径。

### 3.2 InferencePipeline（基础推理管线）

**文件**: `pipeline/inference_pipeline.py`

#### 初始化流程

```
__init__()
    ├─ 加载 ss_generator (Stage 1 DiT)
    ├─ 加载 slat_generator (Stage 2 DiT)
    ├─ 加载 ss_decoder (稀疏结构解码器)
    ├─ 加载 ss_encoder (稀疏结构编码器, 可选)
    ├─ 加载 slat_decoder_gs_4 (Gaussian Splatting 解码器)
    ├─ 加载 ss_condition_embedder (Stage 1 条件嵌入器, DINO)
    ├─ 加载 slat_condition_embedder (Stage 2 条件嵌入器, DINO)
    ├─ 覆盖 CFG 配置 (cfg_strength, inference_steps, rescale_t 等)
    └─ [可选] torch.compile 编译加速
```

所有模型通过 Hydra `instantiate` + `load_model_from_checkpoint` 加载，支持 `.safetensors` 和 PyTorch checkpoint 格式。

#### 单视角推理流程 `run()`

```python
def run(image, mask=None, seed=42, ...):
    # 1. 合并 mask 到 alpha 通道
    image = merge_image_and_mask(image, mask)  # → RGBA numpy

    # 2. 预处理（分别为两个 stage 准备输入）
    ss_input_dict = preprocess_image(image, ss_preprocessor)
    slat_input_dict = preprocess_image(image, slat_preprocessor)

    # 3. Stage 1: 生成稀疏结构
    torch.manual_seed(seed)
    ss_return_dict = sample_sparse_structure(ss_input_dict)
    #   → 内部: DINO embed → FlowMatching.generate_iter() → ss_decoder → coords
    #   → 下采样 coords (prune + downsample)

    # 4. 姿态解码
    ss_return_dict.update(pose_decoder(ss_return_dict))

    # 5. Stage 2: 生成结构化潜在
    coords = ss_return_dict["coords"]
    slat = sample_slat(slat_input_dict, coords)
    #   → 内部: DINO embed → FlowMatching.generate_iter(coords) → SparseTensor
    #   → 反归一化: slat * std + mean

    # 6. 解码为 3D 表示
    outputs = decode_slat(slat, ["gaussian", "mesh"])
    #   → slat_decoder_gs_4(slat) → List[Gaussian]

    # 7. 后处理（GLB 导出）
    outputs = postprocess_slat_output(outputs, ...)
    #   → postprocessing_utils.to_glb(gaussian, mesh, ...)
```

#### `preprocess_image()` 详细流程

```python
def preprocess_image(image_numpy, preprocessor):
    # image: (H, W, 4) uint8 RGBA
    rgba = torch.from_numpy(image / 255.0).permute(2,0,1)  # (4, H, W) float32
    rgb = rgba[:3]                                           # (3, H, W)
    mask = get_mask(rgba, None, "ALPHA_CHANNEL")             # (1, H, W)

    # 联合变换（裁剪、缩放等）
    rgb, mask = preprocessor.img_mask_joint_transform(rgb, mask)

    # 独立变换
    rgb = preprocessor.img_transform(rgb)    # 归一化等
    mask = preprocessor.mask_transform(mask)  # 二值化等

    return {
        "image": rgb[None].cuda(),           # (1, 3, H', W')
        "mask": mask[None].cuda(),           # (1, 1, H', W')
        "rgb_image": ...,                    # 未裁剪的完整图像
        "rgb_image_mask": ...,               # 未裁剪的完整 mask
    }
```

#### `sample_sparse_structure()` 核心逻辑

```python
def sample_sparse_structure(ss_input_dict):
    # 1. 条件嵌入
    cond_tokens = ss_condition_embedder(image)  # DINO → (bs, 257, 1024)

    # 2. 确定 latent 形状
    latent_shape = (bs, 4096, 8)  # 或 MM-DiT 的 dict 形式

    # 3. Flow Matching 生成
    return_dict = ss_generator(latent_shape, device, cond_tokens)
    # 内部: FlowMatching.generate_iter() 使用 Euler solver
    #   for t in t_seq:
    #       velocity = reverse_fn(x_t, t, cond_tokens)  # DiT forward
    #       x_t = x_t + velocity * dt

    # 4. 解码为占据网格
    shape_latent = return_dict["shape"]  # (bs, 4096, 8)
    ss = ss_decoder(shape_latent → (bs, 8, 16, 16, 16))  # → (bs, 1, 16, 16, 16)
    coords = argwhere(ss > 0)  # 提取占据体素

    # 5. 下采样
    coords = prune_sparse_structure(coords)  # 移除孤立体素
    coords, factor = downsample_sparse_structure(coords)  # 降采样
```

#### `sample_slat()` 核心逻辑

```python
def sample_slat(slat_input, coords):
    # 1. 条件嵌入
    cond_tokens = slat_condition_embedder(image)

    # 2. latent 形状由 coords 决定
    latent_shape = (bs, coords.shape[0], 8)

    # 3. Flow Matching 生成（以 coords 为额外条件）
    slat = slat_generator(latent_shape, device, cond_tokens, coords.numpy())
    # 内部: SLatFlowModelTdfyWrapper.forward()
    #   将 feats 和 coords 构建为 SparseTensor
    #   经过 Sparse U-Net Transformer 处理

    # 4. 构建 SparseTensor 并反归一化
    slat = SparseTensor(coords=coords, feats=slat[0])
    slat = slat * slat_std + slat_mean
```

### 3.3 InferencePipelinePointMap（PointMap 增强管线）

**文件**: `pipeline/inference_pipeline_pointmap.py`

继承自 `InferencePipeline`，增加了 **PointMap 条件**（深度/点云图）支持。

#### 额外组件

- `depth_model`: 深度估计模型（如 MoGe），从 RGB 图像推断 3D 点云图
- `layout_post_optimization_method`: 布局后优化方法（可选）
- `clip_pointmap_beyond_scale`: 裁剪超出范围的点云值

#### 增强的推理流程

```python
def run(image, mask=None, seed=None, pointmap=None, ...):
    image = merge_image_and_mask(image, mask)

    # 1. 计算/加载 PointMap
    pointmap_dict = compute_pointmap(image, pointmap)
    # 如果 pointmap=None:
    #   depth_model(rgb_image) → pointmaps
    #   camera_convention_transform → PyTorch3D 坐标系
    # 如果 pointmap 已提供: 直接使用

    # 2. 预处理（Stage 1 带 pointmap，Stage 2 不带）
    ss_input_dict = preprocess_image(image, ss_preprocessor, pointmap=pointmap)
    slat_input_dict = preprocess_image(image, slat_preprocessor)  # 无 pointmap

    # 3-6. 与基础管线相同，但 ss_input_dict 额外包含:
    #   - pointmap: 归一化后的点云图
    #   - pointmap_scale, pointmap_shift: 归一化参数
    #   - rgb_pointmap: 未裁剪版本的点云图

    # 7. [可选] 布局后优化
    if layout_post_optimization_method:
        postprocessed_pose = run_post_optimization(glb, intrinsics, pose, ...)
```

#### PointMap 预处理增强

`preprocess_image()` 被重写，增加了 pointmap 处理路径：

```python
def preprocess_image(image, preprocessor, pointmap=None):
    # ... 基础 RGB/mask 处理 ...

    # 调用 preprocessor 的扩展方法
    result = preprocessor._process_image_mask_pointmap_mess(
        rgb_image, rgb_image_mask, pointmap
    )
    # 返回额外字段:
    #   pointmap, rgb_pointmap, pointmap_scale, pointmap_shift
```

### 3.4 多视角推理

多视角推理通过 `run_multi_view()` 方法实现，核心机制是 **MultiDiffusion**。

#### 流程

```python
def run_multi_view(view_images, view_masks, mode='multidiffusion', ...):
    # 1. 预处理每个视角
    for image, mask in zip(view_images, view_masks):
        rgba = merge_mask_to_alpha(image, mask)
        ss_input = preprocess_image(rgba, ss_preprocessor)
        slat_input = preprocess_image(rgba, slat_preprocessor)
        view_ss_input_dicts.append(ss_input)
        view_slat_input_dicts.append(slat_input)

    # 2. Stage 1: 多视角稀疏结构生成
    ss_return_dict = sample_sparse_structure_multi_view(
        view_ss_input_dicts, mode=mode
    )

    # 3. Stage 2: 多视角结构化潜在生成
    slat = sample_slat_multi_view(
        view_slat_input_dicts, coords, mode=mode
    )

    # 4. 解码 + 后处理（与单视角相同）
```

#### 多视角条件融合

```python
def get_multi_view_condition_input(embedder, view_input_dicts, mapping):
    view_conditions = []
    for view_dict in view_input_dicts:
        cond = embedder(view_dict["image"])  # 每个视角独立嵌入
        view_conditions.append(cond)
    all_conditions = torch.stack(view_conditions, dim=0)
    # 形状: (num_views, bs, num_tokens, dim)
    return (all_conditions,), {}
```

#### MultiDiffusion 注入

通过 `inject_generator_multi_view` 上下文管理器临时修改生成器行为：

```python
with inject_generator_multi_view(generator, num_views, num_steps, mode='multidiffusion'):
    result = generator(latent_shape, device, *conditions)
```

在 MultiDiffusion 模式下，每个去噪步骤：
1. 对每个视角分别计算速度场
2. 对所有视角的速度场取平均
3. 使用平均速度场更新潜在变量

#### 多视角坐标下采样

多视角生成可能产生更多占据体素，需要额外控制：

```python
max_coords = 5500
while coords.shape[0] > max_coords:
    coords = downsample_sparse_structure(coords, max_coords, downsample_factor=1.2)
    final_downsample_factor *= 1.2
```

---

## 4. 数据处理

### 4.1 PreProcessor（预处理器）

**文件**: `data/dataset/tdfy/preprocessor.py`

`PreProcessor` 是一个 dataclass，封装了图像、mask 和 pointmap 的变换管线。

#### 变换应用顺序

```
1. Pointmap 归一化 (normalize_pointmap=True 时)
   └─ SSIPointmapNormalizer: 计算 scale/shift 归一化点云
2. 联合变换 (三者同步变换，保持空间对齐)
   ├─ img_mask_pointmap_joint_transform (优先，三元组)
   └─ img_mask_joint_transform (回退，二元组)
3. 独立变换
   ├─ img_transform: 图像归一化等
   ├─ mask_transform: mask 二值化等
   └─ pointmap_transform: pointmap 后处理
```

#### 核心方法

**`_process_image_mask_pointmap_mess()`** — 完整处理流程:

```python
def _process_image_mask_pointmap_mess(rgb_image, rgb_image_mask, pointmap=None):
    # 1. Pointmap 归一化
    pointmap, scale, shift = _normalize_pointmap(pointmap, mask, normalizer)

    # 2. RGB 图像联合变换（用于全图版本）
    rgb_image, rgb_image_mask = _preprocess_rgb_image_mask(rgb_image, rgb_image_mask)

    # 3. 裁剪版本的联合变换
    cropped_rgb, cropped_mask, cropped_pm = _preprocess_image_mask_pointmap(
        rgb_image, rgb_image_mask, pointmap
    )

    # 4. 独立变换
    cropped_rgb = img_transform(cropped_rgb)
    cropped_mask = mask_transform(cropped_mask)
    cropped_pm = pointmap_transform(cropped_pm)

    # 5. 全图版本的独立变换
    rgb_image = img_transform(rgb_image)
    rgb_image_mask = mask_transform(rgb_image_mask)
    rgb_pointmap = pointmap_transform(rgb_pointmap)

    return {
        "image": cropped_rgb,          # 裁剪后的图像（送入 DiT）
        "mask": cropped_mask,           # 裁剪后的 mask
        "rgb_image": rgb_image,         # 完整图像
        "rgb_image_mask": rgb_image_mask,
        "pointmap": cropped_pm,         # 裁剪后的点云图
        "rgb_pointmap": rgb_pointmap,   # 完整点云图
        "pointmap_scale": scale,        # 归一化参数
        "pointmap_shift": shift,
    }
```

#### Pointmap 归一化

```python
def _normalize_pointmap(pointmap, mask, normalizer, scale=None, shift=None):
    if normalize_pointmap == False:
        # 旧行为：只计算 scale/shift 但不归一化 pointmap
        _, scale, shift = normalizer.normalize(pointmap, mask)
        return pointmap, scale, shift
    else:
        # 新行为：归一化 pointmap
        return normalizer.normalize(pointmap, mask, scale, shift)
```

### 4.2 图像/Mask 变换

**输入格式要求**:
- 图像: `(H, W, 4)` uint8 RGBA numpy 数组
- 或分离的 RGB 图像 + mask

**变换链**:

```
原始图像 (H, W, 4) uint8
    ▼ / 255.0 → float32 [0, 1]
    ▼ permute → (4, H, W)
    ▼ split → rgb (3, H, W) + mask (1, H, W)
    │
    ├─ mask: get_mask(rgba, None, "ALPHA_CHANNEL") → 从 alpha 通道提取
    │
    ▼ img_mask_joint_transform:
    │   - 中心裁剪（按 mask 边界框）
    │   - 缩放到目标尺寸
    │   - 背景填充（pad_size 控制）
    │
    ▼ img_transform:
    │   - 归一化到 [-1, 1] 或 [0, 1]
    │
    ▼ mask_transform:
    │   - 二值化
    │
    ▼ [None].cuda() → 添加 batch 维度并移至 GPU
```

### 4.3 PointMap 处理（InferencePipelinePointMap 专用）

```python
def compute_pointmap(image, pointmap=None):
    if pointmap is None:
        # 使用深度模型推断
        output = depth_model(rgb_image)  # → pointmaps (H, W, 3)
        # 坐标系转换: R3 → PyTorch3D
        transform = look_at_view_transform(eye=[0,0,-1], at=[0,0,0], up=[0,-1,0])
        points = transform.transform_points(pointmaps)
    else:
        points = pointmap  # 直接使用提供的点云图

    # 裁剪超出范围的点
    if clip_pointmap_beyond_scale:
        mask_distance = median(points[mask][:, z])
        points[abs(z) > scale * mask_distance] = NaN

    # 推断相机内参（如果深度模型未提供）
    if intrinsics is None:
        intrinsics = infer_intrinsics_from_pointmap(points)

    return {"pointmap": points, "pts_color": rgb, "intrinsics": intrinsics}
```

---

## 5. 目录结构速查

```
xpeng_data_process/sam3d/
├── run_inference.py                          # 推理入口脚本
├── demo.py                                   # 演示脚本
├── downasmple_ply.py                         # PLY 降采样工具
├── notebook/
│   ├── inference.py                          # Inference 封装类
│   ├── load_images_and_masks.py              # 图像/mask 加载工具
│   └── mesh_alignment.py                     # 网格对齐工具
│
└── sam3d_objects/
    ├── config/                               # 配置工具
    │
    ├── data/
    │   ├── utils.py                          # 数据工具函数
    │   └── dataset/tdfy/
    │       ├── preprocessor.py               # ★ PreProcessor 预处理器
    │       ├── img_and_mask_transforms.py     # 图像/mask 变换
    │       ├── img_processing.py              # 图像处理工具
    │       ├── pose_target.py                 # 姿态目标
    │       └── transforms_3d.py              # 3D 变换 (DecomposedTransform)
    │
    ├── model/
    │   ├── io.py                             # 模型加载工具
    │   └── backbone/
    │       ├── dit/embedder/
    │       │   ├── dino.py                   # ★ DINO 图像嵌入器
    │       │   ├── pointmap.py               # ★ PointMap 几何嵌入器
    │       │   ├── point_remapper.py          # 点云坐标重映射
    │       │   └── embedder_fuser.py          # 多嵌入器融合
    │       │
    │       ├── generator/
    │       │   ├── base.py                   # 生成器基类
    │       │   ├── classifier_free_guidance.py # CFG 实现
    │       │   ├── flow_matching/
    │       │   │   ├── model.py              # ★ FlowMatching 生成框架
    │       │   │   └── solver.py             # ★ ODE 求解器 (Euler/Midpoint/RK4/SDE)
    │       │   └── shortcut/
    │       │       └── model.py              # 快捷模型（蒸馏加速）
    │       │
    │       └── tdfy_dit/
    │           ├── models/
    │           │   ├── sparse_structure_flow.py    # ★ Stage 1 DiT
    │           │   ├── structured_latent_flow.py   # ★ Stage 2 DiT
    │           │   ├── sparse_structure_vae.py     # SS VAE
    │           │   ├── mm_latent.py                # MM-DiT 变体
    │           │   ├── timestep_embedder.py        # 时间步嵌入
    │           │   └── structured_latent_vae/
    │           │       ├── base.py                 # VAE 基类
    │           │       ├── encoder.py              # ★ SLat 编码器
    │           │       ├── decoder_gs.py           # ★ Gaussian Splatting 解码器
    │           │       ├── decoder_mesh.py         # Mesh 解码器
    │           │       └── decoder_rf.py           # Radiance Field 解码器
    │           │
    │           ├── modules/
    │           │   ├── transformer/               # Dense Transformer 模块
    │           │   ├── sparse/                    # Sparse Transformer 模块
    │           │   │   ├── basic.py               # SparseTensor 基础操作
    │           │   │   ├── conv/                  # 稀疏 3D 卷积
    │           │   │   ├── linear.py              # 稀疏线性层
    │           │   │   ├── spatial.py             # 上/下采样
    │           │   │   └── transformer/           # 稀疏 Transformer blocks
    │           │   ├── spatial.py                 # patchify / unpatchify
    │           │   ├── norm.py                    # LayerNorm
    │           │   └── utils.py                   # 工具函数
    │           │
    │           ├── representations/
    │           │   ├── gaussian/                  # Gaussian Splatting 表示
    │           │   ├── mesh/                      # Mesh 表示 (FlexiCubes)
    │           │   └── octree/                    # Octree 表示
    │           │
    │           ├── renderers/                     # 渲染器
    │           └── utils/
    │               └── postprocessing_utils.py    # GLB 导出、网格简化
    │
    └── pipeline/
        ├── inference_pipeline.py              # ★ 基础推理管线
        ├── inference_pipeline_pointmap.py     # ★ PointMap 增强推理管线
        ├── inference_utils.py                 # 推理工具函数
        ├── preprocess_utils.py                # 默认预处理器工厂
        ├── multi_view_utils.py                # 多视角 MultiDiffusion 工具
        ├── layout_post_optimization_utils.py  # 布局后优化
        ├── depth_models/
        │   ├── base.py                        # 深度模型基类
        │   └── moge.py                        # MoGe 深度估计模型
        └── utils/
            └── pointmap.py                    # 点云图工具（内参推断等）
```

---

## 6. 参考资料

### 6.1 核心论文与技术

| 技术 | 说明 | 在 SAM3D 中的应用 |
|------|------|-------------------|
| Flow Matching | 基于 ODE 的生成框架，学习从噪声到数据的速度场 | 两个 Stage 的核心生成机制 |
| DiT (Diffusion Transformer) | 用 Transformer 替代 U-Net 作为扩散模型骨干 | Stage 1/2 的去噪网络 |
| DINOv2 | 自监督视觉 Transformer，提供强语义特征 | 图像条件嵌入 |
| Gaussian Splatting | 基于 3D 高斯核的实时渲染表示 | 最终 3D 输出格式 |
| Classifier-Free Guidance | 无分类器引导，混合有/无条件预测 | 提升生成质量 |
| MultiDiffusion | 多视角扩散融合 | 多视角一致性生成 |
| LogNorm 时间采样 | 偏向中间时间步的采样策略 | 训练效率优化 |
| FlexiCubes | 可微分网格提取 | Mesh 输出格式 |

### 6.2 关键超参数

| 参数 | Stage 1 默认值 | Stage 2 默认值 | 说明 |
|------|---------------|---------------|------|
| `inference_steps` | 50 | 25 | ODE 求解步数 |
| `cfg_strength` | 7 | 5 | CFG 引导强度 |
| `cfg_interval` | [0, 500] | [0, 500] | CFG 生效的时间步区间 |
| `rescale_t` | 3 | 3 | 时间步重缩放因子 |
| `solver` | Euler | Euler | ODE 求解器 |
| `dtype` | bfloat16 | bfloat16 | 计算精度 |

### 6.3 数据流总结

```
┌──────────────────────────────────────────────────────────────────┐
│                        完整数据流                                │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  输入: RGBA 图像 (H, W, 4) uint8                                │
│    │                                                             │
│    ▼                                                             │
│  PreProcessor                                                    │
│    ├─ 裁剪/缩放 → (3, 518, 518) float32                        │
│    └─ mask → (1, 518, 518) float32                              │
│    │                                                             │
│    ▼                                                             │
│  DINO Embedder                                                   │
│    └─ → condition tokens (1, 257, 1024)                         │
│    │                                                             │
│    ▼                                                             │
│  [可选] PointMap Embedder                                        │
│    └─ → pointmap tokens (1, 1024, 768)                          │
│    │                                                             │
│    ▼                                                             │
│  Stage 1: Sparse Structure DiT + Flow Matching                   │
│    ├─ 噪声 (1, 4096, 8) → 50 步 Euler ODE                     │
│    ├─ ss_decoder → 占据网格 (1, 1, 16, 16, 16)                 │
│    └─ → coords: (N, 4) int  [batch_idx, x, y, z]               │
│    │                                                             │
│    ▼                                                             │
│  Stage 2: Structured Latent DiT + Flow Matching                  │
│    ├─ 噪声 (1, N, 8) → 25 步 Euler ODE                        │
│    ├─ SparseTensor(coords, feats)                                │
│    └─ 反归一化 → 最终 SparseTensor                              │
│    │                                                             │
│    ▼                                                             │
│  SLatGaussianDecoder                                             │
│    ├─ Sparse Transformer → 每体素 GS 参数                       │
│    └─ → List[Gaussian] (xyz, color, scale, rotation, opacity)   │
│    │                                                             │
│    ▼                                                             │
│  后处理                                                          │
│    ├─ Gaussian → PLY 文件                                       │
│    └─ Gaussian + Mesh → GLB 文件 (简化 + 纹理烘焙)             │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```
