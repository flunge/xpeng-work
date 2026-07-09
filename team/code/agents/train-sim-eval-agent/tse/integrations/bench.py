import re
import shlex
import subprocess
from typing import Protocol
from tse.config import Settings
from tse.errors import NonRetryableBuildError

# upload_binary.py 输出里 binary id 的解析正则（按真实输出校准）。
# upload_binary.py 的 push_to_db() 实际打印：
#     "The binary you just uploaded is: ID 12345"
# （见 chief/upload_binary.py：print('The binary you just uploaded is: ID {}'.format(...))）
# 故主匹配 "uploaded is: ID <id>"；同时保留 "binary_id: / binary id=" 兼容旧格式/手工日志。
_BINARY_ID_RE = re.compile(
    r"(?:uploaded\s+is:\s*ID|binary[_ ]id[:=])\s*([A-Za-z0-9_\-]+)",
    re.IGNORECASE,
)
# 分支名 / manifest / group / 车型等参数白名单，防命令注入
_REF_RE = re.compile(r"^[A-Za-z0-9._/\-]+$")


class BenchExecutor(Protocol):
    """编包执行器：5080 为「宿主机 → 虚拟机 → 容器」三层嵌套，故分两个目标层。

    - :meth:`run_vm`：在**虚拟机**层执行（git checkout 切分支）。
    - :meth:`run_container`：在**容器**层执行（pipeline / upload_binary.py 编包）。
    """
    def run_vm(self, cmd: list[str], cwd: str) -> str: ...
    def run_container(self, cmd: list[str], cwd: str) -> str: ...


def _cd_command(cmd: list[str], cwd: str) -> str:
    """拼成 ``cd <cwd> && <cmd>`` 的远程命令串（各段 shlex.quote 防注入）。"""
    joined = " ".join(shlex.quote(p) for p in cmd)
    return f"cd {shlex.quote(cwd)} && {joined}"


def docker_exec_command(container: str, cmd: list[str], cwd: str) -> list[str]:
    """把容器内要执行的命令包成 ``docker exec`` 调用（不在宿主机直接跑）。

      ``docker exec <container> bash -lc 'cd <cwd> && <cmd>'``
    - 非交互（不带 ``-it``）：worker 无 TTY，且自动化禁止交互式命令。
    - ``bash -lc``：加载登录环境，确保容器内 PATH 能找到 pipeline 等工具。
    - cmd / cwd 均经 ``shlex.quote`` 转义，防注入。
    """
    return ["docker", "exec", container, "bash", "-lc", _cd_command(cmd, cwd)]


class LocalExecutor:
    """单机回退（开发/测试）：虚拟机层与容器层都在本机直接执行。"""
    def _run(self, cmd: list[str], cwd: str) -> str:
        proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=3600)
        if proc.returncode != 0:
            raise RuntimeError(f"build failed rc={proc.returncode}: {proc.stderr[-2000:]}")
        return proc.stdout

    def run_vm(self, cmd: list[str], cwd: str) -> str:
        return self._run(cmd, cwd)

    def run_container(self, cmd: list[str], cwd: str) -> str:
        return self._run(cmd, cwd)


class NestedExecutor:
    """5080 三层拓扑：worker 在宿主机 → SSH 进虚拟机 → docker exec 进容器。

    - :meth:`run_vm`：SSH 到虚拟机后 ``cd <vm 路径> && <cmd>``（git checkout）。
    - :meth:`run_container`：SSH 到虚拟机后再 ``docker exec`` 进容器执行（pipeline/编包）。
    """
    def __init__(self, vm_ssh_host: str, container: str):
        self.vm_ssh_host = vm_ssh_host
        self.container = container

    def _ssh_run(self, remote_cmd: str) -> str:
        from fabric import Connection  # 延迟导入（可选依赖）
        return Connection(self.vm_ssh_host).run(remote_cmd, hide=True).stdout

    def run_vm(self, cmd: list[str], cwd: str) -> str:
        return self._ssh_run(_cd_command(cmd, cwd))

    def run_container(self, cmd: list[str], cwd: str) -> str:
        # 在虚拟机上执行 docker exec：整条 docker 命令再 shlex.quote 后随 ssh 下发
        docker_cmd = docker_exec_command(self.container, cmd, cwd)
        return self._ssh_run(" ".join(shlex.quote(p) for p in docker_cmd))


def make_executor(s: Settings) -> BenchExecutor:
    if s.build_mode == "nested":
        assert s.build_vm_ssh_host, "TSE_BUILD_VM_SSH_HOST required for nested mode"
        assert s.build_container, "TSE_BUILD_CONTAINER required for nested mode"
        return NestedExecutor(s.build_vm_ssh_host, s.build_container)
    return LocalExecutor()


def _validate_ref(value: str, what: str) -> str:
    """白名单校验分支/参数，挡命令注入；非法直接抛不可重试错误。"""
    if not value or not _REF_RE.match(value):
        raise NonRetryableBuildError(f"illegal {what}: {value!r}")
    return value


def checkout_command(branch: str) -> list[str]:
    """git checkout <branch>（分支名白名单校验）。

    对齐 guide 第二步：在 simulation / simworld 仓库内切换到目标测试分支。
    """
    return ["git", "checkout", _validate_ref(branch, "branch name")]


def pipeline_checkout_command(manifest_branch: str, group: str) -> list[str]:
    """pipeline -checkout_repo：按 manifest 补齐分组依赖仓库（编包前置）。

    对齐 guide 第四步：``pipeline -checkout_repo -manifest_branch <b> -group <g> -verbose``。
    """
    return [
        "pipeline", "-checkout_repo",
        "-manifest_branch", _validate_ref(manifest_branch, "manifest_branch"),
        "-group", _validate_ref(group, "group"),
        "-verbose",
    ]


def build_command(name: str, *, vehicle: str = "XP5",
                  region: str = "sh") -> list[str]:
    """upload_binary.py 编包命令（对齐 guide 第五步）。

    以 list 形式构造避免 shell 注入；车型 / 区域参数白名单校验后注入。
    分支切换不在此处，由 :func:`checkout_command` 负责。
    注：upload_binary.py 的 argparse 不支持 ``--eea``，故不下发该参数。
    """
    return [
        "./scripts/upload_binary.py", "--cn", "--foundation_model", "--enable_simworld",
        "-v", _validate_ref(vehicle, "vehicle"),
        "-f",
        "--build_region", _validate_ref(region, "build_region"),
        "-n", name,
    ]


def parse_binary_id(stdout: str) -> str:
    m = _BINARY_ID_RE.search(stdout)
    if not m:
        raise RuntimeError("cannot parse binary_id from upload_binary.py output")
    return m.group(1)
