# repos/reference — SimWorld 上游参照物索引

Simworld-Docs 文档库重构（原则2）的落地目录：各模块的公开上游仓库以 git submodule 挂载于此，论文仅做解析不落本地。文档正文全部在飞书 Simworld-Docs（文件夹 `ZIRafNj59l9XHbdfNxkcBakMnEf`），本地只保留本映射。

| 子模块 | 上游仓库 | 对账 commit | 对应 SimWorld 模块 | 飞书文档 |
|---|---|---|---|---|
| `nv-fixer` | [nv-tlabs/Fixer](https://github.com/nv-tlabs/Fixer) | b39dfca | `models/nvfixer` | NVFixer 渲染修复模块（PlROdzLHNoTVQnxDffVcRoSZnNe） |
| `difix3d` | [nv-tlabs/Difix3D](https://github.com/nv-tlabs/Difix3D) | c76edc5 | `models/difix` | Difix3D+ 渲染修复模块（WTfAdPDT1oI1vkxcLZCc9d4wnAf） |
| `drivestudio` | [ziyc/drivestudio](https://github.com/ziyc/drivestudio) | e59bda4 | `models/nail_g3r`、`models/reconic` | G3R（WOjKd2r2woCEONxeiGTcHRRsnec）、OmniRe/Reconic（QDyvdXS0ro5kuxxHlr3cTpoQnwc） |
| `street-gaussians` | [zju3dv/street_gaussians](https://github.com/zju3dv/street_gaussians) | 0924b0c | `models/street_gaussians` | Street Gaussians 动态街景重建（MPxqd3qicoRPisxMyDVcQtIonNh） |
| `dpvo` | [princeton-vl/DPVO](https://github.com/princeton-vl/DPVO) | 859bbbf | `xpeng_data_process/opt_processor` | DPVO 相机位姿优化（RRuodMJg5olRkoxCsldcuRIGnsd） |
| `mvsanywhere` | [nianticlabs/mvsanywhere](https://github.com/nianticlabs/mvsanywhere) | 5bd49bb | `xpeng_data_process/mvsnet_processor` | MVSNet 多视角深度估计（WeCkd8s7doaR0nxmwf6c3khCned） |
| `sam-3d-objects` | [facebookresearch/sam-3d-objects](https://github.com/facebookresearch/sam-3d-objects) | f91db41 | `xpeng_data_process/sam3d` | SAM3D 静态物 3D 补全（WYetdYc4Do3xa5xfWIycgm80nzd） |
| `rogs` | [fzhiheng/RoGS](https://github.com/fzhiheng/RoGS) | 0f816c6 | `xpeng_data_process/ground_processing/rogs` | RoGS 路面重建（K19LdNLvio56npxhFIPcgSZ7nie） |

论文/方法学参照（无公开代码，仅解析）：
- Difix3D+ / Fixer：[arXiv:2503.01774](https://arxiv.org/abs/2503.01774)（CVPR 2025 Oral）
- RoGS：[arXiv:2405.14342](https://arxiv.org/abs/2405.14342)（CVPR 2025）
- OmniRe：[arXiv:2408.16760](https://arxiv.org/abs/2408.16760)（ICLR 2025 Spotlight）
- EvoSplat：[arXiv:2503.20168](https://arxiv.org/abs/2503.20168)（CVPR 2025，无官方开源代码，DSUbd0AdmoW3xixa504ci9k1nzf）
- ROME / InSPATIO / Dynamic Assets：内部自研，无公开上游，文档中按方法学参照解析
- Seg/Mask（Mask2Former+LOMM）、CLIP-IQA：仓内 vendored，未挂 submodule（权重/体积过大）

总索引：SimWorld 模块总索引（UhQydBKEHofw0ExtxZOcPPUbn9g）。

维护约定：
1. 新增模块文档前先在此登记上游 submodule（`git submodule add --depth 1 <url> repos/reference/<name>`）；
2. 上游不可达或无公开实现的模块，降级为「论文解析 + 仓内 vendored 代码解析」，并在飞书文档中注明；
3. 更新上游：进入子模块 `git pull` 后回 daily 仓库提交指针。
