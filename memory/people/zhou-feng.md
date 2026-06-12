---
name: zhou-feng
status: active
level: P6
role: Fixer优化+Diffsion
projects:
  - Fixer优化 (owner)
  - 慢速模式 (contributor)
description: 周冯 — P6，Fixer性能优化核心，Diffusion新模型探索
---

## 周冯 — P6，Fixer与Diffusion

### 角色定位
P6，社招。Fixer性能优化核心执行者，同时负责Diffusion新模型探索（O4-KR1）。

### Q2 OKR分工
- **O2-KR2**：HIL渲染效果与复现率提升，协同瞿鑫宇
- **O3-KR1**：长里程MVP关键协同（杜思聪执行Owner）
- **O4-KR1**：Diffusion新模型探索——轻量化、多摄像头一致性、新视角生成，执行Owner

### 核心项目：SIL & HIL Fixer性能优化

**SIL difix实验（6/10日会）**：
- 第一波：优化带ref图的编码方式，训练到8000步PSNR相对baseline退化，已停止
- 第二波：探索新架构，训练35K步PSNR提升有限，排除噪声影响
- 下午转向：从训练框架和loss设计优化，提交四组优化实验已运行，晚上查看PSNR提升情况

**历史实验数据**（Fixer文档）：
- baseline: difix整卡1:8.8~9.2, MIG 1:17
- 最优实验: EXP_5 (非对称分辨率) 1:14.8, EXP_6 (低层attn) 1:15.5
- HIL侧：v5降分辨率+batch优化后gpu0 193.1ms（baseline 528.7ms）
- Nvfixer TRT转换仍有多项失败（VAE Encoder、DiT导出问题），推荐改法A（torch patcher + TRT core_encoder）

### Diffusion新模型（O4-KR1）
- 三方向探索：轻量化、多摄像头一致性、新视角生成
- 轻量化方向直接服务HIL/SIL链路耗时指标
- 新视角生成方向需拓展到两车道场景

### 协作网络
- 与瞿鑫宇在HIL KR2上协同
- 与杜思聪在生产链路KR1上协同
- 实验依赖GPU资源

### 4-5月补充观察

- **4/20**：负责AIFIX整体流程启动，明后天完成部署，周四-五出第一版结论
- **4/22**：搭建MVSA链路批量化测试，单张DIFIX~75-76ms，转TRT engine时遇到问题
- **5/12**：将Defix优化从PyTorch转到TRT Engine链路，重新生成T2T engine
- **5/13**：展示EXP_5/6优化明显，EXP_4更接近原图（可删cross-attention），本周VAE量化实验
- **5/19**：NVFix CUDA优化（CUDA DAF/CUDA graph/多batch TRT），切换Seer链路
- **5/25**：seal链路NVFixer+TRT（sim engine bug修复），无ref图baseline跑通
- **5/27**：NVFixer无ref图效率1:6.7，修复TRT版本不一致bug
- **5/28**：FM轨迹评测效果差，需加强制跟随+trigger time失效逻辑

### 性格画像（基于4/13-6/12共30+次日会）

- **性格标签**：实验狂热、极其细致、诚实严谨、略显啰嗦、埋头苦干
- **沟通风格**：被动但刹不住——每个实验讲配置/过程/结论，流水账式。学术诚实——"PSNR有退化""效果还不如Difix""提升有限"
- **典型句式**："从昨天到现在又新加了三个实验...","效果均未达预期","V4抑制了PSNR优化"
- **坤哥互动**：经常打断重定向——"哪几个能快速拿到验证结果？""你现在连一个对的东西都没有"。反复引导从"学术探索"转向"工程思路"。5/20郑丽娜要求用cursor修复代码质量静态检查报错

[[team-members]] [[qu-xinyu]]
