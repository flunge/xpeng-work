# NvFixer Reference-Guided 改造总结

## 背景

本次改造的目标是让 `nvfixer` 在保持较高推理效率的前提下，引入 `reference image` 作为外观先验，增强以下能力：

- 光影特点迁移
- 炫光/高光细节恢复
- 色彩风格对齐
- 局部纹理细节补充

最终采用的方案是：

- `ref token cross-attn`
- `decoder detail adapter`

即：

- 将 `ref` 图编码成少量 token，作为 Cosmos DiT 的 `cross-attn` 条件输入
- 将 `ref` 图的 encoder skip 特征注入 VAE decoder，增强局部高频细节恢复

## 本次改动概览

### 1. 模型主干支持 reference image

文件：

- `nvfixer/src/pix2pix_turbo_nocond_cosmos_base_faster_tokenizer.py`

主要改动：

- `Pix2Pix_Turbo` 新增以下可选开关：
  - `use_reference_image`
  - `use_ref_cross_attn`
  - `use_ref_detail_adapter`
  - `ref_token_count`
- `forward()` 现在支持：
  - `forward(x, timesteps=None, ref=None)`
- 新增 `ReferenceTokenAdapter`
  - 将 `ref` 的 latent 压缩为固定数量 token
  - 默认 token 数由 `ref_token_count` 控制
- 将 reference token 写入 `condition.crossattn_emb`
  - 替代原本固定的无文本条件 embedding

### 2. 修正并启用 VAE skip 路径

文件：

- `nvfixer/src/pix2pix_turbo_nocond_cosmos_base_faster_tokenizer.py`

主要改动：

- 原文件中已有自定义：
  - `my_vae_encoder_fwd`
  - `my_vae_decoder_fwd`
- 但此前并没有真正绑定到 Cosmos tokenizer 的 `encoder/decoder`
- 本次改造中已显式绑定：
  - `vae.encoder.forward = my_vae_encoder_fwd`
  - `vae.decoder.forward = my_vae_decoder_fwd`
- 同时补齐 decoder skip adapter：
  - `skip_conv_0...8`
  - `ref_skip_conv_0...8`
  - `ref_skip_gate_0...8`

效果：

- 原有 `vae_skip_connection` 逻辑现在真正可用
- 新增 `ref detail adapter` 可以把 `ref` encoder 的多尺度 skip 特征注入 decoder

### 3. 数据集支持读取 ref_image

文件：

- `nvfixer/src/utils/training_utils.py`

主要改动：

- `PairedDatasetV2` 现在会从 JSON 样本中读取：
  - `ref_image`
- 返回的新字段：
  - `reference_pixel_values`
- 若样本未提供 `ref_image`，则回退为：
  - `conditioning_pixel_values.clone()`

这样可以保证：

- 旧数据可兼容
- 带 ref 的 JSON 可直接训练

### 4. 训练流程接入 reference image

文件：

- `nvfixer/src/train_pix2pix_turbo_nocond_cosmos_base_faster_tokenizer.py`

主要改动：

- 初始化 `Pix2Pix_Turbo` 时传入新参数
- 训练阶段从 batch 中读取：
  - `reference_pixel_values`
- 在启用 `use_reference_image` 时调用：
  - `net_pix2pix(x_src, ref=x_ref)`
- 验证阶段也同步使用 `ref`
- `ref_token_adapter` 参数在启用 `use_ref_cross_attn` 时加入 optimizer
- TensorBoard 和可视化目录中新增 reference 图保存

### 5. 推理脚本支持 reference-guided inference

文件：

- `nvfixer/src/inference_pretrained_model.py`

主要改动：

- 推理 CLI 新增参数：
  - `--ref_dir`
  - `--use_reference_image`
  - `--use_ref_cross_attn`
  - `--use_ref_detail_adapter`
  - `--ref_token_count`
- 单目录和多子目录推理都支持按照同名文件匹配 reference 图
- 推理模型加载时会一并构建 ref 模块

## 新增训练配置项

文件：

- `nvfixer/src/utils/training_utils.py`

新增默认配置：

- `use_reference_image: false`
- `use_ref_cross_attn: false`
- `use_ref_detail_adapter: false`
- `ref_token_count: 32`

命令行 / YAML 对应参数：

- `--use_reference_image`
- `--use_ref_cross_attn`
- `--use_ref_detail_adapter`
- `--ref_token_count`

## Debug 配置更新

文件：

- `nvfixer/debug_configs/train_smoke_from_difix_2buckets.yaml`

已打开：

- `use_reference_image: true`
- `use_ref_cross_attn: true`
- `use_ref_detail_adapter: true`
- `ref_token_count: 32`

该配置可用于最小 smoke 训练验证。

## Checkpoint 兼容性

文件：

- `nvfixer/src/pix2pix_turbo_nocond_cosmos_base_faster_tokenizer.py`

本次已将以下模块加入 ckpt 存储：

- `state_dict_unet`
- `state_dict_vae`
- `state_dict_ref_token_adapter`

加载旧 ckpt 时：

- 若没有 `state_dict_ref_token_adapter`，会自动跳过，不影响兼容

## 当前实现语义

### ref token cross-attn

逻辑：

- `ref image`
- `vae_encode`
- `adaptive pooling + token projection`
- 写入 `condition.crossattn_emb`
- 作为 DiT cross-attention 的 K/V memory

作用更偏：

- 光影结构
- 色彩风格
- 反射/高光模式
- 全局外观参考

### decoder detail adapter

逻辑：

- `ref image`
- `vae_encode`
- 读取 encoder 的多尺度 `current_down_blocks`
- 在 decoder 指定层通过 `ref_skip_conv + gated add` 注入

作用更偏：

- 局部高频细节
- 炫光边缘
- 亮斑/halo 细节
- 局部色彩过渡

## 已完成的检查

已完成：

- `py_compile` 语法检查通过
- 新增和修改文件无 lints
- smoke 配置解析通过
- `PairedDatasetV2` 已确认能够读出：
  - `conditioning_pixel_values`
  - `reference_pixel_values`
  - `output_pixel_values`

## 当前限制与注意事项

### 1. 这是第一版接入，重点是结构打通

当前实现优先保证：

- 训练/推理路径完整可跑
- 旧逻辑兼容
- ref 条件能进入 DiT 和 decoder

还没有做专门针对炫光/高光区域的额外 loss 设计。

### 2. ref token 目前是轻量压缩方案

当前 `ReferenceTokenAdapter` 使用的是：

- latent feature
- conv 投影
- adaptive pooling
- linear 到 `1024`

优点是：

- 推理开销较小
- 实现简单稳定

但后续若要进一步提升参考建模能力，可以继续尝试：

- learned resampler
- perceiver resampler
- 多尺度 ref token

### 3. detail adapter 当前基于 VAE skip 注入

这是一个高效且贴近像素细节的实现，但并不是唯一形式。
后续如果需要更强的局部细节控制，可以继续探索：

- 高亮区域显式分支
- 高频图/Laplacian 辅助输入
- decoder 后段的额外 refinement head

## 推荐下一步

建议按以下顺序验证：

1. 先跑 `train_smoke_from_difix_2buckets.yaml`
2. 确认训练 loss 正常下降且显存可接受
3. 跑一组带 `ref_dir` 的 inference 样例
4. 对比以下 ablation：
   - 无 ref
   - 仅 `ref cross-attn`
   - 仅 `ref detail adapter`
   - `cross-attn + detail adapter`

建议重点观察：

- 光影是否更贴近 ref
- 炫光是否更自然
- 色彩风格是否更稳定
- 局部细节是否更锐利
- 是否出现错误迁移或过度复制 ref 纹理
