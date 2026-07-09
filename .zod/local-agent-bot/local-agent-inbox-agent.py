#!/usr/bin/env python3
"""
Local Agent Inbox Agent — 通用 Tool Use + AI 回复

职责：
1. 每 5 秒轮询 incoming_via_bot.jsonl。
2. 发现 pending 的复杂消息后，通过通用 Tool Use 流程处理：
   - 把用户消息 + 可用工具定义传给 Fuyao LLM。
   - LLM 可选择调用本地/飞书/外部工具（以 JSON 形式输出）。
   - 执行工具，拿到结果，再次交给 LLM 总结。
   - 通过 bot 把最终回复发回飞书聊天窗口。
3. 所有交互写入 conversation history 和 human-readable inbox 留痕。

常驻方式：由 launchd UserAgent com.xpeng.local-agent-inbox.plist 管理，KeepAlive=true。
"""

import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent.parent
INBOX_PATH = WORKSPACE / "team" / "memory" / "daily-sync" / "incoming_via_bot.jsonl"
AGENT_INBOX = WORKSPACE / "team" / "memory" / "daily-sync" / "inbox_for_agent.md"
HISTORY_PATH = WORKSPACE / "team" / "memory" / "daily-sync" / "local-agent-conversation.jsonl"
LOG_PATH = WORKSPACE / "team" / "memory" / "daily-sync" / "local-agent-inbox-agent.log"
USER_PREFS_PATH = WORKSPACE / "team" / "memory" / "daily-sync" / "user-preferences.md"
PROJECT_RULES_PATH = WORKSPACE / "team" / "memory" / "daily-sync" / "project-rules.md"

DM_CHAT = "oc_bc5bb378d432fca62a7786e26cf82578"
BOT_APP_ID = "cli_aaad7e4c46f95bb4"
CHECK_INTERVAL = 5
MAX_TOOL_ROUNDS = 10

FUYAO_BASE_URL = "http://fuyao-ai-gateway.xiaopeng.link/v1"
FUYAO_MODEL = "zod-dp4-flash"
KEYCHAIN_SERVICE = "com.xpeng.local-agent-bot.fuyao-key"

SYSTEM_PROMPT = """你是 Local Agent，小鹏员工的本地 AI 助手，运行在用户 Mac 上，通过飞书单聊窗口与用户对话。

你可以调用以下工具来解决用户问题。如果不需要工具，直接回复即可。

工具调用格式（严格 JSON，Markdown 代码块内）：
```tool
{"name": "工具名", "arguments": {"参数名": "值"}}
```
一次可以调用多个工具，返回多个 ```tool``` 代码块。

可用工具：

1. run_lark_cli
   描述：运行任意 lark-cli 命令访问飞书能力（日历、任务、文档、表格、IM等）。
   参数：
   - command: 数组，命令及参数列表。例如 ["lark-cli","calendar","+agenda","get","--date","2026-07-07"]
   - timeout: 可选，超时秒数（默认60）

2. read_file
   描述：读取本地 workspace 文件内容。
   参数：
   - path: 相对 workspace 根目录的路径，例如 "team/memory/food-library.md" 或绝对路径（但必须在 workspace 内）

3. list_files
   描述：列目录内容。
   参数：
   - path: 目录路径，默认 "."
   - glob: 可选通配符，例如 "**/*.md"

4. search_files
   描述：在 workspace 内搜索文件内容。
   参数：
   - pattern: 正则或关键字
   - glob: 可选文件过滤，例如 "*.md"
   - path: 可选起始目录，默认 "."

5. run_shell
   描述：执行安全 shell 命令（用于调用系统工具、python脚本等）。
   参数：
   - command: 字符串
   - timeout: 可选，超时秒数（默认60）
   注意：禁止破坏性操作（rm -rf /、git push --force、DROP DATABASE 等）。

6. trigger_lingxi_task
   描述：触发 lingxi-trigger.sh 里的固定任务（food/risk/sync）。
   参数：
   - task: 任务名，food|risk|sync

7. get_calendar_agenda
   描述：查询某一天的日程/会议安排（默认主日历）。
   参数：
   - date: 日期，格式 YYYY-MM-DD，例如 "2026-07-07"
   - calendar_id: 可选，日历 ID；不传则查主日历

8. edit_file
   描述：修改本地 workspace 文件中的指定文本块（精确替换）。当用户明确说“改/改成/调整/更新”时直接执行；只有请求模糊时才先说明方案并征求意见。
   参数：
   - path: 文件路径
   - old_string: 文件中完全一致的原文本（必须唯一）
   - new_string: 替换后的文本
   注意：如果 old_string/new_string 包含双引号，请优先选择不含双引号的最小唯一片段；无法避免时把双引号替换为中文引号「」。

9. append_to_file
   描述：在本地 workspace 文件末尾追加文本。适合新增规则、日志、列表项等。
   参数：
   - path: 文件路径
   - content: 要追加的内容

10. write_file
    描述：在 workspace 内创建新文本文件。禁止覆盖已存在文件，禁止写敏感后缀（.env/.pem/.key 等）。
    参数：
    - path: 新文件路径
    - content: 文件内容

11. web_search
    描述：通过网络搜索实时信息。
    参数：
    - query: 搜索关键词

重要约束：
- 用中文回复，简洁直接。
- 不确定时诚实说明，不要编造。
- 绝不暴露 API key、token、密码。
- 如果工具返回错误，把错误原因告诉用户。
- 如果需要多步工具调用，请一步步来，每次只输出当前需要的 tool 代码块。
- 调用工具时，只输出 ` ```tool ` 代码块，不要附加任何解释文字；只有通过工具拿到结果后的最终回复才需要自然语言。
- 历史记录只作为上下文参考；当用户询问实时信息（日程、任务、邮件、文档、天气、股票等）时，必须通过工具重新查询，不能依据历史记录中的旧答案作答。
- 如果一次工具调用没有得到想要的信息，不要编造或结束，必须继续调用其他工具，直到问题解决或确认无法解决。
- 涉及饮食、食谱、菜单、本地文档修改时，优先使用 search_files / read_file / edit_file；涉及未来日程时，使用 get_calendar_agenda。
- 如果工具已经返回了足够的信息，立即给出最终回复，不要继续调用工具。
- 每次最多调用 1 个工具，拿到结果后再决定是否需要调下一个。

长期记忆文件（完整相对路径，更新时必须使用这些路径）：
- team/memory/daily-sync/user-preferences.md：记录用户个人偏好、习惯、反馈。每次处理请求前应参考；若用户表达了新的偏好或反馈，使用 edit_file 更新此文件。
- team/memory/daily-sync/project-rules.md：记录项目运行规则、约定、你给 agent 定的约束。若用户给出了新的规则或约束，使用 edit_file 更新此文件。
- 只写入稳定、长期的规则/偏好；不要把单次查询的具体内容写进去，不要写入敏感信息。
"""


def log(msg: str):
    t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{t}] {msg}"
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        print(line, flush=True)


def get_fuyao_key() -> str:
    r = subprocess.run(
        ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode != 0:
        raise RuntimeError("Fuyao API key not found in keychain")
    return r.stdout.strip()


def call_fuyao(messages: list[dict], max_tokens: int = 4000, temperature: float = 0.5) -> str:
    key = get_fuyao_key()
    payload = {
        "model": FUYAO_MODEL,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{FUYAO_BASE_URL}/chat/completions",
        data=data,
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
    return content.strip()


# ==================== 工具函数 ====================

def _resolve_path(rel: str) -> Path:
    p = Path(rel)
    if not p.is_absolute():
        p = WORKSPACE / p
    p = p.resolve()
    # 安全检查：必须在 workspace 内
    try:
        p.relative_to(WORKSPACE.resolve())
    except ValueError:
        raise ValueError(f"path {rel} is outside workspace")
    return p


def _lark_cli(cmd: list[str], timeout: int = 60) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    if out.startswith("{"):
        try:
            parsed = json.loads(out)
            if isinstance(parsed, dict) and parsed.get("ok") is False:
                err_msg = parsed.get("error", {}).get("message", "unknown lark-cli error")
                return f"error: {err_msg}\n{out[:2000]}"
        except Exception:
            pass
    status = f"exit_code={r.returncode}"
    return "\n".join([s for s in [status, out, err] if s])[:20000]


def tool_run_lark_cli(arguments: dict) -> str:
    cmd = arguments.get("command") or []
    if not isinstance(cmd, list) or not cmd:
        return "error: command must be a non-empty list"
    timeout = int(arguments.get("timeout", 60))
    log(f"[tool] run_lark_cli: {' '.join(cmd[:10])}")
    return _lark_cli(cmd, timeout)


def _format_event(event: dict) -> str:
    summary = event.get("summary", "(无标题)")
    start = event.get("start_time", {}).get("datetime", "")
    end = event.get("end_time", {}).get("datetime", "")
    organizer = event.get("event_organizer", {}).get("display_name", "")
    rsvp = event.get("self_rsvp_status", "")
    vc = event.get("vchat", {}).get("meeting_url", "")
    vc_text = f"会议链接: {vc}" if vc else ""
    return (
        f"- {summary}\n"
        f"  时间: {start} ~ {end}\n"
        f"  组织者: {organizer}\n"
        f"  我的状态: {rsvp}\n"
        f"  {vc_text}".strip()
    )


def tool_get_calendar_agenda(arguments: dict) -> str:
    date = arguments.get("date", "")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        return f"error: invalid date format {date}, expected YYYY-MM-DD"
    start = f"{date}T00:00:00+08:00"
    end_dt = datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)
    end = end_dt.strftime("%Y-%m-%dT00:00:00+08:00")
    calendar_id = arguments.get("calendar_id")
    cmd = ["lark-cli", "calendar", "+agenda", "--as", "user", "--start", start, "--end", end]
    if calendar_id:
        cmd += ["--calendar-id", calendar_id]
    log(f"[tool] get_calendar_agenda: {date}")
    raw = _lark_cli(cmd, timeout=60)
    if raw.startswith("error:"):
        return raw
    try:
        parsed = json.loads(raw.split("exit_code=0\n", 1)[-1])
        events = parsed.get("data", [])
        if not events:
            return f"{date} 没有会议安排。"
        lines = [f"共 {len(events)} 个会议："]
        for ev in events:
            lines.append(_format_event(ev))
        return "\n".join(lines)
    except Exception as e:
        return f"error parsing calendar result: {e}\n{raw[:2000]}"


def tool_read_file(arguments: dict) -> str:
    try:
        p = _resolve_path(arguments.get("path", ""))
        if not p.exists():
            return f"error: file not found: {p}"
        if p.is_dir():
            return f"error: {p} is a directory"
        content = p.read_text(encoding="utf-8", errors="ignore")
        return content[:20000]
    except Exception as e:
        return f"error: {e}"


SENSITIVE_SUFFIXES = {".env", ".pem", ".key", ".p12", ".pfx", ".crt", ".mobileprovision"}
ALLOWED_NEW_SUFFIXES = {".md", ".txt", ".py", ".yaml", ".yml", ".json", ".csv", ".tsv", ".sh", ".conf", ".ini", ".toml"}


def _is_sensitive_path(p: Path) -> bool:
    parts = [x.lower() for x in p.parts]
    if any(x in parts for x in {"library", "keychains", ".ssh"}):
        return True
    return p.suffix.lower() in SENSITIVE_SUFFIXES


def tool_edit_file(arguments: dict) -> str:
    try:
        p = _resolve_path(arguments.get("path", ""))
        if not p.exists():
            return f"error: file not found: {p}"
        if p.is_dir():
            return f"error: {p} is a directory"
        if _is_sensitive_path(p):
            return f"error: editing sensitive file {p.name} is forbidden"
        old = arguments.get("old_string", "")
        new = arguments.get("new_string", "")
        if not old:
            return "error: old_string required"
        content = p.read_text(encoding="utf-8")
        count = content.count(old)
        if count == 0:
            return "error: old_string not found in file"
        if count > 1:
            return f"error: old_string appears {count} times; must be unique"
        new_content = content.replace(old, new, 1)
        # 写回前简单备份
        backup = p.parent / (p.name + ".bak")
        if not backup.exists():
            backup.write_text(content, encoding="utf-8")
        p.write_text(new_content, encoding="utf-8")
        log(f"[tool] edit_file: {p}")
        return f"edited {p.relative_to(WORKSPACE)}"
    except Exception as e:
        return f"error: {e}"


def tool_append_to_file(arguments: dict) -> str:
    try:
        p = _resolve_path(arguments.get("path", ""))
        if _is_sensitive_path(p):
            return f"error: appending to sensitive file {p.name} is forbidden"
        content = arguments.get("content", "")
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        log(f"[tool] append_to_file: {p}")
        return f"appended to {p.relative_to(WORKSPACE)}"
    except Exception as e:
        return f"error: {e}"


def tool_write_file(arguments: dict) -> str:
    try:
        p = _resolve_path(arguments.get("path", ""))
        if p.exists():
            return f"error: file already exists: {p}"
        if _is_sensitive_path(p):
            return f"error: writing sensitive file {p.name} is forbidden"
        suffix = p.suffix.lower()
        if suffix not in ALLOWED_NEW_SUFFIXES:
            return f"error: suffix {suffix} not allowed for new file"
        content = arguments.get("content", "")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        log(f"[tool] write_file: {p}")
        return f"created {p.relative_to(WORKSPACE)}"
    except Exception as e:
        return f"error: {e}"


def tool_list_files(arguments: dict) -> str:
    try:
        p = _resolve_path(arguments.get("path", "."))
        glob = arguments.get("glob")
        if glob:
            items = [str(x.relative_to(WORKSPACE)) for x in p.glob(glob)]
        else:
            items = [str(x.relative_to(WORKSPACE)) + "/" if x.is_dir() else str(x.relative_to(WORKSPACE)) for x in p.iterdir()]
        return "\n".join(sorted(items)[:200]) or "(empty)"
    except Exception as e:
        return f"error: {e}"


def tool_search_files(arguments: dict) -> str:
    try:
        path = _resolve_path(arguments.get("path", "."))
        pattern = arguments.get("pattern", "")
        glob = arguments.get("glob", "*")
        if not pattern:
            return "error: pattern required"
        matches = []
        for f in path.rglob(glob):
            if not f.is_file():
                continue
            try:
                content = f.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for i, line in enumerate(content.splitlines(), 1):
                if re.search(pattern, line):
                    matches.append(f"{f.relative_to(WORKSPACE)}:{i}: {line.strip()}")
                    if len(matches) >= 30:
                        break
            if len(matches) >= 30:
                break
        return "\n".join(matches) or "(no matches)"
    except Exception as e:
        return f"error: {e}"


def tool_run_shell(arguments: dict) -> str:
    cmd = arguments.get("command", "")
    timeout = int(arguments.get("timeout", 60))
    if not isinstance(cmd, str) or not cmd.strip():
        return "error: command required"
    forbidden = ["rm -rf /", "rm -rf ~", "rm -rf $HOME", "git push --force", "git push -f", "DROP DATABASE", "DROP SCHEMA", "TRUNCATE "]
    for f in forbidden:
        if f.lower() in cmd.lower():
            return f"error: destructive operation forbidden: {f}"
    log(f"[tool] run_shell: {cmd[:100]}")
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    status = f"exit_code={r.returncode}"
    result = "\n".join([s for s in [status, out, err] if s])
    return result[:4000]


def tool_trigger_lingxi_task(arguments: dict) -> str:
    task = arguments.get("task", "")
    allowed = {"food", "risk", "sync"}
    if task not in allowed:
        return f"error: task must be one of {allowed}"
    trigger = WORKSPACE / "lingxi-trigger.sh"
    log(f"[tool] trigger_lingxi_task: {task}")
    r = subprocess.run(["bash", str(trigger), task], capture_output=True, text=True, timeout=300)
    out = (r.stdout or "").strip()
    err = (r.stderr or "").strip()
    status = f"exit_code={r.returncode}"
    return "\n".join([s for s in [status, out, err] if s])[:4000]


def tool_web_search(arguments: dict) -> str:
    query = arguments.get("query", "")
    if not query:
        return "error: query required"
    log(f"[tool] web_search: {query}")
    # DuckDuckGo HTML lite 抓取
    try:
        url = "https://duckduckgo.com/html/"
        data = urllib.parse.urlencode({"q": query}).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST", headers={
            "User-Agent": "Mozilla/5.0 (compatible; LocalAgent/1.0)",
            "Content-Type": "application/x-www-form-urlencoded",
        })
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", errors="ignore")
        results = []
        for m in re.finditer(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html):
            title = re.sub(r'<[^>]+>', '', m.group(2))
            href = m.group(1)
            if title and len(results) < 5:
                results.append(f"{title}\n{href}")
        return "\n\n".join(results) or "(no results)"
    except Exception as e:
        return f"error: {e}"


TOOL_REGISTRY = {
    "run_lark_cli": tool_run_lark_cli,
    "read_file": tool_read_file,
    "edit_file": tool_edit_file,
    "append_to_file": tool_append_to_file,
    "write_file": tool_write_file,
    "list_files": tool_list_files,
    "search_files": tool_search_files,
    "run_shell": tool_run_shell,
    "trigger_lingxi_task": tool_trigger_lingxi_task,
    "get_calendar_agenda": tool_get_calendar_agenda,
    "web_search": tool_web_search,
}


# ==================== 消息 / 工具解析 ====================

def _sanitize_json_string(raw: str) -> str:
    """修复 JSON 字符串值内部未转义的双引号（保留已有转义）。"""
    result = []
    i = 0
    in_str = False
    while i < len(raw):
        ch = raw[i]
        if ch == '"' and (i == 0 or raw[i - 1] != '\\'):
            if not in_str:
                in_str = True
                result.append(ch)
            else:
                # 可能是字符串结束，也可能是未转义的内部引号
                # 试探：如果到下一个 " 之间有常见 JSON 结构字符，则当作内部引号
                next_quote = raw.find('"', i + 1)
                if next_quote == -1:
                    # 没有后续引号，这是结束
                    result.append(ch)
                    in_str = False
                else:
                    segment = raw[i + 1:next_quote]
                    # 如果片段里有 : 或 , 或 []{} 等结构字符，说明当前 " 不是字符串结束
                    if any(c in segment for c in ':\\,[]{}'):
                        result.append('\\"')
                    else:
                        result.append(ch)
                        in_str = False
        else:
            result.append(ch)
        i += 1
    return "".join(result)


def _try_parse_tool(raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = raw.get("name")
    args = raw.get("arguments")
    if isinstance(name, str) and (args is None or isinstance(args, dict)):
        return {"name": name, "arguments": args or {}}
    # 兼容 OpenAI function call 风格
    fn = raw.get("function")
    if isinstance(fn, dict) and isinstance(fn.get("name"), str):
        try:
            fn_args = json.loads(fn.get("arguments", "{}"))
        except Exception:
            fn_args = {}
        return {"name": fn["name"], "arguments": fn_args}
    return None


def parse_tool_calls(content: str) -> list[dict]:
    """从模型回复中提取 tool call（支持 ```tool、```json、行内 JSON）。"""
    calls = []
    # 1. 标准 ```tool 代码块
    for block in re.finditer(r"```tool\s*\n(.*?)\n```", content, re.DOTALL):
        for line in block.group(1).strip().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                raw = json.loads(line)
            except Exception:
                try:
                    raw = json.loads(_sanitize_json_string(line))
                except Exception:
                    continue
            tc = _try_parse_tool(raw)
            if tc and tc not in calls:
                calls.append(tc)

    # 2. 任意 ``` 代码块里的 JSON 数组
    for block in re.finditer(r"```(?:json)?\s*\n(.*?)\n```", content, re.DOTALL):
        text = block.group(1).strip()
        # 尝试整个块作为 JSON
        candidates = [text]
        # 也尝试每行
        candidates.extend(text.splitlines())
        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate:
                continue
            try:
                raw = json.loads(candidate)
            except Exception:
                try:
                    raw = json.loads(_sanitize_json_string(candidate))
                except Exception:
                    continue
            if isinstance(raw, list):
                for item in raw:
                    tc = _try_parse_tool(item)
                    if tc and tc not in calls:
                        calls.append(tc)
            else:
                tc = _try_parse_tool(raw)
                if tc and tc not in calls:
                    calls.append(tc)

    # 3. 行内独立 JSON 对象（简单花括号匹配）
    for m in re.finditer(r'\{[^{}]*"name"[^{}]*\}', content):
        try:
            raw = json.loads(m.group(0))
        except Exception:
            try:
                raw = json.loads(_sanitize_json_string(m.group(0)))
            except Exception:
                continue
        tc = _try_parse_tool(raw)
        if tc and tc not in calls:
            calls.append(tc)

    return calls


def execute_tool_call(tc: dict) -> dict:
    name = tc.get("name")
    args = tc.get("arguments") or {}
    if name not in TOOL_REGISTRY:
        return {"tool": name, "result": f"error: unknown tool {name}", "ok": False}
    try:
        result = TOOL_REGISTRY[name](args)
        # 工具函数内部逻辑错误通常以 "error:" 开头返回
        if isinstance(result, str) and result.startswith("error:"):
            return {"tool": name, "result": result, "ok": False}
        return {"tool": name, "result": result, "ok": True}
    except Exception as e:
        return {"tool": name, "result": f"error: {e}", "ok": False}


def send_text(text: str):
    content = json.dumps({"text": text}, ensure_ascii=False)
    r = subprocess.run(
        ["lark-cli", "im", "+messages-send", "--as", "bot",
         "--chat-id", DM_CHAT, "--msg-type", "text", "--content", content],
        capture_output=True, text=True, timeout=30,
    )
    if r.returncode != 0:
        log(f"[send] failed: {(r.stderr or r.stdout).strip()[:200]}")


def read_inbox() -> list[dict]:
    if not INBOX_PATH.exists():
        return []
    entries = []
    with open(INBOX_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def write_inbox(entries: list[dict]):
    INBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INBOX_PATH, "w", encoding="utf-8") as f:
        for e in entries:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def append_agent_inbox(entry: dict, reply: str):
    AGENT_INBOX.parent.mkdir(parents=True, exist_ok=True)
    text = entry.get("text", "")
    sender = entry.get("sender_id", "unknown")
    ts = entry.get("received_at", "")
    mid = entry.get("message_id", "")
    with open(AGENT_INBOX, "a", encoding="utf-8") as f:
        f.write(f"---\n")
        f.write(f"时间: {ts}\n")
        f.write(f"发送者: {sender}\n")
        f.write(f"消息ID: {mid}\n")
        f.write(f"用户: {text}\n")
        f.write(f"助理: {reply}\n\n")


def load_history(limit: int = 6) -> list[dict]:
    if not HISTORY_PATH.exists():
        return []
    try:
        with open(HISTORY_PATH, "r", encoding="utf-8") as f:
            lines = [ln.strip() for ln in f if ln.strip()]
        entries = [json.loads(ln) for ln in lines]
        return entries[-limit:]
    except Exception:
        return []


def append_history(role: str, content: str):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "time": datetime.now().isoformat(),
        "role": role,
        "content": content,
    }
    with open(HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load_memory_file(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8", errors="ignore")
        return content.strip()
    except Exception:
        return ""


def intent_hint(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["食谱", "晚餐", "早餐", "午餐", "菜单", "食堂", "菜名", "吃什么", "food", "meal"]):
        return "（这是关于饮食/食谱/菜单的请求，请优先使用 search_files / read_file / edit_file 处理 workspace 中的相关文件。）"
    if any(k in t for k in ["日程", "会议", "会", "日历", "明天", "今天", "后天", "本周", "下周", "上午", "下午"]):
        return "（这是关于日程/会议的请求，请使用 get_calendar_agenda 查询飞书日历。）"
    if any(k in t for k in ["任务", "待办", "todo", "okr", "文档", "doc", "多维表格", "base"]):
        return "（这是关于飞书能力的请求，请尝试使用 run_lark_cli 调用相应的 lark-cli 命令。）"
    return ""


def looks_like_rule_update(text: str) -> bool:
    """判断用户是否在新增长期规则或个人偏好。"""
    prefixes = ["以后", "之后", "往后", "未来", "下次", "从今以后"]
    markers = ["规则", "规定", "必须", "要", "默认", "都", "所有"]
    has_prefix = any(text.startswith(p) or (f"，{p}" in text) for p in prefixes)
    has_marker = any(m in text for m in markers)
    return has_prefix or has_marker


def auto_update_memory(text: str) -> str:
    """把用户指令沉淀到 user-preferences.md 或 project-rules.md，返回追加的内容。"""
    classify_prompt = (
        "请把下面这条用户指令总结成一条简洁的规则（1-2 句话），并判断它属于个人偏好还是项目规则。\n"
        "只输出 JSON，格式：{\"type\": \"preference\"|\"rule\", \"content\": \"...\"}\n"
        "不要解释。\n\n用户指令：" + text
    )
    try:
        result = call_fuyao([{"role": "user", "content": classify_prompt}], max_tokens=500, temperature=0.2)
        raw = json.loads(result.strip().strip("`").replace("```json", "").replace("```", ""))
        typ = raw.get("type", "rule")
        content = raw.get("content", text)
        target = USER_PREFS_PATH if typ == "preference" else PROJECT_RULES_PATH
        with open(target, "a", encoding="utf-8") as f:
            f.write(f"\n- {content}\n")
        log(f"[memory] appended rule to {target.name}: {content}")
        return f"已自动更新 {target.name}：{content}"
    except Exception as e:
        log(f"[memory] auto-update failed: {e}")
        return ""


def handle_pending(entry: dict):
    text = entry.get("text", "")
    mid = entry.get("message_id", "")
    log(f"[handle] {mid}: {text[:80]}...")

    # 自动沉淀长期规则/偏好
    memory_note = ""
    if looks_like_rule_update(text):
        memory_note = auto_update_memory(text)
        if memory_note:
            log(f"[memory] {memory_note}")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S %A")
    user_prefs = load_memory_file(USER_PREFS_PATH)
    project_rules = load_memory_file(PROJECT_RULES_PATH)
    memory_section = ""
    if user_prefs:
        memory_section += f"\n\n=== user-preferences.md ===\n{user_prefs}"
    if project_rules:
        memory_section += f"\n\n=== project-rules.md ===\n{project_rules}"

    system = SYSTEM_PROMPT + f"\n\n当前时间：{now}（北京时间）。涉及“今天/明天/后天/本周”等相对时间时，请以该时间为基准。" + memory_section
    hint = intent_hint(text)
    update_memory_note = (
        "\n\n如果本次我的指令新增了可长期遵循的规则或个人偏好，"
        "你必须先使用 append_to_file 或 edit_file 工具更新 "
        "team/memory/daily-sync/project-rules.md 或 team/memory/daily-sync/user-preferences.md，"
        "不能只文字回复；更新完成后再给出最终回复。不要把本次单次查询的具体内容写进去。"
    )
    user_content = text
    if hint:
        user_content = f"{hint}\n\n{user_content}"
    user_content += update_memory_note
    messages = [{"role": "system", "content": system}]
    for h in load_history():
        messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_content})

    final_reply = ""
    for round_no in range(MAX_TOOL_ROUNDS):
        try:
            content = call_fuyao(messages, max_tokens=4000)
        except Exception as e:
            final_reply = f"（调用模型出错：{e}）"
            break

        tool_calls = parse_tool_calls(content)
        if not tool_calls:
            final_reply = content
            break

        # 执行工具
        tool_results = []
        for tc in tool_calls:
            log(f"[tool_call] {tc.get('name')}({json.dumps(tc.get('arguments') or {}, ensure_ascii=False)})")
            res = execute_tool_call(tc)
            tool_results.append(res)
            log(f"[tool_result] {res['tool']} ok={res['ok']}")

        # 构造下一轮 messages：把 assistant 的工具调用和 tool results 都放进去
        tool_summary_parts = []
        for tc, tr in zip(tool_calls, tool_results):
            tool_summary_parts.append(
                f"Called {tc.get('name')} with {json.dumps(tc.get('arguments') or {}, ensure_ascii=False)}\n"
                f"Result (ok={tr['ok']}):\n{tr['result']}"
            )
        assistant_content = content + "\n\n" + "\n\n".join(tool_summary_parts)
        messages.append({"role": "assistant", "content": assistant_content})
        messages.append({
            "role": "user",
            "content": (
                "工具执行结果如上。如果这些信息已经足够解决问题，请给出最终回复。"
                "如果还没解决问题，不要编造，继续调用其他工具，直到问题解决或明确无法解决。"
            )
        })
    else:
        # 超过轮数上限，用最后一轮的 content 作为回复
        final_reply = (content if content else "（工具调用轮数超过上限，未能完成）")

    # 如果有自动沉淀的规则，追加到回复中
    if memory_note and memory_note not in final_reply:
        final_reply = f"{final_reply}\n\n{memory_note}"

    # 发送回复
    send_text(final_reply)

    # 留痕
    append_history("user", text)
    append_history("assistant", final_reply)
    append_agent_inbox(entry, final_reply)

    entry["status"] = "replied"
    entry["replied_at"] = datetime.now().isoformat()
    entry["reply_text"] = final_reply
    log(f"[replied] {mid}: {final_reply[:80]}...")


def cycle():
    entries = read_inbox()
    changed = False
    for e in entries:
        if e.get("status") == "pending":
            try:
                handle_pending(e)
                changed = True
                break  # 每次只处理一条
            except Exception as ex:
                log(f"[handle] error: {ex}")
    if changed:
        write_inbox(entries)


def main():
    log("=== Local Agent Inbox Agent started ===")
    try:
        get_fuyao_key()
        log("[auth] Fuyao API key ready")
    except Exception as e:
        log(f"[auth] {e}")

    while True:
        try:
            cycle()
        except Exception as e:
            log(f"[cycle] error: {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("=== stopped by user ===")
        sys.exit(0)
