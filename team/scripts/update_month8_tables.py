#!/usr/bin/env python3
"""Replace tables in 8月 doc (Pdhud83wwo1d4KxnS9dcma1nn1g) with W27-format templates."""
import subprocess, json, sys

SCENE_CELL = (
    '<p><b>业务交付</b></p>'
    '<ul>'
    '<li>【RC长里程】&amp;【闭环场景集】'
    '<cite type="user" user-id="ou_5ff13a6d397bcb698bbfb66800fbb83a" user-name="刘开拓"></cite>'
    '<cite type="user" user-id="ou_279a0e5c146848e3d2dfaefe85f2c505" user-name="郑丽娜"></cite></li>'
    '<li>【长里程看板】<cite type="user" user-id="ou_c9f3e88a0d6f949b332a40a155814e69" user-name="周蔚旭"></cite></li>'
    '<li>【极速模式】<cite type="user" user-id="ou_c9f3e88a0d6f949b332a40a155814e69" user-name="周蔚旭"></cite></li>'
    '</ul>'
    '<p><b>算法优化</b></p>'
    '<ul>'
    '<li>【场景编辑】<cite type="user" user-id="ou_a76e6fffce1c513ed5b33555aec19076" user-name="裴健宏"></cite></li>'
    '<li>【场景泛化】<cite type="user" user-id="ou_16ed70882e5f4247b330612054b07d3f" user-name="王禹丁"></cite></li>'
    '</ul>'
)
SIL_CELL = (
    '<p><b>业务交付</b></p>'
    '<ul>'
    '<li>【车型泛化】<cite type="user" user-id="ou_b41c33085d2e629fbdff0c555cae0a3f" user-name="杨星昊"></cite></li>'
    '<li>【RC路线SIL验证】<cite type="user" user-id="ou_16ed70882e5f4247b330612054b07d3f" user-name="王禹丁"></cite></li>'
    '</ul>'
    '<p><b>算法优化</b></p>'
    '<ul>'
    '<li>【Fixer渲染优化】<cite type="user" user-id="ou_c37bf637460fbc4d1dd53470ecae8889" user-name="周冯"></cite></li>'
    '<li>【CLIP-IQA】<cite type="user" user-id="ou_16ed70882e5f4247b330612054b07d3f" user-name="王禹丁"></cite></li>'
    '</ul>'
)
HIL_CELL = (
    '<p><b>业务交付</b></p>'
    '<ul>'
    '<li>【HIL链路】<cite type="user" user-id="ou_09b6f76c8d98f186bb7163406fe3894a" user-name="朱啸峰"></cite></li>'
    '<li>【业务交付状态】<cite type="user" user-id="ou_279a0e5c146848e3d2dfaefe85f2c505" user-name="郑丽娜"></cite></li>'
    '</ul>'
    '<p><b>算法优化</b></p>'
    '<ul>'
    '<li>【慢速模式】<cite type="user" user-id="ou_f360c7cfbd4fcbdc624c012dc151c6a4" user-name="瞿鑫宇"></cite></li>'
    '</ul>'
)
AGENTS_CELL = (
    '<p><b>业务交付</b></p>'
    '<ul>'
    '<li>【复现率Agent】<cite type="user" user-id="ou_e6eb2da48b30725b46c548a1bcbf3fc6" user-name="吕文杰"></cite>'
    '<cite type="user" user-id="ou_c9f3e88a0d6f949b332a40a155814e69" user-name="周蔚旭"></cite></li>'
    '<li>【Diff Agent】<cite type="user" user-id="ou_e6eb2da48b30725b46c548a1bcbf3fc6" user-name="吕文杰"></cite>'
    '<cite type="user" user-id="ou_c9f3e88a0d6f949b332a40a155814e69" user-name="周蔚旭"></cite></li>'
    '<li>【代码治理】<cite type="user" user-id="ou_b41c33085d2e629fbdff0c555cae0a3f" user-name="杨星昊"></cite></li>'
    '</ul>'
    '<p><b>算法预研</b></p>'
    '<ul>'
    '<li>【Smart Agent】<cite type="user" user-id="ou_41c1fbbdee2aa8ced7cbe495a0e4b9c3" user-name="樊世洲"></cite></li>'
    '<li>【WM+GGS】<cite type="user" user-id="ou_6dbb165c2c7f4dd57532ffda75e51169" user-name="靳希睿"></cite></li>'
    '</ul>'
)

def build_day_row(day_label):
    return (
        f'<tr>'
        f'<td vertical-align="top"><p><b>{day_label}</b></p></td>'
        f'<td vertical-align="top">{SCENE_CELL}</td>'
        f'<td vertical-align="top">{SIL_CELL}</td>'
        f'<td vertical-align="top">{HIL_CELL}</td>'
        f'<td vertical-align="top">{AGENTS_CELL}</td>'
        f'</tr>'
    )

def build_week_table(week_num, days):
    header = (
        '<tr>'
        f'<td vertical-align="top"><p><b>W{week_num}</b></p></td>'
        '<td vertical-align="top"><p><b>场景&amp;生产</b></p></td>'
        '<td vertical-align="top"><p><b>SIL</b></p></td>'
        '<td vertical-align="top"><p><b>HIL</b></p></td>'
        '<td vertical-align="top"><p><b>Agents&amp;预研</b></p></td>'
        '</tr>'
    )
    goal_row = (
        '<tr><td vertical-align="top"><p><b>周目标</b></p></td>'
        '<td vertical-align="top"><p></p></td>'
        '<td vertical-align="top"><p></p></td>'
        '<td vertical-align="top"><p></p></td>'
        '<td vertical-align="top"><p></p></td></tr>'
    )
    risk_row = (
        '<tr><td vertical-align="top"><p><b>核心风险&amp;上下游交互</b></p></td>'
        '<td vertical-align="top"><p></p></td>'
        '<td vertical-align="top"><p></p></td>'
        '<td vertical-align="top"><p></p></td>'
        '<td vertical-align="top"><p></p></td></tr>'
    )
    day_rows = ''.join(build_day_row(d) for d in days)
    return (
        f'<table><colgroup><col/><col/><col/><col/><col/></colgroup><tbody>'
        f'{header}{goal_row}{risk_row}{day_rows}'
        f'</tbody></table>'
    )

DOC = "Pdhud83wwo1d4KxnS9dcma1nn1g"

WEEKS = [
    ('doxcnleeuUanFk3MRG7k44NHPrD', 31, ['周一 8/3', '周二 8/4', '周三 8/5', '周四 8/6', '周五 8/7']),
    ('doxcnBxQyvBCcBam7Pyhkat5T2f', 32, ['周一 8/10', '周二 8/11', '周三 8/12', '周四 8/13', '周五 8/14']),
    ('doxcnQV41Q9qWS7TIA9S9P5sOEs', 33, ['周一 8/17', '周二 8/18', '周三 8/19', '周四 8/20', '周五 8/21']),
    ('doxcnHjNcCu7NVzAfLBikn6iHud', 34, ['周一 8/24', '周二 8/25', '周三 8/26', '周四 8/27', '周五 8/28']),
    ('doxcn2Rs6NXmggoTSUm4EhX9oMb', 35, ['周一 8/31']),
]

def replace_block(block_id, content):
    # Write content to temp file to avoid shell escaping issues
    import tempfile, os
    fd, path = tempfile.mkstemp(suffix='.xml')
    with os.fdopen(fd, 'w') as f:
        f.write(content)
    cmd = (
        f'lark-cli docs +update --api-version v2 '
        f'--doc "{DOC}" '
        f'--command block_replace '
        f'--block-id {block_id} '
        f'--content-file "{path}" '
        f'--format json'
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    os.unlink(path)
    if result.returncode != 0:
        # Try with inline content instead
        cmd2 = (
            f'lark-cli docs +update --api-version v2 '
            f'--doc "{DOC}" '
            f'--command block_replace '
            f'--block-id {block_id} '
            f"--content '{content}' "
            f'--format json'
        )
        result = subprocess.run(cmd2, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        return False, result.stderr
    data = json.loads(result.stdout)
    return data.get('ok', False), result.stdout

if __name__ == '__main__':
    idx = int(sys.argv[1]) if len(sys.argv) > 1 else -1
    if idx < 0 or idx >= len(WEEKS):
        print(f"Usage: python3 {sys.argv[0]} <0-4>  (0=W31, 1=W32, ...)")
        sys.exit(1)
    block_id, week_num, days = WEEKS[idx]
    content = build_week_table(week_num, days)
    ok, msg = replace_block(block_id, content)
    print(f"W{week_num} replace: {'OK' if ok else 'FAILED'}")
    if not ok:
        print(msg[:500])
