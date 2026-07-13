# 命令：【更新 repo】

> 用户在聊天窗口发 **【更新 repo】** 时执行。
> 一键完成：拉取远程 → 解压 tar/zip → 处理冲突 → 提交推送。纯本地操作，不触碰飞书。

---

## 一、执行流程

```
1. 拉取远程        总是执行
2. 解压根目录包    根目录有 .tar/.tar.gz/.zip 时执行
3. 解冲突          出现冲突时执行
4. 提交推送        有改动时执行
```

---

## 二、详细步骤

### 1. 拉取远程（总是）

在仓库根目录执行：

```bash
git stash push -m "update-repo:auto-stash" -u
git pull --ff-only
git stash pop
```

- 如歌工作树干净，`git stash` 仍执行（无副作用）。
- `--ff-only` 保证只执行快进合并；若不能快进，视为异常，需要用户介入。

### 2. 解压 tar/zip 包（根目录有时）

用 `find` 检测仓库根目录第一层的压缩包：

```bash
for f in $(find . -maxdepth 1 -type f \( -name "*.tar" -o -name "*.tar.gz" -o -name "*.tgz" -o -name "*.zip" \) | sort); do
  echo "解压: $f"
  case "$f" in
    *.tar) tar -xf "$f" ;;
    *.tar.gz|*.tgz) tar -xzf "$f" ;;
    *.zip) unzip -o "$f" ;;
  esac
  rm "$f"
done
```

- 覆盖解压（`-o` / 不提示）。
- 解压后删除压缩包。

### 3. 解冲突（有冲突时）

两类冲突分别处理：

| 阶段 | 冲突来源 | 处理原则 | 命令 |
|---|---|---|---|
| `git pull --ff-only` 后 | 远程 vs 本地 | 以远程为准 | `git checkout --theirs .` 后 `git add -A` |
| `git stash pop` 后 | stash vs 本地 | 以本地为准 | `git checkout --ours .` 后 `git add -A`，或按 `git checkout HEAD .` 丢弃 stash 改动 |

冲突处理完成后必须：

```bash
# 默认冲突全部保留远程后，把未合并标为已解决
git add -A
```

如果 stash 也解冲突失败，保留本地版本（因为 stash 通常就是用户的临时改动）。

### 4. 提交推送（有改动时）

如果工作区仍有改动：

```bash
git add -A
git commit -m "sync: 更新 repo"
git push origin main
```

- commit message 固定为 `sync: 更新 repo`。
- 分支根据当前分支推送（不一定是 `main`）。

---

## 三、完整脚本

仓库根目录备用命令：

```bash
bash team/memory/commands/update-repo.sh
```

脚本内容见 `update-repo.sh`。

---

## 四、异常处理

| 情况 | 行为 |
|---|---|
| 网络不可用、pull 失败 | 终止并报错，保留 stash，不自动重试 |
| `--ff-only` 无法快进 | 报错退出，让用户先处理分支分叉 |
| stash pop 冲突 | 按 §3 规则自动以本地为准，然后 add |
| 压缩包解压失败 | 打印错误并跳过该包，不删除 |
| push 被拒绝/触发 secret scanning | 停止，把冲突/扫描结果报告给用户，不强制 force push |

---

## 五、注意事项

- 不要在涉及 `git filter-repo` 重写历史后的仓库中使用普通 `push`，否则需要 `git push --force` 并另行确认。
- 本命令只操作当前 Git 仓库；不处理子模块、不处理 agent Pod 远程目录。
- 压缩包只解压并删除仓库**根目录**一层（`-maxdepth 1`），不递归子目录，避免误删。
