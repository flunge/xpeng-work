# Difix3D+ 技术文档

> 本文档详细介绍 SimWorld 项目中 Difix3D+ 模块的模型结构、训练流程、推理渲染方式及工程优化细节。

---

## 一、概述

Difix3D+（**Di**ffusion-based **Fix**er for **3D** reconstructions）是 NVIDIA 提出的单步扩散模型（CVPR 2025 Oral），用于修复 3D 重建（NeRF / 3DGS）渲染图像中的伪影（floaters、模糊、几何失真等）。在 SimWorld 中，Difix 作为渲染后处理模块，对 3DGS 渲染的新视角图像进行质量增强。

### 核心定位

```
3DGS 渲染输出（含伪影） ──▶ Difix 单步去噪 ──▶ 高质量输出图像
                              ↑
                        可选：参考图像引导
```

### 当前工程增量

当前 develop 已在仓库里补充 TensorRT 推理路径，核心入口包括：

- `difix/src/inference_trt.py`：负责 TensorRT runtime 初始化、engine 加载与推理执行
- `difix/fixerTrt.py`：面向 XPeng 工程侧封装 `DifixTrtFixer`

当前这条路径的关键特点是：

- 运行前会调用 `configure_tensorrt_runtime()` 处理 TensorRT 依赖与 runtime 环境
- 通过 `DifixTensorRT` 从 `trt_root` 或 `ckpt_path/vae_onnx_trt` 加载 engine
- XPeng 封装接口 `fix_image_xpeng()` 强制要求输入 `ref_img`，说明当前工程使用的是带参考图的修复模式，而不是纯单图修复
- 支持按相机名选择默认相机配置，默认 `cam0`

因此，当前 Difix 在仓库中的实际落地已经不只是 PyTorch 推理，还包含一套可直接接入线上/批处理链路的 TensorRT 版本。

### 论文信息

- **论文**: Difix3D+: Improving 3D Reconstructions with Single-Step Diffusion Models
- **会议**: CVPR 2025 (Oral)
- **项目页**: https://research.nvidia.com/labs/toronto-ai/difix3d/
- **预训练模型**: https://huggingface.co/nvidia/difix

---

## 二、模型结构

### 2.1 整体架构

Difix 基于 Stable Diffusion Turbo（`stabilityai/sd-turbo`）改造，核心组件：

```
┌─────────────────────────────────────────────────────────────────┐
│                        Difix 模型架构                            │
│                                                                  │
│  输入图像 ──▶ VAE Encoder ──▶ Latent z ──▶ UNet ──▶ z_denoised  │
│                  │                                      │        │
│                  │ skip connections (4层)                │        │
│                  ▼                                      ▼        │
│              skip_conv_1~4 ──────────────▶ VAE Decoder ──▶ 输出  │
│                                                                  │
│  Text Prompt ──▶ CLIP Text Encoder ──▶ caption_enc ──▶ UNet     │
│                                                                  │
│  (可选) 参考图像 ──▶ 与输入拼接为多视角输入                        │
└─────────────────────────────────────────────────────────────────┘
```

### 2.2 各组件详解

#### 2.2.1 VAE（Variational Autoencoder）

**基础模型**: `stabilityai/sd-turbo` 的 `AutoencoderKL`

**Encoder 结构与数据流**:

Encoder 负责将像素空间图像压缩到 latent 空间，同时保存中间特征供 Decoder 使用。

```
输入: (B, 3, H, W) — RGB 图像，归一化到 [-1, 1]

conv_in: Conv2d(3→128, 3×3, padding=1)
    → (B, 128, H, W)

down_block_0 (DownEncoderBlock2D): 2×ResnetBlock2D(128→128) + Downsample(128, stride=2)
    → 保存 skip: (B, 128, H, W)        ← current_down_blocks[0]
    → 输出: (B, 128, H/2, W/2)

down_block_1 (DownEncoderBlock2D): 2×ResnetBlock2D(128→256) + Downsample(256, stride=2)
    → 保存 skip: (B, 128, H/2, W/2)    ← current_down_blocks[1]（注：保存的是 block 输入）
    → 输出: (B, 256, H/4, W/4)

down_block_2 (DownEncoderBlock2D): 2×ResnetBlock2D(256→512) + Downsample(512, stride=2)
    → 保存 skip: (B, 256, H/4, W/4)    ← current_down_blocks[2]
    → 输出: (B, 512, H/8, W/8)

down_block_3 (DownEncoderBlock2D): 2×ResnetBlock2D(512→512)（无 Downsample）
    → 保存 skip: (B, 512, H/8, W/8)    ← current_down_blocks[3]
    → 输出: (B, 512, H/8, W/8)

mid_block (UNetMidBlock2D): ResnetBlock2D(512→512) + Attention(512) + ResnetBlock2D(512→512)
    → (B, 512, H/8, W/8)

conv_norm_out: GroupNorm(32, 512) → SiLU
conv_out: Conv2d(512→8, 3×3, padding=1)
    → (B, 8, H/8, W/8)

DiagonalGaussianDistribution.sample() → (B, 4, H/8, W/8)
× scaling_factor (0.18215) → latent z
```

**关键改造 — Skip Connection**:

原版 SD VAE 的 Encoder 和 Decoder 完全独立。Difix 通过 monkey-patch 替换 Encoder 的 `forward` 方法（`my_vae_encoder_fwd`），在每个 `down_block` 执行前保存当前特征到 `self.current_down_blocks` 列表。这 4 层中间特征随后通过 1×1 卷积传递给 Decoder：

```python
# my_vae_encoder_fwd — 替换后的 Encoder forward
def my_vae_encoder_fwd(self, sample):
    sample = self.conv_in(sample)
    l_blocks = []
    for down_block in self.down_blocks:
        l_blocks.append(sample)          # 保存 down_block 输入作为 skip
        sample = down_block(sample)
    sample = self.mid_block(sample)
    sample = self.conv_norm_out(sample)
    sample = self.conv_act(sample)
    sample = self.conv_out(sample)
    self.current_down_blocks = l_blocks  # 存储到实例属性
    return sample
```

**Decoder 结构与数据流**:

Decoder 将 latent 解码回像素空间，同时融合 Encoder 的 skip 特征：

```
输入: latent z (B, 4, H/8, W/8) / scaling_factor

conv_in: Conv2d(4→512, 3×3, padding=1)
    → (B, 512, H/8, W/8)

mid_block: ResnetBlock2D(512→512) + Attention(512) + ResnetBlock2D(512→512)
    → (B, 512, H/8, W/8)

up_block_0 (UpDecoderBlock2D): 3×ResnetBlock2D(512→512) + Upsample(512)
    ← skip_conv_1: Conv2d(512→512, 1×1, bias=False)
       输入: current_down_blocks[3] × gamma → (B, 512, H/8, W/8)
       sample = sample + skip_conv_1(skip)
    → (B, 512, H/4, W/4)

up_block_1 (UpDecoderBlock2D): 3×ResnetBlock2D(512→512) + Upsample(512)
    ← skip_conv_2: Conv2d(256→512, 1×1, bias=False)
       输入: current_down_blocks[2] × gamma → (B, 256, H/4, W/4) → (B, 512, H/4, W/4)
       sample = sample + skip_conv_2(skip)
    → (B, 512, H/2, W/2)

up_block_2 (UpDecoderBlock2D): 3×ResnetBlock2D(512→256) + Upsample(256)
    ← skip_conv_3: Conv2d(128→512, 1×1, bias=False)
       输入: current_down_blocks[1] × gamma → (B, 128, H/2, W/2) → (B, 512, H/2, W/2)
       sample = sample + skip_conv_3(skip)
    → (B, 256, H, W)

up_block_3 (UpDecoderBlock2D): 3×ResnetBlock2D(256→128)（无 Upsample）
    ← skip_conv_4: Conv2d(128→256, 1×1, bias=False)
       输入: current_down_blocks[0] × gamma → (B, 128, H, W) → (B, 256, H, W)
       sample = sample + skip_conv_4(skip)
    → (B, 128, H, W)

conv_norm_out: GroupNorm(32, 128) → SiLU
conv_out: Conv2d(128→3, 3×3, padding=1)
    → (B, 3, H, W) — 输出图像，值域 [-1, 1]
```

**Skip Connection 融合逻辑**（`my_vae_decoder_fwd`）:

```python
def my_vae_decoder_fwd(self, sample, latent_embeds=None):
    sample = self.conv_in(sample)
    sample = self.mid_block(sample, latent_embeds)
    sample = sample.to(upscale_dtype)
    if not self.ignore_skip:
        skip_convs = [self.skip_conv_1, self.skip_conv_2, self.skip_conv_3, self.skip_conv_4]
        for idx, up_block in enumerate(self.up_blocks):
            # incoming_skip_acts 逆序取用：最深层 skip 对应第一个 up_block
            skip_in = skip_convs[idx](self.incoming_skip_acts[::-1][idx] * self.gamma)
            sample = sample + skip_in   # 残差加法融合
            sample = up_block(sample, latent_embeds)
    # ... conv_norm_out → conv_act → conv_out
```

**gamma 参数**: `vae.decoder.gamma = 1`，乘在 skip 特征上控制融合强度。gamma=0 等价于关闭 skip connection。

**设计意义**: 标准 VAE 的 bottleneck（4 通道 latent）会丢失高频细节。Skip connection 将 Encoder 各分辨率的特征直接传递给 Decoder 对应层，使输出图像保留输入的边缘、纹理等高频信息，这对图像修复任务至关重要——修复后的图像需要与输入在未退化区域保持像素级一致。

#### 2.2.2 UNet（去噪网络）

**基础模型**: `stabilityai/sd-turbo` 的 `UNet2DConditionModel`（~860M 参数）

**架构参数**（sd-turbo 默认配置）:

| 参数 | 值 |
|------|-----|
| `in_channels` | 4（latent 通道数） |
| `out_channels` | 4 |
| `block_out_channels` | (320, 640, 1280, 1280) |
| `down_block_types` | (CrossAttnDownBlock2D ×3, DownBlock2D) |
| `up_block_types` | (UpBlock2D, CrossAttnUpBlock2D ×3) |
| `layers_per_block` | 2 |
| `cross_attention_dim` | 768（CLIP 输出维度） |
| `attention_head_dim` | 8 |

**数据流**:

```
输入: latent z (B, 4, H/8, W/8)
      timestep t = 199
      text_embedding (B, 77, 768)

时间嵌入:
  Timesteps(320) → TimestepEmbedding(320→1280) → t_emb (B, 1280)

conv_in: Conv2d(4→320, 3×3)
    → (B, 320, H/8, W/8)

Down Path:
  CrossAttnDownBlock2D_0: 2×(ResNet(320) + Transformer(320, cross_attn=768)) + Downsample
    → (B, 320, H/16, W/16)
  CrossAttnDownBlock2D_1: 2×(ResNet(640) + Transformer(640, cross_attn=768)) + Downsample
    → (B, 640, H/32, W/32)（注：对 1024×576 输入，此处为 16×9）
  CrossAttnDownBlock2D_2: 2×(ResNet(1280) + Transformer(1280, cross_attn=768)) + Downsample
    → (B, 1280, H/64, W/64)
  DownBlock2D_3: 2×ResNet(1280)（无 attention，无 downsample）
    → (B, 1280, H/64, W/64)

Mid Block:
  UNetMidBlock2DCrossAttn: ResNet(1280) + Transformer(1280, cross_attn=768) + ResNet(1280)
    → (B, 1280, H/64, W/64)

Up Path（对称结构，含 UNet skip connections）:
  UpBlock2D_0 → CrossAttnUpBlock2D_1 → CrossAttnUpBlock2D_2 → CrossAttnUpBlock2D_3
    → (B, 320, H/8, W/8)

conv_norm_out: GroupNorm(32, 320) → SiLU
conv_out: Conv2d(320→4, 3×3)
    → noise prediction ε (B, 4, H/8, W/8)
```

**Transformer Block 内部结构**（每个 `BasicTransformerBlock`）:

```
输入 hidden_states (B, N, D)  — N = spatial tokens, D = channel dim

1. Self-Attention:
   LayerNorm → attn1(Q=K=V=hidden_states) → residual add
   
2. Cross-Attention（文本条件注入）:
   LayerNorm → attn2(Q=hidden_states, K=V=text_embedding) → residual add
   
3. Feed-Forward:
   LayerNorm → GEGLU(D→4D) → Linear(4D→D) → residual add
```

**多视角变体（mv_unet.py）**:

当启用参考图像时，使用 `mv_unet.py` 中的 UNet。该文件通过 monkey-patch 替换 `BasicTransformerBlock.forward`，在 Self-Attention 阶段实现跨视角信息交互（详见第七章 Reference Image 章节）。

**单步去噪调度器**:

```python
def make_1step_sched():
    noise_scheduler_1step = DDPMScheduler.from_pretrained("stabilityai/sd-turbo", subfolder="scheduler")
    noise_scheduler_1step.set_timesteps(1, device="cuda")
    noise_scheduler_1step.alphas_cumprod = noise_scheduler_1step.alphas_cumprod.cuda()
    return noise_scheduler_1step
```

UNet 输出 noise prediction `ε`，经 DDPM Scheduler 的 `step()` 方法计算去噪后的 latent：

```
z_denoised = scheduler.step(ε, timestep=199, z).prev_sample
```

`timestep=199` 对应较低的噪声水平（DDPM 的 1000 步中的第 199 步），意味着输入图像被视为"轻微加噪"的状态，单步即可去噪到干净图像。

#### 2.2.3 CLIP Text Encoder

**模型**: `openai/clip-vit-large-patch14`（随 sd-turbo 分发）

**结构**: 12 层 Transformer，hidden_dim=768，max_length=77 tokens

**数据流**:

```
文本 prompt (str)
    → Tokenizer → input_ids (1, 77)
    → CLIPTextModel → last_hidden_state (1, 77, 768)
    → repeat 到 batch 维度 → caption_enc (B*V, 77, 768)
    → 注入 UNet 的 Cross-Attention 层
```

**缓存机制**（`_encode_text_cached`）:

模型维护一个 `_text_embed_cache` 字典，支持两种 key：
- `("prompt", "文本内容")` — 按 prompt 字符串缓存
- `("tokens", (token_id_tuple))` — 按 token 序列缓存

初始化时预缓存 7 个相机视角的 prompt：
```python
self.prime_camera_prompt_cache(["cam0", "cam2", "cam3", "cam4", "cam5", "cam6", "cam7"])
# 生成 prompt: "Corrected rendering distortion for CAM0 camera view." 等
```

推理时命中缓存直接返回 embedding，避免重复执行 CLIP forward（节省 ~2-5ms/次）。

#### 2.2.4 LoRA 微调层

**目标**: 仅微调 VAE Decoder 的少量参数，保持预训练 UNet 的生成能力。

**配置**:
```python
target_part_vae = [
    "conv1", "conv2", "conv_in", "conv_shortcut", "conv", "conv_out",
    "skip_conv_1", "skip_conv_2", "skip_conv_3", "skip_conv_4",
    "to_k", "to_q", "to_v", "to_out.0",
]
# 仅对 decoder 中匹配上述名称的模块添加 LoRA
vae_lora_config = LoraConfig(r=4, init_lora_weights="gaussian", target_modules=target_modules_vae)
vae.add_adapter(vae_lora_config, adapter_name="vae_skip")
```

**参数量对比**:

| 组件 | 可训练参数 | 说明 |
|------|-----------|------|
| UNet | ~860M | 全参数训练 |
| VAE LoRA + skip_conv | ~2M | 仅 LoRA 层 + 4 个 1×1 卷积 |
| Text Encoder | 0（冻结） | 不参与训练 |
| VAE Encoder | 0（冻结） | 不参与训练 |

### 2.3 关键设计

| 设计点 | 说明 |
|--------|------|
| 单步去噪 | `num_inference_steps=1, timestep=199`，仅需一次 UNet forward |
| Skip Connection | VAE Encoder→Decoder 的 4 层跳跃连接保留输入细节 |
| LoRA 微调 | 仅微调 VAE Decoder 的 LoRA 层 + skip conv，参数量极小 |
| 多视角支持 | 可选 `mv_unet` 实现跨视角注意力 |
| 参考图像引导 | 可选传入参考图像（ref_image），与输入拼接为 2-view 输入 |

### 2.4 完整前向数据流（Tensor 维度追踪）

以 1024×576 输入、单张图像（无参考图）为例：

```
输入: image (1, 1, 3, 576, 1024)  — (B, V, C, H, W)
    ↓ rearrange → (1, 3, 576, 1024)  — (B*V, C, H, W)

VAE Encode:
    conv_in      → (1, 128, 576, 1024)
    down_block_0 → (1, 128, 288, 512)   skip[0]: (1, 128, 576, 1024)
    down_block_1 → (1, 256, 144, 256)   skip[1]: (1, 128, 288, 512)
    down_block_2 → (1, 512, 72, 128)    skip[2]: (1, 256, 144, 256)
    down_block_3 → (1, 512, 72, 128)    skip[3]: (1, 512, 72, 128)
    mid_block    → (1, 512, 72, 128)
    conv_out     → (1, 8, 72, 128)
    sample()     → (1, 4, 72, 128)
    × 0.18215   → latent z (1, 4, 72, 128)

Text Encode:
    "remove degradation" → tokens (1, 77) → CLIP → (1, 77, 768)
    repeat(v=1)          → caption_enc (1, 77, 768)

UNet Forward:
    conv_in              → (1, 320, 72, 128)
    CrossAttnDown_0      → (1, 320, 36, 64)
    CrossAttnDown_1      → (1, 640, 18, 32)
    CrossAttnDown_2      → (1, 1280, 9, 16)
    DownBlock_3          → (1, 1280, 9, 16)
    MidBlock             → (1, 1280, 9, 16)
    UpBlock_0            → (1, 1280, 9, 16)
    CrossAttnUp_1        → (1, 1280, 18, 32)
    CrossAttnUp_2        → (1, 640, 36, 64)
    CrossAttnUp_3        → (1, 320, 72, 128)
    conv_out             → ε (1, 4, 72, 128)

Scheduler Step:
    z_denoised = step(ε, t=199, z) → (1, 4, 72, 128)

VAE Decode (+ skip connections):
    conv_in              → (1, 512, 72, 128)
    mid_block            → (1, 512, 72, 128)
    up_block_0 + skip[3] → (1, 512, 144, 256)
    up_block_1 + skip[2] → (1, 512, 288, 512)
    up_block_2 + skip[1] → (1, 256, 576, 1024)
    up_block_3 + skip[0] → (1, 128, 576, 1024)
    conv_out             → (1, 3, 576, 1024)
    clamp(-1, 1)         → 输出图像

    ↓ rearrange → (1, 1, 3, 576, 1024)  — (B, V, C, H, W)
```

---

## 三、训练流程

### 3.1 数据准备

训练数据为 JSON 格式的配对数据集：

```json
{
  "train": {
    "data_id_001": {
      "image": "path/to/degraded_image.png",
      "target_image": "path/to/ground_truth.png",
      "ref_image": "path/to/reference_image.png",
      "prompt": "remove degradation"
    }
  },
  "test": { ... }
}
```

| 字段 | 说明 |
|------|------|
| `image` | 3DGS 渲染的含伪影图像（输入） |
| `target_image` | 对应的真实图像（监督目标） |
| `ref_image` | 参考视角图像（可选） |
| `prompt` | 文本提示，通常为 `"remove degradation"` |

**数据集类**: `PairedDataset`（`difix/src/dataset.py`）
- 支持车辆 mask 遮罩（按车型 ID 映射不同 mask 文件）
- `CamGroupedBatchSampler`: 保证同一 batch 内样本来自同一相机，避免跨相机混合训练

### 3.2 训练损失

三项损失联合优化：

$$L_{\text{total}} = \lambda_{\text{l2}} \cdot L_{\text{l2}} + \lambda_{\text{lpips}} \cdot L_{\text{lpips}} + \lambda_{\text{gram}} \cdot L_{\text{gram}}$$

| 损失 | 默认权重 | 说明 |
|------|---------|------|
| L2 Loss | `λ_l2 = 10.0` | 像素级重建损失 |
| LPIPS Loss | `λ_lpips = 1.0` | 感知损失（VGG 特征空间） |
| Gram Loss | `λ_gram = 0.1` | 风格损失（VGG 多层 Gram 矩阵），有 warmup |

#### 3.2.1 L2 Loss（像素级重建损失）

**原理与设计思想**：L2 Loss（均方误差）直接度量输出图像与 GT 图像在像素空间的逐点差异。作为最基础的重建损失，它确保修复后的图像在整体亮度、颜色上与真实图像保持一致。权重设为 10.0（三项中最高），因为像素级精确还原是图像修复任务的首要目标——修复后的图像必须在未退化区域与输入保持像素级一致。

**公式**：

$$L_{\text{l2}} = \frac{1}{N} \sum_{i=1}^{N} \| \hat{I}_i - I_i^{*} \|_2^2$$

其中 $\hat{I}_i$ 为模型输出像素值，$I_i^{*}$ 为 GT 像素值，$N$ 为像素总数。

#### 3.2.2 LPIPS Loss（感知损失）

**原理与设计思想**：LPIPS（Learned Perceptual Image Patch Similarity）在预训练 VGG 网络的多层特征空间中度量图像差异，而非直接比较像素值。人眼对图像质量的感知更接近高层语义特征的相似性，而非逐像素的数值差异。例如，轻微的空间偏移在像素空间产生很大的 L2 误差，但人眼几乎无法察觉。LPIPS 弥补了 L2 Loss 对感知质量不敏感的缺陷，引导模型生成在人眼看来更自然的修复结果。

**公式**：

$$L_{\text{lpips}} = \sum_{l} \frac{1}{H_l W_l} \sum_{h,w} \| w_l \odot (\phi_l(\hat{I})_{h,w} - \phi_l(I^{*})_{h,w}) \|_2^2$$

其中 $\phi_l$ 为 VGG 第 $l$ 层的特征提取，$w_l$ 为该层的可学习权重向量，$H_l, W_l$ 为该层特征图的空间尺寸。

#### 3.2.3 Gram Loss（风格损失）

**原理与设计思想**：Gram Matrix 捕捉的是特征图不同通道之间的相关性，即图像的"纹理风格"信息。对于 3DGS 渲染修复任务，输入图像可能存在纹理退化（模糊、伪影），Gram Loss 约束修复后图像的纹理统计特性与 GT 一致，确保修复结果不仅在像素和感知层面正确，在纹理细节的分布特征上也与真实图像匹配。使用 warmup 策略（前 2000 步不启用）是因为训练初期模型输出与 GT 差异过大，此时 Gram Loss 的梯度信号噪声较大，可能干扰基础重建的学习。

**公式**：

给定 VGG 第 $l$ 层特征图 $F_l \in \mathbb{R}^{C_l \times H_l W_l}$，Gram 矩阵定义为：

$$G_l = \frac{F_l \cdot F_l^T}{C_l \cdot H_l \cdot W_l}$$

$$L_{\text{gram}} = \sum_{l} w_l \cdot \| G_l(\hat{I}) - G_l(I^{*}) \|_F^2$$

- 使用 VGG 的 `relu1_2, relu2_2, relu3_3, relu4_3, relu5_3` 五层特征
- 各层权重 $w_l$: `1/2.6, 1/4.8, 1/3.7, 1/5.6, 10/1.5`（浅层权重较低因为浅层特征更局部，深层 relu5_3 权重最高因为它捕捉全局纹理风格）
- Warmup: 前 `gram_loss_warmup_steps`（默认 2000）步不启用

### 3.3 训练配置

关键参数（`config_train.py` 默认值）：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `image_height / image_width` | 576 / 1024 | 训练分辨率 |
| `timestep` | 199 | 扩散时间步（单步） |
| `lora_rank_vae` | 4 | VAE LoRA rank |
| `learning_rate` | 5e-6 | 学习率 |
| `train_batch_size` | 4 | 每 GPU batch size |
| `max_steps_per_epoch` | 4000 | 每 epoch 最大步数 |
| `gradient_accumulation_steps` | 1 | 梯度累积 |
| `mixed_precision` | bf16 | 混合精度 |

**可训练参数**:
- UNet: 全部参数（~860M）
- VAE: 仅 LoRA 层 + skip_conv_1~4（~2M）
- Text Encoder: 冻结

### 3.4 训练命令

```bash
# 单 GPU
accelerate launch --mixed_precision=bf16 src/train_difix.py \
    --output_dir=./outputs/difix/train \
    --dataset_path="data/data.json" \
    --max_train_steps 10000 \
    --resolution=512 --learning_rate 2e-5 \
    --train_batch_size=1 --dataloader_num_workers 8 \
    --enable_xformers_memory_efficient_attention \
    --checkpointing_steps=1000 --eval_freq 1000 --viz_freq 100 \
    --lambda_lpips 1.0 --lambda_l2 1.0 --lambda_gram 1.0 \
    --gram_loss_warmup_steps 2000 --timestep 199

# 多 GPU（8卡）
export NUM_GPUS=8
accelerate launch --mixed_precision=bf16 --multi_gpu --num_processes $NUM_GPUS \
    src/train_difix.py [同上参数]
```

### 3.5 Checkpoint 格式

```python
{
    "vae_lora_target_modules": [...],  # LoRA 目标模块列表
    "rank_vae": 4,                     # LoRA rank
    "state_dict_unet": {...},          # UNet 权重
    "state_dict_vae": {...},           # VAE LoRA + skip conv 权重
    "optimizer": {...},                # 优化器状态
    "epoch": N,                        # 当前 epoch
    "global_step": M,                  # 全局步数
    "lr_scheduler_state": {...}        # 学习率调度器状态
}
```

### 3.6 双分辨率 Bucket 训练

支持按图像宽高比自动选择训练分辨率：

| Bucket | 宽高比 | 分辨率 |
|--------|--------|--------|
| 16:9 | 1.78 | 1024×576 |
| 5:4 | 1.25 | 960×768 |

启用方式: `enable_dual_resolution_bucket: true`

---

## 四、推理与渲染

### 4.1 独立推理

```python
from difix.src.model import Difix
from difix.src.pipeline_difix import DifixPipeline

# 加载模型
pipe = DifixPipeline.from_pretrained("nvidia/difix", trust_remote_code=True)
model = Difix(pipe=pipe, timestep=199)
model.set_eval()

# 推理
output_pil = model.sample(
    image=input_pil,          # PIL Image
    width=1024, height=576,
    prompt="remove degradation"
)
```

### 4.2 推理数据流

```
输入图像 (PIL/Tensor)
    │
    ▼ Resize + Normalize ([-1, 1])
    │
    ▼ VAE Encode → latent z (H/8 × W/8 × 4)
    │         └─ 保存 4 层 skip activations
    │
    ▼ UNet Forward (单步, timestep=199)
    │         └─ 条件: CLIP text embedding
    │
    ▼ Scheduler Step → z_denoised
    │
    ▼ VAE Decode (+ skip connections)
    │
    ▼ Denormalize + Resize → 输出图像
```

### 4.3 SimWorld 集成渲染

在 SimWorld 生产部署中，Difix 通过 `DifixFixer` 类集成：

```python
# ips_deploy 中的调用链
simulator.render(camera, timestamp, ...)  # 3DGS 渲染
    → redistort_gpu(camera_name, rgb)     # 重畸变
    → image_fixer.fix_image_xpeng(...)    # Difix 后处理
```

**`DifixRenderStrategy`** 渲染策略：
1. 调用 simulator 渲染原始图像
2. GPU 上执行重畸变
3. 获取参考图像（可选）
4. 调用 `fix_image_xpeng` 执行 Difix 修复
5. Resize 到目标分辨率输出

### 4.4 `sample_xpeng` 优化推理路径

相比标准 `sample`，`sample_xpeng` 针对生产部署做了优化：

| 优化点 | 说明 |
|--------|------|
| Tensor 输入 | 直接接收 `[C,H,W]` uint8 Tensor，避免 PIL 转换开销 |
| channels_last | 使用 `torch.channels_last` 内存格式加速卷积 |
| Text 缓存 | 预缓存 7 个相机 prompt 的 embedding |
| 跳过 ref 解码 | `decode_ref=False` 时仅解码主图像，减少 VAE Decode 计算 |
| torch.compile | 对 VAE Encoder/Decoder/UNet 使用 `max-autotune-no-cudagraphs` 编译 |
| Warmup buckets | 预热不同分辨率的编译缓存 |

### 4.5 推理性能 Profile

模型内置 `profile=True` 参数，可输出各阶段耗时：

```
text_encode_ms    # CLIP 文本编码
vae_encode_ms     # VAE 编码
unet_ms           # UNet 去噪
scheduler_ms      # Scheduler step
vae_decode_ms     # VAE 解码
forward_total_ms  # 总前向时间
preprocess_ms     # 预处理
postprocess_ms    # 后处理
sample_total_ms   # 端到端总时间
```

---

## 五、工程优化工具

### 5.1 VAE ONNX/TensorRT 导出

`difix/tools/export_vae_onnx_trt.py` 支持将 VAE Encoder/Decoder 导出为 TensorRT 引擎：

- 支持多 bucket 尺寸导出
- Encoder 输出: latent + 4 层 skip tensors
- Decoder 输入: latent + 4 层 skip tensors

### 5.2 torch.compile 缓存

`difix/tools/export_vae_torch_compile_cache.py` 预生成 torch.compile 的 inductor 缓存，避免首次推理时的编译延迟。

---

## 六、与 Reconic 联合训练

在 `omnire_joint_trainning` 中，Difix 可与 3DGS（Reconic）联合训练：

### 6.1 集成方式

```
omnire_joint_trainning/src/reconic/
├── models/generative_models/difix_model.py    # DifixModel 封装
├── pipelines/pipeline_difix.py                # Pipeline 适配
├── simulator/render_strategy/
│   └── difix_render_strategy.py               # 渲染策略
└── training_loop/
    └── generative_recon_training_loop.py       # 联合训练循环
```

### 6.2 DifixModel 类

`DifixModel` 是 Reconic 框架中的 Difix 封装：
- 使用 Accelerator 管理分布式训练
- 支持 GroundingDINO + SAM 生成天空 mask
- 推理时按 batch 处理多张图像

### 6.3 联合训练流程

```
3DGS 渲染 → Difix 修复 → 修复后图像作为伪 GT → 反馈回 3DGS 训练
```

这种渐进式更新（Progressive 3D Update）是 Difix3D 的核心创新：用 Difix 修复的图像蒸馏回 3D 表示，迭代提升重建质量。

---

## 七、Reference Image 设计原理与实现

### 7.1 设计动机与理论基础

#### 问题本质

3DGS 渲染的新视角图像存在两类退化：
1. **可自恢复退化**：floaters、轻微模糊 — 退化图像自身包含足够信息，单步扩散即可修复
2. **不可自恢复退化**：纹理缺失、细节丢失（尤其在稀疏观测区域）— 退化图像中信息已丢失，仅靠去噪无法凭空生成正确纹理

对于第 2 类问题，需要外部信息源。Reference Image（参考图像）提供来自相近视角/时间戳的真实相机图像，为去噪过程注入高频纹理和真实细节先验。

#### 设计原则

Difix 的 Reference Image 方案遵循三个核心原则：

| 原则 | 实现方式 | 设计考量 |
|------|---------|---------|
| **最小侵入** | 不修改 UNet 权重结构，仅通过 monkey-patch Self-Attention 实现 | 保持预训练权重兼容性，可随时关闭 |
| **隐式融合** | 通过 Self-Attention 的 Q/K/V 机制自动学习"从参考图取什么" | 无需显式对齐、光流估计或特征匹配 |
| **非对称处理** | 训练时两个 view 均计算损失，推理时仅解码主图 | 训练稳定性 + 推理效率 |

#### 与其他方案的对比

| 方案 | 优点 | 缺点 | Difix 选择 |
|------|------|------|-----------|
| 通道拼接（channel concat） | 简单 | 需修改 conv_in 通道数，破坏预训练权重 | ❌ |
| Cross-Attention 注入 | 灵活 | 需额外 projection 层，增加参数 | ❌ |
| Self-Attention token 拼接 | 零额外参数，利用已有注意力机制 | 计算量随 view 数平方增长 | ✅ |
| ControlNet 分支 | 不修改主网络 | 参数量翻倍，训练成本高 | ❌ |

### 7.2 整体架构

```
                          ┌──────────────────┐
                          │  Reference Image  │
                          │  (真实相机图像)    │
                          └────────┬─────────┘
                                   │ Resize + Normalize
                                   ▼
┌──────────────┐          ┌──────────────────┐
│ 退化渲染图像  │──Resize──▶│  torch.stack /   │──▶ VAE Encode ──▶ UNet (跨视角注意力) ──▶ VAE Decode ──▶ 输出
│ (3DGS输出)   │  Normalize│  torch.cat       │    (2-view)       (2-view latent)        (仅主图)
└──────────────┘          │  拼接为 2-view    │
                          └──────────────────┘
```

核心思路：将退化图像与参考图像拼接为 **2-view 输入**，在 UNet 的 Self-Attention 层中实现跨视角信息交互，最终仅解码主图像输出。

### 7.3 模型结构变化

#### 7.3.1 标准 UNet vs 多视角 UNet 的差异

多视角 UNet（`mv_unet.py`）与标准 UNet 的**唯一区别**在于 `BasicTransformerBlock.forward` 的 Self-Attention 阶段。通过 monkey-patch 替换：

```python
# mv_unet.py 末尾
BasicTransformerBlock.forward = new_forward
```

**标准 UNet 的 BasicTransformerBlock**:
```
hidden_states: (B*V, N, D)
    → LayerNorm → Self-Attention(Q=K=V=self) → residual add
    → LayerNorm → Cross-Attention(Q=self, K=V=text) → residual add
    → LayerNorm → FFN → residual add
```

**多视角 UNet 的 BasicTransformerBlock**:
```
hidden_states: (B*V, N, D)
    → rearrange: (B*V, N, D) → (B, V*N, D)     ← 关键：拼接两个 view 的 token
    → LayerNorm → Self-Attention(Q=K=V=self)     ← 此时 attention 跨越两个 view
    → residual add
    → rearrange: (B, V*N, D) → (B*V, N, D)      ← 恢复独立 view
    → LayerNorm → Cross-Attention(Q=self, K=V=text) → residual add  ← 文本条件仍按独立 view
    → LayerNorm → FFN → residual add
```

**Tensor 维度变化详解**（以 1024×576 输入、UNet 第一层 CrossAttnDownBlock2D 为例）:

```
输入 latent: (B*2, 4, 72, 128) — 两个 view 的 latent 拼在 batch 维度

经 ResNet + reshape 后进入 Transformer:
  hidden_states: (B*2, 9216, 320)  — N=72×128=9216 spatial tokens, D=320

Self-Attention 前 rearrange:
  (B*2, 9216, 320) → (B, 2×9216, 320) = (B, 18432, 320)
  
  Q, K, V 均为 (B, 18432, 320)
  Attention: softmax(Q·K^T / √d) · V
  → 主图的 9216 个 token 可以 attend 到参考图的 9216 个 token
  → 参考图的 token 同样可以 attend 到主图的 token（双向）

Self-Attention 后 rearrange:
  (B, 18432, 320) → (B*2, 9216, 320)

Cross-Attention（不变）:
  Q: (B*2, 9216, 320)
  K, V: (B*2, 77, 768) → projected to (B*2, 77, 320)
  → 每个 view 独立接收文本条件
```

**设计意义**: Self-Attention 的 token 拼接使得主图的每个空间位置都能"查询"参考图中所有位置的特征。网络自动学习在哪些位置需要从参考图借用纹理（退化严重区域），在哪些位置保持自身信息（退化轻微区域）。这种隐式的特征匹配和融合无需显式的光流估计或几何对齐。

#### 7.3.2 VAE 的处理方式

VAE Encoder 和 Decoder **不做任何结构修改**，两个 view 的图像简单地拼在 batch 维度一起处理：

```python
# model.py forward
x = rearrange(x, 'b v c h w -> (b v) c h w')  # (B*2, C, H, W)
z = self.vae.encode(x).latent_dist.sample() * scaling_factor
# z: (B*2, 4, H/8, W/8) — 两个 view 的 latent
# skip activations: 每层都是 (B*2, C_i, H_i, W_i)
```

推理时通过 `decode_ref=False` 优化，仅解码主图：

```python
if (not decode_ref) and num_views > 1:
    # 从 (B*2, ...) 中只取 view 0（主图）
    decode_latent = rearrange(z_denoised, '(b v) c h w -> b v c h w', v=num_views)[:, 0]
    incoming_skip_acts = [
        rearrange(x_skip, '(b v) c h w -> b v c h w', v=num_views)[:, 0]
        for x_skip in incoming_skip_acts
    ]
```

这意味着 VAE Decode 的计算量不随 view 数增加（`decode_ref=False` 时）。

#### 7.3.3 Pipeline 切换

启用参考图像时，加载不同的预训练 pipeline：

```python
use_ref_img = getattr(args, "use_ref_img", False)
pipeline_name = "nvidia/difix_ref" if use_ref_img else "nvidia/difix"
```

`nvidia/difix_ref` pipeline 内部使用 `mv_unet.py` 中的 `UNet2DConditionModel`（含 monkey-patched Self-Attention），而 `nvidia/difix` 使用标准 diffusers 的 UNet。

### 7.4 数据准备

训练数据 JSON 中通过 `ref_image` 字段指定参考图像路径：

```json
{
  "train": {
    "sample_001": {
      "image": "path/to/degraded.png",
      "target_image": "path/to/ground_truth.png",
      "ref_image": "path/to/reference.png",
      "prompt": "remove degradation"
    }
  }
}
```

`PairedDataset` 中的处理逻辑（`dataset.py`）：

1. 当 `use_ref_img=True` 且 `ref_image` 路径存在时，加载参考图像并与输入图像 stack 为 2-view tensor
2. 当 `use_ref_img=True` 但 `ref_image` 路径为空时，使用 GT 图像作为 fallback 参考
3. 当 `use_ref_img=False` 时，保持单 view 输入

```python
# dataset.py 核心逻辑
if self.use_ref_img:
    if ref_img_path is not None:
        ref_t = F.normalize(F.resize(F.to_tensor(Image.open(ref_img_path)), (H, W)), [0.5], [0.5])
    else:
        ref_t = output_t.clone()  # fallback: 用 GT 作为参考
    img_t = torch.stack([img_t, ref_t], dim=0)       # shape: (2, C, H, W)
    output_t = torch.stack([output_t, ref_t], dim=0)  # 监督目标也对齐为 2-view
```

### 7.5 模型前向：2-View 处理流程

#### 完整 Tensor 维度追踪（B=1, 1024×576, 有参考图）

```
输入:
  degraded_image: (1, 3, 576, 1024)
  reference_image: (1, 3, 576, 1024)
  → torch.stack → x: (1, 2, 3, 576, 1024)  — (B, V=2, C, H, W)

rearrange → (2, 3, 576, 1024)  — (B*V, C, H, W)

VAE Encode（两个 view 一起编码）:
  → latent z: (2, 4, 72, 128)
  → skip[0]: (2, 128, 576, 1024)
  → skip[1]: (2, 128, 288, 512)
  → skip[2]: (2, 256, 144, 256)
  → skip[3]: (2, 512, 72, 128)

Text Encode:
  caption_enc: (1, 77, 768) → repeat(v=2) → (2, 77, 768)

UNet Forward（含跨视角注意力）:
  每个 BasicTransformerBlock 中:
    Self-Attn 前: (2, N, D) → (1, 2N, D)  — 两个 view 的 token 拼接
    Self-Attn:    Q/K/V 均为 (1, 2N, D)   — 跨 view 注意力
    Self-Attn 后: (1, 2N, D) → (2, N, D)  — 恢复独立 view
    Cross-Attn:   Q=(2,N,D), K/V=(2,77,D) — 独立文本条件
  → noise prediction ε: (2, 4, 72, 128)

Scheduler Step:
  → z_denoised: (2, 4, 72, 128)

decode_ref=False 优化:
  z_denoised: (2, 4, 72, 128) → rearrange → (1, 2, 4, 72, 128) → [:, 0] → (1, 4, 72, 128)
  skip acts: 同样只取 view 0

VAE Decode（仅主图）:
  → (1, 3, 576, 1024)
  → unsqueeze(1) → (1, 1, 3, 576, 1024)  — (B, V=1, C, H, W)
```

### 7.6 训练适配

#### 启用方式

训练配置中设置 `use_ref_img: true`：

```yaml
# config.yaml
use_ref_img: true
```

训练脚本会自动切换到 `nvidia/difix_ref` pipeline（含多视角 UNet）：

```python
use_ref_img = getattr(args, "use_ref_img", False)
pipeline_name = "nvidia/difix_ref" if use_ref_img else "nvidia/difix"
```

#### 训练命令

```bash
accelerate launch --mixed_precision=bf16 src/train_difix.py \
    --output_dir=./outputs/difix_ref/train \
    --dataset_path="data/data_with_ref.json" \
    --use_ref_img \
    --max_train_steps 10000 \
    --resolution=512 --learning_rate 2e-5 \
    --train_batch_size=1 --dataloader_num_workers 8 \
    --enable_xformers_memory_efficient_attention \
    --lambda_lpips 1.0 --lambda_l2 1.0 --lambda_gram 1.0
```

#### 损失计算的双 View 策略

训练时，监督目标同样为 2-view：`output_t = torch.stack([gt, ref], dim=0)`。两个 view 的损失均参与优化：

```python
# train_difix.py 训练循环
x_src = batch["conditioning_pixel_values"]  # (B, V=2, C, H, W)
x_tgt = batch["output_pixel_values"]        # (B, V=2, C, H, W)

x_tgt_pred = net_difix(x_src, prompt_tokens=batch["input_ids"])  # (B, V=2, C, H, W)

# 展平为 (B*V, C, H, W) 计算损失
x_tgt = rearrange(x_tgt, 'b v c h w -> (b v) c h w')
x_tgt_pred = rearrange(x_tgt_pred, 'b v c h w -> (b v) c h w')

# L2 损失：按 (B*V) 计算后，rearrange 回 (B, V) 再对 V 维度取均值
loss_l2_per_bv = masked_mse(x_tgt_pred, x_tgt, x_mask) * lambda_l2
loss_l2_per_sample = rearrange(loss_l2_per_bv, '(b v) -> b v', v=V).mean(dim=1)  # V 维度平均
loss_l2 = loss_l2_per_sample.mean()  # B 维度平均

# LPIPS 和 Gram Loss 同理
```

**双 View 损失的设计意义**:

| View | 监督目标 | 损失作用 |
|------|---------|---------|
| View 0（主图） | GT 图像 | 核心修复目标：学习从退化图像恢复到真实图像 |
| View 1（参考图） | 参考图自身 | **恒等约束**：参考图经过网络后应保持不变 |

View 1 的恒等约束（identity loss）至关重要：
- 防止参考图通路退化（如果不约束，网络可能学会忽略参考图输入）
- 保持 Self-Attention 中参考图特征的质量（参考图特征需要"干净"才能为主图提供有用信息）
- 与论文 Difix3D+ Figure 3 / Section 4.1 中的 "Reference Mixing" 设计一致

### 7.7 推理适配

#### 独立推理（sample）

```python
output_pil = model.sample(
    image=degraded_pil,       # 退化图像（PIL）
    ref_image=reference_pil,  # 参考图像（PIL）
    width=1024, height=576,
    prompt="remove degradation"
)
```

内部处理：
```python
# sample() 中的参考图拼接逻辑
if ref_image is None:
    x = T(image).unsqueeze(0).unsqueeze(0).cuda()          # (1, 1, C, H, W)
else:
    ref_image = ref_image.resize((new_width, new_height), Image.LANCZOS)
    x = torch.stack([T(image), T(ref_image)], dim=0)       # (2, C, H, W)
    x = x.unsqueeze(0).cuda()                               # (1, 2, C, H, W)

# forward 输出后取 view 0
output_image = self.forward(x, ...)[:, 0]                   # (1, C, H, W)
```

#### 生产推理（sample_xpeng）

```python
output = model.sample_xpeng(
    image_tensor=input_tensor,   # [C,H,W] uint8 GPU tensor
    ref_image=ref_tensor,        # [C,H,W] uint8 GPU tensor（可选）
    width=1024, height=576,
    prompt="Corrected rendering distortion for FRONT camera view."
)
```

与 `sample` 的关键差异：

| 差异点 | sample | sample_xpeng |
|--------|--------|-------------|
| 输入格式 | PIL Image | `[C,H,W]` uint8 GPU Tensor |
| 拼接方式 | `torch.stack` | `torch.cat` on dim=1 |
| 参考图解码 | 默认解码两个 view | `decode_ref=False`，仅解码主图 |
| 文本编码 | 每次重新编码 | 使用 `_encode_text_cached` 缓存 |
| 内存格式 | 默认 | `channels_last` 加速卷积 |
| 输出格式 | PIL Image | `[C,H,W]` uint8 GPU Tensor |

```python
# sample_xpeng 中的参考图拼接
if ref_image is not None:
    ref_tensor = (ref_image.float() / 255.0 - 0.5) / 0.5
    ref_tensor = F.resize(ref_tensor, (height, width)).unsqueeze(0).unsqueeze(0)
    x = torch.cat([x_main, ref_tensor], dim=1)  # (1, 2, C, H, W) — cat on view dim
else:
    x = x_main  # (1, 1, C, H, W)

# forward 时启用优化
output_image = self.forward(
    x,
    decode_ref=False,              # 不解码参考图
    use_text_cache=True,           # 使用文本缓存
    use_channels_last=True,        # channels_last 内存格式
)[:, 0]
```

#### 批量推理中的参考图选择策略（inference_batch.py）

`ref_image_mode` 参数控制参考图来源：

| ref_image_mode | 行为 |
|----------------|------|
| `None` | 不使用参考图（单 view 推理） |
| `0` | 使用当前帧的 GT 图像作为参考（oracle 模式，用于评估上限） |
| `N`（正数，秒） | 在当前 clip 内，按时间窗口 ±N 秒随机选择一帧 GT 作为参考 |

```python
# 时间窗口选择逻辑
window_ns = int(float(ref_image_mode) * 1e9)
candidates = [idx for idx, ts in enumerate(gt_timestamps_ns)
              if idx != i and abs(ts - cur_ts_ns) <= window_ns]
ref_idx = random.choice(candidates) if candidates else None
```

### 7.8 生产部署适配（DifixRenderStrategy）

在 SimWorld 的 IPS 部署中，`DifixRenderStrategy` 负责获取参考图并调用 Difix：

```
3DGS 渲染 → 重畸变 → 获取参考图 → Difix 修复 → Resize → 输出
```

参考图获取流程：

1. 从 `difix_config` 读取 `use_reference_image` 开关和 `reference_image_path` 基础路径
2. 根据当前渲染时间戳和相机名，在 `reference_image_path` 下查找最近的真实相机图像
3. 加载为 `[C,H,W]` uint8 GPU tensor 传入 `fix_image_xpeng`

```python
# difix_render_strategy.py
def get_reference_image(self, rendered_timestamp, camera):
    if not difix_config.get("use_reference_image", False):
        return None
    base_dir = difix_config.get("reference_image_path", "")
    image_path = self.get_real_car_image(rendered_timestamp, camera, base_dir)
    ref_tensor = torch.from_numpy(np.array(Image.open(image_path))).permute(2, 0, 1).cuda()
    return ref_tensor
```

#### Warmup 机制

生产部署中，`torch.compile` 需要对每种输入尺寸预编译。`warmup_inference_compile_buckets` 方法在服务启动时预热：

```python
model.warmup_inference_compile_buckets(
    bucket_sizes=[(576, 1024), (768, 960)],  # 所有可能的分辨率
    use_ref=True,                             # 是否使用参考图
    camera_names=["cam0", "cam2", ...],       # 相机列表
)
```

预热时使用随机 dummy tensor 执行一次完整推理，触发 inductor 编译并缓存 kernel。

### 7.9 性能影响分析

| 阶段 | 无参考图 | 有参考图 | 增量原因 |
|------|---------|---------|---------|
| 预处理 | ~2ms | ~3ms | 多一张图的 resize + normalize |
| VAE Encode | ~18ms | ~30ms | batch 从 1→2，编码量翻倍 |
| UNet | ~40ms | ~55ms | Self-Attention token 数翻倍（N→2N），计算量约 ×2 |
| Scheduler | ~1ms | ~1ms | 无变化 |
| VAE Decode | ~20ms | ~20ms | `decode_ref=False` 仅解码主图，无增量 |
| 后处理 | ~2ms | ~2ms | 无变化 |
| **总计** | **~80ms** | **~110ms** | **约增加 35% 延迟** |

**计算量分析**:

Self-Attention 的计算复杂度为 O(N²·D)，其中 N 为 token 数。拼接两个 view 后 N 翻倍，Self-Attention 计算量变为原来的 4 倍。但由于 Self-Attention 仅占 UNet 总计算量的一部分（ResNet block、Cross-Attention、FFN 不受影响），实际 UNet 延迟增加约 35-40%。

### 7.10 使用建议

| 场景 | 建议 |
|------|------|
| 纹理缺失严重（远距离视角、稀疏区域） | ✅ 启用参考图，质量提升显著 |
| 实时性要求极高（<80ms/帧） | ❌ 关闭参考图，优先保证帧率 |
| 有高质量近时间戳真实图像可用 | ✅ 启用，时间窗口建议 1-3 秒 |
| 无真实图像可用 | ❌ 关闭，避免用低质量参考引入噪声 |

#### 参考图质量要求

- **视角相近**: 参考图与目标视角的视差不宜过大，否则 Self-Attention 难以建立有效的特征对应
- **时间相近**: 场景变化（光照、动态物体）会降低参考图的有效性
- **分辨率匹配**: 参考图会被 resize 到与输入相同的分辨率，过低分辨率的参考图无法提供有效的高频信息

---

## 八、目录结构速查

```
difix/
├── __init__.py
├── fixer.py                    # DifixFixer - 生产部署入口
├── LICENSE.txt
├── README.md
├── requirements.txt
├── src/
│   ├── config_train.py         # 训练配置加载（YAML）
│   ├── dataset.py              # PairedDataset + CamGroupedBatchSampler
│   ├── inference_batch.py      # 批量推理脚本
│   ├── inference_difix.py      # 单张推理脚本
│   ├── loss.py                 # Gram Loss（VGG 风格损失）
│   ├── model.py                # Difix 核心模型类
│   ├── mv_unet.py              # 多视角 UNet（跨视角注意力）
│   ├── pipeline_difix.py       # DifixPipeline（diffusers 兼容）
│   ├── train_difix.py          # 训练主脚本
│   └── utils_difix.py          # 工具函数（PSNR 等）
└── tools/
    ├── export_vae_onnx_trt.py          # VAE TensorRT 导出
    └── export_vae_torch_compile_cache.py # torch.compile 缓存预热
```

---

## 九、Diffusion 延迟瓶颈分析与优化方向

### 8.1 当前延迟瓶颈

Difix 虽然已是单步扩散（1-step），但推理延迟仍然较高，主要瓶颈：

| 阶段 | 瓶颈原因 |
|------|---------|
| **VAE Encode** | 全分辨率图像编码，含 4 层下采样 + mid block |
| **UNet Forward** | ~860M 参数的完整 UNet 前向，即使单步也是最大耗时 |
| **VAE Decode** | 含 skip connection 的解码，4 层上采样 |
| **数据搬运** | CPU↔GPU 的图像预处理/后处理 |

典型耗时分布（A100, 1024×576, bf16）：
- VAE Encode: ~15-20ms
- UNet: ~30-50ms
- VAE Decode: ~15-25ms
- 预处理+后处理: ~5-10ms
- **总计: ~70-100ms/帧**

### 8.2 优化方向一：Flow Matching 替换 Diffusion

**可行性: ⭐⭐⭐⭐ 高**

Flow Matching 构建从噪声到数据的直线概率路径，相比 DDPM 的曲线路径更高效。关键研究：

**ELIR（Efficient Latent Image Restoration）**
- 在 latent space 使用 consistency flow matching 进行图像修复
- 比 SOTA diffusion/flow 方法快 4 倍以上，模型也小 4 倍以上
- 先预测 MMSE 估计的 latent 表示，再用 flow 传输到高质量图像
- 参考: https://arxiv.org/abs/2502.03500

**ResFlow（Reversing Flow for Image Restoration）**
- 采用熵保持的 flow 路径，学习增强退化 flow 的速度场
- 少于 4 步采样即可完成图像修复
- 参考: https://arxiv.org/abs/2506.16961

**替换方案**:
```
当前: 输入 → VAE Encode → DDPM UNet (1-step) → VAE Decode → 输出
替换: 输入 → Lightweight Encoder → Flow ODE (1-2 step) → Decoder → 输出
```

**优势**: Flow Matching 的 ODE 路径更直，单步质量更高；可进一步用 ReFlow 蒸馏到真正的 1-step。

### 8.3 优化方向二：模型蒸馏与压缩

**Consistency Distillation**
- 将多步扩散模型蒸馏为单步一致性模型
- 保持生成质量的同时大幅减少推理步数
- 参考: Latent Consistency Models (LCM)

**UNet 架构轻量化**
- 当前 UNet 约 860M 参数，对于图像修复任务过重
- 可考虑:
  - 通道剪枝: 减少 UNet 各层通道数（如 320→192）
  - 层剪枝: 移除部分 Transformer block
  - 知识蒸馏: 用大 UNet 教小 UNet

### 8.4 优化方向三：VAE 加速

**TensorRT 部署**（已有工具支持）
- `export_vae_onnx_trt.py` 已支持 VAE 的 TensorRT 导出
- FP16/INT8 量化可进一步加速
- 预期 VAE 延迟降低 2-3 倍

**Tiny VAE**
- 使用更小的 VAE（如 TAESD），牺牲少量质量换取速度
- 适合对延迟极度敏感的实时场景

### 8.5 优化方向四：推理工程优化

| 方法 | 预期收益 | 复杂度 |
|------|---------|--------|
| **torch.compile** (已实现) | 10-30% | 低 |
| **TensorRT UNet** | 30-50% | 中 |
| **FP8 量化** (H100/H200) | 20-40% | 中 |
| **Feature Caching** | 15-25% | 低 |
| **异步 Pipeline** | 减少等待 | 中 |

**Feature Caching**: 对于连续帧渲染，相邻帧的 UNet 中间特征高度相似，可缓存部分层的输出复用。NVIDIA TensorRT Model Optimizer v0.15 已支持 cache diffusion 技术。

### 8.6 优化方向五：端到端替代方案

**GAN-based Fixer**
- 用 GAN（如 Real-ESRGAN 架构）替代 Diffusion
- 单次前向，无需迭代去噪
- 延迟可降至 10-20ms
- 缺点: 生成多样性和细节不如 Diffusion

**Adversarial Distillation**
- 结合 Consistency Model + GAN 判别器
- 在保持 Diffusion 质量的同时实现单步高速推理
- 参考: Hierarchical Distillation, Self-Corrected Flow Distillation

### 8.7 推荐优化路线图

```
短期（1-2 月）:
  ├─ 启用 TensorRT VAE 导出（工具已就绪）
  ├─ 完善 torch.compile warmup 流程
  └─ UNet FP8 量化实验

中期（2-4 月）:
  ├─ Flow Matching 替换 DDPM Scheduler
  │   └─ 基于 ELIR/ResFlow 思路重训
  ├─ UNet 通道剪枝 + 知识蒸馏
  └─ Feature Caching 实现

长期（4-6 月）:
  ├─ 端到端 Flow Matching 轻量模型
  ├─ Consistency Distillation 单步模型
  └─ 评估 GAN-based 替代方案
```

---

## 十、参考资料

- [Difix3D+ 论文](https://arxiv.org/abs/2503.01774)
- [NVIDIA 项目页](https://research.nvidia.com/labs/toronto-ai/difix3d/)
- [HuggingFace 模型](https://huggingface.co/nvidia/difix)
- [ELIR: Efficient Image Restoration via Latent Consistency Flow Matching](https://arxiv.org/abs/2502.03500)
- [ResFlow: Reversing Flow for Image Restoration](https://arxiv.org/abs/2506.16961)
- [Improved Techniques for Fast Flow Models](https://arxiv.org/abs/2410.07815)
- [Score Distillation of Flow Matching Models](https://arxiv.org/abs/2509.25127)
