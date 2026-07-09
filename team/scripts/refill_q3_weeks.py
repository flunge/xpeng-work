#!/usr/bin/env python3
"""Re-fill W29-W40 tables (content was lost during colwidth fix).
Uses section-scoped fetch to get block IDs, then replaces with full content."""

import subprocess
import json
import re
import time
import sys

DOC_TOKEN = "SBUYwm8Lri9aJ6kmexFcBAuGnlh"

WEEKS_DATA = {
    "W29": {
        "date": "7/13-7/17",
        "场景&生产": (
            "园区摆动+导航走错路毕业；Robotaxi 新增2项 metrics 测试完成；RC 系统每日运行稳定化",
            "Robotaxi case 不足影响毕业进度；大数据 pipeline 修复依赖 TC 排期"
        ),
        "SIL": (
            "NVFixer 64卡训练结果评估 + FM轨迹仿真验证；Moe 模型发版后批量造泛化 case（≥10款）",
            "GPU 资源被 630 训练抢占；V3C 与 V3D 产线化选型待定"
        ),
        "HIL": (
            "三节点最终稳定性压测完成；万兆网卡对比实验出结论；可用率冲 97%",
            "掉帧 12% 根因未完全定位；HIL 多次运行随机性管理"
        ),
        "Agents&预研": (
            "7/6 专职人员到位后 Behavior 层规则收敛；顿挫 Agent 迭代至 80%+；TopDiff 项目管理化启动",
            "metric diff agent 准确率仅 50%；Agent 整体延期（原计划 630 集成）"
        ),
    },
    "W30": {
        "date": "7/20-7/24",
        "场景&生产": (
            "case 裁剪全部完成（4700项清洗验证）；场景执行效率验证达标（20min/4000case）；日产稳定 ≥100km",
            "160-200 个 case 时间段不在 DDS 范围需人工 review；极速模式交互简化依赖平台排期"
        ),
        "SIL": (
            "10 个核心 metric 筛选确认；V3C 产线化 pipeline 打通；CLIP-IQA Cloudsim 联调完成",
            "metric 老框架 RTM topic 格式变更阻塞（DSOP 根因待修）"
        ),
        "HIL": (
            "Seal 链路正式合入 + 全局开关（HIL/Seal 切换）；TensorRT 转换完成；latent 直读链路开发",
            "Seal/HIL 切换可能引入新稳定性问题"
        ),
        "Agents&预研": (
            "新增 2 个 metric agent 开发启动（从城区 P0 选）；复现率 Agent 画龙迭代至 82%+",
            "Agent 与场景集管理集成复杂度高于预期"
        ),
    },
    "W31": {
        "date": "7/27-7/31",
        "场景&生产": (
            "🔴 630 模型冻结周｜极速漏斗策略上线；Robotaxi 3项延期解决；全链路留存率 ≥65%",
            "630 冻结倒计时，gating 链路必须就绪；留存率提升依赖 TC 抢占修复进度"
        ),
        "SIL": (
            "10 metric 首轮跑通 + 首份可解读 SIL 报告产出；difix MIG 1:8 路径确认；车型聚类初步方案输出",
            "630 冻结前 gating 报告可信度不足；difix 1:5 目标受算力约束"
        ),
        "HIL": (
            "掉帧问题根因修复（目标 ≤5%）；慢速 latent 直读跑通；连续 case 尾部掉帧验证",
            "连续 case 尾部掉帧未完全解决；H265→latent 重刷耗时不确定"
        ),
        "Agents&预研": (
            "Behavior 层 3 类 metric KPI 提升 5% 验收；6项「暂不自动化」评估启动 2-3项",
            "7/30 冻结前 agent 能力需证明 ROI（高炳涛要求量化收益）"
        ),
    },
    "W32": {
        "date": "8/3-8/7",
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
    "W33": {
        "date": "8/10-8/14",
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
    "W34": {
        "date": "8/17-8/21",
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
    "W35": {
        "date": "8/24-8/28",
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
    "W36": {
        "date": "8/31-9/4",
        "场景&生产": (
            "630 量产后监控 + 问题响应；场景集运营化启动（甘特图 + 周更新）；新增高速/漫游专项纳入",
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
            "12 专项全覆盖冲刺；TopDiff 8 metric 覆盖验收；代码治理 Q3 大调整启动",
            "尾部专项自动化难度高"
        ),
    },
    "W37": {
        "date": "9/7-9/11",
        "场景&生产": (
            "日产 ≥100km 稳态运营；复现率监控周报化；极速模式异常自动告警",
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
            "12 专项 ≥85% 有效率逐项验收；量化收益月度汇报至双周会",
            "有效率尾部提升困难"
        ),
    },
    "W38": {
        "date": "9/14-9/18",
        "场景&生产": (
            "月度用户满意度回访；场景集管理新专项常态化纳入",
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
    "W39": {
        "date": "9/21-9/25",
        "场景&生产": (
            "Q3 收官准备：各项 KPI 最终冲刺（留存 75%+、日产 100km+、执行效率 20min）",
            "最后一周冲刺压力"
        ),
        "SIL": (
            "Q3 收官：difix 1:5 / CLIP-IQA gating / 30+ 车型 / 10 metric 日运行 全部验收",
            "遗留项风险"
        ),
        "HIL": (
            "Q3 收官：可用率 99%+ / 掉帧 ≤2% / 效率 1:25 / 慢速 ≤1:8 全部验收",
            "遗留掉帧问题"
        ),
        "Agents&预研": (
            "Q3 收官：12 专项 Agent 覆盖 / TopDiff 8 metric / 量化收益闭环 全部验收",
            "尾部目标达成风险"
        ),
    },
    "W40": {
        "date": "9/28-9/30",
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


def build_table_xml(week_key, data):
    """Build XML for a week table with header + goals + risks rows.
    Include colgroup with widths."""
    scene_goal, scene_risk = data["场景&生产"]
    sil_goal, sil_risk = data["SIL"]
    hil_goal, hil_risk = data["HIL"]
    agent_goal, agent_risk = data["Agents&预研"]

    xml = '<table><colgroup><col width="100"/><col width="500"/><col width="500"/><col width="500"/><col width="500"/></colgroup><tbody>'
    # Row 1: Header
    xml += f'<tr><td vertical-align="top"><p align="center"><b>{week_key}</b></p></td>'
    xml += '<td vertical-align="top"><p align="center"><b>场景&amp;生产</b></p></td>'
    xml += '<td vertical-align="top"><p align="center"><b>SIL</b></p></td>'
    xml += '<td vertical-align="top"><p align="center"><b>HIL</b></p></td>'
    xml += '<td vertical-align="top"><p align="center"><b>Agents&amp;预研</b></p></td></tr>'
    # Row 2: 周目标
    xml += '<tr><td vertical-align="top"><p align="center"><b>周目标</b></p></td>'
    xml += f'<td vertical-align="top"><p>{scene_goal}</p></td>'
    xml += f'<td vertical-align="top"><p>{sil_goal}</p></td>'
    xml += f'<td vertical-align="top"><p>{hil_goal}</p></td>'
    xml += f'<td vertical-align="top"><p>{agent_goal}</p></td></tr>'
    # Row 3: 核心风险
    xml += '<tr><td vertical-align="top"><p align="center"><b>核心风险&amp;上下游交互</b></p></td>'
    xml += f'<td vertical-align="top"><p>{scene_risk}</p></td>'
    xml += f'<td vertical-align="top"><p>{sil_risk}</p></td>'
    xml += f'<td vertical-align="top"><p>{hil_risk}</p></td>'
    xml += f'<td vertical-align="top"><p>{agent_risk}</p></td></tr>'
    xml += '</tbody></table>'
    return xml


def get_table_block_id_via_section(heading_block_id):
    """Get table block ID by reading the section starting from its heading."""
    result = subprocess.run(
        ["lark-cli", "docs", "+fetch",
         "--api-version", "v2",
         "--doc", DOC_TOKEN,
         "--scope", "section",
         "--start-block-id", heading_block_id,
         "--detail", "with-ids",
         "--format", "json"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    data = json.loads(result.stdout)
    content = data.get("data", {}).get("document", {}).get("content", "")
    match = re.search(r'<table id="([^"]+)"', content)
    if match:
        return match.group(1)
    return None


# Heading block IDs from the outline (verified earlier)
HEADING_IDS = {
    "W29": "JeW9dW3RDozpVoxD5okc8Rmbnaf",
    "W30": "ZCOedshrEoAcEhxkD8MciOdgnKg",
    "W31": "GzuhdihKhoTTRJx7w7scc02Nn9e",
    "W32": "doxcnkFQQQngKZFrtaTnozgLuQY",
    "W33": "doxcnGxKQwx784SNYHK0O6lbjFd",
    "W34": "doxcnQpjpoLTPHHzZH3rqKpZPNc",
    "W35": "doxcnDg91F2MeGgiYmeW8dmuadc",
    "W36": "doxcn7BTxt7kI4BeZyE7t6t0lng",
    "W37": "doxcnkquBqd0ZtWuAnCL2RPkqid",
    "W38": "doxcn5SOyn0Nygevfygm145BtdG",
    "W39": "doxcngMKkRpWHDujqJ3GbWoR72p",
    "W40": "doxcnpp1AJU481OYHKy9D6hbtWe",
}


def main():
    weeks = ["W29", "W30", "W31", "W32", "W33", "W34", "W35", "W36", "W37", "W38", "W39", "W40"]

    for week in weeks:
        print(f"\n{'='*40}")
        print(f"Refilling {week}...")

        heading_id = HEADING_IDS[week]

        # Get current table block ID via section fetch
        table_id = get_table_block_id_via_section(heading_id)
        if not table_id:
            print(f"  ERROR: Could not find table for {week}")
            continue

        print(f"  Table block: {table_id}")

        # Build replacement content
        xml = build_table_xml(week, WEEKS_DATA[week])

        # Replace
        result = subprocess.run(
            ["lark-cli", "docs", "+update",
             "--api-version", "v2",
             "--doc", DOC_TOKEN,
             "--command", "block_replace",
             "--block-id", table_id,
             "--content", xml],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"  REPLACE FAILED: {result.stderr[:300]}")
            sys.exit(1)

        print(f"  OK - {week} refilled")
        time.sleep(1)

    print(f"\n{'='*40}")
    print("All W29-W40 tables refilled successfully!")


if __name__ == "__main__":
    main()
