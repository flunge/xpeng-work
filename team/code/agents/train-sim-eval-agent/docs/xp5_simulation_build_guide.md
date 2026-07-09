# XP5 仿真编包操作清单

## 前置：挂载关系（理解用，不需操作）

```
虚拟机(5080)                                                              容器(xp5_simulator)
/mnt/vm_shared_data/workspace/data/host_xp_tools_and_sandbox/simulation  ──挂载──>  /sandbox
```

> 两边是同一份文件：虚拟机里切分支 → 容器内 `/sandbox` 立即可见。
> 代码物理存放在虚拟机磁盘，容器只是通过 bind mount 共享同一份数据。

---

## 第一步：进入【虚拟机】

```bash
ssh xpeng@192.168.122.180
```

---

## 第二步：在【虚拟机】里切分支

仅切换主仓库分支，不执行 `pipeline`。

```bash
# 1. 切 simulation 仓库分支
cd /mnt/vm_shared_data/workspace/data/host_xp_tools_and_sandbox/simulation/simulation
git checkout dev_xngp_xp5_zf     # simulation 所需分支
git status                       # 确认分支正确、工作区状态清晰

# 2. 切 simworld 仓库分支
cd /mnt/vm_shared_data/workspace/data/host_xp_tools_and_sandbox/simulation/simworld
git checkout dev_zf_nvfixer      # simworld 所需分支
git status                       # 确认分支正确
```

> 因为代码物理存放在虚拟机磁盘、容器只是挂载共享，所以在虚拟机里切好分支后，
> 容器内看到的就是同一份目标分支代码。

---

## 第三步：进入【容器】

```bash
docker exec -it xp5_simulator /bin/bash
```

---

## 第四步：在【容器】内检出依赖仓库

```bash
pipeline -checkout_repo -manifest_branch dev_xngp_xp5 -group simulation -verbose
```

参数含义：

| 参数 | 含义 |
|------|------|
| `-checkout_repo` | 执行多仓库检出 |
| `-manifest_branch dev_xngp_xp5` | 使用 `dev_xngp_xp5` 这套清单分支 |
| `-group simulation` | 只检出 `simulation` 分组的仓库 |
| `-verbose` | 打印详细日志 |

> 此步按 manifest 把 `simulation` 分组其余依赖仓库补齐，凑齐编包所需的完整代码集合。

---

## 第五步：在【容器】内编包

```bash
cd /sandbox/simulation/simulation
./scripts/upload_binary.py \
    --cn \
    --foundation_model \
    --enable_simworld \
    -v XP5 \
    -f \
    --build_region sh \
    -n zhouf4_nvfixer_xxx
```

编包参数含义：

| 参数 | 含义 |
|------|------|
| `--cn` | 国内（China）配置/区域 |
| `--foundation_model` | 启用 foundation model（基础模型） |
| `--enable_simworld` | 启用 simworld 模块 |
| `-v XP5` | 车型版本 XP5 |
| `-f` | 强制执行（force） |
| `--build_region sh` | 构建区域 上海(sh) |
| `-n zhouf4_nvfixer_xxx` | 包名 / 任务名（按需替换为实际命名） |

---

## 整体顺序速览

1. 【虚拟机】`ssh xpeng@192.168.122.180` 进入虚拟机
2. 【虚拟机】`simulation` 仓库 → `git checkout dev_xngp_xp5_zf`
3. 【虚拟机】`simworld` 仓库 → `git checkout dev_zf_nvfixer`
4. 【容器】`docker exec -it xp5_simulator /bin/bash` 进入容器
5. 【容器】`pipeline -checkout_repo ...` 检出依赖仓库
6. 【容器】`upload_binary.py ...` 编包

---

## 注意事项

- 第四步的 `pipeline -checkout_repo` 是否会覆盖第二步手动切换的
  `simulation`/`simworld` 分支，取决于该工具实现。若编包用的分支不对，
  先检查 `pipeline` 检出后这两个仓库的分支是否被改动。
- 首次执行后建议用 `git status` 复核 `simulation`/`simworld` 的分支是否正确。
