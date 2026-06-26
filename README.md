# lik44-star-team

「灵犀」运行的多项目工作空间（monorepo）。仓库根下并列三个**相互独立**的项目，外加一层把它们的自动化任务串起来的**根触发层**。

```
/workspace
├── bootstrap.sh           # Pod 启动自愈：补运行依赖（PyYAML 等）
├── lingxi-trigger.sh      # 统一任务触发入口：food | risk | sync
│
├── meal/                  # ① 家庭食谱自动化（Python + YAML + 飞书 Webhook）
├── team/                  # ② 仿真部飞书工作空间交互（lark-cli + 记忆库）
└── ppt-slide-formatter/   # ③ 网页版可编辑 PPT（Vite）
```

> ⚠️ 三个项目各自独立，无代码依赖。根目录的两个脚本是**已部署运行**的触发层，
> 硬编码了 `/workspace/meal`、`/workspace/team/scripts/...` 等绝对路径，
> 并被飞书消息驱动 / crontab 调用——**请勿移动项目根目录或重命名顶层目录**。

---

## 项目一览

| 目录 | 用途 | 技术栈 | 详细文档 |
|------|------|--------|----------|
| [`meal/`](meal/) | 一家四口的自动化食谱：每日推送明日食谱 + 采购清单，月末生成下月计划 | Python3 + PyYAML + Shell + 飞书 Webhook | [meal/README.md](meal/README.md) · [meal/WORKFLOW.md](meal/WORKFLOW.md) |
| [`team/`](team/) | 通过 `lark-cli` 读写飞书文档、采集会议纪要、维护团队记忆库、推送项目风险 | Python3 + Shell + Node.js + lark-cli | [team/CLAUDE.md](team/CLAUDE.md) |
| [`ppt-slide-formatter/`](ppt-slide-formatter/) | 小鹏自动驾驶仿真算法 15 页可编辑网页版 PPT（HUD 深色科技风格） | Vite + 原生 JS/HTML/CSS | [ppt-slide-formatter/package.json](ppt-slide-formatter/package.json) |

---

## 根触发层

任何触发源（飞书消息、外部调度器）都只调用统一入口：

```bash
bash /workspace/lingxi-trigger.sh <task>
```

| task | 动作 | 落到 |
|------|------|------|
| `food` | 推送「明日食谱」到飞书 | `meal/scripts/notify_daily.py` |
| `risk` | 推送「项目风险播报」到飞书 | `team/scripts/risk-push.py` |
| `sync` | 采集会议纪要 / 主文档更新并更新记忆 | `team/scripts/daily-sync.sh` |

Pod 重启后补依赖：

```bash
bash /workspace/bootstrap.sh
```

---

## 部署说明

本工作空间部署在 Agent Pod。工程文件（`/workspace`）与飞书授权（`/platform/.lark-cli`）在持久盘，Pod 重启不丢；PyYAML、crontab、cron 守护进程在容器临时层，重启后由 `bootstrap.sh` / 各项目 `setup.sh` 恢复。
