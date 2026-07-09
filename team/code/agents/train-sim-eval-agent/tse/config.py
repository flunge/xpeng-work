from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TSE_", env_file=".env", extra="ignore")

    # Temporal
    temporal_target: str = "127.0.0.1:7233"
    temporal_namespace: str = "default"
    task_queue: str = "tse-experiment"

    # 存储
    db_path: str = "./tse.db"

    # 编包（对齐 docs/xp5_simulation_build_guide.md）
    # 5080 三层嵌套：worker(宿主机) → SSH 虚拟机(git checkout) → docker exec 容器(pipeline/编包)。
    build_mode: str = "nested"                # nested（5080 三层）| local（单机回退，开发/测试）
    # —— 虚拟机层（git checkout 切分支）——
    build_vm_ssh_host: str = "xpeng@192.168.122.180"   # 宿主机 SSH 进虚拟机
    build_vm_simulation_workdir: str = (
        "/mnt/vm_shared_data/workspace/data/host_xp_tools_and_sandbox/simulation/simulation")
    build_vm_simworld_workdir: str = (
        "/mnt/vm_shared_data/workspace/data/host_xp_tools_and_sandbox/simulation/simworld")
    # —— 容器层（pipeline 检出 + upload_binary 编包；容器内路径）——
    build_container: str = "xp5_simulator"    # 虚拟机内 docker exec 进入的容器名
    build_workdir: str = "/sandbox/simulation/simulation"   # 容器内 simulation 仓库路径
    # pipeline 多仓检出（manifest）：按清单补齐 simulation 分组的依赖仓库
    build_manifest_branch: str = "dev_xngp_xp5"
    build_manifest_group: str = "simulation"
    # upload_binary.py 编包固定参数（车型 / 构建区域）；按需覆盖
    # 注：upload_binary.py 不支持 --eea，故无 build_eea 配置
    build_vehicle: str = "XP5"
    build_region: str = "sh"

    # 仿真平台（cloudsim.xiaopeng.link）
    sim_base_url: str = "https://cloudsim.xiaopeng.link"
    sim_api_token: str = Field(default="", repr=False)            # 兼容 Bearer（如平台另有需要）
    sim_x_token: str = Field(default="", repr=False)              # x-token（JWT，鉴权用，仅台架持有）
    sim_x_account: str = ""                                       # x-account（账号邮箱）
    sim_query_path: str = "/simulation/pytorch_test/query_e2e_job_by_id/"  # 任务状态查询路径
    sim_submit_path: str = "/simulation/pytorch_test/rerun_e2e_job/"        # 提交（rerun）闭环仿真

    # rerun 提交的 binary id 来源：
    #   stage1_binary_id —— 每次编包（upload_binary.py）输出，运行时由 build 活动回填；
    #   stage2_binary_id —— 固定值（来自真实抓包），如需切换在此覆盖。
    sim_stage2_binary_id: int = 1692170
    # model_id —— 固定配置（不属于每次提交的可变项）；如需切换在此覆盖或由 req 显式传入。
    sim_model_id: int = 17098

    # 提交（rerun_e2e_job）随请求下发的 fuyao_config 默认值；可按真实需要覆盖
    sim_source: str = "cloudsim_e2e"
    sim_is_upload_fm_ipc: int = 0
    sim_fuyao_priority: str = "high"
    sim_fuyao_site: str = "fuyao_b1_prod2"
    sim_fuyao_partition: str = "adc-sim-mig"
    sim_fuyao_gpus_per_node: float = 0.5
    sim_fuyao_job_batch_size: int = 11
    sim_fuyao_enable_inferserver: bool = True
    sim_fuyao_enable_closeloop: bool = True
    sim_fuyao_job_timeout_seconds: int = 5999940

    # 飞书（自建应用机器人；报告直接发文件/图片，不再经 LLM 摘要）
    feishu_app_id: str = ""
    feishu_app_secret: str = Field(default="", repr=False)
    feishu_base_url: str = "https://open.feishu.cn"   # 飞书 OpenAPI 域名
    feishu_receive_id: str = ""               # 显式接收人 id（设了则优先，跳过邮箱解析）
    # 接收者 id 类型：open_id | union_id | user_id | email | chat_id
    feishu_receive_id_type: str = "open_id"
    # 接收同事邮箱：receive_id 留空时，首次运行按此邮箱解析 open_id 并缓存，后续直接读缓存
    feishu_receive_email: str = ""
    feishu_open_id_cache: str = "./.feishu_open_id_cache.json"   # open_id 缓存文件

    # —— 评测（simworld 工具）——
    # 报告 = 渲染耗时统计(.csv) + FM 轨迹评测(图片)，由 simworld 仓库 tools/ 下脚本产出：
    #   渲染耗时：log_downloader（下载日志） + time_analyze（统计 CSV）
    #   FM 评测：eval_tasks_download（下载 fm_output_comparison.json） + eval_main（评测+画图）
    # 工具复用仿真平台凭据（sim_x_token / sim_x_account）。
    simworld_repo_root: str = "/workspace"            # simworld 仓库根（含 tools/）
    eval_output_root: str = "./eval_artifacts"        # 每次实验产物输出根目录

    # 渲染耗时分析
    eval_render_log_file: str = "3dgs_server1_out.log"     # 待下载的日志文件名
    eval_render_log_glob: str = "*_3dgs_server1_out.log"   # time_analyze 匹配模式
    eval_render_max_scenarios: int = 100                   # 每个 job 最多下载的 scenario 数

    # 候选 vs 基线均由 client CLI 输入，不在服务端配置：
    #   候选 job（待评测）= 本次 rerun 的 job（--rerun-job-id == sim_task_id），
    #     其 job_name 取自请求（--job-name，缺省由 branch+实验号生成）；
    #   基线 job = `tse run --baseline job_name=job_id ...`（每次对比可不同）。
    # 渲染耗时与 FM 评测复用同一份 jobs（两脚本任务集合一致）。

    # 控制 API（agentd）
    control_listen: str = "0.0.0.0:8443"
    tls_cert: str | None = None
    tls_key: str | None = None


def get_settings() -> Settings:
    return Settings()


def effective_settings(sim_x_token: str | None = None,
                       sim_x_account: str | None = None) -> Settings:
    """返回应用了「客户端每次实验传入凭据」覆盖后的 Settings 副本。

    仿真平台凭据（x-token/x-account）现由 client CLI 随请求下发；此处用其覆盖 .env 配置：
    传入非空则优先，留空则回落到 .env 中的 sim_x_token / sim_x_account（兼容旧用法）。
    """
    update: dict = {}
    if sim_x_token:
        update["sim_x_token"] = sim_x_token
    if sim_x_account:
        update["sim_x_account"] = sim_x_account
    s = get_settings()
    return s.model_copy(update=update) if update else s
