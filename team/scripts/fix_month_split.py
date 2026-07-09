#!/usr/bin/env python3
"""
Fix the month split issue:
1. Delete W32-W40 from 7-month doc (they were added by mistake)
2. Fill W31-W35 周目标+核心风险 in 8-month doc
3. Fill W36-W40 周目标+核心风险 in 9-month doc

Key: 8月 doc W31=8/3-8/7, W32=8/10-8/14, W33=8/17-8/21, W34=8/24-8/28, W35=8/31
     9月 doc W36=9/1-9/4, W37=9/7-9/11, W38=9/14-9/18, W39=9/21-9/25, W40=9/28-9/30
"""

import subprocess
import json
import re
import time
import sys

DOC_7 = "SBUYwm8Lri9aJ6kmexFcBAuGnlh"
DOC_8 = "VeJwwSjEgiUNjokVLWycIMM0nod"
DOC_9 = "AQZbwZLpni7vR3kysWMcomVanye"

# Heading block IDs for W32-W40 in 7-month doc (from outline)
HEADINGS_TO_DELETE_7 = [
    "doxcnkFQQQngKZFrtaTnozgLuQY",  # W32
    "doxcnGxKQwx784SNYHK0O6lbjFd",  # W33
    "doxcnQpjpoLTPHHzZH3rqKpZPNc",  # W34
    "doxcnDg91F2MeGgiYmeW8dmuadc",  # W35
    "doxcn7BTxt7kI4BeZyE7t6t0lng",  # W36
    "doxcnkquBqd0ZtWuAnCL2RPkqid",  # W37
    "doxcn5SOyn0Nygevfygm145BtdG",  # W38
    "doxcngMKkRpWHDujqJ3GbWoR72p",  # W39
    "doxcnpp1AJU481OYHKy9D6hbtWe",  # W40
]

# 8月 doc content (W31=8/3, W32=8/10, W33=8/17, W34=8/24, W35=8/31)
AUG_GOALS = {
    "W31": {
        "场景&生产": (
            "630 新模型验证场景集搭建（新增误减速/RCR 专项）；极速模式渲染质量迭代（Difix 训练）",
            "630 模型效果若不及预期，场景集补充压力增大"
        ),
        "SIL": (
            "latent 提取接入生产链路及自动下载；车型泛化批量验证（≥10款 KPI 对比）；CLIP-IQA 精确度 ≥82%",
            "latent 重刷耗时大；车型泛化结论不收敛"
        ),
        "HIL": (
            "NVFixer 接入 HIL（带 ref 图）；闭环效率验证启动（目标 1:25）",
            "NVFixer + HIL 集成调试复杂"
        ),
        "Agents&预研": (
            "AI agent 迭代提升正式启动；累计 4 个 metric agent 开发（准确率 ≥90%）",
            "agent 与场景集管理集成联调工期"
        ),
    },
    "W32": {
        "场景&生产": (
            "630 RC 路线每日运行 + 报告自动生成 + 问题自动归类；极速 Difix MIG 迭代验证",
            "630 新模型可能引入新问题类型"
        ),
        "SIL": (
            "NVFixer 自动下载完成；CLIP-IQA 误检 case 反馈优化（精确度 ≥85%）；车型聚类方法论输出",
            "V3C 产线化后生产环境稳定性待验证"
        ),
        "HIL": (
            "HIL 闭环效率目标 1:25 验证；慢速模式端到端效率验证（目标 ≤1:8）",
            "效率不达标需回退方案"
        ),
        "Agents&预研": (
            "新增 3 项 Agent 上线（累计 9/12）；量化收益报告 V1（对比人工 review 时间）",
            "量化收益方法论需与管理层对齐"
        ),
    },
    "W33": {
        "场景&生产": (
            "630 vs base 对比报告产出；全链路留存率 ≥70%；用户推广极速默认+漏斗",
            "8/30 量产倒计时，报告质量直接影响发版决策"
        ),
        "SIL": (
            "车型泛化覆盖 20+ 款验证；CLIP-IQA HIL 链路接入；difix MIG 持续优化",
            "车型泛化结论不收敛；HIL CLIP-IQA 依赖 HIL 部署稳定"
        ),
        "HIL": (
            "锐集群闭环提效验证（目标优于 Cloudsim）；慢速模式产线化（自动触发 + 异常重试）",
            "锐集群稳定性待长期验证"
        ),
        "Agents&预研": (
            "新增 2 个 metric agent；Agent 与场景集管理集成联调完成",
            "集成联调工期可能溢出"
        ),
    },
    "W34": {
        "场景&生产": (
            "🔴 630 量产准备周｜全链路留存率 ≥75% 验收；全量用户切极速默认；630 场景集验收完成",
            "量产前仿真质量关卡必须完整通过"
        ),
        "SIL": (
            "difix MIG 1:5 达标验收（不达则输出备选方案）；630 RC gating 报告正式发版参考；30+ 车型覆盖验收",
            "1:5 目标若无法达到需切换技术方案"
        ),
        "HIL": (
            "可用率达 99%+ 验收；慢速 + NVFix 效率 ≤1:8 达标；HIL 作为正式质量关卡",
            "规模扩展风险；掉帧兜底方案"
        ),
        "Agents&预研": (
            "量化收益报告 V2（月度统计）；agent 输出直接标记 case 复现/未复现",
            "收益量化与管理层预期差距"
        ),
    },
    "W35": {
        "场景&生产": (
            "630 量产后首周监控 + 问题快速响应；场景集运营化启动（甘特图 + 周更新）",
            "量产后用户反馈差风险（620 教训：满意度下降 6%+）"
        ),
        "SIL": (
            "CLIP-IQA 正式 gating 上线（异常自动标记）；NVFixer 版本管理稳态化",
            "gating 误拦率控制"
        ),
        "HIL": (
            "稳态运营 + 规模扩展评估（更多节点/更多路线）",
            "运维人力瓶颈"
        ),
        "Agents&预研": (
            "12 专项全覆盖冲刺启动；TopDiff 8 metric 覆盖验收",
            "尾部专项自动化难度高"
        ),
    },
}

# 9月 doc content (W36=9/1, W37=9/7, W38=9/14, W39=9/21, W40=9/28)
SEP_GOALS = {
    "W36": {
        "场景&生产": (
            "630 量产后稳态监控；新增高速/漫游专项纳入场景集；日产 ≥100km 稳态运营",
            "长期运营人力分配"
        ),
        "SIL": (
            "metric 周级迭代覆盖新增路线；车型泛化结论推广至研发",
            "新路线 metric 适配"
        ),
        "HIL": (
            "锐集群稳态接入日常生产；慢速模式作为 HIL 默认模式纳入",
            "锐集群长期稳定性"
        ),
        "Agents&预研": (
            "12 专项 Agent 有效率逐项验收（≥85%）；量化收益月度汇报至双周会",
            "有效率尾部提升困难"
        ),
    },
    "W37": {
        "场景&生产": (
            "复现率监控周报化；极速模式异常自动告警；场景集管理新专项常态化",
            "用户需求变化响应"
        ),
        "SIL": (
            "稳态迭代：metric 异常自动告警 + 周报归档；车型泛化平台自助功能推广",
            "平台功能推广采用率"
        ),
        "HIL": (
            "运营数据月报；节点扩展方案定稿",
            "预算审批"
        ),
        "Agents&预研": (
            "Agent 运营化：每周进度 + 双周会汇报机制固化",
            "运营机制落地阻力"
        ),
    },
    "W38": {
        "场景&生产": (
            "月度用户满意度回访；Q3 收官准备——各项 KPI 对齐检查",
            "最后阶段冲刺压力"
        ),
        "SIL": (
            "Q3 收官冲刺：difix 1:5 / CLIP-IQA gating / 30+ 车型 全部进入最终验收",
            "遗留项风险"
        ),
        "HIL": (
            "Q3 收官冲刺：可用率 99%+ / 掉帧 ≤2% / 效率 1:25 / 慢速 ≤1:8 进入最终验收",
            "遗留掉帧问题"
        ),
        "Agents&预研": (
            "Q3 收官冲刺：12 专项 Agent 覆盖 / TopDiff 8 metric / 量化收益闭环 进入最终验收",
            "尾部目标达成风险"
        ),
    },
    "W39": {
        "场景&生产": (
            "Q3 收官验收：留存 75%+、日产 100km+、执行效率 20min 全部达标",
            "无"
        ),
        "SIL": (
            "Q3 收官验收：10 metric 日运行 + gating 体系完整运营",
            "无"
        ),
        "HIL": (
            "Q3 收官验收：HIL 全部指标达标 + 稳态运营文档归档",
            "无"
        ),
        "Agents&预研": (
            "Q3 收官验收：Agent 全部指标达标 + 能力全景图归档",
            "无"
        ),
    },
    "W40": {
        "场景&生产": (
            "Q3 OKR 验收 + Q4 规划输入；运营数据归档",
            "无"
        ),
        "SIL": (
            "Q3 OKR 验收 + Q4 规划输入；技术方案归档",
            "无"
        ),
        "HIL": (
            "Q3 OKR 验收 + Q4 规划输入；稳定性报告归档",
            "无"
        ),
        "Agents&预研": (
            "Q3 OKR 验收 + Q4 规划输入；Agent 能力全景图归档",
            "无"
        ),
    },
}


def run_cmd(args):
    result = subprocess.run(args, capture_output=True, text=True)
    return result.stdout, result.stderr, result.returncode


def delete_block(doc_token, block_id):
    """Delete a block from a document."""
    out, err, rc = run_cmd([
        "lark-cli", "docs", "+update",
        "--api-version", "v2",
        "--doc", doc_token,
        "--command", "block_delete",
        "--block-id", block_id
    ])
    return rc == 0


def get_table_id_from_section(doc_token, heading_id):
    """Get the table block ID from a section."""
    out, _, rc = run_cmd([
        "lark-cli", "docs", "+fetch",
        "--api-version", "v2",
        "--doc", doc_token,
        "--scope", "section",
        "--start-block-id", heading_id,
        "--detail", "with-ids",
        "--format", "json"
    ])
    if rc != 0:
        return None
    data = json.loads(out)
    content = data.get("data", {}).get("document", {}).get("content", "")
    match = re.search(r'<table id="([^"]+)"', content)
    return match.group(1) if match else None


def get_section_content(doc_token, heading_id):
    """Get full section content (for extracting current table structure)."""
    out, _, rc = run_cmd([
        "lark-cli", "docs", "+fetch",
        "--api-version", "v2",
        "--doc", doc_token,
        "--scope", "section",
        "--start-block-id", heading_id,
        "--detail", "with-ids",
        "--format", "json"
    ])
    if rc != 0:
        return None
    data = json.loads(out)
    return data.get("data", {}).get("document", {}).get("content", "")


def fill_goals_in_existing_table(doc_token, heading_id, goals_data):
    """
    The 8/9 month docs have tables with daily rows (Mon-Fri with @mentions).
    We only need to fill the '周目标' and '核心风险' rows (rows 2 and 3).
    Strategy: use str_replace on the document to fill empty cells.
    """
    content = get_section_content(doc_token, heading_id)
    if not content:
        return False

    table_id = None
    match = re.search(r'<table id="([^"]+)"', content)
    if match:
        table_id = match.group(1)

    if not table_id:
        return False

    # Extract the full table
    table_match = re.search(r'(<table id="[^"]*">)(.*?)(</table>)', content, re.DOTALL)
    if not table_match:
        return False

    full_table = table_match.group(0)
    inner = table_match.group(2)

    # Find the 周目标 row - it's the second <tr>
    # We'll rebuild the table with goals filled in
    rows = re.findall(r'<tr>(.*?)</tr>', inner, re.DOTALL)
    if len(rows) < 3:
        print(f"    Table has only {len(rows)} rows, expected >=3")
        return False

    # Row 0: header (W##, 场景&生产, SIL, HIL, Agents&预研)
    # Row 1: 周目标 (need to fill)
    # Row 2: 核心风险 (need to fill)
    # Rows 3+: daily rows (keep as-is)

    scene_goal, scene_risk = goals_data["场景&生产"]
    sil_goal, sil_risk = goals_data["SIL"]
    hil_goal, hil_risk = goals_data["HIL"]
    agent_goal, agent_risk = goals_data["Agents&预研"]

    # Build new row 1 (周目标)
    new_row1 = '<tr>'
    new_row1 += '<td vertical-align="top"><p align="center"><b>周目标</b></p></td>'
    new_row1 += f'<td vertical-align="top"><p>{scene_goal}</p></td>'
    new_row1 += f'<td vertical-align="top"><p>{sil_goal}</p></td>'
    new_row1 += f'<td vertical-align="top"><p>{hil_goal}</p></td>'
    new_row1 += f'<td vertical-align="top"><p>{agent_goal}</p></td>'
    new_row1 += '</tr>'

    # Build new row 2 (核心风险)
    new_row2 = '<tr>'
    new_row2 += '<td vertical-align="top"><p align="center"><b>核心风险&amp;上下游交互</b></p></td>'
    new_row2 += f'<td vertical-align="top"><p>{scene_risk}</p></td>'
    new_row2 += f'<td vertical-align="top"><p>{sil_risk}</p></td>'
    new_row2 += f'<td vertical-align="top"><p>{hil_risk}</p></td>'
    new_row2 += f'<td vertical-align="top"><p>{agent_risk}</p></td>'
    new_row2 += '</tr>'

    # Reconstruct table: keep header + replace rows 1,2 + keep rest
    # Remove IDs from all rows to avoid conflicts
    header_row = '<tr>' + re.sub(r' id="[^"]*"', '', rows[0]) + '</tr>'
    daily_rows = ''.join('<tr>' + re.sub(r' id="[^"]*"', '', r) + '</tr>' for r in rows[3:])

    new_inner = '<colgroup><col width="100"/><col width="500"/><col width="500"/><col width="500"/><col width="500"/></colgroup><tbody>'
    new_inner += header_row + new_row1 + new_row2 + daily_rows
    new_inner += '</tbody>'

    new_table = f'<table>{new_inner}</table>'

    # Replace the table
    out, err, rc = run_cmd([
        "lark-cli", "docs", "+update",
        "--api-version", "v2",
        "--doc", doc_token,
        "--command", "block_replace",
        "--block-id", table_id,
        "--content", new_table
    ])
    if rc != 0:
        print(f"    Replace failed: {err[:200]}")
        return False
    return True


def main():
    # ============================================================
    # Phase 1: Delete W32-W40 from 7-month doc
    # ============================================================
    print("=" * 50)
    print("Phase 1: Deleting W32-W40 from 7-month doc...")
    print("=" * 50)

    for i, heading_id in enumerate(HEADINGS_TO_DELETE_7):
        week_num = 32 + i
        print(f"  Deleting W{week_num} heading: {heading_id}")

        # First get the table under this heading and delete it
        table_id = get_table_id_from_section(DOC_7, heading_id)
        if table_id:
            ok = delete_block(DOC_7, table_id)
            print(f"    Table {table_id}: {'deleted' if ok else 'FAILED'}")
            time.sleep(0.5)

        # Then delete the heading itself
        ok = delete_block(DOC_7, heading_id)
        print(f"    Heading: {'deleted' if ok else 'FAILED'}")
        time.sleep(0.5)

    # ============================================================
    # Phase 2: Fill 8-month doc W31-W35
    # ============================================================
    print("\n" + "=" * 50)
    print("Phase 2: Filling 8-month doc (W31-W35)...")
    print("=" * 50)

    AUG_HEADINGS = {
        "W31": "doxcnxC5ydnQ9ZY8q9zmvANuYvc",
        "W32": "doxcnFPojVtab5HK0emL2hAHwpe",
        "W33": "doxcnQIY9VUYMpg5SmdFu1UpmMb",
        "W34": "doxcni2ejGuo47ZX3auM7KiMnxb",
        "W35": "doxcnpU99yyswpKYVqILsyZZ5Bg",
    }

    for week, heading_id in AUG_HEADINGS.items():
        print(f"\n  Filling {week}...")
        ok = fill_goals_in_existing_table(DOC_8, heading_id, AUG_GOALS[week])
        print(f"    {'OK' if ok else 'FAILED'}")
        time.sleep(1)

    # ============================================================
    # Phase 3: Fill 9-month doc W36-W40
    # ============================================================
    print("\n" + "=" * 50)
    print("Phase 3: Filling 9-month doc (W36-W40)...")
    print("=" * 50)

    SEP_HEADINGS = {
        "W36": "doxcnev6NlzdFRR20xaglR6PCIg",
        "W37": "doxcnxAOF7Cx95uHUt76I5KP7wY",
        "W38": "doxcnUDzcPik5Nj0hdcQlwOvDJb",
        "W39": "doxcnrCJ2tVjXRt3D0vDZBJhusf",
        "W40": "doxcnJ2jF4B3TlRTVmk2hPAYhfh",
    }

    for week, heading_id in SEP_HEADINGS.items():
        print(f"\n  Filling {week}...")
        ok = fill_goals_in_existing_table(DOC_9, heading_id, SEP_GOALS[week])
        print(f"    {'OK' if ok else 'FAILED'}")
        time.sleep(1)

    print("\n" + "=" * 50)
    print("Done! All three docs properly split.")


if __name__ == "__main__":
    main()
