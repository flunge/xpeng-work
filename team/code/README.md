# simworld

## 简介

本仓库用于三维重建任务的相关开发，包括模型训练、渲染、数据处理和生产部署等流程。

---

## 🐳 使用镜像

| 用途               | 镜像地址                                                                                    |
| ---------------- | --------------------------------------------------------------------------------------- |
| A100 镜像       | `infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:dusc-260426-1918` |
| PPU 镜像        | `infra-registry-vpc.cn-wulanchabu.cr.aliyuncs.com/data-infra/fuyao:peijh-260526-0220` |
---

## 📚 目录结构

```text
simworld/
├── pipeline/fuyao/          # Fuyao 训练/预处理提交
├── pipeline/ucp/            # IPS/UCP 场景生产
├── xpeng_data_process/      # 数据预处理
├── omnire_joint_trainning/  # Reconic 训练与渲染（render_sim 等）
├── hil/                     # HIL 仿真服务
├── models/                  # 各模型目录（difix、g3r、street_gaussians 等）
├── sim_interface/           # 闭环仿真接口
├── libs/xpeng_raster/      # 光栅化库
├── tools/                   # 调试与评测（含 dockerfile）
├── agents/                  # 飞书 Agent
└── skills/                  # 团队 Skills
```

| 功能模块      | 入口脚本路径                                        |
| --------- | --------------------------------------------- |
| 数据拉取与预处理  | `xpeng_data_process/main.py`                  |
| (only) 数据拉取  | `xpeng_data_process/generate_dataset_data.py` |
| 预处理 Fuyao 提交 | `pipeline/fuyao/deploy_preproc.bash`          |
| IPS 平台主脚本 | `pipeline/ucp/ucp_xpeng_vision.py`             |

---

## 🚀 模型训练

* **Fuyao 部署脚本**：`pipeline/fuyao/deploy_reconic.sh`
* **默认配置文件**：`pipeline/configs/sim3dgs_v416.yaml`
* **预处理 Fuyao 部署**：`pipeline/fuyao/deploy_preproc.bash <config_file> <job_name>`
* **默认预处理配置**：`pipeline/configs/sim3dgs_v416_preprocess.yaml`

---


## 📦 数据处理

* **数据拉取与预处理整体流程**：`xpeng_data_process/main.py`
* **独立拉取大数据平台数据**：`xpeng_data_process/generate_dataset_data.py`

---

## 🏭 生产部署（IPS平台）

* **部署主程序**：`pipeline/ucp/ucp_xpeng_vision.py`

---

## 🤖 团队 Skills 与飞书 Agent

| 目录 | 说明 |
|------|------|
| [`skills/`](skills/README.md) | 团队 Skill 单一来源（飞书 `lark-*`、3DGS `3dgs-*` 等） |
| [`agents/`](agents/README.md) | 飞书群 Bot 服务（`大模型 …` 等） |
| [`docs/feishu/onboarding.md`](docs/feishu/onboarding.md) | 不用 Cursor 也能部署 Bot |

Clone 后（飞书 skill / Bot，Ubuntu）：

```bash
bash agents/scripts/setup-dev-environment.sh
lark-cli config init --new && lark-cli auth login   # 首次
```

---

## 📖 相关文档

* **\[2025年8月最新] 3D Gaussian Splatting 跑通 + 生产部署手把手指南**
  👉 [查看文档](https://xiaopeng.feishu.cn/docx/VYimdbtakoTbetxTGS9cDYDYnjh)
* **IPS V2 跑通手把手教学**
  👉 [查看文档](https://xiaopeng.feishu.cn/docx/QlZbdfmGpoe39gxFkrkc02hbnQc)
* **IPS V2 深度迁移后如何提交job**
  👉 [查看文档](https://xiaopeng.feishu.cn/wiki/Tpnow2u5Wi1VqTkaoqHcpSzznhU)
* **纯视觉生产/扶摇任务执行流程说明**
  👉 [查看文档](https://xiaopeng.feishu.cn/wiki/S3fBw5Z83inSQGksaV4cVbennvc)
