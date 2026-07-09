---
name: 3dgs-fuyao-safe-workdir
description: Ensures Fuyao commands are executed from a newly created minimal working directory to avoid uploading the whole 3DGS repository. Use whenever running fuyao, fuyao deploy/status/log/download, submitting Fuyao jobs, or editing scripts that invoke Fuyao in this repository.
---

# 3DGS Fuyao 安全工作目录

## 背景

在本仓库执行 `fuyao` 相关命令时，Fuyao 默认会上传当前目录下的所有文件。3DGS 代码和数据位于 NAS，可在集群任务中直接通过绝对路径访问，不需要随命令上传仓库内容。

## 必须遵守

1. **不要在仓库根目录或包含大量文件的目录中直接执行 `fuyao` 命令。**
2. 执行任何 `fuyao` 命令前，先创建一个新的空目录或极简目录，并在该目录内执行命令。
3. 目录中只放提交任务必须上传的最小文件；如果没有必须上传的文件，保持目录为空。
4. Fuyao 任务命令内部应使用 NAS 上的绝对路径访问代码，例如：
   - 仓库路径：`/workspace/yangxh7@xiaopeng.com/codes/3dgs`
   - 进入仓库：`cd /workspace/yangxh7@xiaopeng.com/codes/3dgs`
5. 如果需要传入配置文件，优先在任务命令中引用 NAS 绝对路径；只有确实需要上传临时配置时，才把该配置复制到安全工作目录。

## 推荐目录

优先使用仓库外的临时目录：

```bash
FUYAO_WORKDIR="/tmp/fuyao-submit-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$FUYAO_WORKDIR"
cd "$FUYAO_WORKDIR"
```

如需保留提交记录，也可使用仓库内已忽略的输出目录：

```bash
FUYAO_WORKDIR="/workspace/yangxh7@xiaopeng.com/codes/3dgs/outputs/fuyao_submit/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$FUYAO_WORKDIR"
cd "$FUYAO_WORKDIR"
```

## 提交模板

```bash
REPO="/workspace/yangxh7@xiaopeng.com/codes/3dgs"
FUYAO_WORKDIR="/tmp/fuyao-submit-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$FUYAO_WORKDIR"
cd "$FUYAO_WORKDIR"

fuyao deploy \
  --site fuyao_b1_prod2 \
  --job-name "$JOB_NAME" \
  --label "$JOB_NAME" \
  --project "adc-sim" \
  --experiment "sim3dgs-sim" \
  --volume "adc-sim" \
  --queue "adc-sim" \
  --gpu-type "A100" \
  --gpus-per-node 1 \
  --nodes 1 \
  --release \
  "cd $REPO && python xpeng_data_process/main.py --config $REPO/xpeng_data_process/configs/config_vision.yaml"
```

## 修改脚本时

当编辑会调用 `fuyao` 的脚本时，确保脚本：

1. 在执行 `fuyao` 前创建安全工作目录。
2. 通过 `pushd "$FUYAO_WORKDIR"` / `popd` 或子 shell 在安全目录中执行。
3. 不依赖当前目录作为仓库路径；仓库路径应显式使用绝对路径或脚本计算出的固定路径。
4. 打印实际 Fuyao 工作目录，便于排查上传范围。

示例：

```bash
REPO_ROOT="/workspace/yangxh7@xiaopeng.com/codes/3dgs"
FUYAO_WORKDIR="${FUYAO_WORKDIR:-/tmp/fuyao-submit-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$FUYAO_WORKDIR"
echo "Fuyao submit workdir: $FUYAO_WORKDIR"

(
  cd "$FUYAO_WORKDIR"
  fuyao deploy ... "cd $REPO_ROOT && python ..."
)
```

## 检查清单

执行或生成 Fuyao 命令前确认：

- 当前 shell 目录不是仓库根目录。
- 安全工作目录是新建的空目录或只含少量必要文件。
- 任务运行命令中使用 NAS 绝对路径进入 3DGS 仓库。
- 没有把整个仓库、`outputs/`、数据集或大文件复制到 Fuyao 工作目录。
