#!/usr/bin/env python3
"""GIC 双周报 20260630（窗口 6/18-6/30）— 文字正文。
风格：每节 标题+<cite>李坤</cite> + whiteboard + 目标 + 进展(3条,突出算法迭代) + 配图占位 + 风险 + 计划。
配图：SoCheap 当前不支持图像生成，用占位符，prompt 写在占位符旁，李坤手动贴图。
所有数字可溯源；只写本组工作。
"""
import subprocess, json

LIKUN = '<cite type="user" user-id="ou_f9cd23092a356c297d6a9f38fd7cfd5e" user-name="李坤"></cite>'

CONTENT = f'''<title>仿真算法组双周进展 20260630</title>
<h1>仿真算法组双周进展 20260630 {LIKUN}</h1>

<h2>团队情况 {LIKUN}</h2>
<ul>
<li>在岗 16 人 + 产假 1 人（冯美慧）：P8 负责人 1（李坤）、P7 1（郑丽娜）、P6 正式 4（杨星昊/周蔚旭/裴健宏/周冯）、P5 正式 4（吕文杰/王禹丁/朱啸峰/瞿鑫宇）、闭环场景集 PM 刘开拓，其余为实习生（靳希睿/严潇竹/樊世洲/李祉浚/谷佳萱）。</li>
<li>本阶段新增 3 名实习生（樊世洲—障碍车智能体/编包 Agent、李祉浚—生产 OnCall Agent、谷佳萱—场景编辑），全部投入 AI Agent 与场景生产方向。</li>
<li>主线：3DGS 闭环仿真规模化（SIL/HIL + RC 产线）；辅线：渲染算法迭代（NVFixer/CLIP-IQA）、AI Agent 重塑研发评测流、World Model 预研。</li>
</ul>

<h2>Topic 1 ｜ 3DGS 生产链路：长里程量产 + 1 小时极速 {LIKUN}</h2>
<p><b>目标</b>：北上广深核心 RC 路线稳定日产、支撑发版 gating；极速模式把单场景生产压到 1 小时级，承接客诉 case 快速验证。</p>
<p>【此处贴图：biweekly_0630_topic1_3dgs_production.png】（prompt 见文末配图清单 #1）</p>
<p><b>进展</b>：</p>
<ul>
<li>长里程 timeout 根因定位为 undistort 模块多进程且非 spawn 方式（Ray 官方不建议），改造后在 3DGS 卡池重跑数十 case 未复现；端午重产广州 184km subrun 完整数据、786 个 scenario 成功。</li>
<li>极速模式训练侧提速 2.6×（4h→1.5h），UCP 全链路约 100 分钟跑通；复现率 108 个 case 复现 80 个、按全量折损后约 50% 作为可用基线先行；6/26 对外交付文档完成。</li>
<li>大数据侧长里程入库折损 35%（旧链路超长数据边界问题），已提 backfill 补偿并重试；TC 采集累计 968km（30% 折损后目标 1750km）。</li>
</ul>
<p><b>风险</b>：</p>
<ul>
<li>🟡 公共卡池被高优任务挤占，3DGS 私有卡池并发仅约 40，是长里程产能瓶颈，正申请高优权限。</li>
<li>🟡 AJS 长路线采集 20-30% 数据损失，初判为 TC 采集软件抢占资源致数据损坏，已上升排查。</li>
</ul>
<p><b>计划</b>：7/2 累计冲 1000km、失败 case 单独重产上线 ｜ Q3 优化 feedforward、训练 NVFixer 提复现率、简化交互。</p>

<h2>Topic 2 ｜ 闭环仿真 SIL：渲染算法迭代 + 图像质检 {LIKUN}</h2>
<p><b>目标</b>：把渲染效率与质量推到可支撑发版评测的水平——渲染效率比冲 1:5、图像质量自动 gating，车型泛化常态化。</p>
<p>【此处贴图：biweekly_0630_topic2_sil_algorithm.png】（prompt 见文末配图清单 #2）</p>
<p><b>进展</b>：</p>
<ul>
<li>NVFixer 渲染：带 ref 图新版本 TRT 模型渲染效率比 1:7.2（旧未优化版 1:6.5、Difix 1:17），TRT 与 PyTorch 输出完全对齐、轨迹评测量化指标一致；新架构 V3C（DIT 全局 self-attention 拼接 ref+render latent，+8dB PSNR）/ V3D（VAE decoder 后注入 ref，+6dB PSNR）合并后启动 64 卡全量训练，test set 最高 PSNR 31。</li>
<li>渲染提效已触物理瓶颈：PTQ 量化 + 1k calibration 在耗时大头层精度敏感易溢出、敏感层 FP32 大 GEMM 层 INT8 反而更慢，算子融合 FMHA 已是天花板 → 转向 TinyVAE/LightVAE 蒸馏（wan latent 空间与 cosmos 不一致，拟用自有 VAE 当 teacher 蒸馏）。</li>
<li>CLIP-IQA 图像质检 6/26 接入 SIL 评测链路、可过滤极差渲染 case；车型泛化多车型 Pipeline 上线、Moe 模型自测正常待发版，并联合算法定出三参数（车衣 / 摄像头外参 pitch+roll / 车型）敏感性扫描方案——已验证斑马车衣致车辆不加速、侧前 pitch 1° 即影响加减速与居中。</li>
</ul>
<p><b>风险</b>：</p>
<ul>
<li>🔴 渲染效率 1:5 目标在现有 TRT 量化路径下已触顶，需靠 VAE 蒸馏或硬件迁移突破，存在不确定性。</li>
<li>🟡 ref 图 OOD（cross-attention 过尖锐）仍影响泛化场景渲染稳定性。</li>
</ul>
<p><b>计划</b>：本周 64 卡训练出结论、冻结架构 ｜ TinyVAE 蒸馏验证 ｜ CLIP-IQA 大规模上线后调阈值、HIL 链路接入方案定稿。</p>

<h2>Topic 3 ｜ 闭环仿真 HIL：阶段性验收 {LIKUN}</h2>
<p><b>目标</b>：HIL 链路成为发版上车的最终 gating——1000km+ RC 稳定运行、可用率 95%+、结论可对外输出。</p>
<p>【此处贴图：biweekly_0630_topic3_hil.png】（prompt 见文末配图清单 #3）</p>
<p><b>进展</b>：</p>
<ul>
<li>6/29 完成实时模式阶段性验收：5 个台架节点机房部署可用，3 节点跑近 1500 条数据无中断；效率比 batch=20 为 1:2.82、batch≥30 达 1:2.5（达成月目标 1:3）；数据可用性 100%（5% 丢帧阈值，localpose UDP 阶段掉帧待网络层优化）。</li>
<li>100 case × 5 次多轮一致性检测：优秀/良好档无显著随机性，14% 一般档需 PAT 评测确认影响，8 个最差档判为不可用、列入优化记录；PAT 评测链路已打通、跑通两版本模型对比。</li>
<li>慢速模式带 ref 图链路：把 H265 经 NVFixer VAE encoder 重刷成 latent、HIL 链路直读 latent（代码适配 50%），规避 H265 经 DDS 解析耗时与磁盘占用；连续 case 尾部掉帧根因分析中。</li>
</ul>
<p><b>风险</b>：</p>
<ul>
<li>🔴 6 月底"1000 工作台/天"目标未达（当前可用率 92%）；5080 台架预算月底到位，IT 采购 + 供应商交付预计延至 7 月底/8 月初，节点规模化是 Q3 关键瓶颈。</li>
</ul>
<p><b>计划</b>：7 月底前用 5 台机器跑通问题、标准化操作系统镜像 ｜ NVFixer 接入 HIL 后慢速效率冲 1:8 ｜ 与评估组协同补齐 PAT metric。</p>

<h2>Topic 4 ｜ AI Agent 重塑研发·生产·评测流 🆕 {LIKUN}</h2>
<p><b>目标</b>：用 AI Agent 把复现分析、A/B 评测、环境构建等重复劳动自动化，常态化集成进各需求环节、各项准确率达 80%+。</p>
<p>【此处贴图：biweekly_0630_topic4_agent.png】（prompt 见文末配图清单 #4）</p>
<p><b>进展</b>：</p>
<ul>
<li>复现率 Agent：本阶段新增 7 类问题场景、累计支持 11 类；道内画龙准确率 81%（22/27）达上线标准，生产验收复现正确率 89%，摆动复现 19/24（79%）；FMprompt 复现率用 deepseek-v4 微调（20 训练 + 40 验证）单训练集达 80%。</li>
<li>闭环 Diff Agent：已支持 6 个 metric 自动 edit-review（准确率 50% 迭代中），道内画龙 Topdiff 7/11 正确上报；6/29 演示 AB Review 质检 Agent——可对两版本特定指标直接出静态质检报告。</li>
<li>Prompt 对齐 Agent 准确率 83.3%→冲 85%（解决 viewpoint 提示词开关 + 飞书机器人 HTML 输出）；环境构建 Agent 打通"输入 base image + 安装包 → 自动产出 Dockerfile"；编包 Agent 实现自动排队提交、规避资源争抢。</li>
</ul>
<p><b>风险</b>：</p>
<ul>
<li>🟡 Agent 落地的量化收益（节省人力 / 提效比）尚未系统对齐，需在下一阶段明确节点与收益口径。</li>
<li>🟡 Diff Agent 与人工复验一致率偏低，根因是画龙幅度 vs 蛇形次数的评价准则差异，待对齐。</li>
</ul>
<p><b>计划</b>：复现率 Agent 全量集成 + 难场景（危险变道/绕行）攻坚 ｜ Diff Agent 准确率提至 80%+ ｜ 量化收益口径与汇报机制建立。</p>

<hr/>
<p><b>【配图清单 — 待李坤手动生成贴图，1024x576，深色信息图风格】</b></p>
<p>#1 topic1：见 scripts/gen_biweekly_images.py IMAGES["topic1_3dgs_production"]</p>
<p>#2 topic2：见 scripts/gen_biweekly_images.py IMAGES["topic2_sil_algorithm"]</p>
<p>#3 topic3：见 scripts/gen_biweekly_images.py IMAGES["topic3_hil"]</p>
<p>#4 topic4：见 scripts/gen_biweekly_images.py IMAGES["topic4_agent"]</p>
'''


def main():
    r = subprocess.run(
        ["lark-cli", "docs", "+create", "--api-version", "v2",
         "--content", CONTENT, "--format", "json"],
        capture_output=True, text=True
    )
    if r.returncode != 0:
        print("FAILED:", r.stderr[:500]); return
    d = json.loads(r.stdout)
    doc = d.get("data", {}).get("document", {})
    tok = doc.get("document_id") or doc.get("obj_token")
    print("OK token:", tok)
    print("url:", doc.get("url"))
    # move to weekly folder
    mv = subprocess.run(
        ["lark-cli", "drive", "+move", "--file-token", tok, "--type", "docx",
         "--folder-token", "JIb3ftcJclQ1DvdHFkIc6gxNnOb", "--format", "json"],
        capture_output=True, text=True
    )
    print("move:", mv.stdout[:150] if mv.returncode == 0 else mv.stderr[:200])


if __name__ == "__main__":
    main()
