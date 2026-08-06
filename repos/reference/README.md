# repos/reference — SimWorld 上游参照物索引

Simworld-Docs 文档库重构（原则2）的落地目录：各模块的公开上游仓库以 git submodule 挂载于此，论文仅做解析不落本地。文档正文全部在飞书 Simworld-Docs（文件夹 `ZIRafNj59l9XHbdfNxkcBakMnEf`），本地只保留本映射。

| 子模块 | 上游仓库 | 对应 SimWorld 模块 | 飞书文档 |
|---|---|---|---|
| `nv-fixer` | [nv-tlabs/Fixer](https://github.com/nv-tlabs/Fixer) | `models/nvfixer` | NVFixer 渲染修复模块（PlROdzLHNoTVQnxDffVcRoSZnNe） |
| `difix3d` | [nv-tlabs/Difix3D](https://github.com/nv-tlabs/Difix3D) | `models/difix` | Difix3D+ 渲染修复 |

论文参照（arXiv，仅解析）：
- Difix3D+ / Fixer：[arXiv:2503.01774](https://arxiv.org/abs/2503.01774)（CVPR 2025 Oral）

维护约定：
1. 新增模块文档前先在此登记上游 submodule（`git submodule add --depth 1 <url> repos/reference/<name>`）；
2. 上游不可达或无公开实现的模块，降级为「论文解析 + 仓内 vendored 代码解析」，并在飞书文档中注明；
3. 更新上游：进入子模块 `git pull` 后回 daily 仓库提交指针。
