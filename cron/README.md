# cron/ — 定时任务集中管理

所有 cron 定时任务的入口脚本、安装脚本和配置集中在此目录。

## 目录结构

```
cron/
├── install.sh              # 一键安装 crontab（替换现有 crontab）
├── jobs/                   # Python 任务脚本
│   ├── ai_news.py          # AI 圈头部 10 条新闻
│   ├── chat_summary.py     # Chat 汇报（早/中/晚）
│   └── stock_pick.py       # 10 支最具投资价值股票
└── scripts/                # 各任务入口脚本
    ├── daily-sync.sh       # 每天 22:00 — 数据同步
    ├── risk-push.sh        # 每天 09:00 — 项目风险播报
    ├── week-label.sh       # 每周一 08:00 — 更新周标题
    ├── ai-news.sh          # 每天 09:00 — AI 圈头部 10 条新闻
    ├── stock-pick.sh       # 每天 09:00 — 10 支最具投资价值股票
    ├── morning-chat.sh     # 每天 09:00 — 上午 chat 汇报
    ├── noon-chat.sh        # 每天 12:00 — 中午 chat 汇报
    ├── evening-chat.sh     # 每天 18:00 — 下午 chat 汇报
    ├── meal-notify.sh      # 每天 18:00 — 食谱推送
    └── meal-generate-month.sh  # 每月最后一天 20:00 — 生成下月计划
```

## 安装

```bash
bash cron/install.sh
```

## 修改任务

1. 编辑对应的 `cron/scripts/xxx.sh`
2. 如需调整时间或增删任务，编辑 `cron/install.sh` 中的 heredoc
3. 重新运行 `bash cron/install.sh` 生效

## 查看当前 crontab

```bash
crontab -l
```
