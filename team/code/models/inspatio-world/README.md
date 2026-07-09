# InSpatio-World 
## 待验证修改
- ref_time_shift_seconds: 设为0时可复现test数据训练推理结果：先默认设为5
- tensorboard
  - epoch 设置为无限，什么时候收敛什么时候停止
- 训练测试数据集划分: 目前直接按相机划分，而非按场景划分
- vae / tae：目前训练用的是 vae，推理用的是 tae，更换是否可复现结果？

## 数据准备

原始视频 → metadata → 训练/测试划分，两个脚本配合使用：

| 脚本 | 用途 | 产出 |
|---|---|---|
| `scripts/json_dataset.py` | 扫描数据根目录下的场景，自动配对每个相机的 GT 与渲染视频（`cam{N}_gt` 与 `cam{N}_render`/`cam{N}_rgb`，支持扁平文件或带 `rgb/` 子目录两种结构），生成完整 metadata | `data/metadata.json`（全量条目列表） |
| `scripts/split_dataset.py` | 把一份 metadata 随机切分为训练集与测试集（验证集不在此处，由 `train.py` 按 `data.val_split` 在代码内再切） | `data/train_metadata.json`（~95%）、`data/test_metadata.json`（~5%） |

```bash
# 1) 扫描原始视频，生成全量 metadata
python scripts/json_dataset.py \
    --data_root /abs/path/to/inspatio_videos \
    --output ./data/metadata.json

# 2) 切分 train / test（test 比例默认 0.05）
python scripts/split_dataset.py --input_json ./data/metadata.json --test_split 0.05 --seed 42
```

每个条目格式（训练与推理同构）：
```json
[
  {
    "target_path": "/abs/path/c-xxxx/cam2_gt.mp4",
    "render_path": "/abs/path/c-xxxx/cam2_rgb.mp4",
    "ref_path":    "/abs/path/c-xxxx/cam2_gt.mp4"
  }
]
```
`target_path` 为 GT 视频，`render_path` 为 3DGS 渲染输入，`ref_path` 为参考视图（缺省时等于 `target_path`，即自重建条件）。

---

## 数据入口

训练与推理统一使用 metadata JSON（不再扫描目录、不再生成中间 `cam_list.json`）：

- 训练：`data.metadata`（见 `configs/*.yaml`，默认 `data/train_metadata.json`）
- 推理：`run.sh` 顶部内置默认 `data/test_metadata.json`（非 CLI 参数，如需更换在 `run.sh` 内修改）

所有条目会被一次性加载到同一个数据集中逐一处理。

---

## 使用方法

统一入口为 `scripts/run.sh`，用 `--mode` 选择 train / infer / both：

```bash
bash scripts/run.sh --mode <train|infer|both> [选项] [section.key=value ...]
```

### 训练模式（`--mode train`）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--train_config` | `configs/train_lora_1.3b.yaml` | 训练配置；对应三种模式 `train.mode = lora / full / partial` |
| `--num_gpus` | `1` | `accelerate launch` 的进程数（GPU 数） |
| `section.key=value` | — | 透传给 `train.py` 的 OmegaConf 覆盖，如 `train.learning_rate=2e-4`、`lora.rank=16`、`debug.enabled=true` |

底层等价：`accelerate launch --num_processes <N> train.py --config <cfg> <overrides>`。

### 推理模式（`--mode infer`）

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--run_dir` | 自动选最新 | 训练产出目录（含 `config_used.yaml` 与 `*_final` / `*_step<N>` 权重）。基础 checkpoint 路径与 LoRA/全量权重均自动从此目录与配置读取 |
| `--ref_time_shift` | `0` | 参考视频时间偏移（秒）；正=取更晚（未来）帧，负=更早。确定性偏移，与训练的随机增强无关 |
| `--max_videos` | `0` | >0 时只渲染 metadata 前 N 条 |
| `--use_tae` | 关（默认用 VAE） | 启用 TAE 解码器（更快、更省显存，质量略低） |
| `--compile_dit` | 关 | 对 DiT 应用 `torch.compile` 提升吞吐（首次需长时间预热，适合长期服务部署） |
| `--no_finetune` | 关 | 不加载 `run_dir` 中的微调权重，仅跑基座预训练模型；输出 ckpt 标签记为 `<train_mode>_step0`（即 0 步微调），便于与微调结果对比 |

> 测试集 `data/test_metadata.json` 与输出目录 `./output/test_infer` 为 `run.sh` 顶部内置默认值，无对应 CLI 参数，使用默认即可；如需更换在 `run.sh` 内修改。

> 权重读取规则：优先读 `run_dir` 下的 `*_final.safetensors`；若无 final，则取 `*_step<N>` 中 N 最大者。无需手动指定权重路径。

自定义配置参数同样用 `section.key=value` 形式（参照 `.yaml` 配置文件）。

- fuyao job（训练）
```bash
cd ./scripts
bash deploy_ngpu.bash
```

- fuyao job（推理）：编辑 `scripts/deploy_infer.bash` 顶部「可调参数」与 `jobs` 数组后提交。该脚本默认申请 **4 张 A100、四卡并行**，每张卡跑一组参数（透传给 `run.sh --mode infer`）：
  - 公共参数：`run_dir`（训练产出目录，留空自动选 `output/` 下最新）、`max_videos`（>0 只渲前 N 条）
  - 默认四组任务（`jobs` 数组，格式 `GPU序号|torchrun端口|附加参数`）：
    - GPU0 `--ref_time_shift 2` → `combined_refshift2.mp4`
    - GPU1 `--ref_time_shift 4` → `combined_refshift4.mp4`
    - GPU2 `--ref_time_shift 6` → `combined_refshift6.mp4`
    - GPU3 `--use_tae`（ref_time_shift=0）→ `combined_tae.mp4`
  - 四组输出文件名互不相同（见下文输出结构），共用同一 `output/test_infer` 不会覆盖；各卡日志写到节点 `/tmp/infer_gpu{0..3}.log`，任务结束统一 `tail` 打印
  - 增减任务数 = 改 `jobs` 数组并同步 `gpu_num`；每行的 GPU 序号与端口须唯一（端口供并行 torchrun rendezvous 用，避免冲突）
```bash
cd ./scripts
bash deploy_infer.bash
```
 
> 单卡/单组推理仍可直接 `bash run.sh --mode infer [--ref_time_shift N] [--use_tae] ...`；`run.sh` 通过环境变量 `INFER_GPU`（默认 0）、`INFER_MASTER_PORT`（默认 29610）选择推理用卡与端口。

---

## 输出结构

每个样本按 `<场景id>/<相机id>/<run标签>/<ckpt标签>` 落到独立子目录，互不覆盖：
```
output/test_infer/
  c-xxxx/
    cam2/
      lora_20260616_153045/        # run 标签：时间戳 + 训练模式
        lora_step1500/             # ckpt 标签：训练模式 + 轮次（或 *_final）
          combined.mp4             # render | GT | 生成 三联拼接（无额外参数时）
  c-yyyy/
    cam4/
      ...
```
- `run标签` = `run_dir` 目录名（体现时间戳与训练模式）
- `ckpt标签` = 实际读取的权重文件名（体现训练模式与步数，如 `lora_step1500` / `lora_final`）
- 文件名：默认 `combined.mp4`；当指定了影响结果的额外参数时，会拼到名字里，如 `combined_tae.mp4`、`combined_refshift2.mp4`、`combined_tae_refshift2_seed5.mp4`（仅含 `--use_tae` / `--ref_time_shift` / `--seed` 中非默认者）
- 输出视频帧率 = 训练配置的 `data.target_fps`（默认 10fps），推理读取每一帧、不做子采样

