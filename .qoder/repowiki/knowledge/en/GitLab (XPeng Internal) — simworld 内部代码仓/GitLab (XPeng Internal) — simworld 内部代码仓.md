---
kind: external_dependency
name: GitLab (XPeng Internal) — simworld 内部代码仓
slug: gitlab-xpeng
category: external_dependency
category_hints:
    - client_constraint
scope:
    - '**'
---

### GitLab (XPeng Internal)
- **角色**：simworld 三维重建/仿真项目的内部代码托管，作为 daily 仓库的 submodule 挂载于 `team/simworld`。
- **地址**：`git@gitlab-adc.xiaopeng.link:simworld/simworld.git`，仅限 XPeng 内网/VPN 访问。
- **用途**：包含 3DGS 模型、Fuyao 训练管线、UCP 生产部署、HIL 仿真接口等核心算法与工程代码。