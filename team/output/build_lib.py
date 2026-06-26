#!/usr/bin/env python3
# 重建 C7qUd 文档库表格。数据即真相：改这里 → 跑一次即可。
import subprocess,json,re
DOC="C7qUdeACso0SSpxVCdgct6winDg"
UID={'刘开拓':'ou_5ff13a6d397bcb698bbfb66800fbb83a','周蔚旭':'ou_c9f3e88a0d6f949b332a40a155814e69','裴健宏':'ou_a76e6fffce1c513ed5b33555aec19076','王禹丁':'ou_16ed70882e5f4247b330612054b07d3f','杨星昊':'ou_b41c33085d2e629fbdff0c555cae0a3f','靳希睿':'ou_6dbb165c2c7f4dd57532ffda75e51169','李坤':'ou_f9cd23092a356c297d6a9f38fd7cfd5e','郑丽娜':'ou_279a0e5c146848e3d2dfaefe85f2c505','吕文杰':'ou_e6eb2da48b30725b46c548a1bcbf3fc6','朱啸峰':'ou_09b6f76c8d98f186bb7163406fe3894a','周冯':'ou_c37bf637460fbc4d1dd53470ecae8889','瞿鑫宇':'ou_f360c7cfbd4fcbdc624c012dc151c6a4'}
def U(n): return ''.join(f'<cite type="user" user-id="{UID[x]}" user-name="{x}"></cite>' if x in UID else f'（@{x}）' for x in n.split('/'))
def C(t,k): return f'<cite doc-id="{k}" file-type="wiki" title="{t}" type="doc"></cite>'
def li(e,n,o,lst): return f'<li>{e} <b>【{n}】</b>'+''.join(C(t,k) for t,k in lst)+U(o)+'</li>'
ROWS={
'场景&生产':[
 ('🔵','RC 路线（长里程生产）','李坤/刘开拓',[('长里程生产任务文档','BMNPwB5C6iMCTPkTCTVcFjwungd'),('长里程生产流程梳理','YGgUwd80RiAE51komJBcAy6AnRh'),('生产自动化链路方案','QKMswhFOziKLalk6J5Jc9NcVndg'),('产线指标状态同步','TMV3wdj6PiV7WKk8pkLcdX4Zndg'),('UCP 3dgs 任务参数说明','B99cwamIjiVpoMkSYncctsWNnye'),('3dgs 生产信息统计增字段','YZMFwWFomiuDqVkB01XcHOtznCe')]),
 ('🔵','极速模式','周蔚旭',[('极速模式交付文档','X6a2wQUVpimODBkVidxcnHOvnuc'),('极速验证合入主线测试报告','VVCNwnV4wixsDvkl9oYcXIGQnNd'),('市场问题极速/普通对比0602','Kn8OwqlNVirJI6k89Zhc3HL7nKe'),('高优 case 极速验证方案','WAS8wadJcidpHFkJkJIcoPiknyf'),('预处理链路优化调研','C6l2w9YbbiI4XXk72yUcakxDnfh')]),
 ('🔵','闭环场景集推进','刘开拓',[('城区专项集','LC0ewNV0Zi41vjkAy9McCTbnnEd'),('FM 闭环情况汇总','WX5twqI8nipfV2khQsxc0unLn2d'),('闭环目标对齐(4/22)','StdMdVqlIoyLpIxfQqxc9ZBRncc'),('闭环 Gating 综合统计','JRmhwSrQTiWMrmkvGBXcGJckn5d'),('闭环 Metric 测评','CsCfw229bixjB8kqeLRc8spWnwf'),('场景语义差异闭环诊断','RL24wW2UGiptOvkPmPMcw7OMn8g'),('减速缓/不减速判责标准','OtHewiTAviWAnCk3pgPcfgODnNb')]),
 ('🔵','场景编辑（CornerCase 生产）','裴健宏',[('资产库&场景编辑方案文档','ELjkwAsaaiNiKxk3JmscMWKfnLc'),('场景编辑','EeemwpVwdiJ1l0kEs9bc3ryZnUe'),('场景编辑方案概要设计','LK8Qwjcx0ia1dakCPiqcMYsAnwg'),('和谐化调研与方案评审','X4vowZo4Bio9UkkdsbVcwksanOc'),('和谐化方案整理','Nn2IwAnAUieNpikqMTDc9YLBnbc'),('和谐化方案测试对比','ZuMewdK7Cizl0Zkk2ErcULfgnZc'),('生成式 AI 在仿真的使用','FswZwhfUhiLORjk6s6qcYdHznDb')]),
 ('✅','产线看板 + 3DGS 生产指标体系','李坤',[('产线指标状态同步','TMV3wdj6PiV7WKk8pkLcdX4Zndg'),('3dgs 生产信息统计增字段','YZMFwWFomiuDqVkB01XcHOtznCe')]),
 ('🔵','生产质检 / gating','裴健宏',[('场景重建质检概要设计','LK8Qwjcx0ia1dakCPiqcMYsAnwg')]),
],
'SIL':[
 ('🔵','车型泛化','杨星昊/裴健宏',[('仿真车型泛化验证报告','E7klwTcSEieyYNkNdXJcFsZHnr7'),('开闭环车型验证方案','G6I4w06nPiJ1g3kVlJ7cgnZinPg'),('趋势对比图','YB7Psoz2Vh0ulhtkKnEcj0VOnid'),('difix ref 图模式优化','V7VMwJ6ZHi9jgJk9hSNck2TFn9U'),('同场景对比-跑不到限速','CbjLwRb30ijRfWk6TmOcrXgunsg'),('CloudSim 多车型转换需求','NA9IwSUG1iy8V3kTdYrcj1L1neb'),('斑马车衣(斑马→正常)','CahawlqWtiRJxUk6Kqfcnqwynoe'),('斑马车衣(正常→斑马)','HeppwUrk7iscoRkDdFGcBdAUnid'),('闭环换车型数据集','AfHawLfYvi3ZNOk2tnzcE47sn1d'),('13 车型泛化','PvOmwcBePigPKtkQhv0cttDanAh'),('车型泛化(范裴沛)','AbWqwE7l3i8wGqkdCSoc6eMdnUh'),('车型泛化应用-实验汇总','NNHAwfr8Vi0t3RkGxGacCvmrnDb')]),
 ('🔵','RC 路线 SIL 验证','李坤',[('广州 RC 路线 SIL 仿真结果','NxBmwuHcqieJXzkmLFzcQ8bMnFe'),('200km 长里程对比报告0522','XS5CwPfhNiFbIDkhqVAcAgWAnyh'),('200km 长里程对比报告','N864wtDjFi9UZukOlnycPASEn8c'),('批量一致性分析总览','IoWpwxKVWivyNLk7ay7c6DEgnyh')]),
 ('✅','CLIP-IQA 图像质检','王禹丁',[('CLIP-IQA 实验文档','HUSiwSNqkixNIzkZO9vcE4q8nph'),('clip-iqa 用法说明','XYd0wkz19iZgHTk6XUKcqyaPnpE')]),
 ('🔵','Fixer 优化 / 渲染','周冯/李坤',[('NVFixer 技术分析文档','PlROdzLHNoTVQnxDffVcRoSZnNe'),('SIL&HIL fixer 性能优化实验','STxrwJBKGi1QPOk1OXrcENZInG6'),('HIL fixer 性能优化','A8aowUZtRifVwkkYN9QcgNgZnRh'),('动态物体问题整理&优化','GqKCwqNy3iYblXkQabucZxUQn8b')]),
],
'HIL':[
 ('🔵','HIL 链路部署','朱啸峰',[('HIL 台架仿真方案及记录','NxAhwFyVViaPumkbcusc7VGknRf'),('HIL_PC 台架仿真方案','WSB2w5RusiK3V1kVQvmcJeQ3nnd'),('3DGS_HIL 台架内部培训','Jplzw5aDvi1uY3kYs9Xca3B9nds'),('全链路集成计划','KGAWwhB9ziDQYokR2dFcvMgKnvd'),('XTest 接入大规模闭环待办','RkHIwGL5NirXvVkdbRmcAnyunKf'),('XTest 任务交接及分工','C1YYwH8zziQifgkk9sxcB2Din1e'),('链路计划及进展汇总','ACCFwgyckivIrjkUuiZcHv2ynBe'),('验证报告 Ver0','FkvGwhhALiQMK5k7zrCcJbQenMe'),('阶段性验收报告','QlSrw3e4Ciuc6vkgZgdcNuHZnOb'),('xtest 联调文档','XE2awuxvIimC0rkNGcHc4uJMnMf'),('链路方案选型','Ezcwwl2pPiohyWkdO4hc6mkxnZH'),('运行耗时评估','VYT0woUSEiLk0NkxrjEcdIp4nbc'),('10KM 压测','AM1BwBYEYiFI32kdJg5cYE8yn35'),('Q2 目标讨论(5/21)','FW4Ydgv4QoGLYRxeXPscYMCxnyg')]),
 ('🔵','慢速模式','瞿鑫宇',[('慢速模式验证实验','XlStwBQDnibTEUk0jE3c7EEQn4c'),('慢速模式+nvfix 耗时估算','VxL2wV146iP7N4klfQ9ccptSnQb')]),
 ('🟣','HIL 等效性与规模化','朱啸峰',[('HIL 台架仿真一致性报告','IPWmwIROOi28vWkxRJHct4Lln3e')]),
],
'算法预研':[
 ('🔵','AVM 鱼眼 / 新视角','王禹丁',[('avm 链路-鱼眼','WDfGwUa0IiRWf5kVnflcokrHnth'),('3DGS avm 链路开发','JZ24wgQG5if4JgkwvghcQNnYnVf'),('Gsplat 适应 mei 相机','KU0jwfZFOiQC2zkW28gceAYcnjh')]),
 ('🟣','Feedforward / 世界模型探索','杨星昊',[('FF Gaussian 技术综述15篇','R65tw0Tg4iKdAnkvN64cmR6ynPg'),('场景重建前沿技术调研','GWcHw65bjinbYlk1e6jcI0genNe'),('世界模型方案调研','TjBXwI1QiiADy0kDSMHcmD6qn2g'),('Inspatio-world 微调结果','Da5nwHE1TiisOXkhgfrcur2gnXg')]),
 ('🟣','3DGS 场景泛化（非 WM）','王禹丁',[('3DGS 场景天气/光照泛化','PLfYwqP23iO2jnk6VnKcRgSXnAg'),('WeatherEdit','NOlAw0xjhiJosLkzYMpcBIfinCf')]),
],
'Agents':[
 ('🔵','复现率 Agent','郑丽娜/吕文杰',[('复现 Agent 阶段性验证报告','XF97w6WB2ihOtXkIvacchIe8nmc'),('AI agent 看复现上线 review','Y1uDwU1xxivL59klM2Kc2pKwnVh'),('复现 Agent AI 改进','QV6uw07TLiWD9QkP0hdcc1nOnZf'),('开发计划','K9eIw7MGBiXig6kJbsdcCIX5nVv'),('Reference Defect 新问题 Agent','QfsrwPVLki2r9Hk02HrcMAD4nwb'),('Reference Defect 定向回归验证','UXLJwAGpei90YfkfaD9cLwy4nVM')]),
 ('🔵','闭环 Diff-Agent / TopDiff','吕文杰',[('“变道晚”检测流水线','PXZWwJBdQiU35gkIuY7cqg5wnmf'),('A/B 视觉横测架构','TwzswsTl6iEPxLkkz59c4PScncc'),('Topdiff Agent Review','VBZVwXcImi9oNmkvkeBcZEZonbg'),('Metric Diff Agent 进度','QqABwxADHi6UXeknT6fcu9ZknKc'),('Top Diff Agent 计划','ELmuwmwcsiClzIkgnLWcNcSinYb'),('CCES Metric 评测体系','NdEGwDJn6iRcdEkTgF2clKSbn7e')]),
 ('🔵','通用 Evaluator / 研发 Agent','郑丽娜',[('研发闭环 agent','G0BGwftdsiIkKJkLeTKcne5hnhe'),('Agent 汇总开发计划','NyZQwAiyQikW2Nk844vcv8zLnYd'),('训练仿真评测闭环 Agent 开发','ZUGCwVB3fiDcRDkwqYbcCDyInxf')]),
 ('🔵','Simworld 治理 / 环境 Agent','杨星昊',[('3DGS 仓库架构优化对比','A4UuwYfMmiAZkakUw1QcMrEen4c'),('simworld 仓库优化回归方案','O1CXdGF2HoUJ3axrBHQcTMBHn2d'),('Simworld Agent 模块升级','Vi7Vw0hTyiVUssk8tivc32m7nDe'),('agent 构建','CcOOwN1r0iYgdfk9P5LcHSLenLh'),('Docker Agent 指南','Hsw0wTiRpiync6kkLYlcEhIcnXg'),('XPU 自动更新&编包环境','L41IwsWGTi24f4kYScYcQ4OZnQc'),('预处理优化方案(img)','B65jdV4fCow2DJxO64ncnepEnVe')]),
],
}
def build():
    cell=lambda items:'<ul>'+''.join(li(*it) for it in items)+'</ul>'
    rows=''.join(f'<tr><td vertical-align="middle"><b>{k}</b></td><td vertical-align="middle"></td><td>{cell(v)}</td></tr>' for k,v in ROWS.items())
    return ('<table><colgroup><col/><col/><col/></colgroup><tbody>'
      '<tr><td vertical-align="middle"><b>链路</b></td><td vertical-align="middle"><b>月目标（写周报时填）</b></td><td><b>文档库（全量项目 · ✅完成 / 🔵跟进 / 🟣规划）</b></td></tr>'
      +rows+'</tbody></table>')
if __name__=='__main__':
    f=subprocess.run(["lark-cli","docs","+fetch","--api-version","v2","--doc",DOC,"--detail","with-ids","--format","json"],capture_output=True,text=True,timeout=70)
    md=json.loads(f.stdout)['data']['document']['content']
    TABLE=re.search(r'<table\b[^>]*?\sid=\"([^\"]+)\"',md).group(1)
    r=subprocess.run(["lark-cli","docs","+update","--api-version","v2","--doc",DOC,"--as","user","--command","block_replace","--block-id",TABLE,"--content",build(),"--format","json"],capture_output=True,text=True,timeout=70)
    print('替换:', '"result": "success"' in r.stdout or '"ok": true' in r.stdout, '| failed' if 'failed' in r.stdout else '')
    n=sum(len(v) for v in ROWS.values()); docs=sum(len(it[3]) for v in ROWS.values() for it in v)
    print(f'项目 {n} 个 / 文档 {docs} 条')
