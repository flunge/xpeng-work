# CLIP-IQA Result Evaluation

DDS CLIP-IQA Fidelity Pipeline 评测流程。

## 文件说明

- **`dds_clipiqa_fidelity_pipeline.md`**: 完整的 Fidelity 评测流程文档
- **`analyze_json_iqa_local_fidelity.py`**: Fidelity 分析主脚本
- **`download_cases_oss1.py`**: OSS 数据下载脚本
- **`deploy_cmd/`**: Fuyao 提交脚本目录
  - `download_dual_source.sh`: 双源下载提交脚本
  - `clip-iqa-local_fidelity_job.sh`: Fidelity 分析提交脚本

## 快速开始
### 前提条件

请在对话中提供 `CCES_job_id` （stage2 job id）和 `e2e_job_id` （stage1 job id） 对应的 `binary_id` 以及拉取数据所需要的adc-sim集群的GPU卡数量（默认8张），数量多速度快，但要低于case数量。

### 1. 配置环境变量

```bash
# 在 ~/.bashrc 或 ~/.zshrc 中添加
export USER_WORKSPACE="/workspace/${USER}@xiaopeng.com"
export USER_SHARED="/workspace/group_share/adc-sim/users/${USER}"
```

### 2. 运行流程

详细步骤请参考 [`dds_clipiqa_fidelity_pipeline.md`](dds_clipiqa_fidelity_pipeline.md)

```bash
# Step 1: 提交下载
cd ${USER_WORKSPACE}/simworld/models/CLIP-IQA/result_evaluation/deploy_cmd
bash download_dual_source.sh <CCES_job_id> <e2e_job_id> 8

# Step 2: 提交 Fidelity 分析
bash clip-iqa-local_fidelity_job.sh J<CCES_job_id> 8

# Step 3: 本地合并并生成结果
cd ${USER_WORKSPACE}/simworld/models/CLIP-IQA
python result_evaluation/analyze_json_iqa_local_fidelity.py \
    --merge \
    --shard_dir ${USER_SHARED}/jobid_dds/J<job_id>_clipiqa_fidelity_shards \
    --output_dir ${USER_WORKSPACE}/clip_iqa_result/dds/J<job_id>_exp1_v2full \
    --filter_mode v2_full_weights \
    --gap_mean_threshold 20.0 \
    --gap_std_threshold 15.0
```

## 输出结果

结果将保存在：`${USER_WORKSPACE}/clip_iqa_result/dds/`

## 支持

如有问题，请查阅完整文档 [`dds_clipiqa_fidelity_pipeline.md`](dds_clipiqa_fidelity_pipeline.md)
