from datetime import timedelta
from enum import Enum
from temporalio.common import RetryPolicy
from tse.switches import SWITCH_ALIASES

TASK_QUEUE = "tse-experiment"

# 编包固定分支（按当前生产固定值 hardcode，不再由 CLI / 请求输入）。
# 编包前 simulation 主仓库与 simworld 仓库分别 checkout 到以下分支：
#   simulation -> git checkout dev_xngp_xp5_zf
#   simworld   -> git checkout dev_zf_nvfixer
SIMULATION_BRANCH = "dev_xngp_xp5_zf"
SIMWORLD_BRANCH = "dev_zf_nvfixer"

# 开关白名单：请求构建时只允许这些键，防止注入与拼写错误。
# 由开关注册表（tse/switches.py）派生，新增开关只需改注册表一处。
SWITCH_WHITELIST = frozenset(SWITCH_ALIASES)


class Status(str, Enum):
    CREATED = "CREATED"
    BUILDING = "BUILDING"
    BUILD_SUCCESS = "BUILD_SUCCESS"
    BUILD_FAILED = "BUILD_FAILED"
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    EVALUATING = "EVALUATING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"

    @property
    def is_terminal(self) -> bool:
        return self in {Status.COMPLETED, Status.BUILD_FAILED, Status.SIMULATION_FAILED}


# 各阶段重试策略（不可重试错误用 ApplicationError(non_retryable=True) 区分，见 errors.py）
BUILD_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5), backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=2), maximum_attempts=3,
)
SUBMIT_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=5), backoff_coefficient=2.0, maximum_attempts=3,
)
# 监视：Activity 自身长时运行，崩溃后靠 heartbeat 超时续起，故 attempts 放大
MONITOR_RETRY = RetryPolicy(
    initial_interval=timedelta(seconds=10), backoff_coefficient=2.0,
    maximum_interval=timedelta(minutes=1), maximum_attempts=100,
)
EVAL_RETRY = RetryPolicy(maximum_attempts=3)
REPORT_RETRY = RetryPolicy(maximum_attempts=3)
INFRA_RETRY = RetryPolicy(maximum_attempts=5)   # mirror_status 等基础设施
