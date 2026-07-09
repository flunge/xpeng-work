#!/usr/bin/env python3
"""Update W27 风险行的 SIL/HIL/Agents 三格（场景&生产 已有内容不动）。
基于 6/29 核心日会 + 各项目 ledger 最新数据。
"""

import subprocess

DOC_TOKEN = "SBUYwm8Lri9aJ6kmexFcBAuGnlh"

# Empty <p> block IDs in 核心风险 row (from fetched content)
SIL_RISK_BLOCK = "doxcndi7wAE0uh4Pbtbgmhrr7Ve"
HIL_RISK_BLOCK = "doxcnyNn1SDSqUx3nxfI7j6mm0b"
AGENT_RISK_BLOCK = "doxcn8TNwRT0GEGz7GkvCCUAs3d"

# Content for each risk cell
SIL_CONTENT = '''<p><b>【SIL】</b></p><ul><li>【Fixer渲染优化】UCP subrun 大量任务排队 pending，nvfixer ref 新链路验证延后</li><li>【车型泛化】Moe 模型自测正常但全链路联调未完成，发版时间未敲定</li><li>【CLIP-IQA】平台 Cloudsim 联调排期未对齐，阻塞 SIL 链路集成</li><li>【RC路线SIL验证】DSOP 闭环 metric 因 RTM topic 格式变更读不到，10 metric 起跑阻塞，依赖夏志勋根因修复</li></ul>'''

HIL_CONTENT = '''<p><b>【HIL】</b></p><ul><li>【HIL链路】XOS630 在 HIL 3DGS 链路兼容性待验证；SF VRU 缺失（mflocalpose 字段）需 SF 同学配合实现</li><li>【慢速模式】xos/perception_xp5/simulation 实车 DT 合入主线编包部署中，rebase 后回归测试尚未完成</li><li>【慢速模式】NVFixer Ref latent 链路适配中（生产侧未完成）；连续 case 尾部掉帧根因待定</li><li>【交付】交付组明日（6/30）开始试用评测准确度，评测结果查看易用性问题较多</li></ul>'''

AGENT_CONTENT = '''<p><b>【Agents&预研】</b></p><ul><li>【Diff Agent】主辅路/分合流未跟导航 50+case 一致率仅 70%，距上线门槛差距大；进逆向车道旧数据过期需重新准备</li><li>【复现率Agent】异常减速/不减速优化基于试用反馈更新，量化收益未对齐（高炳涛 6/22 双周会要求）</li><li>【OnCall Agent】演化路径长（错误诊断→报告→对比→问答），各阶段时间点未拆解</li><li>【代码治理】高炳涛 6/22 要求下周一前提交整改计划，安全/核心链路问题分配未明确</li></ul>'''


def replace_block(block_id, content):
    result = subprocess.run(
        ["lark-cli", "docs", "+update",
         "--api-version", "v2",
         "--doc", DOC_TOKEN,
         "--command", "block_replace",
         "--block-id", block_id,
         "--content", content],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"FAILED {block_id}: {result.stderr[:300]}")
        return False
    print(f"OK {block_id}")
    return True


def main():
    print("Updating W27 核心风险 row...")
    replace_block(SIL_RISK_BLOCK, SIL_CONTENT)
    replace_block(HIL_RISK_BLOCK, HIL_CONTENT)
    replace_block(AGENT_RISK_BLOCK, AGENT_CONTENT)
    print("Done.")


if __name__ == "__main__":
    main()
