---
name: liuxianming
status: active
role: GIC负责人（李坤的二级上级）
projects: []
---

## 刘先明 (Xianming Liu) — GIC负责人

### 角色
通用智能中心（GIC）负责人，高炳涛的上级，李坤的二级上级。主持GIC双周会。

### 已知互动
- 6/11 WM同步会出席，说"坤哥，你先讲，我也想听听你的看法"（对徐林鵾）
- 主持GIC双周会，审阅各部门仿真进展
- 6/9 邓爽起草部门介绍文档给GIC质量管理组
- 关注仿真和模型的匹配度提升

### 对李坤的影响
- 刘先明记不住组里细粒度事项，脑子里只有几个大桶（闭环仿真SIL/HIL、3DGS生产、Agent技术创新）
- GIC汇报必须归类到大scope下呈现
- [[gic-report-judgment]]

### 架构构想（来自 CVPR 同款公开课讲座 projects/xianming-talk.md，2026-06录入）
- **核心论点**：VLA 2.0 与世界模型本质同为一个 **Foundation 基座模型**，沿 scaling law、用自监督真实数据（X Miner 触发回传，已累计 1.5亿+ clip、~1亿用于训练）训练；不打标、纯视觉、不用激光雷达。终局 = **闭环强化学习 + self-play**（自我博弈生成更强 policy）。
- **AI Infra 是壁垒**：单次读取 50–100PB；GPU 训练效率 +43×（global samples/s）、单 sample +10×、SM 利用率 82.5%；图灵芯片+compiler co-design → 单帧 80ms、推理 12×。
- **世界模型三要素 → 三个工作**：Thinking=**Xmind**（visual/latent CoT、BEV 推理、ADE/FDE 改善）；Controllable=**Xworld**（受控生成 simulator：ego/动态/**静态受控**抗幻觉真实物理边界；dash-cam 补全多相机解海外无数据）；Rollout=**Xforesight**（"拼高达"全攒一起，预测 action+未来视频）。**Xcache**：DiT block-skip 2.7×、跳过 71% block、PSNR>51dB。
- **对仿真组的含义**：他的 Xworld 静态受控 ≈ 李坤 3DGS 几何接地；闭环 RL/self-play 需要可靠仿真考场 = 李坤 SIL/HIL+复现率；强调 data scale/quality/distribution（园区"见弯就转"因左转数据过多）。
