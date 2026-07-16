---
kind: external_dependency
name: GitHub — 简历仓库托管
slug: github
category: external_dependency
category_hints:
    - client_constraint
scope:
    - '**'
---

### GitHub
- **角色**：个人简历源码的 Git 托管服务，作为 daily 仓库的 submodule 挂载于 `personal/resume`。
- **分支约定**：`master` 中文简历（默认检出）、`eng` 英文简历；`.gitmodules` 固定 `branch = master`。
- **访问方式**：SSH (`git@github.com:flunge/resume.git`)，sandbox 环境无法访问 SSH key，需在宿主机执行 git 操作。