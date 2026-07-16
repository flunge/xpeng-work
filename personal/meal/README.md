# 🍳 家庭食谱系统

一家四口（夫妻 + 5岁/7岁男孩）的自动化食谱管理。每晚 18:00 飞书推送次日食谱与备餐清单；每月底自动生成下月不重样计划。

> 规则「宪法」见 [`../.claude/RECIPE_RULES.md`](../.claude/RECIPE_RULES.md)、完整工作流见 [`../.claude/WORKFLOW.md`](../.claude/WORKFLOW.md)、数据架构总览见 [`../.claude/CLAUDE.md`](../.claude/CLAUDE.md)。

---

## 一、和云端（飞书）的关联方式

**内容数据全部在飞书**（配方 / 月计划 / 每日卡片 / 配置），多 agent 协作共享；本地只留脚本 + 一份映射。

### 飞书对象与 token

根文件夹：<https://xiaopeng.feishu.cn/drive/folder/IVBgfymaolzx9Bdbpbsc1VPGnAc>

| 飞书对象 | 类型 | token | 内容 |
|----------|------|-------|------|
| 家庭配方库 | Base 多维表格 | `KZZabRArpa2hRasr4oDcpuRWn03`（表 `tblySaVfOXOoyCk8`） | 94 个配方 |
| 月度计划 | 文件夹 | `PeCkfAaTAlJpGbdUYkNc7ICPndg` | 月概览 `YYYY-MM.md` |
| 每日菜谱 | 文件夹 | `QiVWfg2BplEYBVdtUYEcpdDUnac` | 每日卡片 `YYYY-MM-DD.md` |
| 配置与规则 | 文件夹 | `X5nHfR7xDlrn4hdHEYpcxOYgnmb` | family/holidays/vacations.yaml + 规则文档 |

这些 token 全部固化在 [`config/feishu.yaml`](config/feishu.yaml)。**换文件夹 / 换表只改这一处**，脚本不含硬编码 token。

### 关联是怎么建立的

- 所有飞书读写都走命令行工具 **`lark-cli`**（需已登录授权，与 team 脚本共用同一套授权）。
- 脚本不直接调 `lark-cli`，而是经数据层 [`scripts/feishu_data.py`](scripts/feishu_data.py) 统一封装。它读 `config/feishu.yaml` 拿 token，再拼 `lark-cli` 命令。

### 配方库 Base 的关键设计（一行 = 一个配方）

- 标量字段拆成独立列（`类型`/`难度`/`星期`/`周次`/`份数`/`系列`/`总耗时`/`厨具`/`标签`/`食材标签`…），供飞书筛选、多 agent 直接编辑。
- 深度嵌套的食材、做法渲染成可读长文本列（`食材`/`做法`）。
- 另有 **`原始YAML` 列**存整份 YAML 原文——脚本用它 `yaml.safe_load` 无损还原为原本的嵌套 dict，故生成器逻辑零改动。
- ⚠️ **新增 / 修改配方时，结构化列与「原始YAML」列都要同步更新**（脚本只认「原始YAML」列）。

### 数据流

```
生成月计划:  飞书 Base(读配方) ─▶ generate_month.py ─▶ 本地生成 md ─▶ 回传飞书「月度计划」「每日菜谱」
每日推送:    飞书「每日菜谱」(下载当日卡片) ─▶ notify_daily.py ─▶ 飞书群/单聊消息
配置读取:    飞书「配置与规则」─▶ 拉到 .feishu_cache/ ─▶ 脚本读取
```

---

## 二、目录结构

```
personal/meal/
├── config/
│   ├── feishu.yaml       # 飞书数据源映射（Base / 各文件夹 token）—— 唯一需维护的关联配置
│   └── webhook.yaml      # 旧群 webhook（已废弃，改用 app 机器人单聊；不上传飞书）
├── scripts/
│   ├── feishu_data.py    # 飞书数据层：Base/云盘读写的统一封装
│   ├── generate_month.py # 月度计划生成器（从飞书读配方，生成后回传飞书）
│   ├── notify_daily.py   # 每日飞书推送（本地无卡片则从飞书下载）
│   ├── run_daily.sh          # run_daily 包装：调 notify_daily.py
│   ├── generate_next_month.sh # 月末包装：生成下月计划
│   ├── check_feedback.py/.sh  # 群反馈检查
│   └── check_dup.py / check_breakfast.py / qc_plan.py  # 质检工具
├── setup.sh              # 环境引导（装 PyYAML + crontab）
├── README.md
└── .feishu_cache/        # 运行时从飞书拉取的缓存（gitignore，勿入库）
```

> 本地**不再有** `recipes/`、`plans/` 目录——配方在 Base，计划/卡片在飞书文件夹。生成器运行时会临时生成本地 `plans/` 再回传，该目录已 gitignore。

---

## 三、运行前置

```bash
pip3 install --break-system-packages pyyaml   # 数据层依赖 PyYAML
lark-cli --version                            # 需已登录授权（读写飞书）
```

Pod 重启后一键恢复（装依赖 + crontab）：

```bash
bash /workspace/personal/meal/setup.sh
```

---

## 四、常用命令

```bash
cd /workspace/personal/meal

# 生成指定月份计划：从飞书读配方 → 生成 → 自动回传飞书
python3 scripts/generate_month.py --year 2026 --month 9

# 只在本地生成、不回传飞书（调试用）
python3 scripts/generate_month.py --year 2026 --month 9 --no-upload

# 推送今日/明日通知（北京 18:00 前=今日，之后=明日；本地无卡片自动从飞书下载）
python3 scripts/notify_daily.py
python3 scripts/notify_daily.py --date 2026-09-15   # 指定日期

# 自检数据层：打印从 Base 读回的各类配方数量
python3 scripts/feishu_data.py

# 质检（生成后必跑，校验跨餐主食不撞车）
python3 scripts/qc_plan.py --months 6,7,8
```

`feishu_data.py` 对外函数：`load_all_recipes(type)`（从 Base 还原配方）、`load_config(name)`（拉 config 缓存）、`upload_plans(dir)` / `upload_daily(dir)`（回传飞书）、`fetch_daily_card(date)`（下载单日卡片）。生成器/推送脚本优先走这些函数，数据层不可用时自动回退本地文件。

> ⚠️ `lark-cli` 的 `+pull`/`+push`/`+download` 的 `--local-dir`/`--output` 必须是**相对 cwd 的路径**；数据层统一以 meal 根为 cwd、传相对路径，改动这些函数时务必保持。

---

## 五、如何添加 / 修改配方

配方在飞书「家庭配方库」Base。新增一行时，结构化列（标题/类型/难度…）与 **`原始YAML` 列**都要填——脚本只认「原始YAML」列做无损还原。YAML 格式：

```yaml
title: "菜名"
type: breakfast          # breakfast/lunch/dinner/side/lunch_quick/special
difficulty: easy
total_time: "用时描述"
servings: 4
tools: [工具1, 工具2]
ingredients:
  菜品1:
    - name: 食材名
      amount: 分量
      note: 备注（可选）
night_prep: ["前一晚可做的操作"]
morning_steps: ["早上操作步骤"]   # 早餐用；快手午餐用 noon_steps
notes: "注意事项"
```

新增/改配方、跑生成器前请遵循 [`../.claude/RECIPE_RULES.md`](../.claude/RECIPE_RULES.md)（食谱「宪法」：份量/口味/烹饪约束/早餐三件套/午晚定位/食材经济）与 [`../.claude/WORKFLOW.md`](../.claude/WORKFLOW.md)。
