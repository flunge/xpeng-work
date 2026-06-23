# 仿真部 - 飞书工作空间交互

> **核心定位**：本项目通过 `lark-cli` 与飞书工作空间进行交互，包括读文档、写文档、内容调整等。

---

## 零、启动时自动同步（数字分身每日更新）

### 核心原则

> **daily-sync JSON 只是索引/指针，不是事实源。严禁从 JSON 摘要直接写 memory。**

### 启动检查

```bash
ls /Users/xpeng/Documents/team/memory/daily-sync/*.json 2>/dev/null | while read f; do
  date=$(basename "$f" .json)
  last=$(cat /Users/xpeng/Documents/team/memory/daily-sync/.last-processed 2>/dev/null || echo "2026-01-01")
  if [[ "$date" > "$last" ]]; then
    echo "New sync data: $date"
  fi
done
```

### 处理流程（有序，不可跳过）

有新的 daily-sync 文件时，**必须严格按以下步骤执行**：

#### 步骤清单

```
□ Phase 1: 盘点 — 从 JSON 列出所有待读取的源文档 URL
□ Phase 2: 源文档读取 — 逐篇读取，不可跳过
□ Phase 3: 聊天上下文 — 补读父消息和链接文档
□ Phase 4: 人物画像更新 — 从源文档提取行为/性格观察
□ Phase 5: 记忆写入 — 每条事实标注出处
□ Phase 6: 自检 — 逐条核查"三不写"
```

#### Phase 1: 盘点源文档

从 JSON 中提取所有待读取的 URL 清单：
- `meeting_docs` 中的每个会议纪要（智能纪要）
- **每个智能纪要中「相关链接 → 文字记录」的链接**（逐字稿，[[meeting-reading-rules]]）
- `wiki_doc` 中的 Wiki 文档
- IM `@me` 消息中包含的飞书文档/Wiki URL
- IM 成员搜索结果中可能包含的链接

#### Phase 2: 源文档读取（强制）

| 必须读 | 读取方式 | 原因 |
|--------|---------|------|
| **会议文字记录（逐字稿）** 🔴 | `docs +fetch --doc-format markdown` | 看到每个人实际说了什么、语气、真实关注点。AI摘要丢失个体声音 |
| 会议智能纪要 | `docs +fetch --doc-format markdown` | 理解会议主题和结论框架 |
| Wiki 文档 | `docs +fetch --doc-format markdown` | 了解最新业务文档内容 |
| 聊天中的文档链接 | `docs +fetch --doc-format markdown` | 理解消息引用的实际内容 |

- **智能纪要中必有「相关链接 → 文字记录」**，必须同时读取
- **跨文档搜索项目/人名时，用 `--scope keyword`**，不下载全文
- 每个文档读取后用 3 句话总结：①主题 ②谁说了什么关键话 ③与我组的关系

#### Phase 3: 聊天上下文

- 有 `reply_to` 的消息 → **必须读取父消息**（`lark-cli im +messages-mget --message-ids "<parent_id>"`）
- 消息中包含飞书 URL → **必须读取该 URL 指向的文档**
- 成员搜索结果中有技术讨论 → 评估是否需要扩展读取上下文
- **🔴 关键词搜索到消息后，必须读取对应 p2p/群聊的上下文**：`im search` 只能搜到含关键词的消息，搜不到不含关键词的回复。搜到一条消息后，用 `im +chat-messages-list --chat-id "<id>" --start/--end` 读前后的完整对话，确认是否有老板/关键人物的回复被遗漏

#### Phase 4: 人物画像更新

从源文档中提取并更新每个人的人物画像（[[people/_index]]）：

| 来源 | 提取什么 | 更新目标 |
|------|---------|---------|
| 逐字稿 | 发言内容、语气、追问模式、主动/被动、被谁cue | `people/<name>.md` |
| 智能纪要 | 被分配到什么待办、承担什么角色 | people + projects |
| IM 消息 | 谁@了谁、回复速度、表达风格、群内参与度 | `people/<name>.md` |
| 文档 | 谁写了什么文档、什么风格 | people |

**每个在岗组员 + 高炳涛，每次同步至少检查是否有新观察可写入 `people/<name>.md`。**

#### Phase 5: 记忆写入

**写入前必读**：OKR文档 `LpbTdfU95oDnnTx5LmAc7Q1WnVg` 是项目边界的基准——创建/更新任何项目文件前，先确认其OKR归属、执行Owner、验收标准。

**三级记忆更新体系**（按新结构）：

| 类型 | 文件位置 | 更新内容 |
|------|---------|---------|
| **线1：人物** | `people/<name>.md` | 性格观察、工作进展、项目变动 |
| **线2：团队** | `teams/*.md` | 架构变化、协作关系 |
| **线3：事情** | `projects/<track>/<project>.md` | 里程碑、状态变化、风险 |
| **洞察** | `insights/chat-log.md` | 群聊关键决策、新事件 |

**关联更新规则**：
- 项目换了owner → 旧owner的项目列表删该项目，新owner加
- 人离职 → 移入 `people/_departed/`，遍历其所有项目更新owner
- 项目完成 → 移入 `projects/<track>/_archive/`，从相关人员projects列表移除

**每条关键事实必须能在源文档中找到原文支撑。**

#### Phase 6: 自检（逐条核查）

写入 memory 前，对每条声明自问：

```
□ 这句话是从哪里来的？能指到具体文档/消息吗？
□ 涉及哪个 project？对应 projects/<track>/<name>.md 更新了吗？
□ 涉及哪个人物？对应 people/<name>.md 更新了吗？
□ 双向索引：people/_index.md 的交叉矩阵是否同步了？
□ 我是读了源文档，还是从 JSON 摘要脑补的？
□ 有没有我没读但应该读的链接？
□ 核对标准："高炳涛/老板在这个会上具体说了哪几句话？" — 答不上来说明没读逐字稿
```

#### 「三不写」规则

1. **没有读源文档的声明 → 不写**（标记为 `[待验证]` 可以写）
2. **从消息摘要脑补的推断 → 不写**
3. **无法用原文引证的关键决策 → 不写**

---

### 自动采集机制

macOS LaunchAgent 每天22:07运行脚本，采集数据存为 `daily-sync/YYYY-MM-DD.json`。
- 脚本位置：`scripts/daily-sync.sh`（项目根目录下）
- Plist 位置：`~/Library/LaunchAgents/com.xpeng.claude-daily-sync.plist`
- 检查 LaunchAgent 状态：`launchctl list | grep claude-daily`

---

## 一、身份与认证

### 默认身份

- **所有操作默认使用 `--as user`**（用户身份），除非用户明确说"以应用/bot 身份"
- 原因：bot 看不到用户的文档、日历、云空间等个人资源

### 认证处理

- 遇到权限错误时，按 `lark-shared` skill 的 split-flow 流程处理
- 发起授权：`lark-cli auth login --scope "<scope>" --no-wait --json`
- 从输出提取 `verification_url` 和 `device_code`，生成二维码给用户
- 用户确认后：`lark-cli auth login --device-code <device_code>`
- **禁止缓存 verification_url/device_code**，每次需要授权时必须重新生成

### 安全规则

- 禁止输出密钥（appSecret、accessToken）
- 写入/删除操作前必须确认用户意图
- 高风险操作先用 `--dry-run` 预览
- 遇到 exit code 10（`confirmation_required`）→ 向用户确认后再加 `--yes` 重试

---

## 二、读文档（核心工作流）

### 飞书文档 / Wiki 文档

**直接用 `docs +fetch` 读取，不要每次都去读 skill 文件：**

```bash
# 读取文档全文（XML格式，默认）
lark-cli docs +fetch --api-version v2 --doc "<URL或token>" --format json

# 读取文档（Markdown格式）
lark-cli docs +fetch --api-version v2 --doc "<URL或token>" --doc-format markdown --format json

# 先看目录（结构未知时优先用）
lark-cli docs +fetch --api-version v2 --doc "<URL或token>" --scope outline --max-depth 3 --format json

# 按关键词定位（大文档/多文档搜索优先用，不下载全文）
lark-cli docs +fetch --api-version v2 --doc "<URL或token>" --scope keyword --keyword "关键词1|关键词2" --format json

# 按章节读取（需要 block_id）
lark-cli docs +fetch --api-version v2 --doc "<URL或token>" --scope section --start-block-id <标题id> --format json

# 带 block ID（用于后续编辑定位）
lark-cli docs +fetch --api-version v2 --doc "<URL或token>" --detail with-ids --format json
```

- **`--api-version v2` 必须显式传入，不可省略**
- 支持 `/docx/` 和 `/wiki/` 两种 URL
- `--scope` 参数：`outline` | `section` | `range` | `keyword`（省略=读整篇）
- `--detail` 参数：`simple`（默认，只读）| `with-ids`（定位）| `full`（编辑）

### 飞书电子表格

- 文档中嵌入的 `<sheet token="..." sheet-id="...">` → 切到 `lark-sheets` skill
- 用 `lark-cli sheets +fetch --sheet "<token>" --sheet-id "<sheet-id>" --format json` 读取

### 飞书多维表格（Base）

- 文档中嵌入的 `<bitable token="..." table-id="...">` → 切到 `lark-base` skill

### 文档内嵌资源

- `<img>` / `<source>` 带 `url` → 直接用 HTTP GET 下载
- 无 `url` 或预览 → `lark-cli docs +media-preview --token <token>`
- 下载或画板 → `lark-cli docs +media-download --token <token>`

---

## 三、写文档

### 创建文档

```bash
lark-cli docs +create --api-version v2 --content '<title>标题</title><p>内容</p>' --format json
```

### 编辑已有文档

```bash
# 追加内容
lark-cli docs +update --api-version v2 --doc "<URL或token>" --command append --content '<p>新内容</p>'

# 字符串替换
lark-cli docs +update --api-version v2 --doc "<URL或token>" --command str_replace --find "旧文本" --replace "新文本"

# Block 级操作（需要先 fetch 拿到 block_id）
lark-cli docs +update --api-version v2 --doc "<URL或token>" --command block_insert_after --block-id <id> --content '...'
lark-cli docs +update --api-version v2 --doc "<URL或token>" --command block_replace --block-id <id> --content '...'
lark-cli docs +update --api-version v2 --doc "<URL或token>" --command block_delete --block-id <id>
```

- 格式选择：创建/整段写入可用 XML 或 Markdown；精准编辑（str_replace/block_*）优先用 XML
- 写文档前如需了解 XML 语法细节，读 `.claude/skills/lark-doc/references/lark-doc-xml.md`

---

## 四、Wiki 知识库操作

### 知识空间管理

```bash
# 列出知识空间
lark-cli wiki +space-list --format json

# 获取节点信息（从 URL 解析 space_id）
lark-cli wiki spaces get_node --params '{"token":"<wiki_token>"}' --format json
```

### 节点操作

```bash
# 创建节点
lark-cli wiki +node-create --space-id <space_id> --parent-id <parent_node_id> --title "标题" --format json

# 列出子节点
lark-cli wiki +node-list --space-id <space_id> --parent-id <node_id> --format json

# 移动节点
lark-cli wiki +move --node-token <token> --target-space-id <space_id> --target-parent-id <node_id>
```

---

## 五、操作原则

1. **读文档前不要反复确认**：看到飞书 URL 直接用 `docs +fetch --api-version v2` 读取
2. **先读目录再精读**：大文档先用 `--scope outline` 看结构，再按需精读
3. **局部优于全量**：能用 `--scope section/keyword/range` 就不要读整篇
4. **文档中有嵌入表格**：主动提取 token 下钻，不要只呈现标签
5. **写操作前确认**：创建、编辑、删除等写操作先向用户确认
6. **优先用 shortcut**：`lark-cli <service> +<verb>` 形式优于直接调 API
7. **不确定时查 skill 参考文档**：`.claude/skills/<service>/references/` 下有详细参数说明
8. **🔴 不懂就问，严禁脑补**：遇到以下情况立即向用户确认，不跳过、不猜测、不瞎写：
   - 不认识的缩写/术语（如 UCP、CPFS、Seal、Hail）→ 问
   - 不确定项目边界（如"数据精简是独立项目还是HIL子任务"）→ 问
   - 不知道某个人是谁（如参会名单里的陌生名字）→ 问
   - 不确定数字/百分比是否准确 → 核实源文档，核实不了就问
   - 发现两个源文档信息矛盾 → 指出矛盾，问哪个为准
9. **🔴 周报铁律：强制输出检查清单**：每次写周报前，必须先输出以下清单，逐项打勾，未全部打勾禁止动笔：

```
□ Step 1: Q2 Wiki W<n>+W<n+1>两个block全文读完？ [ ]
□ Step 2: 两个block内所有嵌套文档逐个读完？ [ ]  共__个
□ Step 3: 本周全部核心日会+组内日会的纪要读完？ [ ]  共__篇
□ Step 4: 本周全部核心日会+组内日会的文字记录读完？ [ ]  共__篇
□ Step 5: 本周全部@我消息+组内群聊+p2p读完？ [ ]  共__条
□ Step 6: 写的每条进展能从源文档追溯到原文？ [ ]
□ Step 7: 逐条过quality-rules.md全部规则？ [ ]
```

清单输出后，逐项执行并勾选。全部✅后才能写第一行字。
   - **Step 1**：读 Q2 Wiki 本周更新 + 所有关联嵌套文档
   - **Step 2**：读本周全部核心日会+组内日会+其他会议的智能纪要和文字记录
   - **Step 3**：读本周全部聊天记录（@我 + 组内群聊 + p2p）
   - 优先级逐个递减。遍历完才能动笔。违例：跳过任一步骤直接写
10. **🔴 写前必读规则，不靠记忆**：以下场景在动笔前，必须先用 Read 工具打开对应的规则文件读一遍，再写。禁止靠记忆写：
   - 飞书文档 → 先读 `insights/doc-rules.md` + `insights/quality-rules.md`
   - project 文件 → 先读 `insights/quality-rules.md`
   - person 文件 → 先读 `insights/quality-rules.md`
   - 违例：不读规则直接写。记不住规则不是问题，不读规则才是问题
