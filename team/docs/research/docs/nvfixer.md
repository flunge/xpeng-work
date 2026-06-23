# NVFixer 技术分析文档

## 1. 概述

NVFixer 是一个图像质量增强模块，采用 Cosmos Tokenizer + Pix2Pix Turbo 架构，作为 DiFix 的替代方案。其核心思路是将图像质量增强问题建模为条件图像翻译任务：输入低质量渲染图像，输出高质量增强图像。

核心特点：
- 基于 NVIDIA Cosmos Predict2 的 Text2Image Pipeline，复用其 DiT（Diffusion Transformer）和 VAE Tokenizer
- 单步扩散推理（one-step diffusion），通过固定 timestep 实现快速推理
- VAE 编码器-解码器之间可选跳跃连接（skip connection），保留输入图像的结构信息
- 多损失函数组合训练：L2 + LPIPS + Gram Matrix Style Loss + CLIP Similarity
- 支持 DINO 结构损失（Structural Loss）用于保持图像结构一致性
- 支持 `torch.compile` 加速推理，支持批量文件夹处理和速度基准测试
- 使用车辆掩码（Vehicle Mask）排除自车区域，仅对有效区域计算损失

### 当前工程增量

当前 develop 已把 NVFixer 从“无条件质量增强”扩展成“可参考图引导的增强”版本，核心变更包括：

- 模型侧新增 `use_reference_image`、`use_ref_cross_attn`、`use_ref_detail_adapter`、`ref_token_count`
- 数据集 `PairedDatasetV2` 新增 `reference_pixel_values`，允许每个训练样本携带独立参考图
- 推理脚本 `inference_pretrained_model.py` 新增 `--ref_dir` 及上述 reference 相关开关
- checkpoint 额外保存 `state_dict_ref_token_adapter`，同时保持对旧 checkpoint 的兼容加载

当前这套 reference-guided 方案在工程上分成两部分：

- `ref token cross-attn`：把参考图编码成少量 token，注入 Cosmos DiT 的 cross-attention 条件，主要约束全局外观、光照和色彩风格
- `decoder detail adapter`：把参考图 encoder 的多尺度 skip 特征注入 decoder，主要增强局部高频细节、炫光边缘和纹理补充

如果只关心本仓库当前主线能力，而不是论文原始设计，建议把 NVFixer 理解成“支持 reference-guided 的 Cosmos/Pix2Pix Turbo 质量增强模块”。

## 2. 模型结构

### 2.1 整体架构 (`Pix2Pix_Turbo`)

文件：`src/pix2pix_turbo_nocond_cosmos_base_faster_tokenizer.py`

```
输入图像 x [B, 3, H, W]
  │
  ├─ 扩展时间维度: x → [B, 3, 1, H, W]
  │
  ├─ VAE 编码: vae.encode(x) × sigma_data → unet_input [B, 16, 1, H/8, W/8]
  │     （如启用 skip_connection，编码器保存中间特征 current_down_blocks）
  │
  ├─ DiT 去噪: unet.denoise(unet_input, sigma, condition) → z_denoised
  │     sigma = timestep / 1000（固定时间步）
  │     condition = 无条件嵌入（uncondition）
  │
  ├─ VAE 解码: vae.decode(z_denoised / sigma_data) → output [B, 3, 1, H, W]
  │     （如启用 skip_connection，解码器接收编码器中间特征）
  │
  └─ 移除时间维度: output[:, :, 0] → [B, 3, H, W]
```

关键组件：

| 组件 | 来源 | 参数量 | 功能 |
|------|------|--------|------|
| `unet` (DiT) | Cosmos Predict2 Text2Image Pipeline (0.6B) | ~数百M | 潜空间去噪/翻译 |
| `vae` (Tokenizer) | Cosmos Fast Tokenizer | ~数百M | 图像 ↔ 潜空间编解码 |
| `condition` | Cosmos Conditioner (uncondition) | - | 无条件生成的条件嵌入 |

关键超参数：
- `timestep`：扩散时间步（训练默认 999，推理默认 250-400）
- `sigma_data`：从 Cosmos 模型继承的数据标准差缩放因子
- `vae_skip_connection`：是否启用 VAE 跳跃连接
- 潜空间压缩比：8×（空间维度 H/8, W/8），通道数 16

### 2.2 Cosmos VAE 编解码器（自定义前向传播）

为支持跳跃连接，对 Cosmos VAE 的编码器和解码器进行了自定义前向传播重写：

**编码器 (`my_vae_encoder_fwd`)**：
- 在下采样过程中保存各层中间特征到 `self.current_down_blocks`
- 支持因果卷积（CausalConv3d）的时序缓存机制（`feat_cache`）

**解码器 (`my_vae_decoder_fwd`)**：
- 通过 9 个 `skip_conv` (1×1 卷积) 将编码器中间特征注入解码器
- 编码器-解码器层映射关系：`{0:0, 1:1, 2:2, 5:3, 6:4, 8:6, 10:7, 12:9, 14:10}`
- 跳跃连接公式：`x = x + skip_conv(encoder_feat[::-1][enc_idx])`

### 2.3 调度器 (`model.py`)

使用 `DPMSolverMultistepScheduler`（来自 Sana 1600M 配置），设置为单步推理模式：
```python
noise_scheduler_1step.set_timesteps(1)
```

### 2.4 判别器

使用 Vision-Aided GAN 判别器（`vision_aided_loss`）：
- 类型：`vagan_clip`（基于 CLIP 视觉特征）
- 损失类型：`multilevel_sigmoid_s`
- CLIP 视觉骨干冻结（`cv_ensemble.requires_grad_(False)`）

### 2.5 DINO 结构损失 (`utils/dino_struct.py`)

基于 DINO ViT-B/8 的自相似性结构损失：

```
VitExtractor (dino_vitb8)
  │
  ├─ 提取第 11 层的 Key 特征
  ├─ 计算 Key 的自相似矩阵 (cosine similarity)
  └─ MSE(output_self_sim, input_self_sim)
```

- 使用 hook 机制提取 ViT 各层的 Block、Attention、QKV、Patch 中间特征
- `calculate_global_ssim_loss`：逐样本计算输入和输出的 Key 自相似矩阵的 MSE 损失
- 输入图像的自相似矩阵在 `torch.no_grad()` 下计算（作为目标）

### 2.6 Style Loss (`utils/style_loss.py`)

基于 VGG16 的 Gram Matrix 风格损失：

```
提取 VGG 特征层: relu1_2, relu2_2, relu3_3, relu4_3, relu5_3
  │
  ├─ 计算各层 Gram Matrix: G = F × F^T
  └─ 加权 MSE: Σ w_l × ||G_pred - G_target||² / (d×h×w)
```

各层权重：`relu1_2: 1/2.6, relu2_2: 1/4.8, relu3_3: 1/3.7, relu4_3: 1/5.6, relu5_3: 10/1.5`

## 3. 训练流程

### 3.1 训练入口 (`train_pix2pix_turbo_nocond_cosmos_base_faster_tokenizer.py`)

使用 HuggingFace Accelerate 框架进行分布式训练。

**训练循环：**

```
for epoch in range(num_training_epochs):
    for batch in dl_train:
        x_src = batch["conditioning_pixel_values"]   # 输入（低质量）
        x_tgt = batch["output_pixel_values"]          # 目标（高质量）
        x_mask = batch["mask"]                         # 车辆掩码

        # 1. 前向传播
        x_tgt_pred = net_pix2pix(x_src)

        # 2. 计算损失
        loss = masked_L2 + LPIPS + [Gram] + [CLIP_sim]

        # 3. 反向传播 + 优化
        accelerator.backward(loss)
        optimizer.step()
```

### 3.2 损失函数组合

| 损失 | 权重参数 | 默认值 | 说明 |
|------|---------|--------|------|
| Masked L2 | `lambda_l2` | 1.0 | 仅在掩码区域计算 MSE |
| LPIPS | `lambda_lpips` | 5.0 | 随机裁剪 128-512 区域计算感知损失 |
| Gram Matrix | `lambda_gram` | 1.0 | VGG 风格损失，512×512 随机裁剪，warmup 2000 步后启用 |
| CLIP Similarity | `lambda_clipsim` | 5.0 | 输出图像与文本描述的 CLIP 相似度 |

**Masked MSE 实现：**
```python
def masked_mse(pred, tgt, mask):
    diff_sq = (pred - tgt) ** 2
    num_masked = mask.sum().clamp(min=1)
    return (diff_sq * mask).sum() / num_masked
```

掩码来源：车辆掩码（Vehicle Mask），排除自车区域（mask > 1 的区域为有效区域）。

### 3.3 优化器配置

| 参数 | 值 |
|------|-----|
| 优化器 | AdamW |
| 学习率 | 5e-6 |
| Beta1/Beta2 | 0.9 / 0.999 |
| Weight Decay | 1e-2 |
| 梯度裁剪 | max_norm = 1.0 |
| LR 调度器 | constant（可选 cosine 等） |
| 混合精度 | bf16 |

**可训练参数控制：**
- `train_full_unet=True`：训练整个 UNet/DiT
- `freeze_vae=False`：训练 VAE（但冻结 `time_conv` 层）
- `freeze_vae_encoder=True`：仅训练 VAE 解码器

### 3.4 数据集 (`utils/training_utils.py` - `PairedDatasetV2`)

支持两种数据源格式：
1. **JSON 格式**：`{split: {img_name: {image, target_image, prompt}}}`
2. **目录格式**：`{split}_A/`（输入）+ `{split}_B/`（输出）+ `{split}_prompts.json`

支持多数据源逗号分隔合并。

**车辆掩码机制：**
- 根据 `metadata.json` 中的 `vehicle_model` 字段查找对应车型掩码
- 支持多种车型（F30, E38A, E28A, H93, F57, XP5 等）
- 掩码按相机名称（cam0-cam7）分别加载
- 使用两级缓存：`clip_vehicle_model_cache` + `vehicle_mask_cache`

**图像预处理：**
- 支持多种分辨率变换（`build_transform`）：resize_576x1024, resize_544x960, resize_768x1360 等
- 图像归一化到 [-1, 1]：`(img - 0.5) / 0.5`

### 3.5 检查点管理

保存内容：
```python
{
    "state_dict_unet": net_pix2pix.unet.state_dict(),
    "state_dict_vae": net_pix2pix.vae.state_dict(),
    "net_disc": net_disc.state_dict(),
    "optimizer": optimizer.state_dict(),
    "optimizer_disc": optimizer_disc.state_dict()
}
```

支持从目录（自动选最新）或指定 `.pkl` 文件恢复训练。

## 4. 推理流程

### 4.1 推理入口 (`inference_pretrained_model.py`)

支持三种模式：

**单文件夹推理：**
```bash
python inference_pretrained_model.py \
    --model path/to/model.pkl \
    --input input_dir/ \
    --output output_dir/ \
    --resolution 1024 \
    --timestep 400
```

**批量文件夹推理：**
```bash
python inference_pretrained_model.py \
    --model path/to/model.pkl \
    --input parent_dir/ \
    --output output_dir/ \
    --batch_folders \
    --folder_pattern "cam*"
```

**速度基准测试：**
```bash
python inference_pretrained_model.py \
    --model path/to/model.pkl \
    --input dummy \
    --test-speed \
    --batch_size 8
```

### 4.2 推理流程

```
1. 加载模型 + torch.compile 编译优化
2. 预热（默认 10-50 次空推理）
3. 逐图处理：
   a. 加载图像 → resize 到目标分辨率（如 1024×576）
   b. 归一化到 [-1, 1]
   c. 模型推理（torch.autocast bf16）
   d. 反归一化 → resize 回原始分辨率 → 保存
4. 可选：生成视频（30fps/15fps/10fps）
```

支持的分辨率映射：

| 分辨率参数 | 实际尺寸 (W×H) |
|-----------|----------------|
| 256 | 256×144 |
| 512 | 512×288 |
| 704 | 704×384 |
| 960 | 960×544 |
| 1024 | 1024×576 |
| 1360 | 1360×768 |

### 4.3 评估流程 (`evaluate_test_dataset.py`)

全面的模型评估流程：

```
1. 速度基准测试（batch_size=8）
2. 加载模型（batch_size=1）
3. 逐场景、逐相机处理：
   a. 加载渲染图 + GT 图
   b. 模型推理 → 保存输出
   c. 计算指标：PSNR, LPIPS, FID
   d. 可选：计算输入 vs GT 的指标
4. 汇总统计 → 保存 metrics.yaml
```

评估指标：

| 指标 | 库 | 说明 |
|------|-----|------|
| PSNR | torchmetrics | 峰值信噪比，data_range=1.0 |
| LPIPS | torchmetrics (alex) | 感知相似度 |
| FID | torchmetrics (InceptionV3, feature=2048) | Fréchet Inception Distance |
| GPU 内存 | pynvml | 峰值显存使用量 |
| 延迟 | 手动计时 | 每样本推理时间 |

输出 `metrics.yaml` 包含：overall 统计 + per_scene 统计 + 速度基准 + 显存使用。

## 5. 目录结构速查

```
nvfixer/
├── src/
│   ├── model.py                          # 调度器工厂、VAE 自定义前向传播、下载工具
│   ├── pix2pix_turbo_nocond_cosmos_base_faster_tokenizer.py
│   │                                     # Pix2Pix_Turbo 主模型（Cosmos DiT + VAE + skip connection）
│   ├── train_pix2pix_turbo_nocond_cosmos_base_faster_tokenizer.py
│   │                                     # 训练脚本（Accelerate + 多损失 + WandB）
│   ├── inference_pretrained_model.py     # 推理脚本（单图/批量/速度测试/视频生成）
│   ├── evaluate_test_dataset.py          # 评估脚本（PSNR/LPIPS/FID/速度/显存）
│   └── utils/
│       ├── dino_struct.py                # DINO ViT-B/8 结构损失（Key 自相似性）
│       ├── style_loss.py                 # VGG16 Gram Matrix 风格损失
│       └── training_utils.py             # 参数解析 + PairedDatasetV2 + 图像变换
└── (外部依赖)
    ├── cosmos_predict2/                  # NVIDIA Cosmos Predict2 框架
    ├── vision_aided_loss/                # Vision-Aided GAN 判别器
    └── transformer_engine/               # NVIDIA Transformer Engine（推理加速）
```

## 6. 参考资料

- **Cosmos Predict2**: NVIDIA 的视觉生成框架，提供 DiT 和 VAE Tokenizer
- **Pix2Pix Turbo**: Brooks et al., 基于扩散模型的单步图像翻译
- **DPMSolver**: Lu et al., 快速扩散模型采样器
- **DINO**: Caron et al., "Emerging Properties in Self-Supervised Vision Transformers", ICCV 2021
- **Gram Matrix Style Loss**: Gatys et al., "A Neural Algorithm of Artistic Style", 2015
- **LPIPS**: Zhang et al., "The Unreasonable Effectiveness of Deep Features as a Perceptual Metric", CVPR 2018
- **Vision-Aided GAN**: Kumari et al., 利用预训练视觉模型辅助 GAN 训练
- **Sana**: Efficient-Large-Model/Sana_1600M，提供调度器配置基础
