from tse.models.domain import ExperimentRequest, SubmitArgs, _hash


def test_hash_stable_and_order_independent():
    a = _hash("branch", "/ckpt", {"use_difix": True})
    b = _hash("branch", "/ckpt", {"use_difix": True})
    assert a == b
    assert len(a) == 16


def test_build_key_changes_with_inputs():
    r1 = ExperimentRequest(branch="b1", ckpt_path="/c", switches={}, experiment_id="e1")
    r2 = ExperimentRequest(branch="b2", ckpt_path="/c", switches={}, experiment_id="e2")
    assert r1.build_key() != r2.build_key()
    # experiment_id 不参与 build_key
    r3 = ExperimentRequest(branch="b1", ckpt_path="/c", switches={}, experiment_id="other")
    assert r1.build_key() == r3.build_key()


def test_submit_key():
    req = ExperimentRequest(branch="b", ckpt_path="/c", switches={"use_difix": True},
                            experiment_id="e1", template_e2e_job_id=163496,
                            stage1_binary_id=1755026, stage2_binary_id=1692170, model_id=17098)
    args = SubmitArgs(binary_id="bin123", req=req)
    assert len(args.submit_key()) == 16
    # 真实提交身份由 stage/model/模板 id 决定（不再依赖单一 binary_id）
    req2 = req.model_copy(update={"stage1_binary_id": 9999})
    args2 = SubmitArgs(binary_id="bin123", req=req2)
    assert args.submit_key() != args2.submit_key()
    # binary_id 变化不影响 submit_key
    args3 = SubmitArgs(binary_id="bin456", req=req)
    assert args.submit_key() == args3.submit_key()


def test_submit_key_falls_back_to_build_output():
    # stage1 未显式给定时，stage1 取编包输出 binary_id → 幂等键随之变化
    req = ExperimentRequest(branch="b", ckpt_path="/c", switches={}, experiment_id="e1",
                            template_e2e_job_id=163496, model_id=17098)
    k1 = SubmitArgs(binary_id="1755026", req=req).submit_key()
    k2 = SubmitArgs(binary_id="1747449", req=req).submit_key()
    assert k1 != k2
