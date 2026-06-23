# 🍳 家庭食谱系统 — 工作流文档

> 一家四口（夫妻 + 5岁/7岁男宝）的自动化食谱管理。
> 口味：不辣、少油少盐、儿童友好。

---

## 📋 系统架构总览

```
meal/
├── config/                  # ← 配置文件（家庭信息、节假日、Webhook）
├── recipes/                 # ← 食谱库（YAML格式，早餐27道/午餐10道/晚餐10道/加菜8道）
├── plans/                   # ← 生成的月计划、每日卡片（自动生成）
├── scripts/                 # ← 自动化脚本（核心工作流）
└── notifications/           # ← 通知日志
```

**核心技术栈：** Python3（标准库 + PyYAML）+ Shell（cron）+ 飞书 Webhook API

---

## 🔁 完整工作流

### 1️⃣ 月度计划生成（每月最后一天 20:00 自动触发）

**触发：** `generate_next_month.sh` → `generate_month.py`

```
gen_next_month.sh      generate_month.py
┌─────────────┐        ┌───────────────────┐
│ 检查是否     │──▶    │ 1. 加载食谱库     │
│ 本月最后一天  │        │    - recipes/breakfast/*.yaml
└─────────────┘        │    - recipes/lunch/*.yaml     ◀── 食谱库
                        │    - recipes/dinner/*.yaml
                        │ 2. 加载节假日配置  │ ◀── holidays-2026.yaml
                        │ 3. 遍历每天：      │
                        │    · 工作日 → 仅早餐
                        │    · 周末/节假日 → 早+午+晚餐
                        │      （午/晚餐各 +1 加菜，凑齐 3 菜）
                        │ 4. 食材标签聚类     │
                        │    （连续日共享食材，减少浪费）
                        │ 5. 输出：          │
                        │    ┌──────────────┤
                        │    │ plans/2026-06.md       ← 月概览
                        │    │ plans/daily/*.md       ← 16-30张每日卡片
                        │    └──────────────┤
                        └───────────────────┘
```

#### 核心逻辑：`generate_month.py`

| 函数 | 职责 |
|---|---|
| `load_all_recipes()` | 按类型（breakfast/lunch/dinner/side）加载所有 YAML 食谱 |
| `get_day_type()` | 判断每天类型：workday / weekend / holiday（含调休） |
| `pick_recipes()` | 食材聚类选择：优先选 adjacent day 共享 ingredient_tags 的食谱 |
| `pick_side()` | 全餐日加菜选择：食材聚类 + 用尽自动重置 + 同天午/晚不重复 |
| `generate_month_plan()` | 主循环：生成全月计划（一天一行，标记三餐 + 加菜） |
| `write_daily_card()` | 为每天写详细 Markdown（含食材、步骤、加菜、采购清单） |
| `format_monthly_markdown()` | 生成本月概览表格 |

**关键设计：**
- 早餐池 27 道，一个月工作日 ~22 天，基本不重复
- `ingredient_tags` 用于 cross-day 聚类：昨天用了鸡蛋，今天选也用鸡蛋的菜
- 节假日自动识别（国务院 2026 年安排，含调休日）

---

### 2️⃣ 每日通知发送（每天 18:00 自动触发）

**触发：** `run_daily.sh` → `notify_daily.py`

```
run_daily.sh           notify_daily.py
┌─────────────┐        ┌───────────────────┐
│ cd to meal/  │──▶    │ 1. 读明日卡片      │ ◀── plans/daily/YYYY-MM-DD.md
└─────────────┘        │ 2. 解析 Markdown   │
                        │    提取：早餐/午餐/晚餐/采购清单
                        │ 3. 构建飞书卡片     │
                        │    · 蓝色 header + 互动卡片
                        │    · 每餐分区展示
                        │    · 采购清单 + 脚注提示
                        │ 4. POST → Webhook │ ◀── config/webhook.yaml
                        │ 5. 记日志          │ → notifications/send.log
                        └───────────────────┘
```

**飞书卡片内容示例：** 明天日期 + 星期 + 节假日标签 → 早餐（标题/用时/工具/前一晚准备）→ 午餐（标题/食材/做法）→ 晚餐 → 采购清单 → 温馨脚注

**容错：**
- 无明日卡片 → 提示需先生成月计划
- Webhook 失败 → HTTP/网络/异常三层捕获 + 日志
- 飞书卡片格式备选：纯文本回退

---

### 3️⃣ 每周采购规划（手动触发，建议每周日用）

**触发：** `python3 scripts/weekly_shop.py [--week 周数]`

```
weekly_shop.py
┌────────────────────────────────────┐
│ 1. 确定周数范围（周一~周日）        │
│ 2. 扫描本周所有每日卡片             │ ◀── plans/daily/*.md
│ 3. 提取所有食材去重聚合             │
│ 4. 按保质期分类：                   │
│    🔴 鲜（3天内）→ 绿叶菜/嫩豆腐/鲜肉等
│    🟡 耐（1周内）→ 根茎/蛋奶/火腿等
│    🟢 存（长期） → 干货/调料/冷冻品
│ 5. 输出：                          │
│    · 按保鲜期的食材清单 + 频次      │
│    · 跨菜共享食材提示               │
│    · 单次易耗品预警                 │
│    · 按超市分区的采购清单           │
│    · 采购策略建议                   │
└────────────────────────────────────┘
```

---

### 4️⃣ 反馈监控（✅ 已修复，可用）

**触发：** `check_feedback.sh`（每 2 小时）→ `check_feedback.py`

- 通过 `lark-cli` 拉取群最近 50 条消息
- 关键词匹配（"不好吃"、"换一个"、"太油" 等）
- 保存到 `notifications/feedback.md`

> ✅ 当前状态：`lark-cli`（v1.0.55）已安装并完成飞书用户授权，脚本端到端跑通。
> 飞书授权配置持久化在 `/platform/.lark-cli/`，无需每次重新授权。

---

## 📦 组件详情

### 配置文件 (`config/`)

| 文件 | 内容 | 作用域 |
|---|---|---|
| `family.yaml` | 家庭成员、饮食限制、厨具清单、时间约束 | 全局 |
| `holidays-2026.yaml` | 7 个节假日 + 调休日 | 年度 |
| `webhook.yaml` | 飞书群机器人 URL + 发送时间 | 每日通知 |

### 食谱库 (`recipes/`)

每个 YAML 文件一道菜（组合餐），结构：

```yaml
title: "菜名"                  # 显示名称
type: breakfast                # breakfast / lunch / dinner
difficulty: easy               # 难度
total_time: "25分钟"           # 用时描述
servings: 4                    # 份量
tools: [破壁机, 不粘煎锅]      # 所需工具
tags: [快手, 蔬菜]             # 分类标签
ingredient_tags: [鸡蛋, 牛奶]  # 食材标签（用于聚类）
ingredients:                   # 食材清单（分 section）
  主食类:
    - name: 鸡蛋; amount: 3个; note: 可选备注; optional: false
night_prep: [前一晚操作]        # 前一晚备餐步骤
morning_steps: [早上操作]       # 早餐早上步骤（≤30 分钟）
steps: [操作步骤]              # 午/晚餐步骤
notes: 注意事项
```

**库存：** 早餐 27 道 · 午餐 10 道 · 晚餐 10 道 · 加菜 8 道（`recipes/side/`，节假日/周末为午晚餐各补 1 道，凑齐 3 菜）

### 计划文件 (`plans/`)

| 文件类型 | 生成方式 | 示例 |
|---|---|---|
| 月度概览 | `plans/2026-06.md` | 全月日历 + 每餐摘要 |
| 每日卡片 | `plans/daily/2026-06-18.md` | 当日完整食材/步骤/采购清单 |

### 自动化脚本 (`scripts/`)

| 脚本 | 触发 | 频率 | 状态 |
|---|---|---|---|
| `generate_month.py` | `generate_next_month.sh` | 月 | ✅ 正常 |
| `notify_daily.py` | `run_daily.sh` | 日 | ✅ 正常 |
| `weekly_shop.py` | 手动 | 按需 | ✅ 正常 |
| `check_feedback.py` | `check_feedback.sh` | 2h | ✅ 正常（lark-cli 已就绪） |

---

## 🕒 时间调度

```
cron 定时任务：

每天 18:00       → run_daily.sh       → 发送明日食谱通知
每月最后一天 20:00 → generate_next_month.sh → 生成下月食谱计划
每 2 小时         → check_feedback.sh  → 检查群反馈（当前不可用）
```

---

## 🧪 手动操作

```bash
cd /workspace/meal

# 生成指定月份计划
python3 scripts/generate_month.py --year 2026 --month 7

# 手动发送明日通知
python3 scripts/notify_daily.py

# 查看本周采购规划
python3 scripts/weekly_shop.py

# 查看指定周
python3 scripts/weekly_shop.py --week 26
```

---

## ➕ 添加新食谱

1. 在 `recipes/breakfast/`、`recipes/lunch/` 或 `recipes/dinner/` 下创建新的 `.yaml` 文件
2. 文件命名建议：`两位编号-中文菜名.yaml`（如 `28-番茄疙瘩汤-鸡蛋饼.yaml`）
3. 参考现有 YAML 格式填写
4. 注意填写 `ingredient_tags`（用于聚类优化）和 `tools`（用于工具提醒）
5. 重新运行 `generate_month.py` 生成含新食谱的计划

---

## 🔧 系统依赖

| 依赖 | 用途 | 安装方式 |
|---|---|---|
| Python 3 | 运行所有脚本 | 系统自带 |
| PyYAML | YAML 解析 | `pip3 install --break-system-packages pyyaml`（由 `setup.sh` 自动处理） |
| 飞书 Webhook | 消息推送 | 配置 webhook.yaml |
| lark-cli ✅ | 反馈监控 | 已就绪（v1.0.55），授权持久化在 `/platform/.lark-cli/` |

---

## 📊 运行日志

| 日志文件 | 内容 |
|---|---|
| `notifications/send.log` | 每日通知发送记录 |
| `notifications/cron.log` | cron 执行日志 |
| `notifications/feedback_cron.log` | 反馈检查错误日志 |

---

## 💾 持久化与重启恢复（部署在 Agent Pod）

本系统部署在 Agent Pod 环境，存储分两层：

| 内容 | 位置 | Pod 重启后 |
|---|---|---|
| 工程文件（`/workspace/meal` 全部） | 持久盘 `/dev/nvme1n1` | ✅ 保留 |
| lark-cli 飞书授权（`/platform/.lark-cli/`） | 持久盘 | ✅ 保留（无需重新授权） |
| lark-cli 二进制、PyYAML、crontab、cron 守护进程 | 容器临时层（overlay） | ❌ 丢失 |

**重启后一键恢复：**

```bash
bash /workspace/meal/setup.sh
```

`setup.sh` 会补装 PyYAML、校验 lark-cli 与授权、重装 crontab、启动 cron 守护进程。脚本幂等，可重复运行。
（如不想自动启动 cron 守护进程：`SKIP_CRON_DAEMON=1 bash /workspace/meal/setup.sh`）

---

## ⏰ 定时调度安装

定时任务通过 crontab 管理（`setup.sh` 会自动安装）：

```cron
0 18 * * *     /workspace/meal/scripts/run_daily.sh          # 每日 18:00 发送明日食谱
0 20 28-31 * * /workspace/meal/scripts/generate_next_month.sh # 月末 20:00 生成下月计划
0 */2 * * *    /workspace/meal/scripts/check_feedback.sh      # 每 2 小时检查群反馈
```

用 `crontab -l` 查看，`pgrep -x cron` 确认守护进程运行中。

---

## 🚧 已知问题 & 改进方向

1. **无依赖管理** — 没有 `requirements.txt`，新环境依赖 `setup.sh` 安装 PyYAML
2. **节假日硬编码** — `holidays-2026.yaml` 仅为 2026 年，2027 年需更新
3. **食谱分散** — 目前所有食谱在 YAML 中，没有在线管理界面
4. **无食材库存管理** — 采购规划基于计划，不跟踪家中已有库存
