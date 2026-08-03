#!/usr/bin/env python3
"""doc_rag.py — larkdocs 镜像的混合检索（P1：文档库精准快速检索）

在 larkdocs_sync.py 的镜像之上做离线关键词检索：
  - CJK 按 2 字滑动原子 + 拉丁整词；文档级全原子 AND，确定性子串语义（不黑盒）
  - Python 全量扫描打分（当前规模 ~100 篇/<1000 块，毫秒级；块数上万后再升级 FTS5）
  - 按 markdown 标题层级分块（父子分块：每块带完整标题路径），工程参数不碎裂
  - 每条结果带 文档名/标题路径/飞书 URL/token → 可溯源，需原文用 lark-cli docs +fetch 拉全文

子命令：
  python3 team/scripts/doc_rag.py index                     # 增量重建（按 manifest md5 跳过未变文档）
  python3 team/scripts/doc_rag.py index --force             # 全量重建
  python3 team/scripts/doc_rag.py search "悬架 参数 标定" [--group jiangji|team] [--limit 8] [--json]
  python3 team/scripts/doc_rag.py show "<文档名>"            # 按名称定位文档（模糊匹配）

查询语法：空格分隔多词；中文词再拆 2 字原子；文档须命中全部原子（AND），块按权重降序。
镜像/manifest：team/memory/larkdocs/（larkdocs_sync.py 维护）
索引：        team/memory/larkdocs/index/chunks.db（纯 Python 扫描的物化缓存）
"""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
MIRROR_ROOT = BASE_DIR / "memory" / "larkdocs"
MANIFEST_PATH = MIRROR_ROOT / "manifest.json"
DB_PATH = MIRROR_ROOT / "index" / "chunks.db"
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
MAX_CHUNK = 1500
OVERLAP = 50
_CJK = re.compile(r"[一-鿿]+")


# ---------------- 分块 ----------------

def flush(buf, headings, ordinal, out):
    text = "".join(buf).strip()
    if not text:
        return ordinal
    heading = " > ".join(h for h in headings if h)
    if len(text) <= MAX_CHUNK:
        out.append((heading, ordinal, text))
        return ordinal + 1
    start = 0
    while start < len(text):
        piece = text[start:start + MAX_CHUNK]
        out.append((heading, ordinal, piece))
        ordinal += 1
        start += MAX_CHUNK - OVERLAP
    return ordinal


def split_chunks(md_text):
    chunks, buf = [], []
    headings = [""] * 7
    ordinal = 0
    for line in md_text.splitlines(keepends=True):
        m = HEADING_RE.match(line.rstrip("\n"))
        if m:
            ordinal = flush(buf, headings, ordinal, chunks)
            buf = []
            level = len(m.group(1))
            headings[level] = m.group(2).strip()
            for lv in range(level + 1, 7):
                headings[lv] = ""
        else:
            buf.append(line)
    flush(buf, headings, ordinal, chunks)
    return chunks


# ---------------- 索引 ----------------

def open_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("""CREATE TABLE IF NOT EXISTS chunk_meta(
        group_dir TEXT, doc_path TEXT, doc_name TEXT, token TEXT, url TEXT, md5 TEXT,
        heading TEXT, ordinal INT, content TEXT,
        PRIMARY KEY(doc_path, heading, ordinal))""")
    return con


def cmd_index(args):
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    con = open_db()
    indexed_docs = {r[0]: r[1] for r in con.execute(
        "SELECT doc_path, md5 FROM chunk_meta GROUP BY doc_path")}
    alive = set()
    n_doc, n_chunk, skipped = 0, 0, 0
    with con:
        for d in manifest["docs"]:
            rel = d["rel_path"]
            alive.add(rel)
            f = MIRROR_ROOT / rel
            if not f.exists():
                continue
            if not args.force and indexed_docs.get(rel) == d.get("md5"):
                skipped += 1
                continue
            con.execute("DELETE FROM chunk_meta WHERE doc_path=?", (rel,))
            for heading, ordinal, content in split_chunks(f.read_text(encoding="utf-8")):
                con.execute(
                    "INSERT INTO chunk_meta(group_dir,doc_path,doc_name,token,url,md5,heading,ordinal,content)"
                    " VALUES(?,?,?,?,?,?,?,?,?)",
                    (d["group"], rel, d["name"], d.get("token", ""), d.get("url", ""),
                     d.get("md5", ""), heading, ordinal, content))
                n_chunk += 1
            n_doc += 1
        for rel in set(indexed_docs) - alive:
            con.execute("DELETE FROM chunk_meta WHERE doc_path=?", (rel,))
    total_docs = con.execute("SELECT COUNT(DISTINCT doc_path) FROM chunk_meta").fetchone()[0]
    total_chunks = con.execute("SELECT COUNT(*) FROM chunk_meta").fetchone()[0]
    print(f"[doc-rag index] 重建 {n_doc} 篇（跳过未变 {skipped}），新入库 {n_chunk} 块；"
          f"库内共 {total_docs} 篇 / {total_chunks} 块 → {DB_PATH}")


# ---------------- 检索 ----------------

def tokenize_query(query):
    """返回 groups: [{'word', 'atoms', 'required'}]
    中文 run 拆 2 字滑动原子；拉丁/数字整词。
    required：len<=2 整词必中；更长 run 允许交叉 bigram 缺失，需命中 >=ceil(n/2) 个原子。"""
    groups = []
    for word in re.split(r"\s+", query.strip()):
        if not word:
            continue
        # 复合词（中英混排）：拉丁整词各成一组，中文 run 按 run 成组
        pos = 0
        pieces = []
        for m in _CJK.finditer(word):
            if word[pos:m.start()]:
                pieces.append(("lat", word[pos:m.start()].lower()))
            pieces.append(("cjk", m.group(0)))
            pos = m.end()
        if word[pos:]:
            pieces.append(("lat", word[pos:].lower()))
        for kind, text in pieces:
            if kind == "lat":
                groups.append({"word": text, "atoms": [text], "required": 1})
            else:
                if len(text) <= 2:
                    groups.append({"word": text, "atoms": [text], "required": 1})
                else:
                    b = [text[i:i + 2] for i in range(len(text) - 1)]
                    groups.append({"word": text, "atoms": b,
                                   "required": max(1, -(-len(b) // 2))})  # ceil(n/2)
    return groups


def _weight(atom):
    n = len(atom)
    if n >= 4:
        return 3.0
    if n == 3:
        return 2.5
    if n == 2:
        return 1.0
    return 0.5


def search(query, group=None, limit=8, mode="auto"):
    groups = tokenize_query(query)
    if not groups:
        return []
    all_atoms = {a for g in groups for a in g["atoms"]}
    con = open_db()
    sql = "SELECT doc_path, doc_name, token, url, group_dir, heading, ordinal, content FROM chunk_meta"
    params = []
    if group:
        sql += " WHERE group_dir=?"
        params.append(group)
    doc_atoms, chunks = {}, []          # doc_path -> 命中原子集合
    for r in con.execute(sql, params):
        low = r[7].lower()
        hit = {a for a in all_atoms if a in low}
        if hit:
            chunks.append((r, hit))
            doc_atoms.setdefault(r[0], set()).update(hit)

    def doc_ok(doc_path):
        ds = doc_atoms[doc_path]
        return all(len([a for a in g["atoms"] if a in ds]) >= g["required"]
                   for g in groups)

    # OR 召回：显式 or，或 auto 且查询原子数多（>=9）时——AND 太严改 OR×覆盖率
    use_or = mode == "or" or (mode == "auto" and len(all_atoms) >= 9)
    results = []
    for r, hit in chunks:
        doc_path, name, token, url, g, heading, ordinal, content = r
        if doc_path not in doc_atoms:
            continue
        if not use_or and not doc_ok(doc_path):
            continue
        low = content.lower()
        score = sum(min(low.count(a), 5) * _weight(a) for a in hit)
        head_low = ((heading or "") + " " + name).lower()
        score += 3.0 * sum(1 for gr in groups if gr["word"] in head_low)
        score *= 1.0 / (1.0 + ordinal * 0.05)
        if use_or:
            score *= len(hit) / len(all_atoms)
        results.append({
            "doc": name, "path": doc_path, "group": g, "heading": heading,
            "url": url, "token": token, "score": round(score, 2),
            "snippet": make_snippet(content, list(all_atoms), terms=[gr["word"] for gr in groups]),
        })
    per_doc, dedup = {}, []
    for r in sorted(results, key=lambda x: -x["score"]):
        c = per_doc.get(r["path"], 0)
        if c < 2:
            dedup.append(r)
            per_doc[r["path"]] = c + 1
    return dedup[:limit]


def make_snippet(content, atoms=None, width=160, terms=None):
    low = content.lower()
    pos = -1
    for t in (terms or atoms or []):
        p = low.find(t.lower())
        if p < 0 and atoms:
            for a in sorted(atoms, key=len):
                p = low.find(a.lower())
                if p >= 0:
                    break
        if p >= 0 and (pos < 0 or p < pos):
            pos = p
    if pos < 0:
        return content[:width].strip() + ("…" if len(content) > width else "")
    start = max(0, pos - width // 2)
    end = min(len(content), pos + width // 2)
    s = content[start:end].strip()
    return ("…" if start > 0 else "") + s + ("…" if len(content) > end else "")


def cmd_search(args):
    results = search(args.query, group=args.group, limit=args.limit, mode=args.mode)
    if args.json:
        print(json.dumps({"query": args.query,
                          "groups": tokenize_query(args.query),
                          "results": results}, ensure_ascii=False, indent=1))
        return
    if not results:
        print("无命中。可减词重试，或用 show 按文档名定位。")
        return
    print(f"命中 {len(results)} 块（按相关度降序）：\n")
    for i, r in enumerate(results, 1):
        print(f"[{i}] {r['doc']}  ‹{r['group']}›  {r['heading'] or '(全文)'}  score={r['score']}")
        print(f"    {r['url']}")
        for line in r["snippet"].splitlines()[:6]:
            print(f"    {line}")
        print()


def cmd_show(args):
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    hits = [d for d in manifest["docs"] if args.name in d["name"] or args.name in d["path"]]
    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=1))
        return
    for d in hits:
        f = MIRROR_ROOT / d["rel_path"]
        print(f"[{d['group']}] {d['path']}  rev={d.get('revision')}  {d.get('bytes', 0) // 1024}KB")
        print(f"    {d['url']}")
        print(f"    本地: {f}")
    if not hits:
        print("无匹配文档。")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index")
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_index)
    p = sub.add_parser("search")
    p.add_argument("query")
    p.add_argument("--group", choices=["jiangji", "team"])
    p.add_argument("--limit", type=int, default=8)
    p.add_argument("--mode", choices=["auto", "and", "or"], default="auto",
                   help="auto=原子数<9 走 AND；>=9 自动转 OR×覆盖率召回")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_search)
    p = sub.add_parser("show")
    p.add_argument("name")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_show)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
