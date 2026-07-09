#!/usr/bin/env python3
"""Test block_replace with align=center using content-file."""
import subprocess, json, tempfile, os

DOC = "SBUYwm8Lri9aJ6kmexFcBAuGnlh"
BLOCK_ID = "doxcnDRK5RRtNauuPJ2ayIWXAeb"

# Simple 2x2 table with centered first row and first column
content = (
    '<table><colgroup><col/><col/><col/><col/><col/></colgroup><tbody>'
    '<tr>'
    '<td vertical-align="top"><p align="center"><b>W28</b></p></td>'
    '<td vertical-align="top"><p align="center"><b>场景&amp;生产</b></p></td>'
    '<td vertical-align="top"><p align="center"><b>SIL</b></p></td>'
    '<td vertical-align="top"><p align="center"><b>HIL</b></p></td>'
    '<td vertical-align="top"><p align="center"><b>Agents&amp;预研</b></p></td>'
    '</tr>'
    '<tr>'
    '<td vertical-align="top"><p align="center"><b>周目标</b></p></td>'
    '<td vertical-align="top"><p>test goal</p></td>'
    '<td vertical-align="top"><p></p></td>'
    '<td vertical-align="top"><p></p></td>'
    '<td vertical-align="top"><p></p></td>'
    '</tr>'
    '</tbody></table>'
)

fd, path = tempfile.mkstemp(suffix='.xml')
with os.fdopen(fd, 'w') as f:
    f.write(content)

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

print("Exit:", result.returncode)
if result.stdout:
    data = json.loads(result.stdout)
    print("OK:", data.get('ok'))
    if not data.get('ok'):
        print("Error:", json.dumps(data, ensure_ascii=False)[:300])
else:
    print("Stderr:", result.stderr[:300])
