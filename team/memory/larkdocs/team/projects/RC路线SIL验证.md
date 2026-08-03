# RC路线SIL验证

> **📋 文档属性**
> 
> - **标识**：rc-route-sil ｜ **所属线**：SIL ｜ **状态**：active
> - **负责人**：李坤 ｜ **贡献者**：王禹丁（SIL仿真执行/闭环验证）、杨星昊（数据生产侧对接）、夏志勋（评估组/Metric验收）
> - **起始**：2026-05 ｜ **内容现势**：截至 2026-07-03
> - **相关文档溯源**：本项目相关文档 / 嵌套文档统一在[溯源索引](https://xiaopeng.feishu.cn/docx/SsWCdQbVZohGHFxhE3RcCmJ2nSb)「三、项目维度 → SIL → RC路线SIL验证」行维护。

## 一、背景目标

**项目定位**：用 SIL 仿真对 RC 路线实车版本报告做横向评测，验证仿真结论与实车的趋势对齐率，支撑 RC 发版 gating。

**最终目标**：产出可信的 SIL 仿真评测结论，与实车版本报告趋势对齐，为 RC 发版提供 gating 依据。

**任务缘起**：与 RC 路线生产（场景&生产/RC路线）相互独立，聚焦仿真验证侧。

**实验配置**：

- 对比模型：rl6（model 18929, binary 1712198, A05RC11/RC12/release）vs rl15（model 19345, binary 1712102, A13RC4\~RC5）【来源：[广州RC路线SIL仿真结果](https://xiaopeng.feishu.cn/wiki/NxBmwuHcqieJXzkmLFzcQ8bMnFe)】
- 仿真路线：广州RC路线200km长里程场景集（896 scenarios），同版 Binary build_XRepoMainCloudJob_74149，渲染=group batch + trt，batch size=1【来源：[广州RC路线SIL仿真结果](https://xiaopeng.feishu.cn/wiki/NxBmwuHcqieJXzkmLFzcQ8bMnFe)】
- 验证方法：CCES评估体系五维度（安全/舒适/效率/合规/导航，次/百km），与e29实车KPI做趋势对齐验证【来源：[200km长里程对比报告](https://xiaopeng.feishu.cn/wiki/N864wtDjFi9UZukOlnycPASEn8c)】
- 批量一致性验证：100 Scenarios × 5 Runs闭环轨迹一致性（PCA medoid基准 + 横向P95 + 里程MAD），量化仿真平台确定性复现能力【来源：[批量一致性分析总览](https://xiaopeng.feishu.cn/wiki/IoWpwxKVWivyNLk7ay7c6DEgnyh)】

## 二、当前状态（截至 2026-07-03）

**仿真进度——SIL 仿真数据重跑中，metric 仍被阻塞（截至 7/3）**

- **SIL 仿真**：1000km SIL 仿真已跑完；7/2–7/3 新老数据重跑验证但报错较多（3dgs OOM + simulation 仓库报错），正与振宇排查编包问题【来源：Q3作战表W27+0703日会】。
- 🟢 **验证阻塞已解除（截至 2026-07-15）**：此前 DSOP 闭环 metric 因 RTM topic 格式变更读不到、10 metric 起跑阻塞；RTM 缺失/格式变更根因确定为跨场景地图缓存冲突、本期已修复并符合交付标准（HIL 侧同源修复）。城区闭环六类 Metric 亦已于 7/6 Ready，"metric 不可用致场景无法毕业+RC SIL 结果无法解读"的双线阻塞得以缓解。（来源：HIL 链路部署 7/15 更新 + 闭环场景集 7/6）
- **🔴 人员风险**：评估组 6/18–6/22 有 4 人离职，与 6/20 metric 验收节点直接冲突。
- **依赖关系**：夏志勋（评估组）→ metric 交付 → 李坤可验证 SIL 结论。

**现有链路**：RC 路线数据集 → SIL 仿真跑通 → 等待闭环 metric → 输出评测结论。

**已产出仿真结论（5月仿真批次）**：

- **rl6 vs rl15 仿真交集对比（0522，公共801场景≈112km）**：rl15全面领先23:7，安全维度10:0压倒性优势；rl15退化点为静止方向盘摆动(116.56 vs 40.19/百km)、急减速(53.87 vs 28.58)、闯红灯(7.95 vs 5.36)【来源：[200km长里程对比报告0522](https://xiaopeng.feishu.cn/wiki/XS5CwPfhNiFbIDkhqVAcAgWAnyh)】
- **实车与仿真对齐率**：对齐率35%\~46%（可信对齐率约50%）。安全维度对齐最高（碰撞/VRU/撞路沿/危险变道4项全对齐）；核心失真集中在舒适维度——道内画龙(实车rl15=0.9，仿真未捕捉)、顿挫(实车rl15更差但仿真显示更好)【来源：[200km长里程对比报告0522](https://xiaopeng.feishu.cn/wiki/XS5CwPfhNiFbIDkhqVAcAgWAnyh), [200km长里程对比报告](https://xiaopeng.feishu.cn/wiki/N864wtDjFi9UZukOlnycPASEn8c)】
- **200km原始数据对比**：安全rl6更优(碰撞总计-15.6次/百km)、效率rl15全面更优(变道成功率高26%，开不到限速少89次/百km)、舒适各有胜负(rl15顿挫远少−1409次/百km，rl6急减速/蛇形更好)【来源：[200km长里程对比报告](https://xiaopeng.feishu.cn/wiki/N864wtDjFi9UZukOlnycPASEn8c)】
- **最大失真点**：仿真rl15 EgoLaneDrift=147.24/百km(rl6=0)，实车无此问题——高度疑似仿真控制层异常【来源：[200km长里程对比报告](https://xiaopeng.feishu.cn/wiki/N864wtDjFi9UZukOlnycPASEn8c)】
- **批量一致性结论**：100场景×5轮，98%可执行；75.3%场景横向P95≤0.6m，MAD中位数0.22%；41.2%达A级(P95≤0.3m，高确定性)；8.2%（8个）P95>3m需根因分析，主因为决策分叉(变道/绕行不确定性)【来源：[批量一致性分析总览](https://xiaopeng.feishu.cn/wiki/IoWpwxKVWivyNLk7ay7c6DEgnyh)】

## 三、持续进展

> 同一天若作战表（日报）与日会 / 纪要都有内容，则并列同一行、按来源分列；空格表示该来源当日无对应记录。

| 时间 | 作战表（日报进展） | 会议纪要 / 日会 | 其他来源 |
|-|-|-|-|
| 2026-04-24（W4） | PDJ2 W4：算法版本gating机制方案制定；；Metric指标摸底：[闭环Metric测评]【来源：PDJ2 W4】 | — | — |
| 2026-04-30（W5） | PDJ2 W5：RC路线运行&指标初步摸底（400km）；【来源：PDJ2 W5】 | — | — |
| 2026-05-09（W6） | PDJ2 W6：【算法优化】Difix性能和效果优化提升gating机制上线【来源：PDJ2 W6】 | — | — |
| 2026-05-15（W7） | PDJ2 W7：【业务交付】SIL上完成广州RC路线的验证及结论对齐。；【算法优化】在gating数据集上完成复现率指标摸底。；【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。复现率现状约为60%，当前问题和prompt一致性/pc or mc/trigger time耦合，下一步todo；；闭环验证：• 100km RC路线结论[闭环Metric测评]【来源：PDJ2 W7】 | — | — |
| 2026-05-20 | PDJ2 W8：【业务交付】SIL上完成广州RC路线的验证及结论对齐。；【算法优化】复现率自动化提升：完成gating数据集全量功能验证以及自动化归因，出具复现率分析报告。自动调整trigger time的功能（生产阶段）上线；【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。复现率现状约为60%，当前问题和prompt一致性/pc or mc/trigger time耦合，下一步todo；；闭环验证：[200km长里程对比报告0522]• 确认如何确认metric评价正确性【来源：PDJ2 W8】 | — | RC 路线 1000km 数据集准备，带 CLIP-IQA 重新跑，评估图像质量【来源：RC路线.md】 |
| 2026-05-27 | PDJ2 W9：【业务交付】广州RC路线指标对齐；【算法优化】Gating数据集完成复现率和归因分析。；【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。；【复现agent】Gating数据集完成复现率和归因分析• 人机一致率：157/183 ≈ 85%【来源：PDJ2 W9】 | "主要风险点在 metric 投入上，闭环 metric 不可用"；高炳涛要求 5 月底前至少能跑几个 metric【来源：0527核心日会逐字稿】 | — |
| 2026-06-03 | PDJ2 W10：【算法优化】ClipIQA完成评估并接入链路。ClipIQA计算Ref图的结果，通过ref和渲染图的得分差优化评价方式，重新编包提交1000km的长里程仿真。；【业务交付】【RC路线仿真】完成北上广深的RC路线（1000+km）仿真以及一阶段闭环指标的验证。；【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。；已提交nvfixer_ref pytorch & trt两个版本gating数据集仿真，看是否较上周有质量提升【来源：PDJ2 W10】 | "等志勋这边的 metric ready，之后就可以常态化地跑"【来源：0603核心日会逐字稿】 | — |
| 2026-06-10 | PDJ2 W11：【业务交付】【RC路线仿真】完成北上广深的RC路线（1000+km）仿真以及一阶段闭环指标的验证。；【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。；【RC路线】：N/A；【RC路线】：当前1000km的SIL仿真已跑完，待metric准出之后验证指标。【来源：PDJ2 W11】 | 1000km SIL 仿真已跑完，但无可用 metric，等夏志勋评估组交付后再验证【来源：0610核心日会逐字稿】 | — |
| 2026-06-19（W12） | PDJ2 W12：【业务交付】【RC路线仿真】完成北上广深的RC路线（1000+km）仿真以及一阶段闭环指标的验证。；【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。【来源：PDJ2 W12】 | — | — |
| 2026-06-26（W13） | PDJ2 W13：【业务交付】【RC路线仿真】完成北上广深的RC路线（1000+km）仿真以及一阶段闭环指标的验证。；【算法优化】复现率gating数据集上复现率达成80%以上，效率达到1：25，渲染效率1：5。；【场景编辑】完整需求：[RT 长里程仿真编辑重建需求]【来源：PDJ2 W13】 | — | — |
| 2026-07-02 | 新数据已和仿真其他同学对齐后跑上SIL验证，旧数据待xiaofeng更新后跑上仿真【来源：Q3作战表W27周四】 | RC路线新数据已跑完seal验证，旧数据缺少部分内容，啸峰更新后可跑仿真；clip-iqa相关代码开发完成【来源：0702核心日会纪要】 | — |
| 2026-07-03 | 新老数据均跑完，报错较多——一部分是3dgs oom，另一部分是simulation仓库报错，需要和zhenyu一起看编包问题【来源：Q3作战表W27周五】 | RC链路新老数据跑完但报错多，怀疑是simulation仓库问题，王禹丁和振宇将查看编包问题后重跑【来源：0703核心日会纪要】 | — |

## 四、后续规划

- **等待 metric 交付**：夏志勋评估组完成闭环 metric 验收后，立即启动 SIL 结论解读与对齐率验证。
- **常态化运行**：metric ready 后实现 SIL 仿真常态化跑通。
- **风险缓解**：关注评估组 6/18–6/22 离职人员对 metric 交付进度的影响。
- **失真盲区修复优先级**：①排查仿真rl15 EgoLaneDrift异常（最大失真点）；②舒适维度仿真评估标准与实车对齐（道内画龙/顿挫定义不一致）；③闯红灯仿真高估问题【来源：[200km长里程对比报告](https://xiaopeng.feishu.cn/wiki/N864wtDjFi9UZukOlnycPASEn8c), [200km长里程对比报告0522](https://xiaopeng.feishu.cn/wiki/XS5CwPfhNiFbIDkhqVAcAgWAnyh)】
- **一致性改善方向**：对8个P95>3m场景做根因分析，重点关注决策分叉(变道/绕行)不确定性来源；对里程MAD>5%的7个场景排查提前停车/路径规划差异；将40个A级场景作为回归基线，建议合格标准为横向P95<1.0m且里程MAD<1%【来源：[批量一致性分析总览](https://xiaopeng.feishu.cn/wiki/IoWpwxKVWivyNLk7ay7c6DEgnyh)】
- **变道效率作为核心亮点**：变道效率是仿真与实车对齐度最高的维度，可作为SIL评测的可信指标优先输出【来源：[200km长里程对比报告](https://xiaopeng.feishu.cn/wiki/N864wtDjFi9UZukOlnycPASEn8c)】