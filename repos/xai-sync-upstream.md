# xai 上游监控（earendil-works/pi）

- `flunge` = 我们自己的 fork/工作仓（git@github.com:flunge/xai.git，main = feat/hermes-memory 构建基线）
- `origin` = 上游公开仓 earendil-works/pi（只读跟踪公开更新）

## 每周/需要时检查上游更新

```bash
cd repos/xai
git fetch origin main
git log --oneline HEAD..origin/main   # 上游新增了什么
git log --oneline origin/main..HEAD   # 我们领先了什么（我们的 hermes-memory 改造）
```

## 合并上游优化（review 后手动挑选）

```bash
git merge --no-commit --no-ff origin/main   # 看冲突/差异
# 或 cherry-pick 单个 commit：git cherry-pick <sha>
# 合并/通过后：git push flunge main
```
