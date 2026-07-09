# 客户端 CLI（`tse`）安装与使用指南

> 面向**使用方/模型同学**：在自己的开发机或测试设备上安装 `tse` 瘦客户端，
> 通过它远程向台架上的 `agentd` 提交「编包 → 提交仿真 → 等待 → 评测 → 发飞书」闭环实验。
>
> 客户端**不跑** Temporal、不持有任何业务凭据，只做三件事：调用 `agentd` 的 HTTP 控制 API 发起
> `run` / 查询 `status` / 拉取 `list`。所有重活与凭据都在台架侧。

---

## 1. 前置条件

| 项 | 要求 |
| --- | --- |
| 操作系统 | Linux / macOS（Windows 可用 WSL） |
| Python | 3.10 及以上（`python3 --version` 确认） |
| 网络 | 能访问台架 `agentd` 的监听地址（默认端口 `8443`，公司内网即可） |
| 鉴权 | **无需令牌**——控制 API 已移除 token 鉴权，内网直连即可调用 |

> 客户端与台架**走内网直连**即可，不需要外网。
> 服务地址已 hardcode 在代码里（`tse/cli/client.py` 的 `DEFAULT_ENDPOINT = http://10.99.75.210:8443`），
> 一般无需任何配置即可使用；如需临时改指别的台架，再设环境变量 `TSE_ENDPOINT` 覆盖。

---

## 2. 安装

`tse` 是 `train-sim-eval-agent` 包的一个入口脚本（`pyproject.toml` 中 `[project.scripts] tse = "tse.cli.main:app"`）。
安装该包后即可使用 `tse` 命令。下面给出三种方式，**推荐方式 A（pipx 隔离安装）**。

### 方式 A：pipx 隔离安装（推荐）

pipx 会把 `tse` 装进独立虚拟环境并把命令挂到 PATH，不污染系统 Python：

```bash
# 0) 安装 pipx（只需一次）
python3 -m pip install --user pipx
python3 -m pipx ensurepath
#   重开终端，使 PATH 生效

# 1) 从 GitLab 克隆仓库（地址向管理员索取；内网可达）
git clone <GITLAB_REPO_URL> simworld
cd simworld/agents/train-sim-eval-agent

# 2) 用 pipx 安装本目录的瘦客户端（含 tse 命令，仅拉 typer + httpx）
pipx install ".[client]"
#   升级：在仓库目录执行 `git pull` 后 `pipx install ".[client]" --force`
```

### 方式 B：普通 venv + pip

```bash
git clone <GITLAB_REPO_URL> simworld
cd simworld/agents/train-sim-eval-agent

python3 -m venv .venv
source .venv/bin/activate
pip install ".[client]"
#   开发可改用可编辑安装：pip install -e ".[client]"
```

> 说明：依赖已按角色拆分（`pyproject.toml` 的 optional-dependencies）。
> `[client]` 只装瘦客户端运行所需的 `typer` + `httpx`，**不会**拉取 `temporalio` / `fastapi`
> 等服务端重依赖，安装体积小、离线打包也轻。若你的环境无外网，见 [§5 离线安装](#5-无外网环境的离线安装)。

### 方式 C：仅装运行时依赖跑模块（轻量、不装入口脚本）

若不想安装整个包，也可只装两个瘦依赖后直接跑模块：

```bash
pip install "typer>=0.12" "httpx>=0.27"
cd simworld/agents/train-sim-eval-agent
python -m tse.cli.main --help        # 等价于 tse --help
```

---

## 3. 配置（可选）

服务地址已 hardcode 在 `tse/cli/client.py`（`DEFAULT_ENDPOINT = "http://10.99.75.210:8443"`），
且控制 API **无需令牌鉴权**，所以**默认零配置即可直接用 `tse`**。

仅当需要临时指向其它台架时，设环境变量覆盖：

```bash
export TSE_ENDPOINT=https://<其它台架IP>:8443    # 可选，覆盖代码里的默认地址
```

（可写进 `~/.bashrc` / `~/.zshrc`，或命令前内联 `TSE_ENDPOINT=... tse ...`。）

### TLS / 协议说明

- 默认地址是 `http://`（台架 `agentd` 默认不配 TLS，`config.py` 中 `tls_cert`/`tls_key` 默认 `None`，即纯 HTTP）。若台架**启用了 TLS**，请改用 **`https://`** 前缀的 `TSE_ENDPOINT` 覆盖。
- 若台架用 **自签证书**（HTTPS）：当前客户端默认校验证书链，自签会报 SSL 错误。
  解决：把台架的 CA 证书加入信任，或运行前指定 `export SSL_CERT_FILE=/path/to/bench-ca.pem`（向管理员索取该 CA 文件）。

---

## 4. 使用

### 4.1 查看可用开关

提交前先看支持哪些仿真开关简称（映射见 `tse/switches.py`）：

```bash
tse switches
```

输出示例（简称 → 平台完整 token）：

```
perfect_control           ->  simulation@perfect_control:1
use_difix                 ->  simworld@use_difix:1
use_nvfixer               ->  USE_NVFIXER=true
...
```

### 4.2 发起一次实验（`run`）

```bash
tse run \
  --rerun-job-id 134316 \               # rerun 的模板 e2e job_id（每次提交可变）
  --sim-x-token <仿真平台 x-token> \     # 仿真平台鉴权 JWT（会过期，每次提交随请求下发）
  --sim-x-account you@xiaopeng.com \    # 仿真平台账号（邮箱）
  --job-name difix_0612_exp1 \          # 任务名（可选，缺省由 分支+实验号 生成）
  --set use_difix=true \                # 打开开关（可重复；简称见 `tse switches`）
  --baseline 3dgs_3w=133785 \           # 评测基线 job（可重复，job_name=job_id）
  --baseline origin_png=134316
```

> 编包分支已固定（hardcode）在服务端：simulation 仓库 `git checkout dev_xngp_xp5_zf`、
> simworld 仓库 `git checkout dev_zf_nvfixer`。因此 `run` **不再接受** `--branch` / `--simworld-branch`，
> 也不再需要 `--ckpt`。如需更换编包分支，改服务端 `tse/constants.py` 的
> `SIMULATION_BRANCH` / `SIMWORLD_BRANCH` 即可。

> `--sim-x-token` / `--sim-x-account` 为**必填**：仿真平台凭据现由客户端每次随请求传入（不再仅存台架）。
> x-token 是会过期的 JWT，从仿真平台获取后填入；过期就更新重跑。
> ⚠️ 安全：token 会出现在 shell 历史和进程列表里，注意环境安全；如不希望留痕，可改用 `read -s` 读入变量后引用。

成功后输出：

```
experiment_id = <实验ID>
```

参数说明：

| 参数 | 必填 | 说明 |
| --- | --- | --- |
| `--rerun-job-id` | 是 | 作为 rerun 模板的云端 e2e `job_id` |
| `--sim-x-token` | 是 | 仿真平台 x-token（JWT，会过期；用于提交/查询/评测下载鉴权） |
| `--sim-x-account` | 是 | 仿真平台 x-account（账号邮箱） |
| `--job-name` | 否 | 本次任务名；缺省由分支+实验号自动生成 |
| `--manifest-branch` | 否 | pipeline 清单分支；缺省走服务端配置 |
| `--set k=v` | 否 | 打开开关，可重复，如 `--set use_difix=true` |
| `--baseline name=id` | 否 | 评测对比基线，可重复，如 `--baseline 3dgs_3w=133785`；支持 `name=id1,id2` |

> 编包分支（simulation=`dev_xngp_xp5_zf`、simworld=`dev_zf_nvfixer`）已 hardcode 在服务端
> `tse/constants.py`，不再作为命令行参数；模型权重路径（原 `--ckpt`）也已移除。

### 4.3 查询状态（`status`）

```bash
tse status <experiment_id>
```

返回该实验的当前状态（10 态之一：`CREATED / BUILDING / BUILD_SUCCESS / BUILD_FAILED /
SUBMITTED / RUNNING / SIMULATION_FAILED / EVALUATING / REPORTING / COMPLETED`）及报告链接等。

### 4.4 列出历史（`list`）

```bash
tse list
```

每行展示 `实验ID  状态  报告URL`。

> 实验完成后，渲染耗时 CSV 与 FM 轨迹评测图片会**由台架直接发送到飞书**，客户端无需拉取产物。

---

## 5. 无外网环境的离线安装

若客户端设备同样无外网，用「联网机器打包 → 拷贝 → 离线安装」：

1. 在一台**同架构（Linux x86_64）、同 Python 大版本**的联网机器上下载 wheel：
   ```bash
   cd simworld/agents/train-sim-eval-agent
   pip download ".[client]" -d tse-wheels
   #   仅瘦客户端依赖很少（typer + httpx 及其传递依赖），打包很轻
   ```
2. 把 `tse-wheels/` 目录拷到客户端设备（U 盘 / 内网 scp）。
3. 在客户端离线安装：
   ```bash
   python3 -m venv .venv && source .venv/bin/activate
   pip install --no-index --find-links=./tse-wheels "train-sim-eval-agent[client]"
   ```

> 台架侧（server）的离线安装与启动见 [deployment-bench.md](deployment-bench.md)。

---

## 6. 常见问题

| 现象 | 排查 |
| --- | --- |
| `KeyError: 'TSE_ENDPOINT'` | 不应再出现（地址已 hardcode）；若你显式用了该变量名又拼错，检查 `TSE_ENDPOINT` 拼写 |
| `Connection refused` / 超时 | 台架 `agentd` 未启动，或地址/端口不对；确认能 `curl http://10.99.75.210:8443/list` |
| `SSL: CERTIFICATE_VERIFY_FAILED` | 服务端用自签证书，见 §3「TLS 说明」配置 `SSL_CERT_FILE`，或服务端改用 `http://`（用 `TSE_ENDPOINT` 覆盖） |
| `tse: command not found` | 用方式 A 时执行 `pipx ensurepath` 后重开终端；或用方式 C 的 `python -m tse.cli.main` |
| `Missing option '--branch'`（或其它已删参数仍被要求） | **安装的是旧版本入口**。`--branch`/`--ckpt` 已移除，但非可编辑安装（`pip install` / `pipx install` 不带 `-e`）在 `git pull` 后不会更新已装入口。在仓库目录重装：pipx 用 `pipx install ".[client]" --force`；venv 用 `pip install --force-reinstall ".[client]"`（或改用可编辑安装 `pip install -e ".[client]"`，此后 `git pull` 即生效）。装好后 `tse run --help` 应不再出现 `--branch` |
| `--baseline 格式` 报错 | 格式必须为 `job_name=job_id`，多个 id 用逗号：`name=1,2` |
