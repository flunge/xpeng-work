import hashlib
import hmac
import json
import os
import time

import requests

from urllib.parse import urlparse

ACCOUNT = os.getenv("CLOUDSIM_ACCOUNT", "cloudsim-engine@xiaopeng.com")

# 通过环境变量提供密钥，见 skills/cloudsim-cces-job-report/.env.example
_SECRET_ENV_BY_DOMAIN = {
    "cloudsim.xiaopeng.link": "CLOUDSIM_SECRET_CLOUDSIM_XIAOPENG_LINK",
    "cloudsim-dev.xiaopeng.link": "CLOUDSIM_SECRET_CLOUDSIM_DEV_XIAOPENG_LINK",
    "wl-cloudsim-dev.xiaopeng.link": "CLOUDSIM_SECRET_WL_CLOUDSIM_DEV_XIAOPENG_LINK",
    "cloudsim-staging.xiaopeng.link": "CLOUDSIM_SECRET_CLOUDSIM_STAGING_XIAOPENG_LINK",
}


def _secret_for_domain(domain: str) -> str:
    env_key = _SECRET_ENV_BY_DOMAIN.get(domain)
    if not env_key:
        raise RuntimeError("No secret env mapping for domain: " + domain)
    secret = os.getenv(env_key)
    if not secret:
        raise RuntimeError(f"Missing env {env_key} for CloudSim domain {domain}")
    return secret


def cloudsim_request(url, data):
    domain = urlparse(url).netloc
    secret = _secret_for_domain(domain)
    app_key = "simulation-auth"
    version = "1.0"
    sign_message = "/".join([app_key, version, ACCOUNT, str(int(time.time() * 1000))])
    sign = generate_hmac_sha256_signature(secret, sign_message)

    headers = {
        "X-Sign": sign_message + "/" + sign,
    }
    rsp = requests.post(url, data=data, headers=headers)

    return json.loads(rsp.text)


def cces_get_ids_by_filter(
    job_ids,
    job_type=14,
    model_type="default",
    is_exclude_trend_summary_data="1",
    base="https://cloudsim.xiaopeng.link",
):
    """
    POST /simulation/cces/get_ids_by_filter/ — 与前端表单一致：
    job_ids（JSON 数组字符串）、job_type、model_type、is_exclude_trend_summary_data。
    其中 job_ids 一般为界面上的 scenario / 列表 id（与 get_job_overview 的 CCES _id 不同）。
    """
    url = base.rstrip("/") + "/simulation/cces/get_ids_by_filter/"
    ids = [int(x) for x in job_ids]
    payload = {
        "job_ids": json.dumps(ids, separators=(",", ":")),
        "job_type": str(job_type),
        "model_type": str(model_type),
        "is_exclude_trend_summary_data": str(is_exclude_trend_summary_data),
    }
    return cloudsim_request(url, payload)


def cces_get_ids_by_filter_from_filter_json(job_type, filter_obj, base="https://cloudsim.xiaopeng.link"):
    """POST /simulation/cces/get_ids_by_filter/ — 旧版：仅 form 字段 job_type + filter(JSON 字符串)。"""
    url = base.rstrip("/") + "/simulation/cces/get_ids_by_filter/"
    payload = {
        "job_type": str(job_type),
        "filter": json.dumps(filter_obj, separators=(",", ":")),
    }
    return cloudsim_request(url, payload)


def cces_get_job_overview(job_ids, base="https://cloudsim.xiaopeng.link"):
    """POST /simulation/cces/get_job_overview/ — form: ids(JSON array string of CCES job ids)."""
    url = base.rstrip("/") + "/simulation/cces/get_job_overview/"
    ids = [int(x) for x in job_ids]
    payload = {"ids": json.dumps(ids, separators=(",", ":"))}
    return cloudsim_request(url, payload)


def cces_report_from_filter(job_type, filter_obj, base="https://cloudsim.xiaopeng.link"):
    """兼容旧名，等价于 cces_report_from_filter_json。"""
    return cces_report_from_filter_json(job_type, filter_obj, base=base)


def cces_report_from_filter_json(job_type, filter_obj, base="https://cloudsim.xiaopeng.link"):
    """filter JSON 旧路径 → get_ids_by_filter_from_filter_json → get_job_overview。"""
    resolved = cces_get_ids_by_filter_from_filter_json(job_type, filter_obj, base=base)
    if resolved.get("result") != "success":
        return resolved
    ids = resolved.get("data") or []
    if not ids:
        return {
            "result": "error",
            "msg": "get_ids_by_filter returned empty data; check filter vs frontend",
            "get_ids_by_filter_response": resolved,
        }
    return cces_get_job_overview(ids, base=base)


def cces_report_from_job_ids(
    job_ids,
    job_type=14,
    model_type="default",
    is_exclude_trend_summary_data="1",
    base="https://cloudsim.xiaopeng.link",
):
    """
    前端同款 job_ids + job_type + model_type + is_exclude_trend_summary_data
    → get_ids_by_filter → get_job_overview。
    """
    resolved = cces_get_ids_by_filter(
        job_ids,
        job_type=job_type,
        model_type=model_type,
        is_exclude_trend_summary_data=is_exclude_trend_summary_data,
        base=base,
    )
    if resolved.get("result") != "success":
        return resolved
    ids = resolved.get("data") or []
    if not ids:
        return {
            "result": "error",
            "msg": "get_ids_by_filter returned empty data; check job_ids / job_type / model_type",
            "get_ids_by_filter_response": resolved,
        }
    return cces_get_job_overview(ids, base=base)


def cces_report_from_selected_job_ids(
    selected_job_ids,
    job_type=14,
    model_type="default",
    is_exclude_trend_summary_data="1",
    base="https://cloudsim.xiaopeng.link",
):
    """兼容旧名：等价于 cces_report_from_job_ids（不再使用 filter JSON）。"""
    return cces_report_from_job_ids(
        selected_job_ids,
        job_type=job_type,
        model_type=model_type,
        is_exclude_trend_summary_data=is_exclude_trend_summary_data,
        base=base,
    )


def cces_report_long_mileage(job_ids, **kwargs):
    """长里程 CCES 概览：`get_ids_by_filter` 常用 `job_type=1`。"""
    kw = dict(kwargs)
    kw.setdefault("job_type", 1)
    return cces_report_from_job_ids(job_ids, **kw)


def cces_report_scenario_eval(job_ids, **kwargs):
    """场景集 / 专项评测类 CCES 概览（帧 Fail 比例等）：`get_ids_by_filter` 常用 `job_type=4`。"""
    kw = dict(kwargs)
    kw.setdefault("job_type", 4)
    return cces_report_from_job_ids(job_ids, **kw)


def generate_hmac_sha256_signature(secret, message):
    hmac_key = bytes(secret, "utf-8")
    hmac_message = bytes(message, "utf-8")
    signature = hmac.new(hmac_key, hmac_message, hashlib.sha256).hexdigest()
    return signature
