#!/usr/bin/env python3
"""全项目 Episode 回填（backfill_episode_from_ledger 的批量封装）

- 遍历 team/memory/larkdocs/team/projects/*.md，逐个调用 backfill_episode_from_ledger.py。
- 每个 ledger 的项目名 = 文件名 stem（与 _feishu_map.json 的 projects key 对齐）。
- backfill 本身幂等（ledger:// 幂等键），重跑只会补新行，不会重复入库——
  所以本脚本可以安全地作为 larkdocs_sync / storyline_gen 的前置链每日/每周跑。
- WM-内部探索 这类研究型 ledger（无「三、持续进展」表）会自动跳过，静默 OK。

用法：
  python3 team/scripts/backfill_all.py [--dry-run]
"""
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPT = BASE_DIR / "scripts" / "backfill_episode_from_ledger.py"
PROJ_DIR = BASE_DIR / "memory" / "larkdocs" / "team" / "projects"


def main():
    dry_run = "--dry-run" in sys.argv
    ledgers = sorted(PROJ_DIR.glob("*.md"))
    total, ok, empty, fail = 0, 0, 0, 0
    for f in ledgers:
        project = f.stem
        cmd = [sys.executable, str(SCRIPT),
               "--ledger", str(f),
               "--project", project] + (["--dry-run"] if dry_run else [])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        out = (r.stdout + r.stderr).strip()
        total += 1
        if r.returncode != 0:
            fail += 1
            print(f"[{project}] FAIL: {out[-150:]}")
        elif "新增 0 条" in out or "全部幂等已入" in out or "抽出任何行" in out:
            empty += 1
        else:
            ok += 1
            # 截最后一行（写库结果）
            print(f"[{project}] {out.splitlines()[-1][:120]}")
    print(f"[backfill-all] 总项目={total} 新增={ok} 无新增={empty} 失败={fail}"
          f"{'（dry-run）' if dry_run else ''}")
    if fail:
        sys.exit(2)


if __name__ == "__main__":
    main()
