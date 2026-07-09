import typer
from tse.cli.client import ControlClient
from tse.switches import SWITCH_REGISTRY

app = typer.Typer(help="训练仿真评测闭环 Agent —— 远程瘦客户端")


@app.command()
def run(rerun_job_id: int = typer.Option(
            ..., "--rerun-job-id", help="rerun 的模板 e2e job_id（每次提交可变）"),
        sim_x_token: str = typer.Option(
            ..., "--sim-x-token", help="仿真平台 x-token（JWT，会过期；每次提交随请求下发）"),
        sim_x_account: str = typer.Option(
            ..., "--sim-x-account", help="仿真平台 x-account（账号邮箱）"),
        job_name: str = typer.Option(
            None, "--job-name", help="任务名（每次提交可变；缺省由分支+实验号生成）"),
        manifest_branch: str = typer.Option(
            None, "--manifest-branch", help="pipeline 清单分支（缺省走服务端配置）"),
        baseline: list[str] = typer.Option(
            None, "--baseline",
            help="评测基线 job：job_name=job_id（可重复，如 --baseline 3dgs_3w=133785 "
                 "--baseline origin_png=134316）。每次评测对比的基线可不同。"),
        set_: list[str] = typer.Option(
            None, "--set",
            help="打开开关简称（可重复）：裸写即开启，如 --set use_difix；"
                 "也可显式 --set use_difix=true / =false（简称见 `switches` 命令）")):
    # 编包分支（simulation / simworld）已 hardcode 在服务端 constants，CLI 不再传入。
    switches = _parse_switches(set_)
    baseline_jobs = _parse_baseline_jobs(baseline)
    res = ControlClient().run(switches=switches,
                              template_e2e_job_id=rerun_job_id, job_name=job_name,
                              manifest_branch=manifest_branch,
                              baseline_jobs=baseline_jobs,
                              sim_x_token=sim_x_token,
                              sim_x_account=sim_x_account)
    typer.echo(f"experiment_id = {res['experiment_id']}")


def _parse_switches(values: list[str] | None) -> dict[str, bool]:
    """解析 ``--set`` 开关，返回 {开关名: 是否开启}。

    支持两种写法：
      - 裸写开关名（``--set use_difix``）→ 视为开启（True）；
      - 显式赋值（``--set use_difix=true`` / ``=false`` / ``=1`` / ``=0`` 等）。
    取值大小写不敏感；``true/1/yes/on`` 为开，其余为关。空开关名直接报错。
    """
    truthy = {"true", "1", "yes", "on"}
    out: dict[str, bool] = {}
    for item in values or []:
        key, sep, val = item.partition("=")
        key = key.strip()
        if not key:
            raise typer.BadParameter(f"--set 开关名不能为空: {item!r}")
        out[key] = True if not sep else val.strip().lower() in truthy
    return out


def _parse_baseline_jobs(values: list[str] | None) -> dict[str, list[int]]:
    """把 ``--baseline job_name=job_id`` 解析为 {job_name: [job_id,...]}（同名累加）。"""
    jobs: dict[str, list[int]] = {}
    for item in values or []:
        job_name, sep, ids = item.partition("=")
        job_name = job_name.strip()
        if not job_name or not sep:
            raise typer.BadParameter(f"--baseline 格式应为 job_name=job_id，收到: {item!r}")
        try:
            id_list = [int(x) for x in ids.split(",") if x.strip()]
        except ValueError:
            raise typer.BadParameter(f"--baseline {job_name!r} 的 job_id 必须为整数: {item!r}")
        if not id_list:
            raise typer.BadParameter(f"--baseline {job_name!r} 缺少 job_id: {item!r}")
        jobs.setdefault(job_name, []).extend(id_list)
    return jobs


@app.command()
def switches():
    """列出所有可用的全局开关简称及其对应的平台完整配置。"""
    width = max(len(a) for a in SWITCH_REGISTRY)
    for alias, token in SWITCH_REGISTRY.items():
        typer.echo(f"{alias:<{width}}  ->  {token}")


@app.command()
def status(eid: str):
    typer.echo(ControlClient().status(eid))


@app.command("list")
def list_():
    for row in ControlClient().list():
        typer.echo(f"{row['id']}  {row['status']:<18} {row.get('report_url') or ''}")


# TODO: watch（消费 /watch 流）、resume、cancel、logs
if __name__ == "__main__":
    app()
