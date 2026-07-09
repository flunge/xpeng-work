# Debug 训练模式

`train.py` 内置的轻量级冒烟测试（smoke test）模式，用于在跑完整训练前快速验证整条训练链路能否跑通。通过 `debug.enabled=true` 启用，不依赖任何额外脚本。

## 它做了什么

启用后（`train.py` 中 `debug.enabled=true` 时），会自动：

- `train.max_steps` ← `debug.num_steps`（默认 **2 步**）
- `train.num_epochs` ← `1`
- `data.repeat` ← `1`
- `output.path` ← `<output.path>/<debug.save_dir>`（默认追加 `debug` 子目录）
- 数据集仅保留前 `debug.num_samples` 个样本（默认 **1 个**）

用于快速检查：✅ 模型能否加载 · ✅ 数据集能否处理 · ✅ LoRA 能否注入 · ✅ 训练流程能否跑通。

> ⚠️ Debug 只训练 2 步，权重未收敛，**不能用于推理或评估**，仅用于验证流程。

## 配置项（`configs/train_lora_1.3b.yaml` 的 `debug` 段）

```yaml
debug:
  enabled: false      # 是否启用 debug 模式
  num_steps: 2        # debug 时的最大训练步数
  num_samples: 1      # debug 时使用的数据样本数
  save_dir: debug     # 相对于 output.path 的输出子目录
```

| 选项 | 默认值 | 说明 |
|------|--------|------|
| `debug.enabled` | `false` | 是否启用 debug 模式 |
| `debug.num_steps` | `2` | debug 时的最大训练步数 |
| `debug.num_samples` | `1` | debug 时使用的数据样本数 |
| `debug.save_dir` | `debug` | 相对于 `output.path` 的输出子目录 |

## 怎么用

### 方式 1：命令行启用（推荐）

```bash
cd models/inspatio-world
accelerate launch train.py --config configs/train_lora_1.3b.yaml debug.enabled=true
```

也可通过 `scripts/run.sh` 包装脚本启动（它会把 `key=value` 透传给 `train.py`）：

```bash
bash scripts/run.sh --mode train --train_config configs/train_lora_1.3b.yaml debug.enabled=true
```

### 方式 2：在配置文件中设置

把 `configs/train_lora_1.3b.yaml` 中的 `debug.enabled` 改为 `true`，再正常启动：

```bash
accelerate launch train.py --config configs/train_lora_1.3b.yaml
```

### 多 GPU

```bash
accelerate launch --num_processes 2 train.py \
    --config configs/train_lora_1.3b.yaml debug.enabled=true
# 或
bash scripts/run.sh --mode train --num_gpus 2 debug.enabled=true
```

## 常用示例

```bash
# 自定义配置文件
accelerate launch train.py --config configs/my_config.yaml debug.enabled=true

# 覆盖学习率 / LoRA rank 等超参
accelerate launch train.py --config configs/train_lora_1.3b.yaml \
    debug.enabled=true train.learning_rate=2e-4 lora.rank=16

# 覆盖 debug 步数 / 样本数
accelerate launch train.py --config configs/train_lora_1.3b.yaml \
    debug.enabled=true debug.num_steps=5 debug.num_samples=2

# 验证新数据集
accelerate launch train.py --config configs/train_lora_1.3b.yaml \
    debug.enabled=true data.metadata=/path/to/new_data.json
```

## 预期输出示例

```
[DEBUG MODE] Quick smoke test enabled
[config]
...
[load] InSpatio-World checkpoint: ...
[load] missing=0 unexpected=...
[DEBUG] Using first 1 samples
[train] steps=2 epochs=1 frames/block=3 lr=0.0001
[DEBUG] Smoke-test: 2 steps × 1 sample(s) → ./output/lora_run/debug
[step 1/2] epoch 0 loss=0.2387 lr=1.00e-04 (0.03 it/s)
[step 2/2] epoch 0 loss=0.0420 lr=1.00e-04 (0.03 it/s)
[save] lora -> ./output/lora_run/debug/lora_final.safetensors (600 tensors)
```

> `[step ...]` 行的打印频率取决于 `output.log_steps`，数字仅为示意。启用成功时日志开头一定会出现 `[DEBUG MODE] Quick smoke test enabled`。

## 输出结构

Debug 运行的输出保存在 `<output.path>/debug/`（LoRA 默认即 `./output/lora_run/debug/`）：

```
./output/lora_run/debug/
├── config_used.yaml          # 实际使用的配置快照
├── config_source.txt         # 源配置路径与 CLI overrides 记录
├── lora_step1.safetensors    # 中间 checkpoint（每 output.save_steps 步保存一次）
├── lora_final.safetensors    # 最终 LoRA 权重
└── tensorboard/              # TensorBoard 日志
```

> checkpoint 直接保存在该目录下，命名为 `<train_mode>_step<N>.safetensors` 与 `<train_mode>_final.safetensors`（LoRA 训练时 `train_mode=lora`），没有单独的 `checkpoints/` 子目录。

## 转为完整训练

不传 `debug.enabled`（默认 false）即可：

```bash
accelerate launch train.py --config configs/train_lora_1.3b.yaml
```

## 工作流建议

```
修改代码/配置
    ↓
debug 验证（debug.enabled=true，< 几分钟）
    ↓
✅ 通过 → 去掉 debug.enabled 运行完整训练
❌ 失败 → 调试问题 → 重新 debug
```

## 故障排查

- **`debug.enabled=true` 不起作用？** 确保 `--config` 指向的配置存在 `debug` 段（或同时用 CLI 传 `debug.num_steps` 等）。启用成功时会打印 `[DEBUG MODE] Quick smoke test enabled`。
- **输出仍显示很多步？** 检查日志开头是否有 `[DEBUG MODE]` 和 `[DEBUG] Smoke-test: ...`；没有说明 `debug.enabled` 仍为 false。
- **运行很慢？** 首次需加载基础 checkpoint 并注入 LoRA adapter；可调小 `data.num_workers`（0 或 1），并用 `nvidia-smi` 检查显存压力。
