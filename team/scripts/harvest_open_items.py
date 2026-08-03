#!/usr/bin/env python3
"""开口项追踪 · 策展入库清单

表层：Base NkIZb7eU7azZIEsegJ7cl2bfnUd / tblZ7Mp5mLhY2Cnw（「开口项追踪」）

注意：
- ITEMS 是人工策展后的开口项事实清单（每条带 项目/事项/开口日期/开口来源/状态/证据）。
- 入库统一走 `base +record-batch-create --json {fields,rows}`；**不允许重复运行**——旧脚本曾用
  record-create 探针成功但静默，导致 33 条重复入库（已用 record-delete 清理）。
- 新开口项只追加在 ITEMS 末尾并先核对表内是否已有同 事项 记录；如需重建整表，先 record-list 留档。

后续钩子：
- risk_sentinel.py 可加入「开口项追踪」为数据源：每天核查 suspected-close 的最近证据。
- memory_query.py 证据包将本表作为 risk 主源之一。"""
import json, subprocess, time, sys

TABLE = "开口项追踪"
BASE = "NkIZb7eU7azZIEsegJ7cl2bfnUd"

ITEMS = [
    # 项目, 事项, 开口日期, 开口来源, 状态, 关闭来源, 证据原文(截断)
    ("慢速模式", "最终验收：500km 规模压测结果 + 刘卓明团队验收结论", "2026-07-31",
     "纪要 VzlVdSBb2oJFBtxvodgcww2Unre（7/31 核心日会）", "open", "",
     "已启动 500 公里规模压测，待刘卓明团队完成最终验收。原「暂缓·等实车答辩」(7/16 判定) 自 7/21 起实际已恢复推进、8/3 已修正为交付验收中。"),
    ("慢速模式", "原 PENDING（暂缓·等实车答辩）判定与实际推进脱节", "2026-07-16",
     "仿真核心日会 7/16 + 慢速模式 ledger 旧状态", "suspected-close", "",
     "移植自 W30 DONE：simworld/simulation/VIL 三仓合主线 + 车端代码（MR!757）合主线；7/21 已恢复验证、7/22 交付业务方测试。"),
    ("HIL链路部署", "看门狗异步化完成 + 远程桌面遗留问题", "2026-06-12",
     "6/12 组内周会逐字稿", "open", "", "8 月起禁试验性迭代须直出量产级结果（7/24 核心日会）。"),
    ("CLIP-IQA", "HIL 链路接入 + 常规模式精调", "2026-07-16",
     "CLIP-IQA ledger 状态", "open", "", "W28 生产原图 clipiqa job 已提交待验证。"),
    ("CLIP-IQA", "1000km 长里程 clip-iqa 过滤效果有限，阈值迭代", "2026-06",
     "Q2 Wiki W10", "open", "", ""),
    ("CLIP-IQA", "W28 生产原图 clipiqa job 验证结果", "2026-07-25",
     "Q3作战表 W28", "suspected-close", "", "若 job 已出结果即可关闭。"),
    ("Fixer优化", "训练集群卡资源缺口（仅并行 2 实验 / FF Difix 需 A100×32×7天）", "2026-06",
     "Fixer优化 ledger", "open", "", "资源型风险，卡池到位进度由李坤协调。"),
    ("Fixer优化", "ref 图 OOD（cross-attention 尖锐）根本解决", "2026-07", "Fixer优化 ledger", "open", "", ""),
    ("Fixer优化", "TRT engine onnx/trt 转换方案复杂、自动化/上手成本高，需重构", "2026-07",
     "Fixer优化 ledger", "open", "", "nvfixer 已上线但 TRT 转换流程仍复杂，是否被替代需确认。"),
    ("极速模式", "diff 训练数据缺（仅 120+ 视频）、无 A100 无法大批量重训", "2026-07",
     "极速模式 ledger", "open", "", "W31 已跑 DVGT-2 24卡 A100（跨国段 175 events），但重训验证未闭环。"),
    ("极速模式", "渲染效果待 DFIX 接入优化（与真值明显差异）", "2026-07", "极速模式 ledger", "open", "", ""),
    ("场景编辑", "3DGS 坐标系偏移 / 编辑车 yaw-roll 几何误差", "2026-06",
     "场景编辑 ledger", "suspected-close", "",
     "W31 作战表：已对齐 sf 与 3dgs 坐标系、资产库 ply 高斯自体歪斜根因已查明并处理手机坐标系。待确认效果。"),
    ("场景编辑", "单次 UCP 编辑约 4 分钟，瓶颈在模型和 DDS 传下载", "2026-06", "场景编辑 ledger", "open", "", ""),
    ("场景编辑", "100 个 cut-in 场景/后续 cut-out、follow、对向车库交付节点（裴健宏被抽调影响）", "2026-07-22",
     "场景编辑 ledger", "open", "", "受 F57 撞 RB 量产 block 抽调影响，需重新确认节点。"),
    ("AVM鱼眼", "cam9 需求方确认 + 是否追加训练阶段（缺仿射矩阵）", "2026-06-13",
     "AVM鱼眼 ledger", "open", "", "李坤已判定非 blocking、先交付第一阶段（不带训练）；需求来源待确认。"),
    ("闭环场景集", "Jira 存量票约 50% 实车版本太老跑不了复现、需重新出包", "2026-07-16",
     "闭环场景集 ledger", "open", "", "自动化编译脚本开发中。"),
    ("闭环场景集", "robotaxi 试运营回传 case 可用比例低（回传慢/缺失/重复）", "2026-07", "闭环场景集 ledger", "open", "", ""),
    ("闭环场景集", "主动安全 scenario 数据被删除，需自动抽检可用性 pipeline", "2026-07", "闭环场景集 ledger", "open", "", ""),
    ("闭环场景集", "全链路留存率偏低（W7 48.9%，开环 44-56%）", "2026-06", "闭环场景集 ledger", "open", "", ""),
    ("闭环场景集", "O3 生产链路技术 Owner 缺位（杜思聪 6/5 离职）", "2026-06-05", "闭环场景集+WM ledger", "open", "", "是否已有新 owner 待确认。"),
    ("RC路线", "数据有效率/留存率未闭环（175 条存量已修复+backfill 待产出）", "2026-07-31",
     "Q3作战表 W31", "open", "", "backfill 终值尚未产出。"),
    ("RC路线", "xminer 元数据文件名规则 DT/正式上线验证", "2026-07", "RC路线 ledger", "open", "", ""),
    ("RC路线", "RTM Road 加载偏慢 + 导航类 metric 时间戳仍待平台侧确认", "2026-07", "RC路线 ledger", "open", "", ""),
    ("Prompt-Agent", "仿真车/实车分离因果颠倒误报根因排期", "2026-06", "Prompt-Agent ledger", "open", "", ""),
    ("TopDiff-Agent", "路口误判/单帧前后差异导致聚合函数误报", "2026-06", "TopDiff-Agent ledger", "open", "", ""),
    ("TopDiff-Agent", "旁车感知缺失，绕行场景拟增加旁车辅助判断", "2026-06", "TopDiff-Agent ledger", "open", "", ""),
    ("TopDiff-Agent", "单条 Diff review token 消耗与年度总费用成本统计", "2026-07-15", "核心日会 7/15", "open", "", ""),
    ("复现率Agent", "方向策略汇报/Agent 体系 v2.2 落地闭环（6/12 高炳涛点名）", "2026-06-12",
     "复现率Agent ledger + 算法组周会 6/12", "suspected-close", "", "W29–W31 已出 Agent 体系 v2.2 OKR、本地部署选型，方向策略已落，待李坤确认。"),
    ("复现率Agent", "因果颠倒误报 待杨雪智排期", "2026-06", "复现率Agent ledger", "open", "", ""),
    ("车型泛化", "F57 KPI 冲突（与生产侧 老李/高远）未解除", "2026-07", "车型泛化 ledger", "open", "", ""),
    ("车型泛化", "异车型生产准入口径尚未统一", "2026-07", "车型泛化 ledger", "open", "", ""),
    ("WM-内部探索", "LoRA+DeepSeek 方案更多实验", "2026-07", "WM-内部探索 ledger", "open", "", ""),
    ("WM-内部探索", "CUDA OOM 与结果差异根因待定位（7/30 WM 进展同步会）", "2026-07-30",
     "EZ5bdFrYaoXH9Mx3tXdcDKfDn1b / 内部索引 W31", "open", "", ""),
]

def cli(*a):
    r = subprocess.run(["lark-cli","--profile","xpeng"]+list(a)+["--as","user"],
                       capture_output=True,text=True,timeout=120)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"ok": False, "raw": r.stdout[:300]}

def main():
    ok, fail = 0, 0
    for proj, item, od, osrc, status, csrc, ev in ITEMS:
        fields = {
            "事项": item, "项目": proj, "开口日期": od, "开口来源": osrc,
            "状态": status, "关闭来源": csrc,
            "最近核查日期": int(time.time()*1000), "证据原文": ev,
        }
        r = cli("base","+record-create","--base-token",BASE,"--table",TABLE,
                "--fields",json.dumps(fields,ensure_ascii=False))
        if r.get("ok"): ok += 1
        else:
            fail += 1
            print("FAIL", proj, item[:40], str(r.get('error',{}).get('message',''))[:120])
    print(f"done ok={ok} fail={fail}")

if __name__ == "__main__":
    main()
