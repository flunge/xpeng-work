---
name: wm-internal
track: 场景&生产
status: active
owner: 杨星昊
contributors:
  - 靳希睿（AI辅助编码）
since: 2026-05
---

# World Model 内部探索

## 定位
我方（算法组）自己的World Model探索，规模远小于张雨团队。目标是改善场景质量和探索feedforward方法。

## 里程碑历史

### 2026-06-11 — DiffSynth LoRA训练10 epoch
- 用DiffSynth框架LoRA训练10 epoch
- 有改善：摩托车训后仍存在（说明训练有效果）
- 有问题：车的幻觉未消失
- 计划：先用视频模型训练，后续用更大数据量测试feedforward

### 2026-06-10 — 周报：Lora+DeepSeek方案
- Lora+DeepSeek微调feedforward方案周五讨论决策
- 背景：X-World无显式静态受控，AutoRegressive长时序漂移，推理~1.5s/帧

### 2026-05-29 — 极佳科技交流
- 杨星昊与极佳科技交流feedforward、dreamzero world model
- 极佳在和小鹏world model团队谈二期项目

## 与外部WM团队的区分
- [[zhangyu-wangboyang]] 是独立的、资源充足的外部WM团队
- 我方探索是辅助性的，用于场景质量优化
- 两者不是同一赛道竞争
