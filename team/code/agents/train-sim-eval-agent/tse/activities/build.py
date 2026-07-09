from temporalio import activity
from tse.config import get_settings
from tse.integrations.bench import (make_executor, build_command, checkout_command,
                                    pipeline_checkout_command, parse_binary_id)
from tse.models.domain import ExperimentRequest
from tse.store.repo import ExperimentRepo


@activity.defn
async def build_binary(req: ExperimentRequest) -> str:
    """编包（5080 三层：宿主机 worker → 虚拟机 git checkout → 容器 pipeline/编包）。

    对齐 docs/xp5_simulation_build_guide.md 的操作顺序：
      1) 【虚拟机】切换 simulation / simworld 两个主仓库到目标测试分支
         （虚拟机仓库与容器 /sandbox 是同一份 bind mount，VM 切分支即容器可见）；
      2) 【容器】``pipeline -checkout_repo`` 按 manifest 补齐 simulation 分组依赖仓库；
      3) 【容器】``./scripts/upload_binary.py`` 在 simulation 仓库内编包，解析 binary_id。

    注：guide 注意事项指出 pipeline -checkout_repo 可能改动 simulation/simworld 分支，
    若编包用的分支不对，需复核第二步后两仓库的实际分支。
    """
    s = get_settings()
    repo = ExperimentRepo(s.db_path)

    # 幂等：命中已有 binary 直接复用，杜绝重复编包（高代价）
    cached = repo.find_binary_by_build_key(req.build_key())
    if cached:
        activity.logger.info("reuse cached binary %s", cached)
        return cached

    executor = make_executor(s)

    # 1) 【虚拟机】切主仓库分支（simulation 必切；simworld 指定了才切）
    activity.logger.info("checkout simulation repo -> %s", req.branch)
    executor.run_vm(checkout_command(req.branch), cwd=s.build_vm_simulation_workdir)
    if req.simworld_branch:
        activity.logger.info("checkout simworld repo -> %s", req.simworld_branch)
        executor.run_vm(checkout_command(req.simworld_branch),
                        cwd=s.build_vm_simworld_workdir)

    # 2) 【容器】按 manifest 检出 simulation 分组依赖仓库
    manifest_branch = req.manifest_branch or s.build_manifest_branch
    activity.logger.info("pipeline checkout_repo manifest=%s group=%s",
                         manifest_branch, s.build_manifest_group)
    executor.run_container(
        pipeline_checkout_command(manifest_branch, s.build_manifest_group),
        cwd=s.build_workdir)

    # 3) 【容器】编包并解析 binary_id
    name = req.binary_name or f"{req.branch}_{req.experiment_id[:8]}"
    cmd = build_command(name, vehicle=s.build_vehicle, region=s.build_region)
    stdout = executor.run_container(cmd, cwd=s.build_workdir)
    return parse_binary_id(stdout)
