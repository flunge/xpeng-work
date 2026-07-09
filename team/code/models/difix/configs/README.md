# 训练配置 (debug_configs)

从 `debug_deploy/run_train_difix_ngpu.sh` 抽出的两套训练配置，以 YAML 形式维护。

## 配置说明

| 文件 | 用途 |
|------|------|
| `overfit.yaml` | 过拟合：单场景、`output_dataset_interval2.json`、500 epoch、从 checkpoint resume |
| `train_full_dataset.yaml` | 全量训练：`output_dataset_interval24.json`、100 epoch、max_steps_per_epoch=6000、gradient_accumulation_steps=2 |

## 运行环境（workspace / version / train_root）

在 **每个 YAML 顶部** 直接写：

- `workspace`：工作目录（路径中的 `${WORKSPACE}` 会替换为此值）
- `version`：版本标识（如 `v1`、`v1_4gpu`）
- `train_root`：训练根目录名（如 `c-855`、`train_v1`）

路径里的 `${WORKSPACE}`、`${VERSION}`、`${TRAIN_ROOT}` 会按 config 里这三项替换；若某项未写，则用环境变量或默认值。

## 使用方式

1. **通过 deploy 选择配置**（推荐）

   在 `debug_deploy/deploy_difix_ngpu.bash` 里改 `config_name`、`gpu_num` 等后执行。`version`/`train_root` 仅用于 deploy 的 `--label`，训练用的路径以 config 内为准。

   ```bash
   ./debug_deploy/deploy_difix_ngpu.bash
   CONFIG_NAME=train_full_dataset GPU_NUM=4 ./debug_deploy/deploy_difix_ngpu.bash
   ```

2. **直接跑 run 脚本**

   ```bash
   bash debug_deploy/run_train_difix_ngpu.sh 0 0 2 29504 overfit
   bash debug_deploy/run_train_difix_ngpu.sh 0 0 4 29502 train_full_dataset
   ```
   （前两个参数仅给 deploy 用，run 时可为占位；第 3、4 为 GPU 数与 port，第 5 为 config 名）

3. **本地用 train_difix.py**

   ```bash
   python src/train_difix.py --config debug_configs/overfit.yaml
   ```
   无需再设环境变量，config 里已包含 workspace / version / train_root。
