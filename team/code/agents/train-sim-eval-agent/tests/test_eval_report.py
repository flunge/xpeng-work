"""评测 + 报告链路测试（无 LLM）：

- simworld_tools 两个封装函数：注入凭据 / 参数化调用 / 产物路径。
- evaluate.build_artifacts：候选 job 合并、EvalArtifacts 装配与文件顺序。
- report.generate_and_send_report：幂等 + 通过飞书发送产物文件（不经 LLM）。
- feishu 工具函数：图片/文件类型判定。

为不依赖 pandas/matplotlib/requests 等重依赖与真实网络，统一以 monkeypatch
替换 simworld 工具模块的加载与外部客户端。
"""
import json
import types

import pytest

from tse.config import Settings
from tse.integrations import simworld_tools
from tse.integrations.feishu import _file_type, _is_image
from tse.models.domain import EvalArtifacts, ExperimentRequest, ReportArgs


# ———————————————————— simworld_tools ————————————————————
def _fake_render_modules(captured):
    log_mod = types.SimpleNamespace()

    def download_all_job_data(jobs, log_list, token, user,
                              target_scenario_ids=None, max_scenario_numbers=None,
                              output_root=None):
        captured["render_download"] = dict(
            jobs=jobs, log_list=log_list, target_scenario_ids=target_scenario_ids,
            max_scenario_numbers=max_scenario_numbers, output_root=output_root,
            token=token, user=user)

    log_mod.download_all_job_data = download_all_job_data

    time_mod = types.SimpleNamespace()

    def analyze_folders(root_dir, log_glob):
        captured["analyze"] = dict(root_dir=str(root_dir), log_glob=log_glob)
        return ([{"folder": "candidate"}], [{"scenario_id": "1", "folder": "candidate"}])

    def write_csv(rows, path, fieldnames):
        captured.setdefault("write_csv", []).append(str(path))

    def build_detail_pivot_rows(detail_rows):
        return ([{"scenario_id": "1"}], ["scenario_id"])

    time_mod.analyze_folders = analyze_folders
    time_mod.write_csv = write_csv
    time_mod.build_detail_pivot_rows = build_detail_pivot_rows
    return {"log_downloader": log_mod, "time_analyze": time_mod}


def test_run_render_time_analysis_injects_creds_and_writes_csv(monkeypatch, tmp_path):
    captured = {}
    mods = _fake_render_modules(captured)
    monkeypatch.setattr(simworld_tools, "_load_module",
                        lambda d, name: mods[name])

    s = Settings(sim_x_token="tok", sim_x_account="me@x.com",
                 eval_render_log_file="3dgs_server1_out.log",
                 eval_render_max_scenarios=42)
    out = simworld_tools.run_render_time_analysis(
        s, {"candidate": [159064]}, tmp_path)

    dl = captured["render_download"]
    assert dl["jobs"] == {"candidate": [159064]}
    assert dl["log_list"] == ["3dgs_server1_out.log"]
    assert dl["max_scenario_numbers"] == 42
    assert dl["token"] == "tok" and dl["user"] == "me@x.com"   # 凭据以参数传入
    # 汇总 + 明细两张 CSV
    assert out["summary_csv"].endswith("render_time_summary.csv")
    assert out["detail_csv"].endswith("render_time_detail.csv")
    assert len(captured["write_csv"]) == 2


def test_run_fm_eval_passes_jobs_creds_and_calls_run_eval(monkeypatch, tmp_path):
    captured = {}
    etd = types.SimpleNamespace()

    def download_all_task_data(jobs, token, user, output_root=None):
        captured.update(download_called=True, jobs=jobs, token=token, user=user,
                        output_root=output_root)

    etd.download_all_task_data = download_all_task_data

    em = types.SimpleNamespace()

    def run_eval(root_dir, input_root, output_csv, output_png, models, **kw):
        captured["run_eval"] = dict(root_dir=str(root_dir), models=models,
                                    output_csv=str(output_csv), output_png=str(output_png))

    em.run_eval = run_eval
    mods = {"eval_tasks_download": etd, "eval_main": em}
    monkeypatch.setattr(simworld_tools, "_load_module", lambda d, name: mods[name])

    s = Settings(sim_x_token="tok", sim_x_account="me@x.com")
    jobs = {"3dgs_3w": [133785], "origin_png": [134316], "candidate": [159064]}
    out = simworld_tools.run_fm_eval(s, jobs, tmp_path / "fm", list(jobs))

    assert captured["download_called"] is True
    assert captured["output_root"] == str(tmp_path / "fm")
    assert captured["jobs"] == jobs
    assert captured["token"] == "tok" and captured["user"] == "me@x.com"
    assert set(captured["run_eval"]["models"]) == set(jobs)
    assert out["fm_png"].endswith("fm_clip_error_selected.png")
    assert out["fm_csv"].endswith("fm_clip_error_selected.csv")


# ———————————————————— evaluate ————————————————————
def test_build_artifacts_merges_candidate_and_orders_files(monkeypatch, tmp_path):
    from tse.activities import evaluate as ev

    seen = {}

    def fake_render(s, jobs, output_dir):
        seen["render_jobs"] = jobs
        return {"summary_csv": str(output_dir / "render_time_summary.csv"),
                "detail_csv": str(output_dir / "render_time_detail.csv")}

    def fake_fm(s, jobs, eval_root, models):
        seen["fm_jobs"] = jobs
        seen["fm_models"] = models
        return {"fm_png": str(eval_root / "fm.png"), "fm_csv": str(eval_root / "fm.csv")}

    monkeypatch.setattr(ev.simworld_tools, "run_render_time_analysis", fake_render)
    monkeypatch.setattr(ev.simworld_tools, "run_fm_eval", fake_fm)

    s = Settings(eval_output_root=str(tmp_path))
    # 候选 job：job_name=difix_v6, e2e_job_id=159064（== rerun-job-id）；基线仅来自 CLI
    art = ev.build_artifacts(s, "159064", "difix_v6",
                             {"3dgs_3w": [133785], "origin_png": [134316]})

    # 候选 job 以 job_name 为键合并进基线映射，渲染耗时与 FM 评测复用同一份 jobs
    expected_jobs = {"3dgs_3w": [133785], "origin_png": [134316], "difix_v6": [159064]}
    assert seen["render_jobs"] == expected_jobs
    assert seen["fm_jobs"] == expected_jobs
    # 产物装配：FM 图片在文件列表首位（便于飞书预览）
    assert isinstance(art, EvalArtifacts)
    assert art.fm_eval_image.endswith("fm.png")
    assert art.files[0].endswith("fm.png")
    assert any(f.endswith("render_time_summary.csv") for f in art.files)


def test_build_artifacts_rejects_non_integer_task_id(monkeypatch, tmp_path):
    from tse.activities import evaluate as ev
    s = Settings(eval_output_root=str(tmp_path))
    with pytest.raises(RuntimeError, match="非整数"):
        ev.build_artifacts(s, "not-an-int", "cand", {})


def test_build_artifacts_baselines_only_from_cli(monkeypatch, tmp_path):
    """基线唯一来源是 CLI 入参：不传基线则 jobs 只含候选。"""
    from tse.activities import evaluate as ev

    seen = {}
    monkeypatch.setattr(ev.simworld_tools, "run_render_time_analysis",
                        lambda s, jobs, output_dir: seen.update(render_jobs=jobs) or
                        {"summary_csv": "a.csv", "detail_csv": "b.csv"})
    monkeypatch.setattr(ev.simworld_tools, "run_fm_eval",
                        lambda s, jobs, eval_root, models: seen.update(fm_jobs=jobs) or
                        {"fm_png": "fm.png", "fm_csv": "fm.csv"})

    s = Settings(eval_output_root=str(tmp_path))
    # 传入基线：候选 + 基线
    ev.build_artifacts(s, "159064", "cand", {"origin_png": [134316]})
    assert seen["render_jobs"] == {"origin_png": [134316], "cand": [159064]}
    assert seen["fm_jobs"] == {"origin_png": [134316], "cand": [159064]}

    # 不传基线：jobs 只含候选
    ev.build_artifacts(s, "777", "cand", {})
    assert seen["render_jobs"] == {"cand": [777]}


# ———————————————————— report ————————————————————
class _FakeRepo:
    def __init__(self, existing=None):
        self.existing = existing
        self.upserts = []

    def get(self, eid):
        return self.existing

    def upsert_status(self, eid, status, **fields):
        self.upserts.append((eid, status, fields))


@pytest.mark.asyncio
async def test_report_sends_files_via_feishu_no_llm(monkeypatch):
    from tse.activities import report as rep

    repo = _FakeRepo(existing=None)
    monkeypatch.setattr(rep, "ExperimentRepo", lambda db_path: repo)

    sent = {}

    class _FakeFeishu:
        def __init__(self, s):
            pass

        def send_report_files(self, title, files, idem_key=None):
            sent["title"] = title
            sent["files"] = files
            return "msg-1", "feishu:msg:msg-1"

    monkeypatch.setattr(rep, "FeishuClient", _FakeFeishu)

    req = ExperimentRequest(branch="dev_x", ckpt_path="/c", switches={},
                            experiment_id="exp-abcdef12")
    art = EvalArtifacts(output_dir="/tmp/e", fm_eval_image="/tmp/e/fm.png",
                        files=["/tmp/e/fm.png", "/tmp/e/render.csv"])
    url = await rep.generate_and_send_report(ReportArgs(req=req, artifacts=art))

    assert url == "feishu:msg:msg-1"
    assert sent["files"] == ["/tmp/e/fm.png", "/tmp/e/render.csv"]
    assert "dev_x" in sent["title"]
    # 写回 report_url + feishu_msg_id
    assert repo.upserts and repo.upserts[0][2]["feishu_msg_id"] == "msg-1"


@pytest.mark.asyncio
async def test_report_idempotent_skip_when_already_sent(monkeypatch):
    from tse.activities import report as rep

    repo = _FakeRepo(existing={"status": "REPORTING",
                               "report_url": "feishu:msg:old",
                               "feishu_msg_id": "old"})
    monkeypatch.setattr(rep, "ExperimentRepo", lambda db_path: repo)

    def _boom(s):
        raise AssertionError("已发送应短路，不应再次构造 FeishuClient")

    monkeypatch.setattr(rep, "FeishuClient", _boom)

    req = ExperimentRequest(branch="b", ckpt_path="/c", switches={}, experiment_id="e1")
    art = EvalArtifacts(output_dir="/tmp/e", files=[])
    url = await rep.generate_and_send_report(ReportArgs(req=req, artifacts=art))
    assert url == "feishu:msg:old"
    assert repo.upserts == []   # 未二次写回


# ———————————————————— feishu 工具 ————————————————————
def test_feishu_file_type_and_image_detection():
    assert _is_image("/x/fm_clip_error.png") is True
    assert _is_image("/x/render_time_summary.csv") is False
    assert _file_type("/x/render_time_summary.csv") == "stream"
    assert _file_type("/x/report.pdf") == "pdf"
    assert _file_type("/x/data.xlsx") == "xls"


# ———————————————————— feishu open_id 解析与缓存 ————————————————————
def test_resolve_open_id_by_email_calls_token_then_batch_get_id(monkeypatch):
    from tse.integrations import feishu

    calls = []

    def fake_post(url, *, headers=None, json_body=None, timeout=10):
        calls.append((url, headers, json_body))
        if "tenant_access_token" in url:
            return {"code": 0, "tenant_access_token": "t-abc"}
        # batch_get_id
        assert "user_id_type=open_id" in url
        assert headers["Authorization"] == "Bearer t-abc"
        assert json_body == {"emails": ["zhouf4@xiaopeng.com"]}
        return {"code": 0, "data": {"user_list": [
            {"email": "zhouf4@xiaopeng.com", "user_id": "ou_zhouf4"}]}}

    monkeypatch.setattr(feishu, "_post", fake_post)
    open_id = feishu.resolve_open_id_by_email(
        "https://open.feishu.cn", "cli_x", "secret", "zhouf4@xiaopeng.com")
    assert open_id == "ou_zhouf4"
    assert len(calls) == 2          # 先换 token，再 batch_get_id


def test_resolve_open_id_raises_when_not_found(monkeypatch):
    from tse.integrations import feishu
    monkeypatch.setattr(feishu, "_post", lambda url, **kw: (
        {"code": 0, "tenant_access_token": "t"} if "tenant_access_token" in url
        else {"code": 0, "data": {"user_list": []}}))
    with pytest.raises(RuntimeError, match="open_id"):
        feishu.resolve_open_id_by_email("https://open.feishu.cn", "a", "b",
                                        "missing@xiaopeng.com")


def test_resolve_target_first_run_resolves_then_uses_cache(monkeypatch, tmp_path):
    """首次按邮箱解析并写缓存，后续命中缓存不再请求飞书。"""
    from tse.integrations.feishu import FeishuClient
    from tse.integrations import feishu

    n = {"count": 0}

    def fake_resolve(base_url, app_id, app_secret, email):
        n["count"] += 1
        return "ou_zhouf4"

    monkeypatch.setattr(feishu, "resolve_open_id_by_email", fake_resolve)

    cache = tmp_path / "oid_cache.json"
    s = Settings(feishu_app_id="cli_x", feishu_app_secret="secret",
                 feishu_receive_email="zhouf4@xiaopeng.com", feishu_receive_id="",
                 feishu_open_id_cache=str(cache))

    # 首次：解析 + 写缓存
    rid, rtype = FeishuClient(s)._resolve_target()
    assert (rid, rtype) == ("ou_zhouf4", "open_id")
    assert n["count"] == 1
    assert json.loads(cache.read_text())["zhouf4@xiaopeng.com"] == "ou_zhouf4"

    # 后续：命中缓存，不再调用解析
    rid2, _ = FeishuClient(s)._resolve_target()
    assert rid2 == "ou_zhouf4"
    assert n["count"] == 1


def test_resolve_target_explicit_receive_id_overrides_email(monkeypatch):
    """显式 receive_id 优先，跳过邮箱解析。"""
    from tse.integrations.feishu import FeishuClient
    from tse.integrations import feishu

    def _boom(*a, **k):
        raise AssertionError("显式 receive_id 时不应解析邮箱")

    monkeypatch.setattr(feishu, "resolve_open_id_by_email", _boom)
    s = Settings(feishu_receive_id="oc_group", feishu_receive_id_type="chat_id",
                 feishu_receive_email="zhouf4@xiaopeng.com")
    assert FeishuClient(s)._resolve_target() == ("oc_group", "chat_id")


def test_resolve_target_requires_id_or_email():
    from tse.integrations.feishu import FeishuClient
    with pytest.raises(RuntimeError, match="receive_id 或 receive_email"):
        FeishuClient(Settings(feishu_receive_id="",
                              feishu_receive_email=""))._resolve_target()


# ———————————————————— 工具脚本 CLI（job_name=job_id 解析）————————————————————
@pytest.mark.parametrize("module_name,tools_dir_attr", [
    ("log_downloader", "_render_tools_dir"),
    ("eval_tasks_download", "_eval_tools_dir"),
])
def test_tool_cli_parse_job_args_by_job_name(module_name, tools_dir_attr):
    s = Settings()
    tools_dir = getattr(simworld_tools, tools_dir_attr)(s)
    mod = simworld_tools._load_module(tools_dir, module_name)

    # 以 job_name 为键解析（候选与基线统一为 --job job_name=job_id）
    jobs = mod.parse_job_args(["3dgs_3w=133785", "origin_png=134316", "difix_v6=159064"])
    assert jobs == {"3dgs_3w": [133785], "origin_png": [134316], "difix_v6": [159064]}

    # 同一 job_name 逗号分隔多个 job_id
    assert mod.parse_job_args(["a=1,2,3"]) == {"a": [1, 2, 3]}

    # 已移除 --candidate 相关的 build_jobs
    assert not hasattr(mod, "build_jobs")

    # 非法格式快速报错
    with pytest.raises(ValueError):
        mod.parse_job_args(["badformat"])
    with pytest.raises(ValueError):
        mod.parse_job_args(["a="])


def test_tool_scripts_have_no_hardcoded_credentials():
    """回归：两个下载脚本不应再出现写死的 TOKEN/USER 字面量。"""
    s = Settings()
    for module_name, attr in (("log_downloader", "_render_tools_dir"),
                              ("eval_tasks_download", "_eval_tools_dir")):
        path = f"{getattr(simworld_tools, attr)(s)}/{module_name}.py"
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
        assert "eyJhbGci" not in text          # JWT 头不应出现
        assert "yangxh7@xiaopeng.com" not in text


# ———————————————————— client CLI 基线 job 透传 ————————————————————
def test_baseline_jobs_not_part_of_experiment_request():
    """baseline_jobs 是评测期参数，不应进入 ExperimentRequest / build_request。"""
    import inspect
    from tse.request.builder import build_request

    req = build_request("b", "/c", {}, template_e2e_job_id=1)
    assert not hasattr(req, "baseline_jobs")
    assert "baseline_jobs" not in inspect.signature(build_request).parameters


def test_eval_args_carries_candidate_and_baselines():
    from tse.models.domain import EvalArgs
    a = EvalArgs(sim_task_id="159064", candidate_job_name="difix_v6",
                 baseline_jobs={"3dgs_3w": [133785]})
    assert a.sim_task_id == "159064"
    assert a.candidate_job_name == "difix_v6"
    assert a.baseline_jobs == {"3dgs_3w": [133785]}
    # 基线缺省为空（仅 CLI 提供）
    assert EvalArgs(sim_task_id="1", candidate_job_name="c").baseline_jobs == {}


def test_cli_parse_baseline_jobs():
    from tse.cli.main import _parse_baseline_jobs
    import typer

    # --baseline 可重复（每次一个 job_name=job_id）
    assert _parse_baseline_jobs(["3dgs_3w=133785", "origin_png=134316"]) == {
        "3dgs_3w": [133785], "origin_png": [134316]}
    # 同一 job_name 逗号分隔多个 job_id
    assert _parse_baseline_jobs(["a=1,2"]) == {"a": [1, 2]}
    assert _parse_baseline_jobs(None) == {}
    for bad in (["nojobsep"], ["a="], ["a=x"]):
        with pytest.raises(typer.BadParameter):
            _parse_baseline_jobs(bad)
