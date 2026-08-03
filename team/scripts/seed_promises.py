#!/usr/bin/env python3
"""承诺追踪（P0 表）首批策展入库 —— 来源明确的承诺（含 deadline + 证据定位）"""
import json, subprocess

BASE = "NkIZb7eU7azZIEsegJ7cl2bfnUd"
TABLE = "承诺追踪"

# (承诺内容, 承诺人, Deadline, 状态, 备注, 证据来源, 相关项目)
ITEMS = [
    ("NVFixer encode 模块主流车型验证并合入主线", "fixer侧（W31 组会口径，未点名到个人）", "2026-08-01", "进行中", "7/28 周二组会本周计划", "纪要 RxbgdW1DioeJdNxaT1RckRbXn8e（7/28 周二组会）", "Fixer优化"),
    ("HIL 监控方案评审", "HIL侧（口径未点名）", "2026-08-01", "进行中", "7/28 周二组会本周计划", "纪要 RxbgdW1DioeJdNxaT1RckRbXn8e（7/28 周二组会）", "HIL链路部署"),
    ("慢速模式 CCES 时间戳适配，7/31 周五进度核查", "慢速模式负责侧", "2026-07-31", "进行中", "李坤点名的核查动作", "纪要 RxbgdW1DioeJdNxaT1RckRbXn8e（7/28 周二组会）", "慢速模式"),
    ("千问模型选型确认", "复现Agent侧（吕文杰/郑丽娜）", "2026-08-01", "进行中", "7/28 周二组会本周计划", "纪要 RxbgdW1DioeJdNxaT1RckRbXn8e（7/28 周二组会）", "复现率Agent"),
    ("慢速模式第二轮 AB 对比启动", "慢速模式负责侧", "2026-08-07", "进行中", "7/30 算法组周会「本周启动」", "纪要 Qrbddg6FSojpQqxk1Fac2NhfnFc（7/30 算法组周会）", "慢速模式"),
    ("慢速模式 500 公里规模压测 + 刘卓明团队最终验收", "刘卓明团队", "2026-08-08", "进行中", "7/31 核心日会「待刘卓明团队完成最终验收」", "纪要 VzlVdSBb2oJFBtxvodgcww2Unre（7/31 核心日会）", "慢速模式"),
    ("复现Agent本地部署落地 + 确定 Qwen3.5-9B；W31 周目标「Diff Agent 验收>8项+新增2项、Oncall 全产品化」", "吕文杰", "2026-08-01", "进行中", "W31 快照既定周目标；#3 完成的已验证", "复现率Agent ledger W31 快照", "复现率Agent"),
    ("实车答案/多车型适用场景技（12车型PAT 8/10 收口）", "车型泛化团队", "2026-08-10", "进行中", "W31 作战表既定", "Q3作战表 W31（cpnnd 双周会 7/31）", "车型泛化"),
    ("CCES 的一致性校验贯通 双视角（格一 AutoDriver Q3 收口）", "WM/AutoDriver 组", "2026-08-31", "进行中", "Q3 既定节点", "WM-内部探索 ledger + Cpnnd（7/31 双周会）", "WM-内部探索"),
    ("审计视图跨区域/跨站验证", "WM 侧", "2026-08-10", "进行中", "7/31 双周会口径", "WM-内部探索 ledger + Cpnnd（7/31 双周会）", "WM-内部探索"),
    ("LoRA+DF-RAG 更新回合", "WM 侧", "2026-08-15", "进行中", "Q3 既定迭代", "WM-内部探索 ledger + Cpnnd（7/31 双周会）", "WM-内部探索"),
    ("评估侧实测实计 + 均价/评价验收", "WM 侧", "2026-08-31", "进行中", "Q3 收口节点", "WM-内部探索 ledger + Cpnnd（7/31 双周会）", "WM-内部探索"),
    ("RC路线：xminer 元数据文件名规则 DT/正式上线验证", "RC路线侧", "2026-08-15", "进行中", "DT/上线验证节点待平台确认", "RC路线 ledger（W31）", "RC路线"),
    ("RC路线：175 条存量 backfill 产出最终有效率", "RC路线侧", "2026-08-08", "进行中", "7/31 已触发 backfill、终值未出", "Q3作战表 W31（RC fact）", "RC路线"),
    ("评估组 metric 复核（6/20 验收节点受 4 人离职影响）",
     "评估组", "2026-08-31", "进行中", "人员风险背景下 metric 复核仍待完成", "RC路线SIL验证 ledger（W31）", "RC路线SIL验证"),
    ("100 个 cut-in 场景交付（副目标：cut-out/follow/对向车库节点）", "裴健宏（场景编辑，受 F57 抽调影响）", "2026-08-31", "进行中", "抽调后需重新确认节点", "场景编辑 ledger（W31）", "场景编辑"),
    ("TopDiff-Agent: 单条 Diff review token 成本与年度总费用统计", "TopDiff-Agent 侧", "2026-08-15", "进行中", "老板（高炳涛）点名的成本可控性量化", "TopDiff-Agent ledger（7/15 核心日会）", "TopDiff-Agent"),
    ("闭环场景集：Jira 存量票重出包（50% 票实车版本太老）", "闭环场景集侧", "2026-08-31", "进行中", "自动化编译脚本开发中", "闭环场景集 ledger（W31）", "闭环场景集推进"),
    ("闭环场景集：主动安全 scenario 自动抽检可用性 pipeline 建立", "闭环场景集侧", "2026-08-31", "进行中", "scenario 数据被删后需建立自动抽检", "闭环场景集 ledger（W31）", "闭环场景集推进"),
]

def cli(*a):
    r = subprocess.run(["lark-cli","--profile","xpeng"]+list(a)+["--as","user"],
                       capture_output=True,text=True,timeout=300)
    try: return json.loads(r.stdout)
    except Exception: return {"ok": False, "raw": (r.stdout or r.stderr)[:300]}

rows = [[c,p,dl,st,remark,ev,proj] for c,p,dl,st,remark,ev,proj in ITEMS]
payload = {"fields":["承诺内容","承诺人","Deadline","状态","备注","证据来源","相关项目"],"rows":rows}
resp = cli("base","+record-batch-create","--base-token",BASE,"--table-id",TABLE,
           "--json",json.dumps(payload,ensure_ascii=False))
out = resp.get("data") or {}
print("ok:",resp.get("ok"),"created:",len((out.get("records") or out.get("record_id_list") or [])))
