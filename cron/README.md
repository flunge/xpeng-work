# cron/ — 定时任务集中管理

所有定时任务的入口脚本、安装脚本和配置集中在此目录。

## ⚠️ 已从 cron 迁移到 LaunchAgent

macOS 的 cron 由系统 launchd 启动，缺少 `~/Documents` 的"完全磁盘访问权限"（TCC），
导致所有任务执行时报 `Operation not permitted`。现已改用**用户级 LaunchAgent**：
launchd 在用户登录会话中运行，继承对 `~/Documents` 的完整访问权。

进一步优化：**11/12 任务直接用 Python 运行**（Python 已有完全磁盘访问权限），
完全绕过 `/bin/bash` 的 TCC 限制。仅 `daily-sync` 因含 bash heredoc 仍需 bash。

## 安装

```bash
bash cron/install.sh
```

安装脚本会：
1. 生成 12 个 plist 到 `~/Library/LaunchAgents/`
2. 用 `launchctl load` 加载全部任务
3. 备份并清空 crontab（备份在 `cron/crontab.backup.*`）

## 卸载

```bash
bash cron/uninstall.sh
```

会卸载所有 `com.xpeng.*` LaunchAgent 并删除 plist 文件。

## 目录结构

```
cron/
├── install.sh                  # 一键安装 LaunchAgent
├── uninstall.sh                 # 一键卸载
├── jobs/                        # Python 任务脚本（LaunchAgent 直接调用）
│   ├── ai_news.py               #   AI 圈新闻
│   ├── chat_summary.py          #   Chat 汇报（早/中/晚）
│   ├── stock_pick.py            #   10 支股票推荐
│   └── meal_generate_month.py   #   月末生成下月食谱（Python 启动器）
├── scripts/                     # 各任务入口脚本（bash 包装，daily-sync 仍用）
│   ├── daily-sync.sh            #   每天 22:00 — 数据同步
│   ├── risk-push.sh             #   每天 09:00 — 项目风险播报
│   ├── week-label.sh            #   每周一 08:00 — 更新周标题
│   ├── ai-news.sh              #   每天 09:00 — AI 圈新闻
│   ├── stock-pick.sh            #   每天 09:00 — 10 支股票
│   ├── morning-chat.sh          #   每天 09:00 — 上午 chat 汇报
│   ├── noon-chat.sh             #   每天 12:00 — 中午 chat 汇报
│   ├── evening-chat.sh          #   每天 18:00 — 下午 chat 汇报
│   ├── meal-notify.sh            #   每天 18:00 — 食谱推送
│   └── meal-generate-month.sh   #   每月 28-31 日 20:00 — 生成下月计划
└── logs/                        # LaunchAgent 日志（自动生成）
```

## 任务清单

| 任务 | Label | 调度 | 运行方式 |
|------|-------|------|----------|
| 数据同步 | com.xpeng.daily-sync | 每天 22:00 | bash（需 FDA） |
| **文档镜像+索引** | com.xpeng.larkdocs-sync | 每天 23:00 | Python direct（P0/P1：larkdocs_sync.py 镜像→doc_rag.py 建库） |
| **Storyline 主线卡** | com.xpeng.storyline-gen | 每周五 20:00 | Python direct（P2：写 Base 待确认 → 推送李坤周六审） |
| 周标题更新 | com.xpeng.week-label | 每周一 08:00 | Python direct |
| 项目风险播报 | com.xpeng.risk-push | 每天 09:00 | Python direct |
| 10支股票推荐 | com.xpeng.stock-pick | 每天 09:00 | Python direct |
| AI圈新闻 | com.xpeng.ai-news | 每天 09:00 | Python direct |
| 上午 chat 汇报 | com.xpeng.morning-chat | 每天 09:00 | Python direct |
| 中午 chat 汇报 | com.xpeng.noon-chat | 每天 12:00 | Python direct |
| 下午 chat 汇报 | com.xpeng.evening-chat | 每天 18:00 | Python direct |
| 食谱通知 | com.xpeng.meal-notify | 每天 18:00 | Python direct |
| 生成下月食谱 | com.xpeng.meal-generate-month | 每月 28-31 日 20:00 | Python direct |

## 修改任务

1. 编辑对应的 Python 脚本（`cron/jobs/*.py`）或入口脚本（`cron/scripts/*.sh`）
2. 如需调整时间或增删任务，编辑 `cron/install.sh` 中的 plist 定义
3. 重新运行 `bash cron/install.sh` 生效（会先卸载旧任务再加载新的）

## 查看状态

```bash
# 查看已加载的 LaunchAgent
launchctl list | grep com.xpeng

# 查看某个任务的退出码
launchctl list com.xpeng.risk-push

# 手动触发一个任务（测试用）
launchctl start com.xpeng.risk-push

# 查看日志
ls cron/logs/
tail -20 cron/logs/com.xpeng.risk-push.log
```

## ⚠️ daily-sync 的 bash 权限

`daily-sync` 仍通过 `/bin/bash` 运行（因 `team/scripts/daily-sync.sh` 含 bash heredoc，
无法直接用 Python 替代）。需要给 bash 授予完全磁盘访问权限：

1. 系统设置 → 隐私与安全性 → **完全磁盘访问权限**
2. 点 `+`，按 `⌘⇧G` 输入 `/bin/bash`，添加并打开开关

其余 11 个任务直接用 Python 运行，无需此步骤。

如果不想给 bash 授权，daily-sync 的数据同步功能可以手动运行：
```bash
cd team && bash scripts/daily-sync.sh
```
