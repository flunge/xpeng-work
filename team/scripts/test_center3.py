#!/usr/bin/env python3
"""Test block_replace with align=center using --content."""
import subprocess, json, sys

DOC = "SBUYwm8Lri9aJ6kmexFcBAuGnlh"
BLOCK_ID = "doxcnDRK5RRtNauuPJ2ayIWXAeb"

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
    '<td vertical-align="top"><p align="center"><b>TESTROW</b></p></td>'
    '<td vertical-align="top"><p>goal text</p></td>'
    '<td vertical-align="top"><p></p></td>'
    '<td vertical-align="top"><p></p></td>'
    '<td vertical-align="top"><p></p></td>'
    '</tr>'
    '</tbody></table>'
)

# Use subprocess with list to avoid shell escaping issues
cmd = [
    'lark-cli', 'docs', '+update',
    '--api-version', 'v2',
    '--doc', DOC,
    '--command', 'block_replace',
    '--block-id', BLOCK_ID,
    '--content', content,
    '--format', 'json'
]

result = subprocess.run(cmd, capture_output=True, text=True)
print("Exit:", result.returncode)
if result.stdout:
    data = json.loads(result.stdout)
    print("OK:", data.get('ok'))
else:
    print("Stderr:", result.stderr[:300])
