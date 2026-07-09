# 训练仿真评测闭环 Agent —— 代码开发文档

> ⚠️ **实现现状更新（v1.1）**：评测/报告已改为无 LLM。
> `EvaluateActivity` 调 `integrations/simworld_tools.py` 跑 simworld `tools/` 脚本，
> 返回 `EvalArtifacts`（渲染耗时 CSV + FM 轨迹评测图片路径）；
> `ReportActivity` 经 `integrations/feishu.py` 把这些文件直接发飞书，无 `LLMClient`、无 `Metrics`。
> 配置见 `tse/config.py` 的 `eval_*` / `feishu_receive_id_type` 与 `.env.example`。
> 下文涉及 `LLMClient/Metrics/summarize_report` 的章节为早期骨架，最新以代码为准。
>
> 版本：v1.0 ｜ 日期：2026-06-15 ｜ 状态：开发指南
>
> 本文档是 [architecture-design.md](architecture-design.md) 的工程落地版，面向实现工程师，给出**逐模块的代码骨架、数据结构、函数签名、实现要点与任务分解**。架构层面的"为什么"见架构文档；本文聚焦"怎么写"。
>
> 文中代码为**实现骨架**：核心控制流可直接使用，标 `TODO` 处需按真实外部系统（仿真平台 API、飞书、LLM、台架脚本输出格式）补全。

---

## 目录

1. [开发约定与阅读指引](#1-开发约定与阅读指引)
2. [技术栈与依赖](#2-技术栈与依赖)
3. [工程目录与模块清单](#3-工程目录与模块清单)
4. [配置与环境变量](#4-配置与环境变量)
5. [公共类型与数据模型（models/）](#5-公共类型与数据模型models)
6. [持久化层（store/）](#6-持久化层store)
7. [外部集成（integrations/）](#7-外部集成integrations)
8. [Activities（activities/）](#8-activitiesactivities)
9. [工作流（workflows/）](#9-工作流workflows)
10. [Worker 注册（worker.py）](#10-worker-注册workerpy)
11. [Planner（planner/）](#11-plannerplanner)
12. [控制面：agentd 与 CLI（server/、cli/）](#12-控制面agentd-与-cliservercli)
13. [错误分类与重试策略](#13-错误分类与重试策略)
14. [安全实现要点](#14-安全实现要点)
15. [测试策略](#15-测试策略)
16. [本地启动与冒烟验证](#16-本地启动与冒烟验证)
17. [编码规范](#17-编码规范)
18. [任务分解（映射里程碑）](#18-任务分解映射里程碑)

---

## 1. 开发约定与阅读指引

### 1.1 三层心智模型（务必牢记）

| 层 | 代码位置 | 能否有副作用 | 关键约束 |
| --- | --- | --- | --- |
| **Workflow** | `workflows/experiment.py` | **否**（必须确定性） | 不得直接调 IO / `datetime.now()` / 随机数 / 直接读写 DB；一切副作用走 Activity |
| **Activity** | `activities/*.py` | 是 | 封装编包、HTTP、DB、LLM、飞书等所有 IO；可重试，须尽量幂等 |
| **Planner / Server / CLI** | `planner/`、`server/`、`cli/` | 是 | 普通应用代码；LLM 仅在 Planner 与 ReportActivity 出现 |

> ⚠️ **最易踩的坑**：架构文档 §5.3 伪代码里的 `self._set_status(...)` 写 DB 是副作用，**不能**在 workflow 里直接执行。本文档将其实现为调用 `mirror_status` Activity（见 [§9.2](#92-状态镜像作为-activity)）。

### 1.2 命名与契约对齐架构文档

- **10 个状态**：`CREATED, BUILDING, BUILD_SUCCESS, BUILD_FAILED, SUBMITTED, RUNNING, SIMULATION_FAILED, EVALUATING, REPORTING, COMPLETED`。
- **5 个业务 Activity**：`build_binary / submit_simulation / monitor_wait / evaluate / generate_and_send_report`，外加 1 个基础设施 Activity `mirror_status`。
- **幂等键**：`build_key = hash(branch+ckpt+switches)`、`submit_key = hash(binary_id+ckpt+switches)`、报告以 `experiment_id` 去重。

---

## 2. 技术栈与依赖

| 类别 | 选型 | 包 |
| --- | --- | --- |
| 语言 | Python 3.10+ | — |
| 工作流 | Temporal | `temporalio>=1.7` |
| 数据校验/序列化 | Pydantic v2 | `pydantic>=2.6` |
| CLI | Typer | `typer>=0.12` |
| 控制 API（服务端） | FastAPI + Uvicorn | `fastapi`, `uvicorn[standard]` |
| 控制 API（客户端） | httpx | `httpx>=0.27` |
| 飞书 | 飞书开放平台 SDK | `lark-oapi` |
| LLM | 直接 SDK（按供应方） | `openai`（占位，按 Q1 替换） |
| SSH（可选编包模式） | Fabric/Paramiko | `fabric`（可选） |
| 测试 | pytest + Temporal 测试环境 | `pytest`, `pytest-asyncio` |

### 2.1 `pyproject.toml`

```toml
[project]
name = "train-sim-eval-agent"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "temporalio>=1.7",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "typer>=0.12",
    "fastapi>=0.110",
    "uvicorn[standard]>=0.29",
    "httpx>=0.27",
    "lark-oapi>=1.2",
    "openai>=1.30",          # 占位：按实际 LLM 供应方替换
]

[project.optional-dependencies]
ssh = ["fabric>=3.2"]
dev = ["pytest>=8", "pytest-asyncio>=0.23", "ruff>=0.4", "mypy>=1.10"]

[project.scripts]
tse = "tse.cli.main:app"               # 远程瘦客户端入口
tse-agentd = "tse.server.agentd:main"  # 台架常驻入口

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

> **Temporal + Pydantic**：Worker 与 Client 必须使用 Pydantic data converter，才能让 Activity/Workflow 直接收发 Pydantic 模型。见 [§10](#10-worker-注册workerpy)。

---

## 3. 工程目录与模块清单

与架构文档 §12.2 一致，逐文件职责如下：

```
train-sim-eval-agent/
├── docs/
│   ├── architecture-design.md
│   └── development-guide.md          # 本文档
├── tse/
│   ├── __init__.py
│   ├── config.py                     # Settings（pydantic-settings），读环境变量
│   ├── constants.py                  # 状态枚举、重试策略、任务队列名、开关白名单
│   ├── errors.py                     # 统一错误类型与可重试/不可重试分类
│   ├── models/
│   │   ├── __init__.py
│   │   ├── domain.py                 # ExperimentRequest/Result、SubmitArgs、ReportArgs、SimResult、Metrics
│   │   └── db.py                     # experiment 表 DDL 与行模型
│   ├── store/
│   │   ├── __init__.py
│   │   └── repo.py                   # SQLite 读写（ExperimentRepo），WAL、幂等查询
│   ├── integrations/
│   │   ├── __init__.py
│   │   ├── bench.py                  # BuildExecutor（local/ssh）+ upload_binary.py 封装与输出解析
│   │   ├── sim_cloud.py              # SimCloudClient：submit / query_status / fetch_metrics
│   │   ├── feishu.py                 # FeishuClient：send_report（幂等）
│   │   └── llm.py                    # LLMClient：parse_intent / summarize_report
│   ├── activities/
│   │   ├── __init__.py
│   │   ├── infra.py                  # mirror_status（状态镜像写 DB）
│   │   ├── build.py                  # build_binary
│   │   ├── submit.py                 # submit_simulation
│   │   ├── monitor.py               # monitor_wait（核心，轮询 + heartbeat）
│   │   ├── evaluate.py               # evaluate
│   │   └── report.py                 # generate_and_send_report
│   ├── workflows/
│   │   ├── __init__.py
│   │   └── experiment.py             # ExperimentWorkflow
│   ├── planner/
│   │   ├── __init__.py
│   │   └── planner.py                # Planner：parse → validate → start workflow
│   ├── server/
│   │   ├── __init__.py
│   │   ├── agentd.py                 # 进程入口：拉起 control_api + Worker
│   │   ├── control_api.py            # FastAPI 路由（Plan/Run/Status/List/Watch/Resume/Cancel）
│   │   └── auth.py                   # 鉴权令牌校验
│   ├── cli/
│   │   ├── __init__.py
│   │   ├── main.py                   # Typer 命令，调用控制 API
│   │   └── client.py                 # 控制 API HTTP 客户端
│   └── worker.py                     # build_worker()：注册 workflow + activities
├── tests/
│   ├── test_models.py
│   ├── test_repo.py
│   ├── test_activities.py
│   └── test_workflow_replay.py
├── pyproject.toml
└── README.md
```

---

## 4. 配置与环境变量

`tse/config.py` —— 所有外部凭据/地址集中读取，**凭据只存台架，不入库不写日志**。

```python
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

    # 编包
    build_mode: str = "local"                 # local | ssh
    build_workdir: str = "/sandbox/simulation/simulation"
    build_ssh_host: str | None = None         # build_mode=ssh 时必填

    # 仿真平台
    sim_base_url: str = ""
    sim_api_token: str = Field(default="", repr=False)

    # 飞书
    feishu_app_id: str = ""
    feishu_app_secret: str = Field(default="", repr=False)
    feishu_receive_id: str = ""               # 报告默认接收者/群

    # LLM
    llm_api_key: str = Field(default="", repr=False)
    llm_model: str = "gpt-4o-mini"            # 占位，按 Q1 替换

    # 控制 API（agentd）
    control_listen: str = "0.0.0.0:8443"
    control_token: str = Field(default="", repr=False)   # 鉴权令牌
    tls_cert: str | None = None
    tls_key: str | None = None


def get_settings() -> Settings:
    return Settings()
```

> `Field(repr=False)` 防止凭据被打印进日志。CLI 侧仅需 `TSE_CONTROL_TOKEN` 与 endpoint，不接触上述业务凭据。

---

## 5. 公共类型与数据模型（models/）

### 5.1 `tse/constants.py`

```python
from datetime import timedelta
from enum import Enum
from temporalio.common import RetryPolicy

TASK_QUEUE = "tse-experiment"

# 开关白名单：Planner 解析结果只允许这些键，防止注入与拼写错误
SWITCH_WHITELIST = {"use_difix", "use_nvfixer", "enable_simworld"}  # TODO: 按真实开关补全


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
```

### 5.2 `tse/models/domain.py`

工作流/Activity 之间传递的数据，统一用 Pydantic（配合 §10 的 pydantic data converter）。

```python
from __future__ import annotations
import hashlib
import json
from pydantic import BaseModel, Field
from tse.constants import Status


class ExperimentRequest(BaseModel):
    branch: str
    ckpt_path: str
    switches: dict[str, bool] = Field(default_factory=dict)
    experiment_id: str           # 由 Planner 生成（如 uuid4）
    binary_name: str | None = None   # upload_binary.py -n 名称；缺省由模板生成

    def build_key(self) -> str:
        return _hash(self.branch, self.ckpt_path, self.switches)


class SubmitArgs(BaseModel):
    binary_id: str
    req: ExperimentRequest

    def submit_key(self) -> str:
        return _hash(self.binary_id, self.req.ckpt_path, self.req.switches)


class SimResult(BaseModel):
    failed: bool = False
    status: str = ""             # 平台原始终态字符串
    error: str | None = None


class Metrics(BaseModel):
    # 统一指标结构：标量 + 命名表格/曲线（按真实评测产物细化）
    scalars: dict[str, float] = Field(default_factory=dict)
    tables: dict[str, list[dict]] = Field(default_factory=dict)
    raw_artifact_uri: str | None = None


class ReportArgs(BaseModel):
    req: ExperimentRequest
    metrics: Metrics


class ExperimentResult(BaseModel):
    experiment_id: str
    status: Status
    report_url: str | None = None


def _hash(*parts) -> str:
    payload = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]
```

### 5.3 `tse/models/db.py`

```python
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS experiment (
    id                   TEXT PRIMARY KEY,
    branch               TEXT NOT NULL,
    ckpt_path            TEXT NOT NULL,
    switches             TEXT NOT NULL,          -- JSON
    binary_id            TEXT,
    sim_task_id          TEXT,
    status               TEXT NOT NULL,
    report_url           TEXT,
    error                TEXT,
    temporal_workflow_id TEXT,
    build_key            TEXT,
    submit_key           TEXT,
    feishu_msg_id        TEXT,
    retry_count          TEXT,                   -- JSON
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_experiment_status ON experiment(status);
CREATE INDEX IF NOT EXISTS idx_experiment_build_key ON experiment(build_key);
CREATE INDEX IF NOT EXISTS idx_experiment_submit_key ON experiment(submit_key);
"""
```

---

## 6. 持久化层（store/）

`tse/store/repo.py` —— SQLite 读模型与幂等查询。**只被 Activity / agentd 调用，绝不被 workflow 直接调用。**

```python
import json
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from tse.constants import Status
from tse.models.db import CREATE_TABLE_SQL


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ExperimentRepo:
    def __init__(self, db_path: str):
        self.db_path = db_path
        with self._conn() as c:
            c.executescript(CREATE_TABLE_SQL)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # —— 写：状态镜像（被 mirror_status Activity 调用）——
    def upsert_status(self, experiment_id: str, status: Status, **fields) -> None:
        cols = {"status": status.value, "updated_at": _now()}
        for k in ("branch", "ckpt_path", "binary_id", "sim_task_id", "report_url",
                  "error", "temporal_workflow_id", "build_key", "submit_key", "feishu_msg_id"):
            if k in fields and fields[k] is not None:
                cols[k] = fields[k]
        if "switches" in fields:
            cols["switches"] = json.dumps(fields["switches"])

        with self._conn() as c:
            exists = c.execute("SELECT 1 FROM experiment WHERE id=?", (experiment_id,)).fetchone()
            if exists:
                sets = ", ".join(f"{k}=?" for k in cols)
                c.execute(f"UPDATE experiment SET {sets} WHERE id=?",
                          (*cols.values(), experiment_id))
            else:
                cols.setdefault("switches", json.dumps(fields.get("switches", {})))
                cols["id"] = experiment_id
                cols["created_at"] = _now()
                keys = ", ".join(cols)
                ph = ", ".join("?" for _ in cols)
                c.execute(f"INSERT INTO experiment ({keys}) VALUES ({ph})", tuple(cols.values()))

    # —— 读：CLI/agentd 查询 ——
    def get(self, experiment_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM experiment WHERE id=?", (experiment_id,)).fetchone()
            return dict(row) if row else None

    def list(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM experiment ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]

    # —— 幂等查询 ——
    def find_binary_by_build_key(self, build_key: str) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT binary_id FROM experiment WHERE build_key=? AND binary_id IS NOT NULL "
                "ORDER BY updated_at DESC LIMIT 1", (build_key,)).fetchone()
            return row["binary_id"] if row else None

    def find_task_by_submit_key(self, submit_key: str) -> str | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT sim_task_id FROM experiment WHERE submit_key=? AND sim_task_id IS NOT NULL "
                "ORDER BY updated_at DESC LIMIT 1", (submit_key,)).fetchone()
            return row["sim_task_id"] if row else None
```

---

## 7. 外部集成（integrations/）

> 这些类封装真实外部系统，是 `TODO` 最集中处。Activity 通过它们完成 IO，便于在测试中 mock。

### 7.1 `tse/integrations/bench.py` —— 编包执行器

```python
import re
import shlex
import subprocess
from typing import Protocol
from tse.config import Settings
from tse.errors import NonRetryableBuildError

# upload_binary.py 输出里 binary id 的解析正则（按真实输出校准）
_BINARY_ID_RE = re.compile(r"binary[_ ]id[:=]\s*([A-Za-z0-9_\-]+)", re.IGNORECASE)
_BRANCH_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")   # 分支名白名单，防命令注入


class BuildExecutor(Protocol):
    def run(self, cmd: list[str], cwd: str) -> str: ...


class LocalExecutor:
    def run(self, cmd: list[str], cwd: str) -> str:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=3600)
        if proc.returncode != 0:
            raise RuntimeError(f"build failed rc={proc.returncode}: {proc.stderr[-2000:]}")
        return proc.stdout


class SSHExecutor:
    def __init__(self, host: str):
        self.host = host

    def run(self, cmd: list[str], cwd: str) -> str:
        from fabric import Connection  # 延迟导入（可选依赖）
        joined = " ".join(shlex.quote(p) for p in cmd)
        result = Connection(self.host).run(f"cd {shlex.quote(cwd)} && {joined}", hide=True)
        return result.stdout


def make_executor(s: Settings) -> BuildExecutor:
    if s.build_mode == "ssh":
        assert s.build_ssh_host, "TSE_BUILD_SSH_HOST required for ssh mode"
        return SSHExecutor(s.build_ssh_host)
    return LocalExecutor()


def build_command(branch: str, name: str) -> list[str]:
    if not _BRANCH_RE.match(branch):
        raise NonRetryableBuildError(f"illegal branch name: {branch!r}")
    # 参考命令（架构文档 §6.2）：以 list 形式避免 shell 注入
    return [
        "./scripts/upload_binary.py", "--cn", "--foundation_model", "--enable_simworld",
        "-v", "XP5", "-f", "--build_region", "sh", "-n", name,
    ]


def parse_binary_id(stdout: str) -> str:
    m = _BINARY_ID_RE.search(stdout)
    if not m:
        raise RuntimeError("cannot parse binary_id from upload_binary.py output")
    return m.group(1)
```

> **多仓切分支**：架构文档指出需在 `simulation` 与 `simworld` 两仓切分支。若 `upload_binary.py` 不负责切分支，则在 `build_binary` Activity 内先执行 pipeline 切分支命令（同样用 list + 白名单），再编包。

### 7.2 `tse/integrations/sim_cloud.py` —— 仿真平台

```python
import httpx
from tse.config import Settings
from tse.models.domain import Metrics

TERMINAL_OK = {"COMPLETED", "SUCCESS"}        # TODO: 对齐平台真实终态
TERMINAL_FAIL = {"FAILED", "ERROR", "KILLED"}  # TODO


class SimCloudClient:
    def __init__(self, s: Settings):
        self._c = httpx.Client(base_url=s.sim_base_url,
                               headers={"Authorization": f"Bearer {s.sim_api_token}"},
                               timeout=30)

    def submit(self, binary_id: str, ckpt_path: str, switches: dict) -> str:
        # TODO: 对齐真实 submit 接口；返回 sim_task_id
        r = self._c.post("/api/sim/submit",
                         json={"binary_id": binary_id, "ckpt": ckpt_path, "switches": switches})
        r.raise_for_status()
        return r.json()["task_id"]

    def query_status(self, sim_task_id: str) -> str:
        # 返回平台原始状态字符串（RUNNING/COMPLETED/FAILED/...）
        r = self._c.get(f"/api/sim/tasks/{sim_task_id}")
        r.raise_for_status()
        return r.json()["status"]

    def fetch_metrics(self, sim_task_id: str) -> Metrics:
        # TODO: 从平台 API / OSS / 路径拉取评测产物并解析
        r = self._c.get(f"/api/sim/tasks/{sim_task_id}/metrics")
        r.raise_for_status()
        data = r.json()
        return Metrics(scalars=data.get("scalars", {}),
                       tables=data.get("tables", {}),
                       raw_artifact_uri=data.get("artifact_uri"))
```

### 7.3 `tse/integrations/feishu.py` 与 `llm.py`

```python
# feishu.py
from tse.config import Settings


class FeishuClient:
    def __init__(self, s: Settings):
        self.app_id, self.app_secret = s.feishu_app_id, s.feishu_app_secret
        self.receive_id = s.feishu_receive_id
        # TODO: lark_oapi.Client.builder()...build()

    def send_report(self, title: str, markdown: str, idem_key: str) -> tuple[str, str]:
        """返回 (message_id, report_url)。idem_key=experiment_id 用于去重。"""
        # TODO: 用 lark-oapi 发送富文本/文档卡片；若需严格幂等，可先按 idem_key 查历史
        ...
        return "msg_xxx", "https://feishu/doc/xxx"
```

```python
# llm.py
from tse.config import Settings
from tse.models.domain import Metrics


class LLMClient:
    def __init__(self, s: Settings):
        self.model = s.llm_model
        # TODO: 初始化真实 LLM SDK（按 Q1 选型）

    def parse_intent(self, raw_text: str) -> dict:
        """自然语言 → {branch, ckpt_path, switches}。返回结构必须再经 Planner 白名单校验。"""
        # TODO: 提示词 + 结构化输出（function calling / JSON mode）
        ...

    def summarize_report(self, metrics: Metrics) -> str:
        """指标 → Markdown 摘要。"""
        # TODO
        ...
```

---

## 8. Activities（activities/）

每个 Activity 都是普通 `async def`，用 `@activity.defn` 注册。**Activity 内自行构造集成客户端**（或从 worker 注入），保持工作流确定性。

### 8.1 `tse/activities/infra.py` —— 状态镜像

```python
from temporalio import activity
from tse.config import get_settings
from tse.constants import Status
from tse.store.repo import ExperimentRepo


@activity.defn
async def mirror_status(experiment_id: str, status: str, fields: dict) -> None:
    repo = ExperimentRepo(get_settings().db_path)
    repo.upsert_status(experiment_id, Status(status), **fields)
```

### 8.2 `tse/activities/build.py`

```python
from temporalio import activity
from tse.config import get_settings
from tse.integrations.bench import make_executor, build_command, parse_binary_id
from tse.models.domain import ExperimentRequest
from tse.store.repo import ExperimentRepo


@activity.defn
async def build_binary(req: ExperimentRequest) -> str:
    s = get_settings()
    repo = ExperimentRepo(s.db_path)

    # 幂等：命中已有 binary 直接复用，杜绝重复编包（高代价）
    cached = repo.find_binary_by_build_key(req.build_key())
    if cached:
        activity.logger.info("reuse cached binary %s", cached)
        return cached

    name = req.binary_name or f"{req.branch}_{req.experiment_id[:8]}"
    cmd = build_command(req.branch, name)               # 内含分支名白名单校验
    stdout = make_executor(s).run(cmd, cwd=s.build_workdir)
    return parse_binary_id(stdout)
```

### 8.3 `tse/activities/submit.py`

```python
from temporalio import activity
from tse.config import get_settings
from tse.integrations.sim_cloud import SimCloudClient
from tse.models.domain import SubmitArgs
from tse.store.repo import ExperimentRepo


@activity.defn
async def submit_simulation(args: SubmitArgs) -> str:
    s = get_settings()
    repo = ExperimentRepo(s.db_path)

    cached = repo.find_task_by_submit_key(args.submit_key())
    if cached:
        return cached

    return SimCloudClient(s).submit(
        binary_id=args.binary_id, ckpt_path=args.req.ckpt_path, switches=args.req.switches
    )
```

### 8.4 `tse/activities/monitor.py` —— 核心：纯轮询 + heartbeat

```python
import asyncio
from temporalio import activity
from tse.config import get_settings
from tse.integrations.sim_cloud import SimCloudClient, TERMINAL_OK, TERMINAL_FAIL
from tse.models.domain import SimResult

# 自适应轮询间隔（秒）：前期密，后期退避，降低平台压力
_INTERVALS = [30, 30, 60, 60, 120, 300]


@activity.defn
async def monitor_wait(sim_task_id: str) -> SimResult:
    """在 Worker 进程内纯 API 轮询，仅终态返回。等待期间不触碰 LLM、不返回中间态。"""
    client = SimCloudClient(get_settings())
    i = 0
    while True:
        status = client.query_status(sim_task_id)
        activity.heartbeat({"sim_task_id": sim_task_id, "status": status})  # 心跳：崩溃后可续起
        if status in TERMINAL_OK:
            return SimResult(failed=False, status=status)
        if status in TERMINAL_FAIL:
            return SimResult(failed=True, status=status, error=f"sim terminal: {status}")
        await asyncio.sleep(_INTERVALS[min(i, len(_INTERVALS) - 1)])
        i += 1
```

> **崩溃续起**：Worker 挂掉后，Temporal 依 `heartbeat_timeout` 重试本 Activity；新一轮从 `query_status` 重新读取云端真实状态即可（仿真任务在云端持续运行），无需本地保存进度。

### 8.5 `tse/activities/evaluate.py` 与 `report.py`

```python
# evaluate.py
from temporalio import activity
from tse.config import get_settings
from tse.integrations.sim_cloud import SimCloudClient
from tse.models.domain import Metrics


@activity.defn
async def evaluate(sim_task_id: str) -> Metrics:
    return SimCloudClient(get_settings()).fetch_metrics(sim_task_id)
```

```python
# report.py
from temporalio import activity
from tse.config import get_settings
from tse.integrations.feishu import FeishuClient
from tse.integrations.llm import LLMClient
from tse.models.domain import ReportArgs
from tse.store.repo import ExperimentRepo


@activity.defn
async def generate_and_send_report(args: ReportArgs) -> str:
    s = get_settings()
    repo = ExperimentRepo(s.db_path)

    # 幂等：已发送过则直接返回旧链接（experiment_id 去重）
    existing = repo.get(args.req.experiment_id)
    if existing and existing.get("report_url") and existing.get("feishu_msg_id"):
        return existing["report_url"]

    summary = LLMClient(s).summarize_report(args.metrics)   # LLM 仅此处 + Planner
    title = f"[仿真评测] {args.req.branch}"
    msg_id, url = FeishuClient(s).send_report(title, summary, idem_key=args.req.experiment_id)
    repo.upsert_status(args.req.experiment_id, status=_keep_current(existing),
                       report_url=url, feishu_msg_id=msg_id)
    return url


def _keep_current(existing: dict | None):
    from tse.constants import Status
    return Status(existing["status"]) if existing else Status.REPORTING
```

---

## 9. 工作流（workflows/）

### 9.1 `tse/workflows/experiment.py`

```python
from datetime import timedelta
from temporalio import workflow
from temporalio.exceptions import ApplicationError

with workflow.unsafe.imports_passed_through():
    from tse.constants import (Status, BUILD_RETRY, SUBMIT_RETRY, MONITOR_RETRY,
                               EVAL_RETRY, REPORT_RETRY, INFRA_RETRY)
    from tse.models.domain import (ExperimentRequest, ExperimentResult, SubmitArgs,
                                   ReportArgs, SimResult, Metrics)
    from tse.activities.infra import mirror_status
    from tse.activities.build import build_binary
    from tse.activities.submit import submit_simulation
    from tse.activities.monitor import monitor_wait
    from tse.activities.evaluate import evaluate
    from tse.activities.report import generate_and_send_report


@workflow.defn
class ExperimentWorkflow:
    @workflow.run
    async def run(self, req: ExperimentRequest) -> ExperimentResult:
        await self._set_status(req, Status.CREATED, branch=req.branch,
                               ckpt_path=req.ckpt_path, switches=req.switches,
                               temporal_workflow_id=workflow.info().workflow_id)

        # 1) 编包
        await self._set_status(req, Status.BUILDING, build_key=req.build_key())
        try:
            binary_id = await workflow.execute_activity(
                build_binary, req, start_to_close_timeout=timedelta(hours=1),
                retry_policy=BUILD_RETRY)
        except ApplicationError as e:
            await self._set_status(req, Status.BUILD_FAILED, error=str(e))
            raise
        await self._set_status(req, Status.BUILD_SUCCESS, binary_id=binary_id)

        # 2) 提交仿真
        args = SubmitArgs(binary_id=binary_id, req=req)
        sim_task_id = await workflow.execute_activity(
            submit_simulation, args, start_to_close_timeout=timedelta(minutes=10),
            retry_policy=SUBMIT_RETRY)
        await self._set_status(req, Status.SUBMITTED,
                               sim_task_id=sim_task_id, submit_key=args.submit_key())
        await self._set_status(req, Status.RUNNING)

        # 3) 监视等待：纯 API 轮询，封装在后台 Activity，仅终态返回（不触碰 LLM）
        final: SimResult = await workflow.execute_activity(
            monitor_wait, sim_task_id, start_to_close_timeout=timedelta(hours=12),
            heartbeat_timeout=timedelta(minutes=5), retry_policy=MONITOR_RETRY)
        if final.failed:
            await self._set_status(req, Status.SIMULATION_FAILED, error=final.error)
            raise ApplicationError("simulation failed", non_retryable=True)

        # 4) 评测拉取
        await self._set_status(req, Status.EVALUATING)
        metrics: Metrics = await workflow.execute_activity(
            evaluate, sim_task_id, start_to_close_timeout=timedelta(minutes=30),
            retry_policy=EVAL_RETRY)

        # 5) 报告 + 飞书
        await self._set_status(req, Status.REPORTING)
        report_url = await workflow.execute_activity(
            generate_and_send_report, ReportArgs(req=req, metrics=metrics),
            start_to_close_timeout=timedelta(minutes=15), retry_policy=REPORT_RETRY)
        await self._set_status(req, Status.COMPLETED, report_url=report_url)

        return ExperimentResult(experiment_id=req.experiment_id,
                                status=Status.COMPLETED, report_url=report_url)

    # —— 状态镜像：作为 Activity 执行（写 DB 是副作用，不能在 workflow 内直接做）——
    async def _set_status(self, req: ExperimentRequest, status: Status, **fields) -> None:
        await workflow.execute_activity(
            mirror_status, args=[req.experiment_id, status.value, fields],
            start_to_close_timeout=timedelta(seconds=30), retry_policy=INFRA_RETRY)
```

### 9.2 状态镜像作为 Activity

要点复述：
- workflow 内**禁止** `sqlite3`、`datetime.now()`、`open()` 等；所有 DB 写入经 `mirror_status`。
- `_set_status` 失败会被 `INFRA_RETRY` 重试；即便最终失败，DB 仅为读模型，不影响 Temporal 权威状态（架构文档 §7.2）。
- `with workflow.unsafe.imports_passed_through()`：让被导入模块（含第三方）跳过沙箱重载，避免确定性沙箱误伤。

---

## 10. Worker 注册（worker.py）

```python
import asyncio
from temporalio.client import Client
from temporalio.worker import Worker
from temporalio.contrib.pydantic import pydantic_data_converter

from tse.config import get_settings
from tse.constants import TASK_QUEUE
from tse.workflows.experiment import ExperimentWorkflow
from tse.activities.infra import mirror_status
from tse.activities.build import build_binary
from tse.activities.submit import submit_simulation
from tse.activities.monitor import monitor_wait
from tse.activities.evaluate import evaluate
from tse.activities.report import generate_and_send_report


async def connect() -> Client:
    s = get_settings()
    return await Client.connect(s.temporal_target, namespace=s.temporal_namespace,
                                data_converter=pydantic_data_converter)


async def run_worker() -> None:
    client = await connect()
    worker = Worker(
        client, task_queue=TASK_QUEUE,
        workflows=[ExperimentWorkflow],
        activities=[mirror_status, build_binary, submit_simulation,
                    monitor_wait, evaluate, generate_and_send_report],
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(run_worker())
```

> `pydantic_data_converter` 必须同时配置在 **Worker 与所有 Client**（包括 Planner、控制 API），否则 Pydantic 模型无法正确序列化。

---

## 11. Planner（planner/）

`tse/planner/planner.py` —— 唯一与用户自然语言交互的 LLM 入口；解析 → 校验 → 启动工作流后**立即退出**（不等待）。

```python
import uuid
from temporalio.client import Client
from tse.config import get_settings
from tse.constants import TASK_QUEUE, SWITCH_WHITELIST
from tse.integrations.llm import LLMClient
from tse.models.domain import ExperimentRequest
from tse.workflows.experiment import ExperimentWorkflow
from tse.errors import PlannerValidationError


class Planner:
    def __init__(self, client: Client):
        self.client = client
        self.llm = LLMClient(get_settings())

    def parse(self, raw_text: str) -> ExperimentRequest:
        data = self.llm.parse_intent(raw_text)           # LLM 抽取
        return self._validate(data)

    def _validate(self, data: dict) -> ExperimentRequest:
        branch = (data.get("branch") or "").strip()
        ckpt = (data.get("ckpt_path") or "").strip()
        switches = data.get("switches") or {}
        if not branch or not ckpt:
            raise PlannerValidationError("branch / ckpt_path 不能为空")
        bad = set(switches) - SWITCH_WHITELIST           # 开关白名单
        if bad:
            raise PlannerValidationError(f"未知开关: {bad}")
        switches = {k: bool(v) for k, v in switches.items()}
        return ExperimentRequest(branch=branch, ckpt_path=ckpt, switches=switches,
                                 experiment_id=str(uuid.uuid4()))

    def plan_text(self, req: ExperimentRequest) -> str:
        # 供 CLI 预览/确认的可读计划（架构文档 §6.1）
        return "\n".join([
            f"1. checkout branch {req.branch}", "2. build binary", "3. get binary id",
            "4. submit simulation", "5. wait completion (monitor, no LLM polling)",
            "6. collect metrics", "7. generate report", "8. send feishu",
        ])

    async def start(self, req: ExperimentRequest) -> str:
        await self.client.start_workflow(
            ExperimentWorkflow.run, req,
            id=f"exp-{req.experiment_id}", task_queue=TASK_QUEUE)
        return req.experiment_id
```

---

## 12. 控制面：agentd 与 CLI（server/、cli/）

### 12.1 鉴权 `tse/server/auth.py`

```python
from fastapi import Header, HTTPException
from tse.config import get_settings


async def require_token(authorization: str = Header(default="")) -> None:
    expected = get_settings().control_token
    if not expected or authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="unauthorized")
```

### 12.2 控制 API `tse/server/control_api.py`

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from temporalio.client import Client
from tse.config import get_settings
from tse.planner.planner import Planner
from tse.store.repo import ExperimentRepo
from tse.server.auth import require_token

router = APIRouter(dependencies=[Depends(require_token)])


class RunBody(BaseModel):
    raw_text: str | None = None
    branch: str | None = None
    ckpt_path: str | None = None
    switches: dict[str, bool] = {}


def build_router(client: Client) -> APIRouter:
    planner = Planner(client)
    repo = ExperimentRepo(get_settings().db_path)

    @router.post("/plan")
    async def plan(body: RunBody):
        req = _to_request(planner, body)
        return {"experiment_id": req.experiment_id, "plan": planner.plan_text(req)}

    @router.post("/run")
    async def run(body: RunBody):
        req = _to_request(planner, body)
        await planner.start(req)
        return {"experiment_id": req.experiment_id}

    @router.get("/status/{eid}")
    async def status(eid: str):
        row = repo.get(eid)
        if not row:
            raise HTTPException(404, "not found")
        return row

    @router.get("/list")
    async def list_(limit: int = 50):
        return repo.list(limit)

    @router.post("/cancel/{eid}")
    async def cancel(eid: str):
        await client.get_workflow_handle(f"exp-{eid}").cancel()
        return {"ok": True}

    # TODO: /watch 用 SSE/WebSocket 推送状态跃迁；/resume 见 §13
    return router


def _to_request(planner: Planner, body: RunBody):
    if body.raw_text:
        return planner.parse(body.raw_text)
    return planner._validate({"branch": body.branch, "ckpt_path": body.ckpt_path,
                              "switches": body.switches})
```

### 12.3 进程入口 `tse/server/agentd.py`

```python
import asyncio
import uvicorn
from fastapi import FastAPI
from tse.config import get_settings
from tse.worker import connect, run_worker
from tse.server.control_api import build_router


async def _serve() -> None:
    s = get_settings()
    client = await connect()

    app = FastAPI(title="tse-agentd")
    app.include_router(build_router(client))

    host, port = s.control_listen.split(":")
    config = uvicorn.Config(app, host=host, port=int(port),
                            ssl_certfile=s.tls_cert, ssl_keyfile=s.tls_key, log_level="info")
    server = uvicorn.Server(config)

    # 同进程并发跑：控制 API + Temporal Worker
    await asyncio.gather(server.serve(), run_worker())


def main() -> None:
    asyncio.run(_serve())


if __name__ == "__main__":
    main()
```

### 12.4 远程 CLI `tse/cli/main.py` + `client.py`

```python
# client.py
import os
import httpx


class ControlClient:
    def __init__(self, endpoint: str | None = None, token: str | None = None):
        self.endpoint = endpoint or os.environ["TSE_ENDPOINT"]
        self.token = token or os.environ.get("TSE_CONTROL_TOKEN", "")
        self._c = httpx.Client(base_url=self.endpoint,
                               headers={"Authorization": f"Bearer {self.token}"}, timeout=30)

    def run(self, **body):
        return self._c.post("/run", json=body).raise_for_status().json()

    def status(self, eid: str):
        return self._c.get(f"/status/{eid}").raise_for_status().json()

    def list(self):
        return self._c.get("/list").raise_for_status().json()
```

```python
# main.py
import typer
from tse.cli.client import ControlClient

app = typer.Typer(help="训练仿真评测闭环 Agent —— 远程瘦客户端")


@app.command()
def run(branch: str = typer.Option(...), ckpt: str = typer.Option(...),
        set_: list[str] = typer.Option(None, "--set", help="use_difix=true")):
    switches = {k: v.lower() == "true" for k, v in (s.split("=", 1) for s in (set_ or []))}
    res = ControlClient().run(branch=branch, ckpt_path=ckpt, switches=switches)
    typer.echo(f"experiment_id = {res['experiment_id']}")


@app.command()
def status(eid: str):
    typer.echo(ControlClient().status(eid))


@app.command("list")
def list_():
    for row in ControlClient().list():
        typer.echo(f"{row['id']}  {row['status']:<18} {row.get('report_url') or ''}")


# TODO: watch（消费 /watch 流）、resume、cancel、logs
if __name__ == "__main__":
    app()
```

---

## 13. 错误分类与重试策略

`tse/errors.py`：

```python
class PlannerValidationError(ValueError):
    """用户输入非法，CLI 直接报错，不进入工作流。"""


class NonRetryableBuildError(Exception):
    """分支不存在 / 编译错误等代码问题，编包重试无意义。"""
```

**可重试 vs 不可重试** 的统一约定：

| 阶段 | 不可重试（包成 `ApplicationError(non_retryable=True)` 或上面的异常） | 可重试（默认） |
| --- | --- | --- |
| 编包 | 分支不存在、编译错误、参数非法 | 网络抖动、临时资源不足 |
| 提交仿真 | 参数非法、配额不足 | 平台 5xx、超时 |
| 监视等待 | 仿真终态 `FAILED`（业务失败，走 `SimResult.failed`，非异常） | 平台查询瞬时错误 |
| 评测拉取 | 产物结构不符 | 产物未就绪（短暂）、网络 |
| 报告 | 模板/权限错误 | 飞书/LLM 瞬时错误 |

- Activity 内将"确定无意义重试"的错误显式抛 `ApplicationError(..., non_retryable=True)`；其余交给 RetryPolicy。
- **续跑 `resume`**：对处于 `BUILD_FAILED / SIMULATION_FAILED` 的实验，控制 API 依据 DB 状态选择重入点重新 `start_workflow`（复用幂等键，已成功的编包/提交不会重做）。M5/M6 落地。

---

## 14. 安全实现要点

| 项 | 实现 |
| --- | --- |
| 命令注入 | 编包命令一律 **list 形式**（不拼 shell 字符串）；分支/名称走 `_BRANCH_RE` 白名单；SSH 模式用 `shlex.quote`。见 [bench.py](#71-tseintegrationsbenchpy--编包执行器) |
| 凭据管理 | 全部经 `Settings` 从环境变量/`.env` 读取，`Field(repr=False)` 防日志泄漏；**仅台架持有**，远程 CLI 只有 endpoint + token |
| 跨设备通信 | 控制 API 走 TLS（`ssl_certfile/keyfile`）+ Bearer 令牌；Temporal frontend 仅 `127.0.0.1` 监听，不对用户网络暴露 |
| 输入校验 | Planner `_validate` 做 schema + 开关白名单；LLM 解析结果**绝不直接拼命令**，必须过校验 |
| LLM 提示注入 | 解析提示词约束输出为结构化 JSON；越权字段在 `_validate` 丢弃 |

---

## 15. 测试策略

| 层 | 工具 | 重点 |
| --- | --- | --- |
| 单元 | pytest | `_hash` 幂等键稳定性、`parse_binary_id` 解析、`build_command` 注入防护、`_validate` 白名单 |
| 集成（Activity） | pytest + mock 集成客户端 | 幂等命中复用、错误分类、`monitor_wait` 终态判定 |
| 工作流 | `temporalio.testing.WorkflowEnvironment` | 用 **time-skipping** 跳过 12h 等待；mock activity 验证状态机顺序 |
| 重放 | Replay test | 用真实历史回放校验 workflow 改动不破坏确定性 |

工作流测试骨架：

```python
import pytest
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.contrib.pydantic import pydantic_data_converter
from tse.workflows.experiment import ExperimentWorkflow
from tse.models.domain import ExperimentRequest, SimResult, Metrics


@pytest.mark.asyncio
async def test_happy_path():
    async with await WorkflowEnvironment.start_time_skipping(
            data_converter=pydantic_data_converter) as env:
        # mock 各 activity（用同名 @activity.defn 桩或 mock）
        async with Worker(env.client, task_queue="t",
                          workflows=[ExperimentWorkflow],
                          activities=[...stub...]):
            req = ExperimentRequest(branch="b", ckpt_path="/c", switches={},
                                    experiment_id="e1")
            res = await env.client.execute_workflow(
                ExperimentWorkflow.run, req, id="w1", task_queue="t")
            assert res.status.value == "COMPLETED"
```

> `start_time_skipping` 让 `monitor_wait` 的 12h 超时与 `sleep` 瞬时跳过，使长流程可秒级测试。

---

## 16. 本地启动与冒烟验证

```bash
# 0) 安装
pip install -e ".[dev]"

# —— 台架（Agent host）——
# 1) Temporal dev server（持久化 + 仅本地监听）
temporal server start-dev --db-filename ./temporal.db --ip 127.0.0.1

# 2) agentd（控制 API + Planner + Worker 同进程）
export TSE_CONTROL_TOKEN=dev-token
export TSE_SIM_BASE_URL=...  TSE_SIM_API_TOKEN=...  TSE_FEISHU_APP_ID=...  # 业务凭据
tse-agentd                       # 默认监听 0.0.0.0:8443

# —— 远程设备（用户侧）——
export TSE_ENDPOINT=https://<bench-host>:8443
export TSE_CONTROL_TOKEN=dev-token
tse run --rerun-job-id 134316 --sim-x-token <仿真平台x-token> --sim-x-account you@xiaopeng.com --set use_difix=true
tse status <experiment_id>
```

**冒烟顺序**（建议先用 stub 集成）：M1 跑通占位闭环 → 逐个替换真实集成 → 验证崩溃恢复（编包后 `kill` agentd 再重启，确认不重复编包）。

---

## 17. 编码规范

- 类型注解齐全；`ruff` + `mypy` 入 CI。
- Workflow 文件**零副作用**：禁止 `import` 带 IO 的模块到顶层执行；统一用 `workflow.unsafe.imports_passed_through()`。
- Activity 幂等优先：任何"重复执行会产生副作用"的步骤都要有幂等键或先查后写。
- 日志不打印凭据；异常信息截断（如 `stderr[-2000:]`）。
- 时间：workflow 内只用 `workflow.now()`；业务代码用带时区的 UTC。

---

## 18. 任务分解（映射里程碑）

> 对齐架构文档 §13。每项给出落点文件，便于排期与并行。

### M1 骨架（最小闭环）
- [ ] `config.py` / `constants.py` / `errors.py`
- [ ] `models/domain.py` / `models/db.py`
- [ ] `store/repo.py`（建表 + upsert + get/list）
- [ ] `activities/infra.py`（`mirror_status`）+ 各 Activity 的 **stub** 版本
- [ ] `workflows/experiment.py`（完整状态机）
- [ ] `worker.py`（pydantic data converter）
- [ ] 本地 `execute_workflow` 跑通 10 态流转

### M2 真实集成（可并行）
- [ ] `integrations/bench.py` + `activities/build.py`（含 build_key 幂等）
- [ ] `integrations/sim_cloud.py` + `activities/submit.py`（含 submit_key 幂等）
- [ ] `integrations/sim_cloud.fetch_metrics` + `activities/evaluate.py`
- [ ] `integrations/feishu.py` + `integrations/llm.py` + `activities/report.py`

### M3 Monitor 机制
- [ ] `activities/monitor.py`（自适应轮询 + heartbeat + 终态判定）
- [ ] 崩溃恢复演练（kill → 重启 → 不重复编包/提交）

### M4 Planner
- [ ] `planner/planner.py`（LLM 解析 + 白名单校验 + plan_text + start）

### M5 远程 CLI / agentd
- [ ] `server/auth.py` / `server/control_api.py` / `server/agentd.py`
- [ ] `cli/client.py` / `cli/main.py`（run/status/list）
- [ ] TLS + 令牌；Temporal 仅本地监听

### M6 打磨
- [ ] `watch`（SSE/WebSocket 状态推送）、`resume`、`cancel`、`logs`
- [ ] 测试补全（replay、time-skipping）、`ruff/mypy` 接入 CI、README/用户手册

---

## 附录：未决项对开发的影响

| 编号 | 未决项 | 开发应对 |
| --- | --- | --- |
| Q1 | LLM 供应方/SDK | `integrations/llm.py` 为唯一适配点，换供应方只改此文件 |
| Q2 | 控制 API 形态/鉴权 | 默认 HTTP+令牌+TLS；换 gRPC 仅替换 `server/control_api.py` 与 `cli/client.py` |
| Q3 | 评测指标来源/报告模板 | `sim_cloud.fetch_metrics` 与 `feishu.send_report` 为适配点；`Metrics` 结构可扩展 |
| — | `upload_binary.py` 输出格式 | 校准 `_BINARY_ID_RE`；如需先切分支，在 `build_binary` 内前置 pipeline 命令 |
| — | 平台终态字符串 | 校准 `TERMINAL_OK / TERMINAL_FAIL` 集合 |
```
