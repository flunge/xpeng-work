#!/usr/bin/env python3
"""larkdocs 镜像同步器（P0：文档库持久化镜像）

把分散在飞书的文档库按 token 清单镜像为本地 markdown，供 doc_rag.py 建索引检索。
镜像只是飞书真源（L0）的**只读缓存**，内容权威永远以飞书为准，禁止手工编辑镜像文件。

数据源（两个租户/两个 profile）：
  - group "jiangji"：星际骑遇项目文档，解析 mini-program/.claude/lark-docs-map.md 的「文档 token（docx）」表
                     profile = 默认（李坤 personal，fqmtvue07d8 租户）
  - group "team"   ：仿真部记忆库，读 team/memory/_feishu_map.json（index/projects/people/teams/insights/weekly-reports）
                     profile = xpeng（xiaopeng 租户）

增量策略：先用 scope=outline 轻量抓取拿 revision_id，与 manifest 中记录一致则跳过全文下载；
          revision 变化才拉全文 markdown。--force 强制全量。

用法：
  python3 team/scripts/larkdocs_sync.py                  # 全量增量同步
  python3 team/scripts/larkdocs_sync.py --group jiangji  # 只同步某组
  python3 team/scripts/larkdocs_sync.py --name 车型泛化   # 只同步名称匹配的
  python3 team/scripts/larkdocs_sync.py --dry-run

输出：
  team/memory/larkdocs/<group>/<相对路径>.md   镜像 markdown
  team/memory/larkdocs/manifest.json           镜像清单（token/revision/md5/分组/飞书 URL）
依赖：lark-cli（user 身份）
"""

import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent          # team/
DAILY_DIR = BASE_DIR.parent                                 # daily/
MIRROR_ROOT = BASE_DIR / "memory" / "larkdocs"
MANIFEST_PATH = MIRROR_ROOT / "manifest.json"
FEISHU_MAP = BASE_DIR / "memory" / "_feishu_map.json"
JIANGJI_MAP = DAILY_DIR / "repos" / ".." / ".." / "codes" / "mini-program" / ".claude" / "lark-docs-map.md"
# mini-program 实际路径（DAILY_DIR 推算不稳定，直接用绝对路径，允许 --jiangji-map 覆盖）
JIANGJI_MAP = Path("/Users/xpeng/Documents/codes/mini-program/.claude/lark-docs-map.md")

CLI = "lark-cli"
OUTLINE_TIMEOUT = 60
FULL_TIMEOUT = 240
WORKERS = 3
RETRIES = 3


def run_cli(args, timeout, profile=None):
    cmd = [CLI]
    if profile:
        cmd += ["--profile", profile]
    cmd += args + ["--as", "user"]
    for attempt in range(RETRIES + 1):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            try:
                data = json.loads(r.stdout)
                if data.get("ok"):
                    return data, None
                err = data.get("error", {})
                err_msg = err.get("message") if isinstance(err, dict) else str(err)
                code = err.get("code") if isinstance(err, dict) else None
                # 权限类错误直接放弃（重试无意义）
                if code in (1061004,) or "permission" in str(err_msg).lower():
                    return None, err_msg or str(err)
                # 限流退避加重
                if code == 99991400 and attempt < RETRIES:
                    time.sleep(6 * (attempt + 1))
                    continue
            except json.JSONDecodeError:
                err_msg = (r.stderr or r.stdout or "").strip()[:300]
            if attempt < RETRIES:
                time.sleep(2 * (attempt + 1))
        except subprocess.TimeoutExpired:
            err_msg = f"timeout>{timeout}s"
            if attempt < RETRIES:
                time.sleep(2 * (attempt + 1))
    return None, err_msg if 'err_msg' in dir() else "unknown"


def sanitize(name: str) -> str:
    """文件名清洗：去掉操作系统不友好字符（保留中文）。"""
    name = re.sub(r'[\\/:*?"<>|]', "_", name)
    name = name.strip().strip(".")
    return name or "untitled"


def load_manifests_jiangji():
    """解析 lark-docs-map.md 的「文档 token（docx）」表。"""
    text = JIANGJI_MAP.read_text(encoding="utf-8")
    m = re.search(r"##\s*文档 token（docx）(.*?)(\n##\s|\Z)", text, re.S)
    if not m:
        raise SystemExit(f"未在 {JIANGJI_MAP} 找到「文档 token（docx）」表")
    entries = []
    for line in m.group(1).splitlines():
        cells = [c.strip() for c in line.split("|") if c.strip()]
        if len(cells) != 2 or cells[0].startswith(("文档", "----", "--", "name")):
            continue
        name, token = cells
        if not re.fullmatch(r"[A-Za-z0-9]{20,}", token):
            continue
        # 名称形如 "04/pcba/原理图（tag 车载板）" —— "/" 即目录层级
        # 但顶层数字前缀（02/03/...）是阶段号不是目录，要归到对应中文章节子目录
        _CHAPTER_DIR = {
            "00": "00-对外门户", "01": "01-项目总览",
            "02": "02-阶段一-有源计时+有源tag", "03": "03-阶段一点五-无源计时+无源tag",
            "04": "04-阶段二-有源计时+姿态tag", "05": "05-阶段三-有源计时+姿态+UWB tag",
            "06": "06-阶段四-有源计时+姿态+UWB tag+视频系统",
            "07": "07-阶段五-有源计时+姿态+UWB+体能数据tag+视频系统",
            "10": "10-核心算法", "11": "11-接口协议与参考",
            "12": "12-软件设计", "13": "13-外设参考",
        }
        parts_raw = name.split("/")
        if len(parts_raw) >= 2 and parts_raw[0] in _CHAPTER_DIR:
            parts = [sanitize(_CHAPTER_DIR[parts_raw[0]])] + [sanitize(x) for x in parts_raw[1:]]
        else:
            parts = [sanitize(x) for x in parts_raw]
        rel = str(Path("jiangji", *parts).with_suffix("")) + ".md"
        entries.append({
            "group": "jiangji",
            "name": name.split("/")[-1],
            "path": name,
            "rel_path": rel,
            "token": token,
            "url": f"https://fqmtvue07d8.feishu.cn/docx/{token}",
            "profile": None,
        })
    return entries


def _list_folder_docx(folder_token, profile, depth=0, max_depth=4):
    """递归枚举云平台目录下 docx（含子文件夹）；返回 {token: (name, rel_dir)}"""
    out = {}
    if depth > max_depth:
        return out
    page = None
    while True:
        params = {"folder_token": folder_token, "page_size": 200}
        if page:
            params["page_token"] = page
        data, err = run_cli(["drive", "files", "list", "--params", json.dumps(params)],
                            OUTLINE_TIMEOUT // 2, profile)
        if not data:
            break
        files = data["data"].get("files", [])
        for f in files:
            if f.get("type") == "docx":
                out[f["token"]] = (f.get("name", f["token"]), "")
            elif f.get("type") == "folder":
                sub = _list_folder_docx(f["token"], profile, depth + 1, max_depth)
                out.update(sub)
        page = data["data"].get("page_token")
        if not data["data"].get("has_more", False) or not page:
            break
    return out


def discover_jiangji_extra(existing):
    """目录实时探测：把 lark-docs-map.md 漏抓的新文档补进清单（防漏网）"""
    try:
        live = _list_folder_docx("ZPG9fMN4flfJROd4tUnc0gSdnKd", None)
    except Exception as e:
        print(f"[larkdocs-sync] 目录探测跳过: {e}")
        return []
    have = {e["token"] for e in existing}
    extra = []
    for token, (name, _) in live.items():
        if token in have:
            continue
        extra.append({
            "group": "jiangji",
            "name": name,
            "path": f"未收录/{name}",
            "rel_path": str(Path("jiangji", "未收录", sanitize(name))) + ".md",
            "token": token,
            "url": f"https://fqmtvue07d8.feishu.cn/docx/{token}",
            "profile": None,
            "_discovered": True,
        })
    if extra:
        print(f"[larkdocs-sync] 目录探测补入 {len(extra)} 篇 lark-docs-map 未收录文档（→ jiangji/未收录/）")
    return extra


def discover_team_extra(existing):
    """仿真部记忆库目录探测（补 _feishu_map.json 未收录的新文档）"""
    try:
        live = _list_folder_docx("W7rqfwqnnlzSfUdEcIGcjcTNnqe", "xpeng")
    except Exception as e:
        print(f"[larkdocs-sync] 记忆库探测跳过: {e}")
        return []
    have = {e["token"] for e in existing}
    extra = []
    for token, (name, _) in live.items():
        if token in have:
            continue
        extra.append({
            "group": "team",
            "name": name,
            "path": f"未收录/{name}",
            "rel_path": str(Path("team", "未收录", sanitize(name))) + ".md",
            "token": token,
            "url": f"https://xiaopeng.feishu.cn/docx/{token}",
            "profile": "xpeng",
            "_discovered": True,
        })
    if extra:
        print(f"[larkdocs-sync] 记忆库探测补入 {len(extra)} 篇 _feishu_map 未收录文档（→ team/未收录/）")
    return extra


def load_manifests_team():
    """从 _feishu_map.json 生成仿真部记忆库条目。"""
    m = json.loads(FEISHU_MAP.read_text(encoding="utf-8"))
    entries = []

    def add(section, name, token, doctype):
        if doctype != "docx" or not token:
            return
        rel = str(Path("team", sanitize(section), sanitize(name))) + ".md"
        entries.append({
            "group": "team",
            "name": name,
            "path": f"{section}/{name}",
            "rel_path": rel,
            "token": token,
            "url": f"https://xiaopeng.feishu.cn/docx/{token}",
            "profile": "xpeng",
        })

    idx = m.get("index_doc")
    if idx:
        add("_索引", "内部索引", idx.get("token"), idx.get("type", "docx"))
    src = m.get("source_index")
    if src:
        add("_索引", "溯源索引", src.get("token"), src.get("type", "docx"))
    for section, key in (("projects", "projects"), ("people", "people"),
                         ("teams", "teams"), ("insights", "insights"),
                         ("weekly-reports", "weekly-reports")):
        for name, info in (m.get(key) or {}).items():
            if isinstance(info, dict):
                add(section, name, info.get("token"), info.get("type", "docx"))
    return entries


def load_all_entries(discover=True):
    jiangji = load_manifests_jiangji()
    team = load_manifests_team()
    entries = jiangji + team
    if discover:
        entries += discover_jiangji_extra(jiangji)
        entries += discover_team_extra(team)
    # 同 rel_path 冲突时加 token 后缀
    seen = {}
    for e in entries:
        if e["rel_path"] in seen:
            stem = e["rel_path"][:-3]
            e["rel_path"] = f"{stem}__{e['token'][:8]}.md"
        seen[e["rel_path"]] = True
    return entries


def fetch_revision(token, profile):
    data, err = run_cli(["docs", "+fetch", "--doc", token, "--doc-format", "markdown",
                         "--scope", "outline"], OUTLINE_TIMEOUT, profile)
    if not data:
        return None, err
    return data["data"]["document"].get("revision_id"), None


def fetch_full(token, profile):
    data, err = run_cli(["docs", "+fetch", "--doc", token, "--doc-format", "markdown",
                         "--scope", "full"], FULL_TIMEOUT, profile)
    if not data:
        return None, None, err
    doc = data["data"]["document"]
    return doc.get("content", ""), doc.get("revision_id"), None


def sync_one(entry, old_entry, force=False):
    """返回 (status, entry|None, err)。status ∈ synced/skipped/unchanged/failed"""
    rev, err = fetch_revision(entry["token"], entry["profile"])
    if rev is None:
        return "failed", None, f"outline: {err}"
    if not force and old_entry and old_entry.get("revision") == rev \
            and (MIRROR_ROOT / entry["rel_path"]).exists():
        e = dict(old_entry)
        e.update({k: entry[k] for k in ("group", "name", "path", "rel_path", "token", "url", "profile")})
        e["revision"] = rev
        return "unchanged", e, None
    content, full_rev, err = fetch_full(entry["token"], entry["profile"])
    if content is None:
        return "failed", None, f"full: {err}"
    import hashlib
    md5 = hashlib.md5(content.encode("utf-8")).hexdigest()
    out = MIRROR_ROOT / entry["rel_path"]
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    e = dict(entry)
    e.update({
        "revision": full_rev or rev,
        "md5": md5,
        "bytes": len(content.encode("utf-8")),
        "fetched_at": datetime.now().isoformat(timespec="seconds"),
    })
    return "synced", e, None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--group", choices=["jiangji", "team"], help="只同步某组")
    ap.add_argument("--name", help="只同步名称包含该子串的文档")
    ap.add_argument("--force", action="store_true", help="忽略 revision，全量重拉")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--no-discover", action="store_true", help="跳过实时目录探测（仅按清单同步）")
    args = ap.parse_args()

    entries = load_all_entries(discover=not args.no_discover)
    if args.group:
        entries = [e for e in entries if e["group"] == args.group]
    if args.name:
        entries = [e for e in entries if args.name in e["name"] or args.name in e["path"]]
    print(f"[larkdocs-sync] 清单 {len(entries)} 篇 → {MIRROR_ROOT}", flush=True)
    if args.dry_run:
        for e in entries:
            print(f"  [{e['group']}] {e['path']}  {e['token']}")
        return

    MIRROR_ROOT.mkdir(parents=True, exist_ok=True)
    old = {}
    if MANIFEST_PATH.exists():
        try:
            old = {e["token"]: e for e in json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))["docs"]}
        except Exception:
            pass

    results, new_docs = {"synced": 0, "unchanged": 0, "failed": 0}, []
    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(sync_one, e, old.get(e["token"]), args.force): e for e in entries}
        for i, fut in enumerate(as_completed(futs), 1):
            e = futs[fut]
            try:
                status, saved, err = fut.result()
            except Exception as ex:  # 防御：单篇失败不拖垮整体
                status, saved, err = "failed", None, str(ex)
            results[status] += 1
            if saved:
                new_docs.append(saved)
            if status == "failed":
                failures.append((e["path"], err))
            if i % 20 == 0 or i == len(entries):
                print(f"  进度 {i}/{len(entries)}  synced={results['synced']} unchanged={results['unchanged']} failed={results['failed']}", flush=True)

    # 未被本次选中的旧 manifest 条目要保留（分组同步时不丢其他组）
    selected = {e["token"] for e in entries}
    merged = [old[t] for t in old if t not in selected] + new_docs
    merged.sort(key=lambda x: (x.get("group", ""), x.get("rel_path", "")))
    manifest = {
        "_comment": "larkdocs 镜像清单：飞书为唯一权威源，本目录只是只读缓存，禁止手工编辑 .md",
        "mirror_root": str(MIRROR_ROOT),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "stats": {"total": len(merged)},
        "docs": merged,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    # 同步完成自动重建检索索引（增量，失败不阻断主流程）
    if results["synced"] > 0 or args.force:
        try:
            r = subprocess.run([sys.executable, str(Path(__file__).parent / "doc_rag.py"), "index"],
                               capture_output=True, text=True, timeout=300)
            print(r.stdout.strip())
        except Exception as ex:
            print(f"[larkdocs-sync] 索引重建失败（不阻断）: {ex}")

    # 每次同步完也自动给 Episode 事件流补米（L1 反向喂，幂等键防重复）
    # ——让 storyline-gen 周五 20:00 有当前周的完整数据，避免 W32 刮米困难
    try:
        r = subprocess.run([sys.executable, str(Path(__file__).parent / "backfill_all.py")],
                           capture_output=True, text=True, timeout=300)
        print(r.stdout.strip())
    except Exception as ex:
        print(f"[larkdocs-sync] backfill_all 失败（不阻断）: {ex}")
    print(f"[larkdocs-sync] 完成：synced={results['synced']} unchanged={results['unchanged']} failed={results['failed']}，manifest 共 {len(merged)} 篇", flush=True)
    if failures:
        print("  失败明细：")
        for p, err in failures:
            print(f"   - {p}: {err}")
        sys.exit(2)


if __name__ == "__main__":
    main()
