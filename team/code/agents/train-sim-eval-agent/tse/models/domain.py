from __future__ import annotations
import hashlib
import json
from pydantic import BaseModel, Field
from tse.constants import Status


class ExperimentRequest(BaseModel):
    branch: str                  # simulation 仓库分支（编包主分支，hardcode 自 constants）
    switches: dict[str, bool] = Field(default_factory=dict)
    experiment_id: str           # 由 Planner 生成（如 uuid4）
    binary_name: str | None = None   # upload_binary.py -n 名称；缺省由模板生成

    # —— 编包多仓分支（对齐 docs/xp5_simulation_build_guide.md）——
    # simulation/simworld 为两个主仓库，编包前需切到目标测试分支。
    # branch / simworld_branch 现由 constants 固定 hardcode（build_request 注入），不再由输入传入；
    # manifest_branch 缺省则用配置 build_manifest_branch（pipeline -manifest_branch）。
    simworld_branch: str | None = None
    manifest_branch: str | None = None

    # —— cloudsim rerun_e2e_job 提交参数 ——
    # 真实接口为「rerun」：基于一个既有模板 job 复跑，需提供以下 id。
    # TODO(数据来源)：stage1/stage2/model_id 与 template_e2e_job_id 如何由 build 步骤产出尚待确认，
    # 当前作为显式请求输入（由 Planner / CLI 传入），submit 时缺失会快速报错而非静默提交。
    template_e2e_job_id: int | None = None    # rerun 依赖的模板 e2e_job_id（如 163496）
    stage1_binary_id: int | None = None
    stage2_binary_id: int | None = None
    model_id: int | None = None
    job_name: str | None = None               # 缺省由模板生成
    # 闭环开关：真实接口编码为 "ns@key:val,..." 字符串（如
    # "simulation@perfect_control:1,simworld@use_difix_reference:1"）。
    # 留空则由 switches（开关简称）经 tse.switches 注册表查表展开拼装；
    # 非空则视为显式覆盖，原样下发。
    manual_sim_configuration: str = ""

    # —— 仿真平台鉴权（每次实验由 client CLI 传入，随请求下发，不再仅存台架 .env）——
    # submit / monitor / evaluate 用其经 effective_settings() 覆盖 Settings；
    # 留空则回落到 .env 配置值。注意：不参与 build_key / submit_key（凭据不改变编包/提交身份）。
    sim_x_token: str | None = None
    sim_x_account: str | None = None

    def build_key(self) -> str:
        # 编包产物由分支组合 + 清单分支 + 开关共同决定
        return _hash(self.branch, self.simworld_branch, self.manifest_branch,
                     self.switches)


class SubmitArgs(BaseModel):
    binary_id: str
    req: ExperimentRequest

    def submit_key(self) -> str:
        r = self.req
        # 提交身份由 rerun 模板 + stage/model id + 开关决定。stage1 优先取显式值，
        # 否则用编包输出 binary_id（与 submit() 的解析口径一致），保证幂等键准确。
        stage1 = r.stage1_binary_id if r.stage1_binary_id is not None else self.binary_id
        return _hash(r.template_e2e_job_id, stage1, r.stage2_binary_id,
                     r.model_id, r.manual_sim_configuration or r.switches)


class SimResult(BaseModel):
    failed: bool = False
    status: str = ""             # 平台原始终态字符串
    error: str | None = None


class EvalArtifacts(BaseModel):
    """评测产物：渲染耗时统计 CSV + FM 轨迹评测图片（由 simworld 工具产出）。

    报告即这些文件本身——不再经 LLM 摘要，直接通过飞书发送给接收人。
    - ``render_time_summary_csv`` / ``render_time_detail_csv``：``time_analyze`` 输出。
    - ``fm_eval_image``：``eval_main`` 画出的 PSNR & FM 误差对比图（核心交付物）。
    - ``fm_eval_csv``：``eval_main`` 输出的逐 clip 误差表。
    - ``files``：用于飞书发送的全部产物路径（图片在前，便于消息预览）。
    """
    output_dir: str
    render_time_summary_csv: str | None = None
    render_time_detail_csv: str | None = None
    fm_eval_image: str | None = None
    fm_eval_csv: str | None = None
    files: list[str] = Field(default_factory=list)


class EvalArgs(BaseModel):
    """评测活动入参（均为运行时值，不属于编包/提交请求）：

    - ``sim_task_id``：候选 job（待评测）的 e2e_job_id（== 本次 rerun 的 --rerun-job-id）。
    - ``candidate_job_name``：候选 job 的 job_name，用作评测产物目录/对比标签。
    - ``baseline_jobs``：基线 job（job_name -> e2e_job_id 列表），仅由 client CLI 输入。
    """
    sim_task_id: str
    candidate_job_name: str
    baseline_jobs: dict[str, list[int]] = Field(default_factory=dict)
    # 仿真平台凭据（client CLI 传入；评测下载工具用其覆盖 Settings）
    sim_x_token: str | None = None
    sim_x_account: str | None = None


class ReportArgs(BaseModel):
    req: ExperimentRequest
    artifacts: EvalArtifacts


class ExperimentResult(BaseModel):
    experiment_id: str
    status: Status
    report_url: str | None = None


def _hash(*parts) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
