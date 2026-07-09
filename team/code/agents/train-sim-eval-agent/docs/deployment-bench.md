# 5080 台架（Server / Agent host）部署指南

> 面向**台架管理员**：在 5080 台架上把 `agentd`（控制 API + Temporal Worker 同进程）跑起来。
> 本文重点回答两个上线待解决事项：
>
> 1. **怎么装 Temporal（SDK + dev server），含 5080 无外网的情况？** → [§2 安装依赖](#2-安装依赖temporal-sdk--cli--项目依赖)（§2.1 在线 / §2.2 离线）
> 2. **如何在 5080 上把代码跑起来（ssh → 建目录 → 拉代码 → 终端运行）？** → [§3 在 5080 上把服务跑起来](#3-在-5080-上把服务跑起来)
>
> 架构与编包三层拓扑见 [architecture-design.md](architecture-design.md) 与 [xp5_simulation_build_guide.md](xp5_simulation_build_guide.md)。

---

## 0. 部署拓扑速览

```
                     ┌─────────────────── 5080 台架（Agent host / 宿主机）───────────────────┐
  客户端 tse ──HTTP──▶│  agentd  ( FastAPI 控制API :8443  +  Temporal Worker 同进程 )         │
  (内网, 8443)        │     │                                                                 │
                     │     ├─▶ Temporal dev server (127.0.0.1:7233, 仅本地, SQLite 持久化)    │
                     │     │                                                                 │
                     │     └─▶ 编包(nested 三层):  SSH 进虚拟机 ──▶ docker exec 进容器 编包   │
                     │            (TSE_BUILD_VM_SSH_HOST → TSE_BUILD_CONTAINER)               │
                     └────────────────────────────────────────────────────────────────────┘
                                   │（外呼，需内网/相应网络可达）
                                   ├─▶ 仿真平台 cloudsim.xiaopeng.link（提交 / 查询 job）
                                   └─▶ 飞书 OpenAPI（发评测报告文件/图片）
```

**两个常驻进程**：① Temporal dev server；② `agentd`。两者都需长期运行（见 §3.5 进程守护）。

---

## 1. 需要装的两样「Temporal」（别混淆）

| 名称 | 是什么 | 谁需要 | 怎么来 |
| --- | --- | --- | --- |
| **`temporalio` Python SDK** | pip 包，`agentd`/Worker 用它连 Temporal、跑 workflow/activity | 必装 | PyPI 上的 manylinux wheel（含预编译 Rust 内核） |
| **`temporal` CLI** | 单文件 Go 二进制，内含 `server start-dev` 嵌入式 dev server（SQLite 持久化） | 若台架自己跑 Temporal 则需要 | GitHub Releases / temporal.download 的 tar.gz |

> **可省去 dev server 的情形**：若公司内网已有可用的 Temporal 集群，直接把
> `TSE_TEMPORAL_TARGET` 指向它（并配 `TSE_TEMPORAL_NAMESPACE`），就**不必**在 5080 装 `temporal` CLI，
> 只需装 `temporalio` SDK。是否有共享集群请与平台/SRE 确认。

---

## 2. 安装依赖（Temporal SDK + CLI + 项目依赖）

按 5080 的**网络情形**选一种安装路径：

| 情形 | 用哪节 |
| --- | --- |
| 能访问外网 **或** 有内网 PyPI 镜像 | **§2.1 在线安装（最简单）** |
| 完全无外网、无内网镜像 | §2.2 离线 wheelhouse |
| 想一次性烤进镜像/搬运 venv | §2.3 docker / venv 搬运 |

无论哪种，`temporal` CLI（dev server 二进制）单独装，见 §2.4。

### 2.1 在线安装（能访问外网或内网镜像，最简单）

> 适用：5080 能直连公网 PyPI，**或**能访问公司内网 PyPI / Artifactory 镜像。

**第 0 步：确认网络与包源**

```bash
# 探测能否直连公网 PyPI（任一返回 200/连接成功即说明外网可用）
curl -sI https://pypi.org/simple/ | head -1

# 看是否已配置内网镜像（若有 index-url，则走内网，无需外网）
pip config list
cat /etc/pip.conf ~/.pip/pip.conf ~/.config/pip/pip.conf 2>/dev/null
```

**第 1 步：建虚拟环境**

```bash
cd ~/tse-deploy/simworld/agents/train-sim-eval-agent   # 进项目目录（含 pyproject.toml）
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip                            # 升级 pip（可选但推荐）
```

**第 2 步：安装服务端依赖**

```bash
# 走外网 PyPI（默认源）
pip install -e ".[server,eval]"

# 或：走内网镜像（无外网但有内部源时；把 URL 换成真实地址）
# pip install -i https://<内网PyPI>/simple -e ".[server,eval]"
```

说明：
- `[server]` 装 `temporalio / fastapi / uvicorn / lark-oapi / requests / httpx`；`[eval]` 装评测画图的 `pandas / matplotlib / numpy`。
- 编包若用 SSH 模式，再加 `ssh`：`pip install -e ".[server,eval,ssh]"`。
- `-e`（可编辑安装）：之后 `git pull` 改了代码无需重装，重启服务即可生效；仅**依赖变化**时才需重跑本命令。
- `temporalio` 是带预编译 Rust 内核的 wheel，在线安装会自动拉取匹配本机平台（linux x86_64 / cp311）的二进制，无需本地编译。

**第 3 步：验证依赖就绪**

```bash
python -c "import temporalio, fastapi, uvicorn, httpx, lark_oapi, pandas; print('deps OK')"
python -c "import tse.server.agentd; print('agentd importable')"
#   注意：直接运行 tse-agentd 会立即启动服务（无 --help），验证用上面的 import 即可
```

**第 4 步：装 `temporal` CLI（dev server 二进制）**

有外网时可一键安装到当前用户（官方安装脚本）：

```bash
curl -sSf https://temporal.download/cli.sh | sh
#   默认装到 ~/.temporalio/bin，按提示把该目录加入 PATH
temporal --version
```

> 若无外网或更偏好手动放置二进制，见 §2.4。

完成后即可按 [§3.4 配置 .env](#34-配置-env凭据只存台架切勿提交) → [§3.5 常驻运行](#35-让两个进程常驻运行)。

### 2.2 离线 wheelhouse（完全无外网）

在一台**联网、且架构/解释器与 5080 一致**的机器（Linux x86_64 + Python 3.11；
最稳妥是用与 5080 相同的 docker 镜像）上打包，再拷到 5080 离线装。

**联网机器上：**

```bash
cd simworld/agents/train-sim-eval-agent

# 方式①：用当前平台直接抓服务端全部依赖 wheel（要求该机平台与 5080 相同）
pip download ".[server,eval]" -d wheelhouse

# 方式②：跨平台显式指定平台/解释器，强制只下二进制 wheel（避免源码编译）
pip download ".[server,eval]" -d wheelhouse \
  --only-binary=:all: \
  --platform manylinux2014_x86_64 \
  --python-version 311 --implementation cp --abi cp311
```

> 关键：`temporalio` 是带 Rust 内核的二进制 wheel，**必须**下到与 5080 匹配的
> `manylinux_x86_64 / cp311` 版本，否则到了 5080 会尝试源码编译而失败。

把 `wheelhouse/` 整目录拷到 5080（内网 scp / 制品库 / U 盘）。

**5080 上离线安装：**

```bash
cd simworld/agents/train-sim-eval-agent
python3 -m venv .venv && source .venv/bin/activate
pip install --no-index --find-links=/path/to/wheelhouse -e ".[server,eval]"
#   [server] 装 temporalio/fastapi/uvicorn/lark-oapi/requests；[eval] 装 pandas/matplotlib/numpy（评测画图）
#   若编包用 SSH 模式还需 ssh（fabric）；可写成 -e ".[server,eval,ssh]"
```

### 2.3 整包搬运 venv / 用 docker 镜像（最稳）

由于 5080 已有成熟的 docker 镜像体系，最稳妥的离线方案是**把依赖烤进镜像**：

- 在联网环境基于 5080 同款基础镜像 `pip install -e ".[server,eval]"`，
  `docker commit` 或写进 Dockerfile，`docker save` 成 tar，拷到 5080 `docker load`。
- 或用 `conda-pack` / 直接 `tar` 打包整个 `.venv`（要求两机系统库 ABI 一致），到 5080 解包即用。

### 2.4 安装 `temporal` CLI（dev server 二进制，离线）

`temporal` 是单文件静态二进制，**无运行期依赖，离线最容易**：

1. 联网机器从 <https://github.com/temporalio/cli/releases>（或 `https://temporal.download`）
   下载 `temporal_cli_<version>_linux_amd64.tar.gz`。
2. 拷到 5080，解包并放到 PATH：
   ```bash
   tar -xzf temporal_cli_*_linux_amd64.tar.gz        # 解出 temporal 可执行文件
   sudo install -m 0755 temporal /usr/local/bin/temporal
   #   无 sudo 权限时：放到 ~/bin 并把 ~/bin 加进 PATH
   temporal --version                                 # 验证
   ```

> 仿真平台（cloudsim.xiaopeng.link）与飞书 OpenAPI 是 `agentd` 运行时的外呼目标。
> 请确认 5080 到这两者**网络可达**（内网/代理）；否则提交仿真与发报告会失败。

---

## 3. 在 5080 上把服务跑起来

你设想的「ssh 进 5080 → 建目录 → 从 GitLab 拉代码 → 开终端运行」是**可行**的，
下面是完整、可照做的步骤；唯一要补强的是「常驻运行」（§3.5），避免关掉 ssh 进程就退出。

### 3.1 SSH 登录并建工作目录

```bash
ssh <user>@<5080-host>
mkdir -p ~/tse-deploy && cd ~/tse-deploy
```

### 3.2 从 GitLab 拉代码

GitLab 是**内网**服务，5080 即使没有公网也通常可达：

```bash
git clone <GITLAB_REPO_URL> simworld
cd simworld/agents/train-sim-eval-agent
```

> 后续更新：`git pull` 即可。凭据用内网账户/部署密钥，**不要**把 token 写进仓库或 `.env` 提交。

### 3.3 安装依赖

依赖安装详见 [§2](#2-安装依赖temporal-sdk--cli--项目依赖)，按网络情形择一：

- 能访问外网 **或** 有内网 PyPI 镜像 → [§2.1 在线安装](#21-在线安装能访问外网或内网镜像最简单)（建 venv + `pip install -e ".[server,eval]"`）。
- 完全无外网 → [§2.2 离线 wheelhouse](#22-离线-wheelhouse完全无外网) 或 [§2.3 docker/venv 搬运](#23-整包搬运-venv--用-docker-镜像最稳)。
- `temporal` CLI（若自跑 dev server）→ [§2.4](#24-安装-temporal-clidev-server-二进制离线)。

### 3.4 配置 `.env`（凭据只存台架，切勿提交）

```bash
cp .env.example .env
#   用编辑器填写真实值（下面是必须项；完整项见 .env.example 注释）
```

最小必填清单：

| 变量 | 说明 |
| --- | --- |
| `TSE_SIM_X_TOKEN` / `TSE_SIM_X_ACCOUNT` | 仿真平台鉴权（x-token 是会过期的 JWT）。**现由客户端每次 `tse run --sim-x-token/--sim-x-account` 传入**；台架 `.env` 这两项可留空，仅作未传入时的回退 |
| `TSE_FEISHU_APP_ID` / `TSE_FEISHU_APP_SECRET` | 飞书自建应用凭据 |
| `TSE_FEISHU_RECEIVE_EMAIL` 或 `TSE_FEISHU_RECEIVE_ID` | 报告接收人 |
| `TSE_SIMWORLD_REPO_ROOT` | **simworld 仓库根**（含 `tools/`，评测脚本所在）。台架上 = 你 clone 出来的仓库根，如 `/home/<user>/tse-deploy/simworld`。`.env.example` 默认的 `/workspace` 仅开发沙箱用，**必须改成真实克隆路径** |
| 编包相关 `TSE_BUILD_*` | nested 三层拓扑：宿主机→SSH 虚拟机→docker 容器（默认值见 `.env.example`，按真实台架核对） |

> 💡 **评测工具如何运行（不需要第二个 venv）**：评测调用的 `tools/render_time_analysis/{log_downloader,time_analyze}.py`、
> `tools/eval_tools/{eval_tasks_download,eval_main}.py` 不是用子进程执行，而是 `agentd` 用 `importlib`
> 把 `$TSE_SIMWORLD_REPO_ROOT/tools/...` 加入 `sys.path` 后**导入到自身进程**运行——即它们跑在 `train-sim-eval-agent` 的同一个 venv 里。
> 因此：① 工具脚本本身无需安装；② 工具的第三方依赖（`requests` 来自 `[server]`，`pandas/matplotlib/numpy` 来自 `[eval]`）已被
> `pip install -e ".[server,eval]"` 覆盖；③ 你只需保证 `TSE_SIMWORLD_REPO_ROOT` 指向**含 `tools/` 的那个 clone**（与 agent 同属一个仓库，无需另外 clone）。

> 安全：控制 API **已移除 token 鉴权**——`agentd` 监听 `0.0.0.0:8443`，
> **凡能访问到该端口的内网客户端均可调用 `/run` `/status` `/list` `/cancel`**，请确保 8443 仅在可信内网开放。
> `TSE_TEMPORAL_TARGET` 默认 `127.0.0.1:7233`（dev server 仅本地监听）。生产建议配 TLS（见 §3.6）。

### 3.5 让两个进程常驻运行

台架需要**两个长期进程**：① Temporal dev server；② `tse-agentd`。
**直接在交互式 ssh 终端里跑，一旦关掉 ssh / 退出登录，进程随会话被杀**（收到 SIGHUP）。
因此必须把它们托管成「脱离终端、可自恢复」的常驻服务。按场景选一种：

| 方式 | 退出 ssh 后存活 | 机器重启后自启 | 崩溃自动重拉 | 适用 |
| --- | :---: | :---: | :---: | --- |
| `nohup` | ✅ | ❌ | ❌ | 临时验证，最省事 |
| `tmux` / `screen` | ✅ | ❌ | ❌ | 调试期、要随时回看交互输出 |
| **`systemd`** | ✅ | ✅ | ✅ | **生产推荐** |

> 关键区别：`tmux`/`nohup` 只解决「关 ssh 不被杀」，**机器重启后不会自启、进程崩了不会重拉**；
> 长期上线请用 `systemd`（§方式 C）。

#### 方式 A：nohup（最快，仅临时）

```bash
cd ~/tse-deploy
# ① dev server（输出重定向到日志文件，& 放后台，nohup 防 SIGHUP）
nohup temporal server start-dev --db-filename ~/tse-deploy/temporal.db --ip 127.0.0.1 \
      > ~/tse-deploy/temporal.log 2>&1 &

# ② agentd（必须在含 .env 的项目目录启动，pydantic 会读 ./.env）
cd ~/tse-deploy/simworld/agents/train-sim-eval-agent && source .venv/bin/activate
nohup tse-agentd > ~/tse-deploy/agentd.log 2>&1 &

jobs -l            # 查看后台进程与 PID
tail -f ~/tse-deploy/agentd.log
```

停止：`pkill -f tse-agentd` / `pkill -f "temporal server start-dev"`（或按 `jobs -l` 的 PID `kill`）。

#### 方式 B：tmux（调试期，可回看交互输出）

**推荐：用仓库自带脚本 `scripts/tse-tmux.sh` 一键编排**（自动先起 dev server、等 7233 就绪再起 agentd，并带前置检查）：

```bash
cd ~/tse-deploy/simworld/agents/train-sim-eval-agent

./scripts/tse-tmux.sh start               # 拉起 Temporal dev server + tse-agentd
./scripts/tse-tmux.sh status              # 看会话 / 端口(7233,8443) / 控制API 健康
./scripts/tse-tmux.sh attach              # 进会话看实时输出（Ctrl-b d 脱离，不杀进程）
./scripts/tse-tmux.sh logs                # 不进会话，抓两个窗口最近输出
./scripts/tse-tmux.sh restart             # 重启
./scripts/tse-tmux.sh stop                # 停止

# 可选覆盖：TSE_VENV / TSE_TEMPORAL_DB / TEMPORAL_BIN / TSE_TMUX_SESSION
```

脚本默认：venv = `<项目目录>/.venv`，dev server db = `<项目目录>/temporal.db`，会话名 `tse`。
> ⚠️ tmux 会话**不随机器重启保留**，长期上线请用 §方式 C systemd。

<details><summary>手动 tmux 步骤（不想用脚本时展开）</summary>

```bash
sudo apt-get install -y tmux        # 如未安装

# 窗口1：dev server
tmux new -s temporal
temporal server start-dev --db-filename ~/tse-deploy/temporal.db --ip 127.0.0.1
#   Ctrl-b 然后按 d 脱离会话（进程继续在后台跑）

# 窗口2：agentd
tmux new -s agentd
cd ~/tse-deploy/simworld/agents/train-sim-eval-agent && source .venv/bin/activate
tse-agentd                          # 读取 ./.env，默认监听 0.0.0.0:8443
#   Ctrl-b d 脱离
```

回看：`tmux attach -t agentd`；列会话：`tmux ls`；停止：attach 后 `Ctrl-c`，或 `tmux kill-session -t agentd`。

</details>

#### 方式 C：systemd（生产推荐，开机自启 + 崩溃重拉）

需要 root/sudo 写 unit 文件。把下面两段里的 `<user>` 改成实际运行账号，路径按 §3.1 的部署目录核对。

`/etc/systemd/system/temporal-dev.service`：

```ini
[Unit]
Description=Temporal dev server (TSE)
After=network-online.target
Wants=network-online.target
# 崩溃风暴保护：60s 内重启超过 5 次则进入 failed，避免疯狂重拉（StartLimit 属于 [Unit]）
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=<user>
# 仅本地监听，避免 7233 暴露到内网；持久化到本地 db（重启不丢工作流状态）
ExecStart=/usr/local/bin/temporal server start-dev --db-filename /home/<user>/tse-deploy/temporal.db --ip 127.0.0.1
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/tse-agentd.service`：

```ini
[Unit]
Description=TSE agentd (control API + Temporal worker)
# 在 dev server 之后启动；dev server 挂了则一并停（保持依赖一致）
After=temporal-dev.service
Requires=temporal-dev.service
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
User=<user>
# WorkingDirectory 指向含 .env 的项目目录：pydantic-settings 会自动读取 ./.env
WorkingDirectory=/home/<user>/tse-deploy/simworld/agents/train-sim-eval-agent
ExecStart=/home/<user>/tse-deploy/simworld/agents/train-sim-eval-agent/.venv/bin/tse-agentd
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

启用并启动：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now temporal-dev tse-agentd
```

> **就绪顺序说明**：systemd 认为 dev server「启动」≠ 端口 7233「就绪」。
> `agentd` 连接 Temporal 是一次性连接（`Client.connect`），若启动瞬间 7233 尚未就绪，`agentd` 会退出，
> 随即被 `Restart=always` 拉起重连——首次开机可能重启一两次属正常，最终会稳定连上。
>
> **凭据加载**：`agentd` 不依赖 systemd 注入环境变量，而是由 `pydantic-settings` 从 `WorkingDirectory` 下的 `.env` 读取，
> 因此 `.env` 必须位于该项目目录（见 §3.4）。如更偏好 systemd 原生方式，也可改用 `EnvironmentFile=.../.env`（二选一即可，勿重复）。

### 3.5.1 验证常驻是否生效

```bash
# 1) 进程/服务状态
systemctl is-active temporal-dev tse-agentd          # 期望都输出 active
sudo systemctl status tse-agentd --no-pager

# 2) 端口监听：7233 仅本地、8443 对外
ss -tlnp | grep -E ':7233|:8443'

# 3) 控制 API 健康（已无 token 鉴权）
curl -s http://127.0.0.1:8443/list

# 4) 真·常驻验证：退出当前 ssh 再重连，确认两个服务仍 active
#    生产可再做一次重启演练：sudo reboot 后，确认开机自动拉起
```

### 3.5.2 日常运维：日志 / 重启 / 更新

```bash
# 跟踪日志
journalctl -u tse-agentd -f
journalctl -u temporal-dev -n 200 --no-pager

# 改了 .env 或需重启服务
sudo systemctl restart tse-agentd

# 更新代码后重新部署（依赖变更才需重装）
cd ~/tse-deploy/simworld/agents/train-sim-eval-agent
git pull
source .venv/bin/activate && pip install -e ".[server,eval]"   # 仅依赖变化时
sudo systemctl restart tse-agentd
```

> 注意：**dev server 只应跑一个实例**（多个实例指向同一 `temporal.db` 会冲突）。
> `agentd` 单实例即可满足台架场景；其内置的 Temporal Worker 重启后会自动重连并续跑未完成的工作流。

### 3.6 （可选）启用 TLS

生产建议给控制 API 配证书，在 `.env` 设：

```bash
TSE_TLS_CERT=/path/to/server.crt
TSE_TLS_KEY=/path/to/server.key
```

客户端随后用 `https://` 连接（自签证书的客户端配置见 [client-cli-setup.md](client-cli-setup.md) §3）。

---

## 4. 冒烟验证

```bash
# 1) 服务存活：列实验（控制 API 已无 token 鉴权）
curl -s http://127.0.0.1:8443/list

# 2) 从客户端发起一次最小实验（见 client-cli-setup.md），观察状态流转
tse run --rerun-job-id <模板job> --sim-x-token <x-token> --sim-x-account <账号> --set use_difix=true
tse status <experiment_id>
```

**建议的冒烟顺序**：先确认 dev server + agentd 起得来、`/list` 通；再跑一次真实 `run`，
盯 `BUILDING → ... → COMPLETED` 的状态跃迁；最后演练崩溃恢复（编包后 `systemctl restart tse-agentd`，确认不重复编包）。

---

## 5. 排障速查

| 现象 | 可能原因 / 处理 |
| --- | --- |
| `pip install` 卡在编译 temporalio | 下到了源码包而非二进制 wheel；按 §2.2 用 `--only-binary=:all: --platform manylinux2014_x86_64` 重抓 |
| `temporal: command not found` | CLI 没装或不在 PATH，见 §2.4 |
| agentd 起不来，连不上 7233 | dev server 没起 / `TSE_TEMPORAL_TARGET` 配错；先 `temporal server start-dev` |
| 提交仿真超时 / 报告发不出 | 5080 到 cloudsim 或飞书 OpenAPI 网络不可达；或 `TSE_SIM_X_TOKEN`（JWT）已过期 |
| 客户端连不上 / 超时 | 检查 8443 是否在内网开放、`tse` 端 `TSE_ENDPOINT` 或 hardcode 地址是否指向正确台架 IP |
| 编包失败 | 核对 nested 三层 `TSE_BUILD_*`：SSH 能进虚拟机、容器名/路径正确（见 xp5_simulation_build_guide.md） |
| 关掉 ssh 后服务停了 | 没用 tmux/systemd 常驻，见 §3.5 |
