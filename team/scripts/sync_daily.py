#!/usr/bin/env python3
"""把作战表W27-W28各项目日报进展同步进各飞书项目ledger。一次性回填全部,含限速+重试。"""
import json,subprocess,time,os
BASE="/workspace/team"
m=json.load(open(f"{BASE}/memory/_feishu_map.json"))
def tok(kw):
    for rel,info in m["projects"].items():
        if kw in info.get("project","") or kw in rel: return info["token"]
    return None

HDR="\n\n---\n\n## 📅 日报进展同步（W27-W28，2026-07-07 从作战表回填）\n\n> 来源:Q3作战表 SBUYwm8L 逐日进展。补齐6月底-7月初日报。\n\n"

# 项目 → (ledger关键词, 日报进展markdown)
DATA={
"车型泛化":("车型泛化","""- **6/29**：已根据业务需求泛化好场景,正在编包、仿真。
- **6/30**：完成需求,发现是 side front left 导致车速慢,反馈车端同学。
- **7/1**：验证 nvfixer 在车型泛化上可视化效果、打通链路;重新设计生产链路可不从 cloudsim 提任务,要了公共池高优权限便于敏捷开发。
- **7/2**：和业务对齐新一版车型泛化方案;ucp 车型泛化兼容手动提交开发中(cloudsim 不支持外部发起,需 simworld 内部处理非 cloudsim 任务)。
- **7/3**：脚本从数据库筛出 1238 个场景周末生产;修复几个批量生产 bug;怀疑内存泄漏。
- **7/6**：排查 custom 模式周末生产问题已解决;支持同时生产多车型、开发完成测试中。
- **风险**：Moe 模型自测正常但全链路联调未完成、发版时间未定;批量生产疑内存泄漏。"""),
"车型泛化生产效率占位":(None,""),
"RC路线":("RC路线","""- **6/29**：日产100km暂无风险,截止昨日累计478km新数据;Event数据回传丢失本周三拉TC讨论。
- **6/30**：高优场景集任务插入致长里程排队被抢占,截止561.5km,明天新老混合先给1000km供仿真;看板计划7/13上线。
- **7/1**：截止606.1km,已给subrunid各链路,剩余历史数据补全;数闭部切新链路需等7/17 lance切换后评估。
- **7/2**：新数据仅遗留10个subrun,和云荟安排广州外所有RC路线重生成(200 subrun);TC反馈RC路线精简、最终只保留3000km+;看板完成pose生成kml工具。
- **7/3**：看板scenario补偿pose工具接口变动、需改代码,预计周一测完。
- **7/6**：截止811km;制定长里程更多评测Metric交付计划;看板链路平台组重评工作量、可能延期。
- **7/7**：截止897km。
- **风险**：数闭部Backfill补偿未成功;TC暂停RC采集、本周五左右新采集数据耗尽;看板可能延期。"""),
"HIL链路部署":("HIL链路部署","""- **6/29**：004/005正式接入;XOS630可正常运行HIL 3DGS链路;SF运行异常(VRU缺失)系mflocalpose字段缺失。
- **6/30**：HIL 3DGS交付验证同学、运行正常;630软件仿真跑不起来、定位到刷包代码bug致模型版本与大小包不匹配、修复中。
- **7/2**：持续支持卓明试用;解决图像时间轴不对齐;630跑失败根因是测试板问题、005换板。
- **7/3**：本周block问题修复,卓明端到端试用迭代中;修复630 B板断连万兆网;渲染图像时间戳对齐、剔除DDS多录空包。
- **7/6**：RTM缺失约30%降级为非block持续调查;005重新接入、630功能跑通;PC topic走万兆网解决掉帧开发中。
- **7/7**：交付反馈算法测链路问题已收敛、整体正常可进行metric评测有效性验证;修复FM偶发异常、可用率+2%;验收标准已和爽初步对齐(需和实车对比+长里程数据质量抽检+Metric准确率,Diff Agent同步切入)。
- **风险**：XOS630兼容性待验证;SF VRU缺失需SF同学配合。"""),
"慢速模式":("慢速模式","""- **6/29**：实车DT合入主线与owner沟通review;改动rebase到dev_xnpg_xp5、编译本地xpu部署验证;Nvfixer Ref待周冯latent链路跑通后测。
- **6/30**：改动跑case发现FM无输出(与主线版本差异大),卡点CI编包部署耗时长;630大包部署致万兆网断联(已修复);perception新增分支致too old拒帧、调试中。
- **7/1**：核心block定位——perception消费多路相机时间错峰,取巧修复=慢速时提高拒帧阈值,无nvfix时FM/Chief正常;接入nvfix仍无输出、主线代码有缺陷调查中。
- **7/2**：630主线旧代码已覆盖但仍有问题;Nvfix+ref报告(老版本):效率满足1:5内、绝大多数1:4.5、极限1:4.86,峰值显存15837/16303。
- **7/3**：nvfix测试报告;慢速代码合入630主线(进行中)。
- **7/7**：代码合630主线;Too old拒帧问题修复(根因xpu两板启动时间微小差异触发underflow);与xos/perception组代码review修复Done,还需补台架仿真性能报告+实车DT。
- **风险**：rebase后回归测试未完成;NVFixer Ref latent链路生产侧未完成、连续case尾部掉帧根因待定。"""),
"极速模式":("极速模式","""- **6/29**：使用便利性后端本周四交付;自己部分卡在其他组主开发分支代码异常、无法跑完一次验证。
- **6/30**：仿真设置参数降到1个已测完准备提mr;自适应无需特殊设置正调研各方。
- **7/1**：自适应理清上下游调度逻辑、无需后端/平台介入、代码完成测试中。
- **7/2**：后端已改好推迟明天发版;自适应跑完一个任务初看没问题。
- **7/3**：后端发版携带;自适应自测通过;端到端耗时2.5-3小时(抛开等GPU),训练1.5-2h、仿真45min(极速与普通无区别)。"""),
"复现率Agent":("复现率Agent","""- **6/29**：异常减速/不减速据试用反馈优化;成本分析中。
- **6/30**：分合流/路口不跟导航/未及时变道本周提供数据;Stage1有保存时效问题、沿用Stage2。
- **7/2**：主辅路/分合流未跟导航基于Diff Agent反哺、明天给30case准确率。
- **7/3**：主辅路/分合流初版完成,105真值case准确率83.5%、F1 76.3%,Recall偏低需提升;日志统一管理同步飞书机器人。
- **7/6**：分合流不跟导航准确率提至85%(88/103)、已上线待生产验收;路口不跟导航初版完成。
- **7/7**：路口不跟导航验证集调优、总准确率15/17=88.2%;100+生产case准备本周核验。
- **风险**：异常减速优化量化收益未对齐。"""),
"TopDiff-Agent":("TopDiff","""(Diff Agent 进展)
- **6/29**：主辅路/分合流50+case一致率70%改进中;路口内数据准备;变道找不到空挡初步开发;进逆向车道数据准备。
- **6/30**：主辅路/分合流最优版一致率78%(28/36)、空间相对位置判定有缺陷;路口内20case训练集65%;变道找不到空挡收尾。
- **7/1**：主辅路/分合流高置信度case准确率90%;路口内训练集80%+;变道找不到空挡10测试集90%。
- **7/2**：路口内训练集85%/测试集高置信80%+(30case);变道找不到空挡迁大规模测试集、非similar案例1/3。
- **7/6**：变道找不到空挡优化提示词与链路结构。
- **7/7**：变道找不到空挡开发基本完成、验证集>80%;不居中两版本数据准备。
- **风险**：主辅路/分合流一致率仅70%距上线有差距;进逆向车道旧数据过期。"""),
"Prompt-Agent":("Prompt","""(OnCall Agent 进展)
- **6/29**：考虑agent演化(错误诊断→测试报告→多版本对比→语义问答);本周打通robot日志传统方式错误诊断。
- **6/30**：日志改造与上游对齐、确认修改方案。
- **7/1**：日志改造从标准格式到上传oss流程已通、处理不规范日志。
- **7/2**：日志改造基本完成跑完一case、今晚进mr;传统方式错误分析大部分代码完成待串;将提供看板。
- **7/3**：日志改造运行时耗时翻2倍正确认;agent"日志获取→分析结果"流程完成。
- **7/6**：耗时确认是平台logger打印耗时,改法1用自己logger/改法2升级镜像(验证中);agent全流程代码完成debug中。
- **7/7**：耗时问题用平台最新镜像可解决;agent流程已通、传统查询打通、未知错误人工辅助判断调试中。
- **风险**：演化路径长、各阶段时间点未拆解。"""),
"CLIP-IQA":("CLIP-IQA","""- **6/29**：HIL侧原图生产阶段评分json代码完成待测;SIL侧链路联调完毕、本周优化clipiqa阈值。
- **7/2**：生产阶段原图评分代码完成(ucp测试复杂待下周平台上线再测);汇总耗时已修复、阈值调优可过滤更多差case、今日合入。
- **7/3**：SIL链路汇总耗时从1:112.3优化到1:79.9、今日合入。
- **7/7**：生产原图clipiqa代码ready、今日提交生产job待验证。
- **风险**：平台Cloudsim联调排期未对齐、阻塞SIL集成。"""),
"Fixer优化":("Fixer","""- **6/29**：HIL nvfixer ref新链路生产测+应用测代码完成,已提ucp subrun生产(排队pending);应用测适配ceph自动下载解压latent按cam/timestamp每帧复用。
- **6/30**：UCP ref latent ppu生产测预处理打通、ref latent正常输出上传oss;解决dpvo不可重复生产bug、优化ppu链路trt加载、修复Nvfixer ppu镜像;ref latent oss→ceph拷贝需平台支持。
- **7/1**：difix动态适配高版本diffuser、生产链路全打通;HIL XPU应用测打通、nvfixer ref trt比原始3dgs质量高;但自车启动画面抖动、慢速+nvfixer无fm输出致轨迹不一致(xinyu修复中)。
- **7/2**：UCP ref latent ppu生产测合入主分支;HIL XPU应用测生产一测试subrun交xinyu批量时延测;车型泛化需求把nvfixer pytorch/trt适配新车型渲染策略、代码完成编包测。
- **7/3**：车型泛化需求代码done、原位FM评测和difix mask策略效果差不多;HIL XPU应用测重跑批量耗时评估、nvfixer ref trt效果仍有问题。
- **7/6**：Nvfixer生产链路subrun config更新;carmask新车型泛化渲染策略增开关待合dev主分支。
- **风险**：UCP subrun排队pending致新链路验证延后;HIL nvfixer ref trt效果仍有问题。"""),
"RC路线SIL验证":("RC路线SIL","""- **7/2**：新数据和仿真同学对齐后跑SIL验证,旧数据待xiaofeng更新后跑仿真。
- **7/3**：新老数据均跑完、报错较多(一部分3dgs oom、一部分simulation仓库报错、需和zhenyu看编包)。
- **风险**：DSOP闭环metric因RTM topic格式变更读不到、10 metric起跑阻塞、依赖夏志勋修复。"""),
"闭环场景集推进":("闭环场景集","""- **7/6**：城区闭环六类Metric均Ready,场景数据集详单——不加速/加速慢跑不到限速179、摆动/蛇形道内画龙70、变道找不到空档17、不发起/过晚导航变道105、主辅路/分合流未跟导航120、路口通行未跟导航57。"""),
"场景泛化":("场景泛化","""- **6/30**：基于WeatherEdit(AAAI2026)pipeline跑通二维图像天气编辑,得rainy/snowy/foggy三种风格样例(部分过度风格化);已整理数据格式适配、批量跑;泛化视频相邻帧天气连续无跳变、多相机视角匹配好;下一步接入3DGS。
- **7/1**：相邻帧连续稳定、多视角匹配好、数据待接入训练。
- **7/2**：泛化图片接入3dgs训练、随步数增加接近雪天、待训练结束检查场效果。
- **W28目标**：IntrinsicWeather本地部署、打通天气编辑并与WeatherEdit对比。"""),
"WM-内部探索":("WM-内部探索","""- **W27**：算法预研列列出@靳希睿、无逐日进展文字。
- **W28目标**：成对3DGS渲染+真实视频训练Wan2.2并测效果(承接杜思聪feedforward线,@赵浩南)。"""),
}

def append(kw,body):
    t=tok(kw)
    if not t: return f"❌ 找不到ledger:{kw}"
    md=HDR+body
    path=f"{BASE}/.sync_tmp.md"
    open(path,"w",encoding="utf-8").write(md)
    for attempt in range(3):
        r=subprocess.run(["lark-cli","docs","+update","--api-version","v2","--doc",t,"--command","append","--doc-format","markdown","--content","@.sync_tmp.md","--format","json"],capture_output=True,text=True,timeout=60,cwd=BASE)
        try: d=json.loads(r.stdout[r.stdout.find("{"):])
        except: return f"❌ {kw} 解析失败"
        if d.get("ok"): return f"✅ {kw}"
        err=d.get("error",{})
        if err.get("subtype")=="rate_limit" or err.get("code")==99991400:
            time.sleep(5*(attempt+1)); continue
        return f"❌ {kw}: {str(err)[:80]}"
    return f"❌ {kw} 重试耗尽"

done=set()
rp=f"{BASE}/.sync_done.txt"
if os.path.exists(rp): done=set(open(rp).read().split("\n"))
import sys
only=sys.argv[1:] if len(sys.argv)>1 else list(DATA.keys())
resf=open(rp,"a")
for proj in only:
    if proj in done or proj not in DATA: continue
    kw,body=DATA[proj]
    if not kw: continue
    print(append(kw,body)); resf.write(proj+"\n"); resf.flush()
    time.sleep(2.5)
os.remove(f"{BASE}/.sync_tmp.md") if os.path.exists(f"{BASE}/.sync_tmp.md") else None
