#!/usr/bin/env python3
"""Test if align=center on p tags is preserved after block_replace."""
import subprocess, json, tempfile, os

DOC = "SBUYwm8Lri9aJ6kmexFcBAuGnlh"
BLOCK_ID = "doxcnDRK5RRtNauuPJ2ayIWXAeb"

# Minimal test table: 2 rows, first row centered
test_content = (
    '<table><colgroup><col/><col/></colgroup><tbody>'
    '<tr>'
    '<td vertical-align="middle"><p align="center"><b>TEST</b></p></td>'
    '<td vertical-align="middle"><p align="center"><b>COL2</b></p></td>'
    '</tr>'
    '<tr>'
    '<td vertical-align="top"><p>normal</p></td>'
    '<td vertical-align="top"><p>normal</p></td>'
    '</tr>'
    '</tbody></table>'
)

fd, path = tempfile.mkstemp(suffix='.xml')
with os.fdopen(fd, 'w') as f:
    f.write(test_content)

cmd = (
    f'lark-cli docs +update --api-version v2 '
    f'--doc "{DOC}" '
    f'--command block_replace '
    f'--block-id {BLOCK_ID} '
    f'--content-file "{path}" '
    f'--format json'
)
result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
os.unlink(path)
print("Exit code:", result.returncode)
data = json.loads(result.stdout) if result.stdout else {}
print("OK:", data.get('ok'))

# Now re-fetch to check
cmd2 = (
    f'lark-cli docs +fetch --api-version v2 '
    f'--doc "{DOC}" --scope keyword --keyword "TEST" --detail with-ids --format json'
)
result2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True)
data2 = json.loads(result2.stdout) if result2.stdout else {}
content = data2.get('data', {}).get('document', {}).get('content', '')
print("Has align=center:", 'align="center"' in content)
print("Has vertical-align=middle:", 'vertical-align="middle"' in content)
print("Content:", content[:500])
