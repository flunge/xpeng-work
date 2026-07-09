#!/usr/bin/env python3
"""Refetch all table block IDs and replace with centered format."""
import subprocess, json, sys, re

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
        '<tr>'
        f'<td vertical-align="top"><p align="center"><b>{day_label}</b></p></td>'
        f'<td vertical-align="top">{SCENE_CELL}</td>'
        f'<td vertical-align="top">{SIL_CELL}</td>'
        f'<td vertical-align="top">{HIL_CELL}</td>'
        f'<td vertical-align="top">{AGENTS_CELL}</td>'
        '</tr>'
    )


def build_week_table(week_num, days, goals=None, risks=None):
    header = (
        '<tr>'
        f'<td vertical-align="top"><p align="center"><b>W{week_num}</b></p></td>'
        '<td vertical-align="top"><p align="center"><b>场景&amp;生产</b></p></td>'
        '<td vertical-align="top"><p align="center"><b>SIL</b></p></td>'
        '<td vertical-align="top"><p align="center"><b>HIL</b></p></td>'
        '<td vertical-align="top"><p align="center"><b>Agents&amp;预研</b></p></td>'
        '</tr>'
    )
    goal_row = (
        '<tr>'
        '<td vertical-align="top"><p align="center"><b>周目标</b></p></td>'
        f'<td vertical-align="top"><p>{goals[0] if goals else ""}</p></td>'
        f'<td vertical-align="top"><p>{goals[1] if goals else ""}</p></td>'
        f'<td vertical-align="top"><p>{goals[2] if goals else ""}</p></td>'
        f'<td vertical-align="top"><p>{goals[3] if goals else ""}</p></td>'
        '</tr>'
    )
    risk_row = (
        '<tr>'
        '<td vertical-align="top"><p align="center"><b>核心风险&amp;上下游交互</b></p></td>'
        f'<td vertical-align="top"><p>{risks[0] if risks else ""}</p></td>'
        f'<td vertical-align="top"><p>{risks[1] if risks else ""}</p></td>'
        f'<td vertical-align="top"><p>{risks[2] if risks else ""}</p></td>'
        f'<td vertical-align="top"><p>{risks[3] if risks else ""}</p></td>'
        '</tr>'
    )
    day_rows = ''.join(build_day_row(d) for d in days)
    return (
        '<table>'
        '<colgroup><col width="100"/><col width="500"/><col width="500"/><col width="500"/><col width="500"/></colgroup>'
        '<tbody>'
        f'{header}{goal_row}{risk_row}{day_rows}'
        '</tbody></table>'
    )


def fetch_table_ids(doc_id, section_block_id):
    """Fetch all table IDs from a section."""
    cmd = [
        'lark-cli', 'docs', '+fetch',
        '--api-version', 'v2',
        '--doc', doc_id,
        '--scope', 'section',
        '--start-block-id', section_block_id,
        '--detail', 'with-ids',
        '--format', 'json'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    data = json.loads(result.stdout)
    content = data.get('data', {}).get('document', {}).get('content', '')
    return re.findall(r'<table id="([^"]+)"', content)


def replace_block(doc, block_id, content):
    cmd = [
        'lark-cli', 'docs', '+update',
        '--api-version', 'v2',
        '--doc', doc,
        '--command', 'block_replace',
        '--block-id', block_id,
        '--content', content,
        '--format', 'json'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return False, result.stderr[:200]
    try:
        data = json.loads(result.stdout)
        return data.get('ok', False), ''
    except:
        return False, result.stdout[:200]


# Config: (doc_id, section_h2_block_id, [(week_num, days, goals, risks), ...])
CONFIGS = [
    {
        'name': 'july (SBUYwm8L)',
        'doc_id': 'SBUYwm8Lri9aJ6kmexFcBAuGnlh',
        'section_id': 'GTIYd42JgoJMq1xBPDhcMwwOn3c',
        'skip_first': 1,  # Skip W27 (user's manual table)
        'weeks': [
            (28, ['周一 7/6', '周二 7/7', '周三 7/8', '周四 7/9', '周五 7/10'],
             ['日产 1000 case、累计破 3500km；极速漏斗常态化',
              'difix(MIG) 1:14.8→1:12；CLIP-IQA 上线联调',
              '005 接入跑稳、可用率冲 95%；difix 复现率 50%',
              'NVFixer 64 卡训练启动；复现率 Agent 准确率补齐'],
             ['公共卡池被高优挤占，产能不稳',
              '1:5 目标受算力约束',
              'HIL 多次运行随机性未管理',
              'metric diff agent 准确率仅 50%']),
            (29, ['周一 7/13', '周二 7/14', '周三 7/15', '周四 7/16', '周五 7/17'], None, None),
            (30, ['周一 7/20', '周二 7/21', '周三 7/22', '周四 7/23', '周五 7/24'], None, None),
            (31, ['周一 7/27', '周二 7/28', '周三 7/29', '周四 7/30', '周五 7/31'], None, None),
        ]
    },
    {
        'name': 'august',
        'doc_id': 'Pdhud83wwo1d4KxnS9dcma1nn1g',
        'section_id': 'doxcnS72SsYU1qbOfG7vW7mmPPf',
        'skip_first': 0,
        'weeks': [
            (31, ['周一 8/3', '周二 8/4', '周三 8/5', '周四 8/6', '周五 8/7'], None, None),
            (32, ['周一 8/10', '周二 8/11', '周三 8/12', '周四 8/13', '周五 8/14'], None, None),
            (33, ['周一 8/17', '周二 8/18', '周三 8/19', '周四 8/20', '周五 8/21'], None, None),
            (34, ['周一 8/24', '周二 8/25', '周三 8/26', '周四 8/27', '周五 8/28'], None, None),
            (35, ['周一 8/31'], None, None),
        ]
    },
    {
        'name': 'september',
        'doc_id': 'KtzpdQdcxotyGZxdmpgcJpnInef',
        'section_id': 'doxcnUasNNXU2J8g7SnRw8DRMZc',
        'skip_first': 0,
        'weeks': [
            (36, ['周一 9/1', '周二 9/2', '周三 9/3', '周四 9/4'], None, None),
            (37, ['周一 9/7', '周二 9/8', '周三 9/9', '周四 9/10', '周五 9/11'], None, None),
            (38, ['周一 9/14', '周二 9/15', '周三 9/16', '周四 9/17', '周五 9/18'], None, None),
            (39, ['周一 9/21', '周二 9/22', '周三 9/23', '周四 9/24', '周五 9/25'], None, None),
            (40, ['周一 9/28', '周二 9/29', '周三 9/30'], None, None),
        ]
    }
]


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else 'all'

    for cfg in CONFIGS:
        if target != 'all' and target not in cfg['name']:
            continue

        print(f"\n=== {cfg['name']} ===")

        # Fetch current table IDs
        table_ids = fetch_table_ids(cfg['doc_id'], cfg['section_id'])
        print(f"Found {len(table_ids)} tables")

        # Skip first N tables (e.g. W27 in july)
        table_ids = table_ids[cfg['skip_first']:]

        if len(table_ids) < len(cfg['weeks']):
            print(f"WARNING: Expected {len(cfg['weeks'])} tables, found {len(table_ids)}")

        for i, (week_num, days, goals, risks) in enumerate(cfg['weeks']):
            if i >= len(table_ids):
                print(f"W{week_num}: SKIP (no table ID)")
                continue

            block_id = table_ids[i]
            content = build_week_table(week_num, days, goals, risks)
            ok, err = replace_block(cfg['doc_id'], block_id, content)
            print(f"W{week_num}: {'OK' if ok else 'FAILED'} (block={block_id[:12]}...)")
            if not ok:
                print(f"  {err}")
