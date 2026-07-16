# cron/ — 定时任务集中管理

所有 cron 定时任务的入口脚本、安装脚本和配置集中在此目录。

## 目录结构

```
cron/
├── install.sh              # 一键安装 crontab（替换现有 crontab）
└── scripts/                # 各任务入口脚本
    ├── daily-sync.sh       # 每天 22:00 — 数据同步
    ├── risk-push.sh        # 每天 09:00 — 项目风险播报
    ├── week-label.sh       # 每周一 08:00 — 更新周标题
    ├── meal-notify.sh      # 每天 18:00 — 食谱推送
    ├── meal-generate-month.sh  # 每月最后一天 20:00 — 生成下月计划
    └── meal-check-feedback.sh  # 每 2 小时 — 检查群反馈
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
