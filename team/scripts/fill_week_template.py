#!/usr/bin/env python3
"""Generate XML for a single day cell matching W27 format from SBUYwm8L."""

import subprocess, json, sys

# W28 daily template - matches W27 structure exactly
# Each cell: 业务交付 (projects+@owners) + 算法优化/算法预研 (projects+@owners)
# For columns: 场景&生产 / SIL / HIL / Agents&预研

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
    """Build a single day row."""
    return (
        f'<tr>'
        f'<td vertical-align="top"><p><b>{day_label}</b></p></td>'
        f'<td vertical-align="top">{SCENE_CELL}</td>'
        f'<td vertical-align="top">{SIL_CELL}</td>'
        f'<td vertical-align="top">{HIL_CELL}</td>'
        f'<td vertical-align="top">{AGENTS_CELL}</td>'
        f'</tr>'
    )


def build_week_table(week_num, date_range, days, goals=None, risks=None):
    """Build a complete week table."""
    header = (
        f'<tr>'
        f'<td vertical-align="top"><p><b>W{week_num}</b></p></td>'
        f'<td vertical-align="top"><p><b>场景&amp;生产</b></p></td>'
        f'<td vertical-align="top"><p><b>SIL</b></p></td>'
        f'<td vertical-align="top"><p><b>HIL</b></p></td>'
        f'<td vertical-align="top"><p><b>Agents&amp;预研</b></p></td>'
        f'</tr>'
    )

    goal_row = (
        f'<tr>'
        f'<td vertical-align="top"><p><b>周目标</b></p></td>'
        f'<td vertical-align="top"><p>{goals[0] if goals else ""}</p></td>'
        f'<td vertical-align="top"><p>{goals[1] if goals else ""}</p></td>'
        f'<td vertical-align="top"><p>{goals[2] if goals else ""}</p></td>'
        f'<td vertical-align="top"><p>{goals[3] if goals else ""}</p></td>'
        f'</tr>'
    )

    risk_row = (
        f'<tr>'
        f'<td vertical-align="top"><p><b>核心风险&amp;上下游交互</b></p></td>'
        f'<td vertical-align="top"><p>{risks[0] if risks else ""}</p></td>'
        f'<td vertical-align="top"><p>{risks[1] if risks else ""}</p></td>'
        f'<td vertical-align="top"><p>{risks[2] if risks else ""}</p></td>'
        f'<td vertical-align="top"><p>{risks[3] if risks else ""}</p></td>'
        f'</tr>'
    )

    day_rows = ''.join(build_day_row(d) for d in days)

    return (
        f'<table><colgroup><col/><col/><col/><col/><col/></colgroup><tbody>'
        f'{header}{goal_row}{risk_row}{day_rows}'
        f'</tbody></table>'
    )


if __name__ == '__main__':
    action = sys.argv[1] if len(sys.argv) > 1 else 'print'

    if action == 'print_w28_days':
        # Print W28 Tue-Fri day rows for filling
        days = ['周二 7/7', '周三 7/8', '周四 7/9', '周五 7/10']
        for d in days:
            print(build_day_row(d))
            print()

    elif action == 'build_8月':
        # Build month 8 tables
        weeks = [
            (31, '8/3-8/7', ['周一 8/3', '周二 8/4', '周三 8/5', '周四 8/6', '周五 8/7']),
            (32, '8/10-8/14', ['周一 8/10', '周二 8/11', '周三 8/12', '周四 8/13', '周五 8/14']),
            (33, '8/17-8/21', ['周一 8/17', '周二 8/18', '周三 8/19', '周四 8/20', '周五 8/21']),
            (34, '8/24-8/28', ['周一 8/24', '周二 8/25', '周三 8/26', '周四 8/27', '周五 8/28']),
            (35, '8/31', ['周一 8/31']),
        ]
        content = ''
        for wn, dr, days in weeks:
            content += f'<h3>W{wn}（{dr}）</h3>\n'
            content += build_week_table(wn, dr, days)
            content += '\n'
        print(content)

    elif action == 'build_9月':
        weeks = [
            (36, '9/1-9/4', ['周一 9/1', '周二 9/2', '周三 9/3', '周四 9/4']),
            (37, '9/7-9/11', ['周一 9/7', '周二 9/8', '周三 9/9', '周四 9/10', '周五 9/11']),
            (38, '9/14-9/18', ['周一 9/14', '周二 9/15', '周三 9/16', '周四 9/17', '周五 9/18']),
            (39, '9/21-9/25', ['周一 9/21', '周二 9/22', '周三 9/23', '周四 9/24', '周五 9/25']),
            (40, '9/28-9/30', ['周一 9/28', '周二 9/29', '周三 9/30']),
        ]
        content = ''
        for wn, dr, days in weeks:
            content += f'<h3>W{wn}（{dr}）</h3>\n'
            content += build_week_table(wn, dr, days)
            content += '\n'
        print(content)

    else:
        print("Usage: python3 fill_week_template.py [print_w28_days|build_8月|build_9月]")
