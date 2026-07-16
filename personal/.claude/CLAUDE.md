# personal 工作区指南

> `personal/` 是个人自动化项目区，与 `team/` 并列、互相独立。当前含 `meal/`（家庭食谱系统）。
> 助手在此区工作时，除遵循根 `.claude/CLAUDE.md` 的通用规则外，另遵循本文件。

## 一、meal 数据架构（2026-07-16 全量迁飞书后）

meal 的**内容数据全部在飞书**，本地只保留脚本与飞书映射。飞书根文件夹
`IVBgfymaolzx9Bdbpbsc1VPGnAc`（多 agent 协作共享）下：

| 飞书对象 | token | 内容 |
|----------|-------|------|
| 家庭配方库（Base 多维表格） | `KZZabRArpa2hRasr4oDcpuRWn03` / 表 `tblySaVfOXOoyCk8` | 94 个配方 |
| 月度计划（文件夹） | `PeCkfAaTAlJpGbdUYkNc7ICPndg` | 月概览 md |
| 每日菜谱（文件夹） | `QiVWfg2BplEYBVdtUYEcpdDUnac` | 每日卡片 md |
| 配置与规则（文件夹） | `X5nHfR7xDlrn4hdHEYpcxOYgnmb` | family/holidays/vacations.yaml + 规则文档 |

映射固化在 `meal/config/feishu.yaml`，脚本据此定位飞书。**改 token 只改这一处。**

### 配方库 Base 的关键设计
- **一行 = 一个配方**。标量字段（类型/难度/星期/周次/份数…）拆成独立列，供飞书筛选、多 agent 直接编辑。
- 深度嵌套的食材、做法渲染成可读长文本列（`食材`/`做法`）。
- 另有 **`原始YAML` 列**存整份 YAML 原文——脚本 `yaml.safe_load` 无损还原为原本的嵌套 dict，故生成器逻辑零改动。**新增/改配方时，结构化列与「原始YAML」列都要同步更新**（脚本只认「原始YAML」列）。

## 二、脚本数据层 `meal/scripts/feishu_data.py`

所有飞书读写经此模块（用命令行 `lark-cli`，与 team 脚本一致）：
- `load_all_recipes(type)` — 从 Base 读「原始YAML」还原配方（替代原本的本地 `recipes/*.yaml` glob）。
- `load_config(name)` — 从飞书「配置与规则」拉取 config 到 `.feishu_cache/`（运行缓存，已 gitignore）后读取。
- `upload_plans(dir)` / `upload_daily(dir)` — 生成后推送月计划/每日卡片到飞书。
- `fetch_daily_card(date)` — 推送通知时，本地无卡片则从飞书下载。

`generate_month.py` / `notify_daily.py` 已改为优先走 `feishu_data`；模块不可用时（离线调试）自动回退本地文件，故接口签名保持不变。

⚠️ **lark-cli 路径约束**：`+pull`/`+push`/`+download` 的 `--local-dir`/`--output` 必须是**相对 cwd 的路径**。数据层统一以 `BASE_DIR`（meal 根）为 cwd、传相对路径，改动这些函数时务必保持。

## 三、常用命令

```bash
cd /workspace/personal/meal
python3 scripts/generate_month.py --year 2026 --month 9      # 生成并同步飞书
python3 scripts/generate_month.py --year 2026 --month 9 --no-upload  # 只本地生成
python3 scripts/notify_daily.py                              # 推送今日/明日食谱
python3 scripts/feishu_data.py                               # 自检：打印各类配方数
```

QC 工具（`check_dup.py` / `check_breakfast.py` / `qc_plan.py`）分析本地生成的
`plans/daily/*.md`，用法不变；生成器改逻辑后必跑 `qc_plan.py` 校验跨餐主食不撞车。

## 四、食谱规则

新增/修改配方、跑生成器前，遵循同目录下：
- [`RECIPE_RULES.md`](RECIPE_RULES.md) — 食谱系统「宪法」（家庭份量、口味、烹饪约束、早餐三件套、午晚定位、食材经济等）。⚠️ 其中 `recipes/dinner/`、`recipes/lunch/` 等路径描述沿用迁飞书前的分类语义——现对应 Base「类型」列的取值（dinner=硬菜池给午餐、lunch=简餐池给晚餐，故意错位），生成器已做交换映射。
- [`WORKFLOW.md`](WORKFLOW.md) — 生成/推送/质检的完整工作流。

## 五、安全

- `meal/config/webhook.yaml` 含飞书 webhook URL（已废弃，脚本改用 app 机器人单聊推送）——**不上传飞书共享文件夹**，不输出其内容。
- 临时产物放 `team/tmp/`（全局约定），用完即弃。
