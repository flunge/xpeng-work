#!/usr/bin/env python3
"""Replace week tables with centered header row + first column."""
import subprocess, json, sys, tempfile, os

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

# Centered td for header row and first column
def td_center(content):
    """First row / first column cell: centered both horizontally and vertically."""
    return f'<td vertical-align="middle"><p align="center">{content}</p></td>'

# Normal td for content cells
def td_top(content):
    return f'<td vertical-align="top">{content}</td>'


def build_day_row(day_label):
    return (
        f'<tr>'
        f'{td_center("<b>" + day_label + "</b>")}'
        f'{td_top(SCENE_CELL)}'
        f'{td_top(SIL_CELL)}'
        f'{td_top(HIL_CELL)}'
        f'{td_top(AGENTS_CELL)}'
        f'</tr>'
    )


def build_week_table(week_num, days, goals=None, risks=None):
    # Header row - ALL cells centered
    header = (
        '<tr>'
        f'{td_center("<b>W" + str(week_num) + "</b>")}'
        f'{td_center("<b>场景&amp;生产</b>")}'
        f'{td_center("<b>SIL</b>")}'
        f'{td_center("<b>HIL</b>")}'
        f'{td_center("<b>Agents&amp;预研</b>")}'
        '</tr>'
    )
    # Goal row - first col centered, rest top-aligned
    goal_row = (
        '<tr>'
        f'{td_center("<b>周目标</b>")}'
        f'<td vertical-align="top"><p>{goals[0] if goals else ""}</p></td>'
        f'<td vertical-align="top"><p>{goals[1] if goals else ""}</p></td>'
        f'<td vertical-align="top"><p>{goals[2] if goals else ""}</p></td>'
        f'<td vertical-align="top"><p>{goals[3] if goals else ""}</p></td>'
        '</tr>'
    )
    # Risk row - first col centered
    risk_row = (
        '<tr>'
        f'{td_center("<b>核心风险&amp;上下游交互</b>")}'
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


def replace_block(doc, block_id, content):
    fd, path = tempfile.mkstemp(suffix='.xml')
    with os.fdopen(fd, 'w') as f:
        f.write(content)
    cmd = (
        f'lark-cli docs +update --api-version v2 '
        f'--doc "{doc}" '
        f'--command block_replace '
        f'--block-id {block_id} '
        f'--content-file "{path}" '
        f'--format json'
    )
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    os.unlink(path)
    if result.returncode != 0:
        cmd2 = (
            f'lark-cli docs +update --api-version v2 '
            f'--doc "{doc}" '
            f'--command block_replace '
            f'--block-id {block_id} '
            f"--content '{content}' "
            f'--format json'
        )
        result = subprocess.run(cmd2, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        return False, result.stderr
    try:
        data = json.loads(result.stdout)
        return data.get('ok', False), ''
    except:
        return False, result.stdout[:200]


# All documents and their table configs
DOCS = {
    'july': {
        'doc_id': 'SBUYwm8Lri9aJ6kmexFcBAuGnlh',
        'tables': [
            ('QPoPdMMYBooNXPxGaGAclD2FnAf', 28, ['周一 7/6', '周二 7/7', '周三 7/8', '周四 7/9', '周五 7/10'],
             ['日产 1000 case、累计破 3500km；极速漏斗常态化',
              'difix(MIG) 1:14.8→1:12；CLIP-IQA 上线联调',
              '005 接入跑稳、可用率冲 95%；difix 复现率 50%',
              'NVFixer 64 卡训练启动；复现率 Agent 准确率补齐'],
             ['公共卡池被高优挤占，产能不稳',
              '1:5 目标受算力约束',
              'HIL 多次运行随机性未管理',
              'metric diff agent 准确率仅 50%']),
            ('AJEEdlvi9oru8px9ZBbcksRVnDd', 29, ['周一 7/13', '周二 7/14', '周三 7/15', '周四 7/16', '周五 7/17'], None, None),
            ('RCfGdp5DTosANHxBXKKcCZynnxh', 30, ['周一 7/20', '周二 7/21', '周三 7/22', '周四 7/23', '周五 7/24'], None, None),
            ('H8JTdOQ8WoaGLaxDbCwcBnsOnuR', 31, ['周一 7/27', '周二 7/28', '周三 7/29', '周四 7/30', '周五 7/31'], None, None),
        ]
    },
    'august': {
        'doc_id': 'Pdhud83wwo1d4KxnS9dcma1nn1g',
        'tables': [
            ('doxcnleeuUanFk3MRG7k44NHPrD', 31, ['周一 8/3', '周二 8/4', '周三 8/5', '周四 8/6', '周五 8/7'], None, None),
            ('doxcnBxQyvBCcBam7Pyhkat5T2f', 32, ['周一 8/10', '周二 8/11', '周三 8/12', '周四 8/13', '周五 8/14'], None, None),
            ('doxcnQV41Q9qWS7TIA9S9P5sOEs', 33, ['周一 8/17', '周二 8/18', '周三 8/19', '周四 8/20', '周五 8/21'], None, None),
            ('doxcnHjNcCu7NVzAfLBikn6iHud', 34, ['周一 8/24', '周二 8/25', '周三 8/26', '周四 8/27', '周五 8/28'], None, None),
            ('doxcn2Rs6NXmggoTSUm4EhX9oMb', 35, ['周一 8/31'], None, None),
        ]
    },
    'september': {
        'doc_id': 'KtzpdQdcxotyGZxdmpgcJpnInef',
        'tables': [
            ('doxcnKW2tvuHNEfLg1Khlklik8f', 36, ['周一 9/1', '周二 9/2', '周三 9/3', '周四 9/4'], None, None),
            ('doxcnfmgBbb5X4AGaSMMivZvmGf', 37, ['周一 9/7', '周二 9/8', '周三 9/9', '周四 9/10', '周五 9/11'], None, None),
            ('doxcnEIXuuDZOUMkGMrtNKPNV4q', 38, ['周一 9/14', '周二 9/15', '周三 9/16', '周四 9/17', '周五 9/18'], None, None),
            ('doxcnuoZtGr5h9nyZ6RB7fkhP6f', 39, ['周一 9/21', '周二 9/22', '周三 9/23', '周四 9/24', '周五 9/25'], None, None),
            ('doxcnaUIHeQiDaw9IaxrJPeX8if', 40, ['周一 9/28', '周二 9/29', '周三 9/30'], None, None),
        ]
    }
}


if __name__ == '__main__':
    month = sys.argv[1] if len(sys.argv) > 1 else 'help'
    idx = int(sys.argv[2]) if len(sys.argv) > 2 else -1

    if month == 'help' or month not in DOCS:
        print(f"Usage: python3 {sys.argv[0]} <july|august|september> <table_index>")
        print("  table_index: 0-based index of the table in that month")
        sys.exit(1)

    cfg = DOCS[month]
    if idx < 0 or idx >= len(cfg['tables']):
        print(f"Index must be 0-{len(cfg['tables'])-1}")
        sys.exit(1)

    block_id, week_num, days, goals, risks = cfg['tables'][idx]
    content = build_week_table(week_num, days, goals, risks)
    ok, err = replace_block(cfg['doc_id'], block_id, content)
    print(f"W{week_num} ({month}): {'OK' if ok else 'FAILED'}")
    if not ok:
        print(err)
