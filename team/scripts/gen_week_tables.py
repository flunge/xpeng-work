#!/usr/bin/env python3
"""重建 W28-W31 周表：表头改 4 优先级列，周目标按周拆解（月底稳达），每日行项目落到新列。
列 = [W## | ① 车型泛化 | ② 闭环+HIL | ③ 极速 | ④ Agent]
生成每周 table XML，供 block_replace。"""

# 项目→新列 owner 映射（周表内保留 @人名，这是内部作战表）
U = {
 "杨星昊":'<cite type="user" user-id="ou_b41c33085d2e629fbdff0c555cae0a3f" user-name="杨星昊"></cite>',
 "裴健宏":'<cite type="user" user-id="ou_a76e6fffce1c513ed5b33555aec19076" user-name="裴健宏"></cite>',
 "王禹丁":'<cite type="user" user-id="ou_16ed70882e5f4247b330612054b07d3f" user-name="王禹丁"></cite>',
 "韩阿东":'韩阿东',
 "周冯":'<cite type="user" user-id="ou_c37bf637460fbc4d1dd53470ecae8889" user-name="周冯"></cite>',
 "刘开拓":'<cite type="user" user-id="ou_5ff13a6d397bcb698bbfb66800fbb83a" user-name="刘开拓"></cite>',
 "郑丽娜":'<cite type="user" user-id="ou_279a0e5c146848e3d2dfaefe85f2c505" user-name="郑丽娜"></cite>',
 "朱啸峰":'<cite type="user" user-id="ou_09b6f76c8d98f186bb7163406fe3894a" user-name="朱啸峰"></cite>',
 "瞿鑫宇":'<cite type="user" user-id="ou_f360c7cfbd4fcbdc624c012dc151c6a4" user-name="瞿鑫宇"></cite>',
 "周蔚旭":'<cite type="user" user-id="ou_c9f3e88a0d6f949b332a40a155814e69" user-name="周蔚旭"></cite>',
 "吕文杰":'<cite type="user" user-id="ou_e6eb2da48b30725b46c548a1bcbf3fc6" user-name="吕文杰"></cite>',
 "严潇竹":'<cite type="user" user-id="ou_9b65b8c67807ce544a5cef3efe5cbf8a" user-name="严潇竹"></cite>',
 "樊世洲":'<cite type="user" user-id="ou_41c1fbbdee2aa8ced7cbe495a0e4b9c3" user-name="樊世洲"></cite>',
 "靳希睿":'<cite type="user" user-id="ou_6dbb165c2c7f4dd57532ffda75e51169" user-name="靳希睿"></cite>',
 "李祉浚":'李祉浚', "谷佳萱":'谷佳萱',
}
def u(n): return U.get(n,n)

COLS = ["① 车型泛化", "② 闭环仿真 + HIL", "③ 极速模式", "④ Agent 产品化"]

# 每周·每列的周目标（月底 W31 稳达 → 反推每周）
WEEKS = {
 "W28": {
   "range": "7/6-7/10",
   "goal": {
     0: f"[批量生产]首批重点车型（高优车型与业务确认）开环投产、NVFixer ref+mask 修复后启动大批量；[规律]CCES 评分矩阵首版、锁定车型敏感场景；[效率]运行时 25min→20min、NVFixer 带 ref 效率比 1:7.2 {u('杨星昊')}{u('王禹丁')}",
     1: f"630 链路交付业务试用、收集反馈；HIL 5 节点(004/005)调通、可用率冲 95%；RC 日产 1000 case、累计破 3500km {u('刘开拓')}{u('朱啸峰')}{u('郑丽娜')}",
     2: f"参数精简至 1 个上线、后端交付；向质量/海外开放试用、收首轮反馈 {u('周蔚旭')}",
     3: f"复现率 Agent 补齐至 10 类；Diff Agent 新增 3 类指标；代码审查扩仓库 {u('吕文杰')}{u('严潇竹')}",
   }},
 "W29": {
   "range": "7/13-7/17",
   "goal": {
     0: f"[批量生产]开环生产扩至 ≥15 款车型；[规律]场景×车型聚类方法在已有结论 case 验证生效（下周二核对后定稿）、扫参标定/车衣/车身遮挡三类；[效率]提速稳定达标、渲染共用步骤复用 {u('杨星昊')}{u('裴健宏')}",
     1: f"业务常态化使用（每个发版周期出 HIL gating 报告）；闭环 metric 七类验收启动；慢速 latent 链路适配完成 {u('朱啸峰')}{u('瞿鑫宇')}",
     2: f"自适应模式上线；入库复现率冲 50%；固化好用工具形态 {u('周蔚旭')}",
     3: f"Diff Agent 准确率冲 70%；复现率 Agent 全量集成进需求环节 {u('吕文杰')}",
   }},
 "W30": {
   "range": "7/20-7/24",
   "goal": {
     0: f"[批量生产]开环生产覆盖 ≥25 款；[规律]四大指标（安全/效率/加减速/居中）定量回归首版、AI 辅助归因；[效率]提速稳定达标、出基准 {u('杨星昊')}{u('王禹丁')}",
     1: f"RC 累计冲 4500km+、4 城铺开；HIL 可用率稳定 95%+、出带 PAT 阶段报告 {u('刘开拓')}{u('朱啸峰')}",
     2: f"产品化收尾：交付海外/质量稳定使用版本、复盘上手反馈 {u('周蔚旭')}",
     3: f"Diff Agent ≥8 类指标、准确率冲 80%；代码审查量化收益汇总 {u('吕文杰')}{u('严潇竹')}",
   }},
 "W31": {
   "range": "7/27-7/31",
   "goal": {
     0: f"🎯 月底交付：[批量生产]≥30 款车型覆盖；[规律]参数偏差↔CCES 定量关系结论 + ≥2 组车型敏感规律；[效率]生产效率 benchmark 出稿——形成稳定业务输出 {u('杨星昊')}",
     1: f"🎯 月底交付：630 链路业务常态化使用、可用率 95%+、RC 5000km/4 城、闭环 metric 七类验收报告 {u('刘开拓')}{u('朱啸峰')}",
     2: f"🎯 月底交付：极速模式成为海外/质量团队自助工具、入库复现率 50% {u('周蔚旭')}",
     3: f"🎯 月底交付：4 类 Agent 全部上线、准确率达标、量化收益结论 {u('吕文杰')}",
   }},
}

# 每列每周的项目清单（每日行统一用这个，日粒度进展留空待填）
PROJ = {
 0: [("车型泛化","杨星昊"),("Fixer 渲染提速","周冯"),("CLIP-IQA 质检","王禹丁"),("场景泛化","王禹丁")],
 1: [("RC 长里程","刘开拓"),("闭环场景集","刘开拓"),("HIL 链路","朱啸峰"),("慢速模式","瞿鑫宇"),("长里程看板","周蔚旭")],
 2: [("极速模式","周蔚旭"),("场景编辑","裴健宏")],
 3: [("复现率 Agent","吕文杰"),("Diff Agent","吕文杰"),("代码审查 Agent","杨星昊"),("Smart Agent","樊世洲"),("WM+GGS 预研","靳希睿")],
}

def cell(items):
    return "".join(f'<p>【{p}】{u(o)}</p>' for p,o in items)

def _hc(txt):  # 首行/首列居中粗体单元格
    return f'<td><p align="center"><b>{txt}</b></p></td>'

def build_table(wk):
    d=WEEKS[wk]
    # 表头：周标签简化为 W##（不带日期区间）；整行居中粗体
    th=f'<tr>{_hc(wk)}' + "".join(_hc(c) for c in COLS) + '</tr>'
    goal=f'<tr>{_hc("周目标")}' + "".join(f'<td>{d["goal"][i]}</td>' for i in range(4)) + '</tr>'
    risk=f'<tr>{_hc("核心风险 &amp; 上下游")}<td>算力/卡池对开环产能的约束</td><td>业务使用反馈闭环、CCES 结论对外确认</td><td>复现率上限受 feedforward 制约</td><td>与业务对齐验收口径</td></tr>'
    days=""
    dates={"W28":["7/6","7/7","7/8","7/9","7/10"],"W29":["7/13","7/14","7/15","7/16","7/17"],
           "W30":["7/20","7/21","7/22","7/23","7/24"],"W31":["7/27","7/28","7/29","7/30","7/31"]}
    names=["周一","周二","周三","周四","周五"]
    for k,(nm,dt) in enumerate(zip(names,dates[wk])):
        days+=f'<tr>{_hc(nm+" "+dt)}' + "".join(f'<td>{cell(PROJ[i])}</td>' for i in range(4)) + '</tr>'
    # 列宽：与 W27 原表一致——首列 100，4 优先级列各 500
    cg = '<colgroup><col width="100"/><col width="500"/><col width="500"/><col width="500"/><col width="500"/></colgroup>'
    return f'<table>{cg}<tbody>{th}{goal}{risk}{days}</tbody></table>'

if __name__=="__main__":
    import sys
    print(build_table(sys.argv[1]))
