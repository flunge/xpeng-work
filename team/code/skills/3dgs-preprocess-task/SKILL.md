---
name: 3dgs-preprocess-task
description: Summarizes how to submit, parse, track, and report 3DGS preprocess tasks in this repository. Use when the user asks to提预处理任务, 启动预处理, deploy preprocess, run xpeng_data_process, monitor Fuyao preprocess jobs, or wire preprocess commands into agents.
---

# 3DGS 预处理任务

## 目标

本 skill 用于在 3DGS 仓库中提交和跟踪预处理任务。当前预处理链路的核心是：

1. 基于配置文件准备 `xpeng_data_process` 的输入。
2. 通过 Fuyao 部署脚本提交 A100 集群任务。
3. 在任务中执行 `python xpeng_data_process/main.py --config <config_file>`。
4. 通过 Fuyao 命令查看任务状态。
5. 将任务状态/产物同步回飞书 Agent 的任务台账。

## 关键文件

- 部署脚本：`pipeline/fuyao/deploy_preproc.bash`
- 默认配置：`xpeng_data_process/configs/config_vision.yaml`
- 预处理入口：`xpeng_data_process/main.py`
- Feishu Agent 执行器：`agents/app/executors/preprocess.py`
- 命令解析：`agents/app/application/command_parser.py`
- 仓库命令目录：`agents/app/infrastructure/repo_catalog.py`
- 状态机：`agents/app/domain/state_machine.py`

## 部署脚本行为

`pipeline/fuyao/deploy_preproc.bash` 接收两个参数：

```bash
bash pipeline/fuyao/deploy_preproc.bash <config_file> <job_name>
```

脚本内部会执行：

```bash
fuyao deploy --gpu-type=A100 --volume=adc-sim --queue=adc-sim --release \
  --site fuyao_b1_prod2 \
  --job-name <job_name> \
  --label <job_name> \
  --docker-image infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:dusc-260426-1918 \
  --project="adc-sim" \
  --experiment "sim3dgs-sim" \
  --gpus-per-node=1 \
  --nodes=1 \
  "export LD_LIBRARY_PATH=...; cd /workspace/yangxh7@xiaopeng.com/codes/3dgs/; python xpeng_data_process/main.py --config <config_file>"
```

固定资源/平台信息：

- site：`fuyao_b1_prod2`
- queue：`adc-sim`
- volume：`adc-sim`
- project：`adc-sim`
- experiment：`sim3dgs-sim`
- gpu：`A100`
- gpus-per-node：`1`
- nodes：`1`
- docker image：`infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:dusc-260426-1918`

## 默认配置文件

默认配置：`xpeng_data_process/configs/config_vision.yaml`

当前默认配置的关键信息：

- `dataset_name: vision_dataset_1021`
- `root: /workspace/yangxh7@xiaopeng.com/datasets/xpeng/agent`
- `clip_id: c-93d52601-92a8-3c57-b56d-50ea05b2c9d2`
- `source: vision`
- `pipeline/ucp: True`
- `use_raw_localpose: True`

默认打开的处理步骤包括：

- `json_processor`
- `img_processor`
- `opt_processor`
- `sam3d_processor`
- `pose_processor`
- `mvsnet_processor`
- `ground_processor`
- `pcd_fusion_processor`
- `point_processor`
- `depth_processor`
- `evosplat_processor`
- `trafficlight_processor`

默认关闭：

- `vision_data_fetcher`
- `colmap_processor`
- `point_densifier`

注意：如果用户只给 `clip_id`，不能只靠命令行参数改变当前 YAML；需要先复制/生成临时 config，把 `datasets[0].clip_id` 改成目标 clip，再提交脚本。当前 `agents` 的 `PreprocessExecutor` 仍主要生成执行计划，后续应升级为真实生成临时配置并调用部署脚本。

## 飞书命令格式

飞书中推荐使用：

```text
@Agent 启动预处理 clip_id=<clip_id> config=xpeng_data_process/configs/config_vision.yaml job_name=<job_name>
```

或：

```text
@Agent 启动 preprocess clip_id=<clip_id> config=xpeng_data_process/configs/config_vision.yaml job_name=<job_name>
```

`CommandParser` 当前识别：

- 包含 `启动 preprocess`
- 或包含 `启动预处理`

并解析 `key=value` 参数。

参数建议：

- `clip_id`：必填，目标 clip。
- `config` / `config_path`：可选，默认 `xpeng_data_process/configs/config_vision.yaml`。
- `job_name`：可选，默认可用 `preprocess_<task_id>`。

示例：

```text
@Agent 启动预处理 clip_id=c-93d52601-92a8-3c57-b56d-50ea05b2c9d2 config=xpeng_data_process/configs/config_vision.yaml job_name=preprocess_test_001
```

## Feishu Agent 当前实现

`agents/app/executors/preprocess.py` 当前逻辑：

- 读取 `config` 或 `config_path`，否则用默认配置。
- 读取 `clip_id`，否则 `unknown_clip`。
- 读取 `job_name`，否则 `preprocess_<task_id>`。
- 生成 command preview：

```text
bash pipeline/fuyao/deploy_preproc.bash <config_file> <job_name> -> clip_id=..., config=..., job_name=...
```

- 调用 `bash pipeline/fuyao/deploy_preproc.bash <generated_config> <job_name>` 提交 Fuyao 任务。
- 返回 `ExecutionResult(status=PREPROCESSING, current_stage="preprocessing")` 或失败信息。

注意：executor 已支持真实 Fuyao 提交；若 returncode 非 0，任务状态为 `failed`。

## Fuyao 状态查询

已验证可以用 Fuyao CLI 监控预处理任务。常用命令：

```bash
fuyao view --site fuyao_b1_prod2 --only-me
fuyao history --site fuyao_b1_prod2 --limit 20
fuyao view --help
fuyao history --help
```

早期尝试过：

```bash
fuyao info -n "$(basename /workspace/yangxh7@xiaopeng.com/codes/3dgs)" -s fuyao_b1_prod2
```

但实际排查最近任务时，更常用 `fuyao view --site fuyao_b1_prod2 --only-me` 和 `fuyao history --site fuyao_b1_prod2 --limit 20`。

状态查询建议：

1. 优先用 `job_name` 或 label 过滤。
2. 如果没有过滤参数，查询最近任务列表并匹配 `job_name`。
3. 将 Fuyao 状态映射到 Agent 状态：
   - pending/running -> `preprocessing`
   - success/done/completed -> `dataset_ready` 或 `done`
   - failed/error -> `failed`
   - cancelled/killed -> `cancelled`
4. 查询结果同步到飞书回复和 Wiki 表格。

## 任务状态

预处理任务类型：`TaskType.PIPELINE_PREPROCESS = "pipeline.preprocess"`

状态机初始运行态：

```text
created -> queued -> preprocessing
```

理想完整状态：

```text
created -> queued -> preprocessing -> dataset_ready -> done
```

失败或取消：

```text
preprocessing -> failed
preprocessing -> cancelled
```

当前 MVP 可能直接把执行计划标记为 `done`，但真实集群任务接入后应拆分：

- 提交成功：任务状态保持 `preprocessing`。
- Fuyao 成功：转 `dataset_ready` 或 `done`。
- Fuyao 失败：转 `failed` 并附日志。

## 飞书同步内容

提交预处理任务后，飞书回复建议包含：

```text
[TASK-xxxxxx] preprocessing
状态: preprocessing
阶段: preprocessing
摘要: 已提交预处理任务
clip_id: <clip_id>
config: <config_path>
job_name: <job_name>
fuyao_site: fuyao_b1_prod2
文档: <doc_url>
```

Wiki 表格结构化字段至少写：

- `Task ID`
- `任务类型` = `pipeline.preprocess`
- `状态`
- `阶段`
- `请求人`
- `摘要`
- `文档链接`
- `文本`

后续建议给 Wiki 表新增字段：

- `clip_id`
- `job_name`
- `fuyao_site`
- `config_path`
- `output_root`

## 安全与确认

真实提交预处理任务前，若用户信息不足，应追问：

- 目标 `clip_id` 是什么？
- 是否使用默认配置 `xpeng_data_process/configs/config_vision.yaml`？
- 是否需要修改输出 root 或步骤开关？
- 是否确认提交到 `fuyao_b1_prod2` 的 A100 队列？

如果用户明确说“直接提”“帮我提交”“启动预处理”，且提供了 `clip_id`，可按默认配置提交。

## 常见问题

- 只传 `clip_id` 不会自动改 YAML：需要生成临时 config，否则脚本仍使用配置文件里的默认 clip。
- `fuyao deploy` 成功但 Agent 无 job id：用 `job_name` 和 `fuyao history/view` 反查。
- 默认配置关闭了 `vision_data_fetcher`：如果目标数据未准备好，可能需要开启数据拉取或先单独准备数据。
- 默认配置关闭了 `colmap_processor` 和 `point_densifier`：不要误以为所有点云/稠密化步骤都会执行。
- 不要修改 `xpeng_data_process/configs/config_vision.yaml` 作为单次任务配置；应复制生成任务专属配置。

## 后续增强建议

- 在 `PreprocessExecutor` 中实现真实 Fuyao 提交。
- 增加 `GeneratedConfigService`，负责复制和 patch YAML。
- 增加 `FuyaoClient`，封装 deploy/view/history/status。
- 将 Fuyao job id、job_name、site 写入 `TaskRun.params` 或单独字段。
- 增加后台轮询器，定期刷新预处理任务状态。
- 将预处理完成后的 dataset root、timing、关键产物写入报告文档。
