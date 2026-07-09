#!/usr/bin/env python3
"""Fix W27 table: add colgroup with widths but preserve all content."""
import subprocess, json, sys, re

DOC = "SBUYwm8Lri9aJ6kmexFcBAuGnlh"
W27_TABLE_ID = "U1DXdLtL3oZ5lsxWpYpchYYInSd"

# Step 1: Fetch W27 table content
cmd = [
    'lark-cli', 'docs', '+fetch',
    '--api-version', 'v2',
    '--doc', DOC,
    '--scope', 'section',
    '--start-block-id', 'ELOUdZh4Iou1ivxzksFc6ohPnvc',  # W27 h3 heading
    '--detail', 'with-ids',
    '--format', 'json'
]
result = subprocess.run(cmd, capture_output=True, text=True)
data = json.loads(result.stdout)
content = data['data']['document']['content']

# Extract the table content (between <table ...> and </table>)
m = re.search(r'<table id="U1DXdLtL3oZ5lsxWpYpchYYInSd">(.*?)</table>', content, re.DOTALL)
if not m:
    print("ERROR: W27 table not found")
    sys.exit(1)

table_inner = m.group(1)
print(f"W27 table content length: {len(table_inner)} chars")

# Remove any existing colgroup
table_inner = re.sub(r'<colgroup>.*?</colgroup>', '', table_inner)

# Build new table with colgroup
new_table = (
    '<table>'
    '<colgroup><col width="100"/><col width="500"/><col width="500"/><col width="500"/><col width="500"/></colgroup>'
    + table_inner
    + '</table>'
)

# Remove id attributes from inner content (API will reassign them)
# Actually keep them - block_replace should handle existing IDs
# But we need to remove the table's own ID since it's in the wrapper

print(f"New table length: {len(new_table)} chars")

# Step 2: block_replace
cmd2 = [
    'lark-cli', 'docs', '+update',
    '--api-version', 'v2',
    '--doc', DOC,
    '--command', 'block_replace',
    '--block-id', W27_TABLE_ID,
    '--content', new_table,
    '--format', 'json'
]
result2 = subprocess.run(cmd2, capture_output=True, text=True)
if result2.returncode != 0:
    print(f"ERROR: {result2.stderr[:300]}")
    sys.exit(1)

data2 = json.loads(result2.stdout)
print(f"W27 colwidth update: {'OK' if data2.get('ok') else 'FAILED'}")
if not data2.get('ok'):
    print(json.dumps(data2, ensure_ascii=False)[:500])
