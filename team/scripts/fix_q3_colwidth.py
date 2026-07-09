#!/usr/bin/env python3
"""Fix column widths for W29-W40 tables to match W28 (100/500/500/500/500)."""

import subprocess
import json
import re
import time
import sys

DOC_TOKEN = "SBUYwm8Lri9aJ6kmexFcBAuGnlh"

WEEKS = ["W29", "W30", "W31", "W32", "W33", "W34", "W35", "W36", "W37", "W38", "W39", "W40"]


def fetch_table_block(keyword):
    """Fetch table block ID and full content for a week."""
    result = subprocess.run(
        ["lark-cli", "docs", "+fetch",
         "--api-version", "v2",
         "--doc", DOC_TOKEN,
         "--scope", "keyword",
         "--keyword", keyword,
         "--detail", "with-ids",
         "--format", "json"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None, None
    data = json.loads(result.stdout)
    content = data.get("data", {}).get("document", {}).get("content", "")
    match = re.search(r'<table id="([^"]+)"', content)
    if not match:
        return None, None
    block_id = match.group(1)
    # Extract table content between <table...> and </table>
    table_match = re.search(r'(<table id="[^"]+">)(.*?)(</table>)', content, re.DOTALL)
    if not table_match:
        return block_id, None
    return block_id, content


def replace_table_with_colwidth(block_id, keyword, week_data_content):
    """Replace table, injecting proper colgroup with widths."""
    # We need to re-fetch current content, fix colgroup, and replace
    result = subprocess.run(
        ["lark-cli", "docs", "+fetch",
         "--api-version", "v2",
         "--doc", DOC_TOKEN,
         "--scope", "keyword",
         "--keyword", keyword,
         "--detail", "full",
         "--format", "json"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  Fetch failed for {keyword}")
        return False

    data = json.loads(result.stdout)
    content = data.get("data", {}).get("document", {}).get("content", "")

    # Extract the full table XML
    table_match = re.search(r'<table id="[^"]*">(.*?)</table>', content, re.DOTALL)
    if not table_match:
        print(f"  Could not extract table content for {keyword}")
        return False

    inner = table_match.group(1)

    # Replace colgroup with proper widths
    new_colgroup = '<colgroup><col width="100"/><col width="500"/><col width="500"/><col width="500"/><col width="500"/></colgroup>'
    inner_fixed = re.sub(r'<colgroup>.*?</colgroup>', new_colgroup, inner, flags=re.DOTALL)

    # Remove all id attributes from inner elements (they get regenerated)
    inner_fixed = re.sub(r' id="[^"]*"', '', inner_fixed)

    new_table = f'<table>{inner_fixed}</table>'

    # Replace
    result = subprocess.run(
        ["lark-cli", "docs", "+update",
         "--api-version", "v2",
         "--doc", DOC_TOKEN,
         "--command", "block_replace",
         "--block-id", block_id,
         "--content", new_table],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"  Replace failed: {result.stderr[:200]}")
        return False
    return True


def main():
    for week in WEEKS:
        print(f"Fixing col width for {week}...")
        block_id, _ = fetch_table_block(week)
        if not block_id:
            print(f"  Could not find {week}, skipping")
            continue

        ok = replace_table_with_colwidth(block_id, week, None)
        if ok:
            print(f"  OK - {week} col width fixed")
        else:
            print(f"  FAILED - {week}")

        time.sleep(1)

    print("\nDone!")


if __name__ == "__main__":
    main()
