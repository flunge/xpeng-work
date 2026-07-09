import pytest
from tse.integrations.bench import (build_command, checkout_command,
                                    pipeline_checkout_command, parse_binary_id,
                                    docker_exec_command, make_executor,
                                    NestedExecutor, LocalExecutor)
from tse.integrations.sim_cloud import classify_terminal, _parse_job_status, _coerce_binary_id
from tse.request.builder import build_request
from tse.errors import NonRetryableBuildError, RequestValidationError


def test_build_command_is_list_and_contains_name():
    cmd = build_command("myname")
    assert isinstance(cmd, list)
    assert "-n" in cmd and "myname" in cmd
    # 默认车型/区域注入正确
    assert cmd[cmd.index("-v") + 1] == "XP5"
    assert cmd[cmd.index("--build_region") + 1] == "sh"
    # upload_binary.py 不支持 --eea，不应下发
    assert "--eea" not in cmd


def test_build_command_params_overridable():
    cmd = build_command("n", vehicle="XP6", region="gz")
    assert cmd[cmd.index("-v") + 1] == "XP6"
    assert cmd[cmd.index("--build_region") + 1] == "gz"


def test_build_command_rejects_param_injection():
    with pytest.raises(NonRetryableBuildError):
        build_command("n", vehicle="XP5; rm -rf /")
    with pytest.raises(NonRetryableBuildError):
        build_command("n", region="$(whoami)")


def test_checkout_command_ok():
    assert checkout_command("dev_difix_zf_0612") == ["git", "checkout", "dev_difix_zf_0612"]


def test_checkout_command_rejects_injection():
    with pytest.raises(NonRetryableBuildError):
        checkout_command("branch; rm -rf /")
    with pytest.raises(NonRetryableBuildError):
        checkout_command("$(whoami)")
    with pytest.raises(NonRetryableBuildError):
        checkout_command("")


def test_pipeline_checkout_command_ok():
    cmd = pipeline_checkout_command("dev_xngp_xp5", "simulation")
    assert cmd == ["pipeline", "-checkout_repo", "-manifest_branch", "dev_xngp_xp5",
                   "-group", "simulation", "-verbose"]


def test_pipeline_checkout_command_rejects_injection():
    with pytest.raises(NonRetryableBuildError):
        pipeline_checkout_command("dev_xngp_xp5; echo x", "simulation")
    with pytest.raises(NonRetryableBuildError):
        pipeline_checkout_command("dev_xngp_xp5", "simulation && rm -rf /")


def test_docker_exec_command_wraps_into_container():
    full = docker_exec_command("xp5_simulator",
                               ["./scripts/upload_binary.py", "-n", "myname"],
                               "/sandbox/simulation/simulation")
    # 非交互（不带 -it），bash -lc 加载登录环境
    assert full[:5] == ["docker", "exec", "xp5_simulator", "bash", "-lc"]
    inner = full[5]
    assert inner.startswith("cd /sandbox/simulation/simulation && ")
    assert "./scripts/upload_binary.py" in inner and "myname" in inner


def test_docker_exec_command_quotes_cwd_and_args():
    # 含特殊字符的 cwd / 参数需被 shlex.quote 转义，防注入
    full = docker_exec_command("c", ["echo", "a; rm -rf /"], "/tmp/x y")
    inner = full[5]
    assert "'a; rm -rf /'" in inner       # 参数被整体引用
    assert "'/tmp/x y'" in inner          # 带空格的 cwd 被引用


def test_make_executor_selects_by_mode():
    from tse.config import Settings
    assert isinstance(make_executor(Settings(build_mode="local")), LocalExecutor)
    nested = make_executor(Settings(build_mode="nested",
                                    build_vm_ssh_host="xpeng@192.168.122.180",
                                    build_container="xp5_simulator"))
    assert isinstance(nested, NestedExecutor)
    # 默认即 nested（5080 三层拓扑）
    assert isinstance(make_executor(Settings()), NestedExecutor)


def test_make_executor_nested_requires_vm_host_and_container():
    from tse.config import Settings
    with pytest.raises(AssertionError):
        make_executor(Settings(build_mode="nested", build_vm_ssh_host="",
                               build_container="xp5_simulator"))
    with pytest.raises(AssertionError):
        make_executor(Settings(build_mode="nested",
                               build_vm_ssh_host="xpeng@192.168.122.180",
                               build_container=""))


def test_nested_executor_routes_vm_and_container(monkeypatch):
    # 不真正 SSH：捕获下发到虚拟机的远程命令串，验证分层包装正确
    ex = NestedExecutor("xpeng@192.168.122.180", "xp5_simulator")
    sent = []
    monkeypatch.setattr(ex, "_ssh_run", lambda remote: sent.append(remote) or "")

    # 虚拟机层（git checkout）：直接 cd + 命令，不经 docker
    ex.run_vm(["git", "checkout", "dev_zf_nvfixer"], "/mnt/vm/simulation/simworld")
    assert sent[-1] == "cd /mnt/vm/simulation/simworld && git checkout dev_zf_nvfixer"
    assert "docker" not in sent[-1]

    # 容器层（pipeline/编包）：虚拟机上再 docker exec 进容器
    ex.run_container(["pipeline", "-checkout_repo"], "/sandbox/simulation/simulation")
    remote = sent[-1]
    assert remote.startswith("docker exec xp5_simulator bash -lc ")
    assert "cd /sandbox/simulation/simulation && pipeline -checkout_repo" in remote


def test_parse_binary_id_ok():
    assert parse_binary_id("some log\nbinary_id: ABC_123\nmore") == "ABC_123"
    assert parse_binary_id("binary id=xyz-9") == "xyz-9"


def test_parse_binary_id_real_upload_binary_output():
    # upload_binary.py push_to_db() 的真实打印格式
    stdout = ("Building latest binary\n"
              "Uploading 100% \n"
              "Successfully inserted into database\n"
              "The binary you just uploaded is: ID 1755026\n")
    assert parse_binary_id(stdout) == "1755026"


def test_parse_binary_id_missing_raises():
    with pytest.raises(RuntimeError):
        parse_binary_id("no id here")


def test_coerce_binary_id():
    # 编包输出（字符串/含空白/整数）转 stage1_binary_id
    assert _coerce_binary_id("1755026") == 1755026
    assert _coerce_binary_id(1755026) == 1755026
    assert _coerce_binary_id(" 1755026 ") == 1755026
    with pytest.raises(RuntimeError):
        _coerce_binary_id("ABC_123")


def test_classify_terminal_case_insensitive():
    assert classify_terminal("SUCCESS") == "ok"
    assert classify_terminal("success") == "ok"
    assert classify_terminal(" Completed ") == "ok"
    assert classify_terminal("FAILED") == "fail"
    assert classify_terminal("error") == "fail"
    assert classify_terminal("RUNNING") is None
    assert classify_terminal("") is None


def test_classify_terminal_real_lowercase_vocab():
    # 平台真实返回为小写状态词（已抓真实响应校准）
    assert classify_terminal("finished") == "ok"
    assert classify_terminal("failed") == "fail"
    assert classify_terminal("errored") == "fail"
    assert classify_terminal("canceled") == "fail"
    assert classify_terminal("running") is None
    assert classify_terminal("pending") is None


def test_parse_job_status_real_envelope_ok():
    # 真实成功信封：result=ok，data 为单条 job 记录 dict，status 小写
    payload = {"result": "ok", "data": {"e2e_job_id": 159064, "status": "finished"}}
    assert _parse_job_status(payload, 159064) == "finished"


def test_parse_job_status_real_envelope_error_raises():
    # 真实失败信封：result=error，data={}，原因在 msg
    payload = {"result": "error", "data": {},
               "msg": "no e2e job found by e2e_job_id:11956581"}
    with pytest.raises(RuntimeError, match="no e2e job found"):
        _parse_job_status(payload, 11956581)


def test_parse_job_status_wrapped_paginated():
    payload = {"code": 0, "msg": "ok",
               "data": {"total": 1, "list": [{"e2e_job_id": 159064, "status": "RUNNING"}]}}
    assert _parse_job_status(payload, 159064) == "RUNNING"


def test_parse_job_status_matches_by_id():
    payload = {"data": {"list": [
        {"e2e_job_id": 1, "status": "FAILED"},
        {"e2e_job_id": 159064, "status": "SUCCESS"},
    ]}}
    assert _parse_job_status(payload, 159064) == "SUCCESS"


def test_parse_job_status_bare_record():
    assert _parse_job_status({"e2e_job_id": 159064, "job_status": "COMPLETED"}, 159064) == "COMPLETED"


def test_parse_job_status_not_found_raises():
    with pytest.raises(RuntimeError):
        _parse_job_status({"data": {"list": []}}, 159064)


def test_build_request_whitelist():
    # 不连接 Temporal，直接测纯构建/校验逻辑
    ok = build_request("b", "/c", {"use_difix": True})
    assert ok.branch == "b"
    assert ok.switches == {"use_difix": True}
    assert ok.experiment_id  # 自动生成 uuid

    with pytest.raises(RequestValidationError):
        build_request("", "/c", {})

    with pytest.raises(RequestValidationError):
        build_request("b", "/c", {"unknown_switch": True})


def test_build_request_sets_variable_inputs():
    # 可变项：template_e2e_job_id（rerun job_id）与 job_name 透传到请求
    req = build_request("b", "/c", {"use_difix": True},
                        template_e2e_job_id=163877, job_name="myjob")
    assert req.template_e2e_job_id == 163877
    assert req.job_name == "myjob"
    # 固定项不在请求里设置 → 提交时由配置兜底
    assert req.model_id is None
    assert req.stage2_binary_id is None
    assert req.stage1_binary_id is None
    # job_name 空串归一为 None（走默认生成）
    assert build_request("b", "/c", {}, template_e2e_job_id=1, job_name="").job_name is None


def test_build_request_sets_build_branches():
    # 编包多仓切分支：simulation(branch) / simworld / manifest 透传到请求
    req = build_request("dev_sim", "/c", {}, template_e2e_job_id=1,
                        simworld_branch="dev_zf_nvfixer", manifest_branch="dev_xngp_xp5")
    assert req.branch == "dev_sim"
    assert req.simworld_branch == "dev_zf_nvfixer"
    assert req.manifest_branch == "dev_xngp_xp5"
    # 空串归一为 None（缺省：simworld 不切换，manifest 走配置）
    base = build_request("dev_sim", "/c", {}, template_e2e_job_id=1,
                         simworld_branch="", manifest_branch="")
    assert base.simworld_branch is None and base.manifest_branch is None


def test_build_key_sensitive_to_build_branches():
    # 不同分支组合 → 不同 build_key（避免错误复用编包产物）
    a = build_request("dev_sim", "/c", {}, template_e2e_job_id=1,
                      simworld_branch="sw_a", manifest_branch="m")
    b = build_request("dev_sim", "/c", {}, template_e2e_job_id=1,
                      simworld_branch="sw_b", manifest_branch="m")
    assert a.build_key() != b.build_key()


def test_submit_payload_variable_vs_fixed(monkeypatch):
    """提交 payload：4 个可变项来自输入/编包，其余（stage2/model_id 等）走固定配置。"""
    import json as _json
    from tse.config import Settings
    from tse.integrations.sim_cloud import SimCloudClient
    from tse.models.domain import ExperimentRequest, SubmitArgs

    client = SimCloudClient(Settings(sim_x_account="tester@xiaopeng.com"))

    captured = {}

    class _Resp:
        def raise_for_status(self):
            return self

        def json(self):
            return {"result": "ok", "data": {"e2e_job_id": 999}}

    def fake_post(path, content=None):
        captured["path"] = path
        captured["body"] = _json.loads(content)
        return _Resp()

    monkeypatch.setattr(client._c, "post", fake_post)

    req = ExperimentRequest(branch="dev_x", ckpt_path="/c", switches={"use_difix": True},
                            experiment_id="exp12345", template_e2e_job_id=163877,
                            job_name="rerun_difix_0616")
    out = client.submit(SubmitArgs(binary_id="1755026", req=req))

    assert out == "999"
    body = captured["body"]
    # —— 可变项 ——
    assert body["e2e_job_id"] == 163877          # rerun 模板 job_id
    assert body["job_name"] == "rerun_difix_0616"
    assert body["stage1_binary_id"] == 1755026   # 编包输出
    fc = _json.loads(body["fuyao_config"])
    assert fc["manual_sim_configuration"] == "simworld@use_difix:1"  # 全局开关
    # —— 固定项（配置兜底）——
    assert body["stage2_binary_id"] == 1692170
    assert body["model_id"] == 17098


def test_submit_requires_rerun_job_id(monkeypatch):
    from tse.config import Settings
    from tse.integrations.sim_cloud import SimCloudClient
    from tse.models.domain import ExperimentRequest, SubmitArgs

    client = SimCloudClient(Settings(sim_x_account="t@x.com"))
    req = ExperimentRequest(branch="b", ckpt_path="/c", switches={},
                            experiment_id="e1")  # 无 template_e2e_job_id
    with pytest.raises(RuntimeError, match="template_e2e_job_id"):
        client.submit(SubmitArgs(binary_id="1755026", req=req))
