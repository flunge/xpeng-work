#!/usr/bin/env python3
"""Update week tables in SBUYwm8L to match W27 format.
Replace W28-W31 tables with properly formatted versions."""

import subprocess, json, sys

# Standard cell templates matching W27 format exactly

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


def build_week_table(week_num, days, goals=None, risks=None):
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
        '<tr>'
        '<td vertical-align="top"><p><b>周目标</b></p></td>'
        f'<td vertical-align="top"><p>{goals[0] if goals else ""}</p></td>'
        f'<td vertical-align="top"><p>{goals[1] if goals else ""}</p></td>'
        f'<td vertical-align="top"><p>{goals[2] if goals else ""}</p></td>'
        f'<td vertical-align="top"><p>{goals[3] if goals else ""}</p></td>'
        '</tr>'
    )
    risk_row = (
        '<tr>'
        '<td vertical-align="top"><p><b>核心风险&amp;上下游交互</b></p></td>'
        f'<td vertical-align="top"><p>{risks[0] if risks else ""}</p></td>'
        f'<td vertical-align="top"><p>{risks[1] if risks else ""}</p></td>'
        f'<td vertical-align="top"><p>{risks[2] if risks else ""}</p></td>'
        f'<td vertical-align="top"><p>{risks[3] if risks else ""}</p></td>'
        '</tr>'
    )
    day_rows = ''.join(build_day_row(d) for d in days)
    return (
        f'<table><colgroup><col/><col/><col/><col/><col/></colgroup><tbody>'
        f'{header}{goal_row}{risk_row}{day_rows}'
        f'</tbody></table>'
    )


def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: {result.stderr}", file=sys.stderr)
        return None
    return result.stdout


def replace_block(doc, block_id, content):
    """Replace a block in the document."""
    cmd = (
        f'lark-cli docs +update --api-version v2 '
        f'--doc "{doc}" '
        f'--command block_replace '
        f'--block-id {block_id} '
        f"--content '{content}' "
        f'--format json'
    )
    out = run_cmd(cmd)
    if out:
        data = json.loads(out)
        if data.get('ok'):
            return True
        print(f"API error: {data}", file=sys.stderr)
    return False


if __name__ == '__main__':
    doc = "SBUYwm8Lri9aJ6kmexFcBAuGnlh"
    action = sys.argv[1] if len(sys.argv) > 1 else 'help'

    if action == 'replace_w28':
        # W28 table block id: QPoPdMMYBooNXPxGaGAclD2FnAf
        block_id = "QPoPdMMYBooNXPxGaGAclD2FnAf"
        goals = [
            '日产 1000 case、累计破 3500km；极速漏斗常态化',
            'difix(MIG) 1:14.8→1:12；CLIP-IQA 上线联调',
            '005 接入跑稳、可用率冲 95%；difix 复现率 50%',
            'NVFixer 64 卡训练启动；复现率 Agent 准确率补齐'
        ]
        risks = [
            '公共卡池被高优挤占，产能不稳',
            '1:5 目标受算力约束',
            'HIL 多次运行随机性未管理',
            'metric diff agent 准确率仅 50%'
        ]
        days = ['周一 7/6', '周二 7/7', '周三 7/8', '周四 7/9', '周五 7/10']
        content = build_week_table(28, days, goals, risks)
        ok = replace_block(doc, block_id, content)
        print(f"W28 replace: {'OK' if ok else 'FAILED'}")

    elif action == 'replace_w29':
        block_id = "AJEEdlvi9oru8px9ZBbcksRVnDd"
        days = ['周一 7/13', '周二 7/14', '周三 7/15', '周四 7/16', '周五 7/17']
        content = build_week_table(29, days)
        ok = replace_block(doc, block_id, content)
        print(f"W29 replace: {'OK' if ok else 'FAILED'}")

    elif action == 'replace_w30':
        block_id = "RCfGdp5DTosANHxBXKKcCZynnxh"
        days = ['周一 7/20', '周二 7/21', '周三 7/22', '周四 7/23', '周五 7/24']
        content = build_week_table(30, days)
        ok = replace_block(doc, block_id, content)
        print(f"W30 replace: {'OK' if ok else 'FAILED'}")

    elif action == 'replace_w31':
        block_id = "H8JTdOQ8WoaGLaxDbCwcBnsOnuR"
        days = ['周一 7/27', '周二 7/28', '周三 7/29', '周四 7/30', '周五 7/31']
        content = build_week_table(31, days)
        ok = replace_block(doc, block_id, content)
        print(f"W31 replace: {'OK' if ok else 'FAILED'}")

    else:
        print("Usage: python3 update_doc_tables.py [replace_w28|replace_w29|replace_w30|replace_w31]")
