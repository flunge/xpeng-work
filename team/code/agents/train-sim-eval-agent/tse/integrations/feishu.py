"""飞书发送适配层（自建应用机器人）。

报告即「渲染耗时 CSV + FM 轨迹评测图片」本身，不再经 LLM 摘要：
本客户端用自建应用的 app_id/app_secret 把这些产物上传到飞书并发给接收人
（图片走图片消息，CSV 等走文件消息）。

接收人解析：
- 若显式配置了 ``feishu_receive_id``，直接使用（手动覆盖，跳过解析）；
- 否则用 ``feishu_receive_email`` 按邮箱解析 open_id —— **首次运行**调
  ``contact/v3/users/batch_get_id`` 解析并写入缓存文件
  （``feishu_open_id_cache``），**后续运行直接读缓存**，不再请求飞书。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from tse.config import Settings

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
# 飞书文件上传 file_type 取值（其余统一用 stream）。
_FILE_TYPE_BY_SUFFIX = {
    ".pdf": "pdf", ".doc": "doc", ".docx": "doc", ".xls": "xls", ".xlsx": "xls",
    ".ppt": "ppt", ".pptx": "ppt", ".mp4": "mp4", ".opus": "opus",
}


def _is_image(path: str) -> bool:
    return Path(path).suffix.lower() in _IMAGE_SUFFIXES


def _file_type(path: str) -> str:
    return _FILE_TYPE_BY_SUFFIX.get(Path(path).suffix.lower(), "stream")


# ———————————————————— open_id 解析（自建应用，按邮箱）————————————————————
def _post(url: str, *, headers: dict | None = None, json_body: dict | None = None,
          timeout: int = 10) -> dict:
    """统一的 HTTP POST（封装成可在测试中替换的接缝）。"""
    import requests  # 延迟导入：导入本模块不强依赖 requests

    resp = requests.post(url, headers=headers, json=json_body, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _tenant_access_token(base_url: str, app_id: str, app_secret: str) -> str:
    """用自建应用凭据换 tenant_access_token（机器人身份）。"""
    data = _post(
        f"{base_url}/open-apis/auth/v3/tenant_access_token/internal",
        json_body={"app_id": app_id, "app_secret": app_secret})
    if data.get("code", 0) != 0 or not data.get("tenant_access_token"):
        raise RuntimeError(
            f"获取 tenant_access_token 失败: code={data.get('code')} "
            f"msg={data.get('msg')}")
    return data["tenant_access_token"]


def resolve_open_id_by_email(base_url: str, app_id: str, app_secret: str,
                             email: str) -> str:
    """按邮箱解析 open_id（需应用开通 contact:user.id:readonly，且该用户在可用范围内）。"""
    token = _tenant_access_token(base_url, app_id, app_secret)
    data = _post(
        f"{base_url}/open-apis/contact/v3/users/batch_get_id?user_id_type=open_id",
        headers={"Authorization": f"Bearer {token}"},
        json_body={"emails": [email]})
    if data.get("code", 0) != 0:
        raise RuntimeError(
            f"按邮箱解析 open_id 失败: code={data.get('code')} msg={data.get('msg')}")
    user_list = (data.get("data") or {}).get("user_list") or []
    for item in user_list:
        # user_id_type=open_id 时，user_id 字段即为 open_id
        open_id = item.get("user_id")
        if item.get("email") == email and open_id:
            return open_id
    # 兜底：列表非空但未严格匹配 email 时取首个带 user_id 的
    for item in user_list:
        if item.get("user_id"):
            return item["user_id"]
    raise RuntimeError(
        f"未能解析邮箱 {email} 的 open_id（用户不在应用可用范围内或邮箱不存在）")


def _load_open_id_cache(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def _save_open_id_cache(path: str, cache: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


class FeishuClient:
    def __init__(self, s: Settings):
        self.app_id, self.app_secret = s.feishu_app_id, s.feishu_app_secret
        self.base_url = s.feishu_base_url.rstrip("/")
        self.receive_id = s.feishu_receive_id
        self.receive_id_type = s.feishu_receive_id_type
        self.receive_email = s.feishu_receive_email
        self.cache_path = s.feishu_open_id_cache

    def _client(self):
        # 延迟导入 lark-oapi：导入本模块不强依赖 SDK，便于无 SDK 环境测试。
        import lark_oapi as lark

        if not (self.app_id and self.app_secret):
            raise RuntimeError("飞书未配置 app_id/app_secret，无法发送报告")
        if not self.receive_id:
            raise RuntimeError("飞书未配置 receive_id（报告接收人/群）")
        return lark.Client.builder().app_id(self.app_id).app_secret(
            self.app_secret).build()

    def _resolve_target(self) -> tuple[str, str]:
        """确定接收人：显式 receive_id 优先；否则按邮箱解析 open_id（首次解析，之后读缓存）。"""
        if self.receive_id:
            return self.receive_id, self.receive_id_type
        if not self.receive_email:
            raise RuntimeError(
                "飞书未配置 receive_id 或 receive_email，无法确定报告接收人")
        if not (self.app_id and self.app_secret):
            raise RuntimeError("飞书未配置 app_id/app_secret，无法按邮箱解析 open_id")

        cache = _load_open_id_cache(self.cache_path)
        open_id = cache.get(self.receive_email)
        if not open_id:
            open_id = resolve_open_id_by_email(
                self.base_url, self.app_id, self.app_secret, self.receive_email)
            cache[self.receive_email] = open_id
            _save_open_id_cache(self.cache_path, cache)
        return open_id, "open_id"

    def send_report_files(self, title: str, files: list[str],
                          idem_key: str | None = None) -> tuple[str, str]:
        """发送报告：先发标题文本，再逐个发送图片/文件。

        :returns: ``(message_id, report_ref)``。report_ref 为可回查的消息引用串
                  （供去重与 CLI 展示；无独立文档链接）。
        """
        # 首次运行在此解析并缓存 open_id；之后直接命中缓存。
        self.receive_id, self.receive_id_type = self._resolve_target()

        client = self._client()
        existing = [f for f in files if f and os.path.exists(f)]
        missing = [f for f in files if f and not os.path.exists(f)]

        intro = title if not missing else f"{title}\n（缺失产物: {', '.join(missing)}）"
        first_msg_id = self._send_text(client, intro)

        last_msg_id = first_msg_id
        for path in existing:
            if _is_image(path):
                last_msg_id = self._send_image(client, path)
            else:
                last_msg_id = self._send_file(client, path)

        report_ref = f"feishu:msg:{first_msg_id}"
        return first_msg_id, report_ref

    # —— 底层调用 ——
    def _send_text(self, client, text: str) -> str:
        return self._create_message(client, "text", {"text": text})

    def _send_image(self, client, path: str) -> str:
        from lark_oapi.api.im.v1 import (CreateImageRequest,
                                         CreateImageRequestBody)
        with open(path, "rb") as f:
            req = (CreateImageRequest.builder()
                   .request_body(CreateImageRequestBody.builder()
                                 .image_type("message").image(f).build())
                   .build())
            resp = client.im.v1.image.create(req)
        self._ensure_ok(resp, f"上传图片失败: {path}")
        return self._create_message(client, "image", {"image_key": resp.data.image_key})

    def _send_file(self, client, path: str) -> str:
        from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody
        name = Path(path).name
        with open(path, "rb") as f:
            req = (CreateFileRequest.builder()
                   .request_body(CreateFileRequestBody.builder()
                                 .file_type(_file_type(path)).file_name(name)
                                 .file(f).build())
                   .build())
            resp = client.im.v1.file.create(req)
        self._ensure_ok(resp, f"上传文件失败: {path}")
        return self._create_message(client, "file", {"file_key": resp.data.file_key})

    def _create_message(self, client, msg_type: str, content: dict) -> str:
        from lark_oapi.api.im.v1 import (CreateMessageRequest,
                                         CreateMessageRequestBody)
        req = (CreateMessageRequest.builder()
               .receive_id_type(self.receive_id_type)
               .request_body(CreateMessageRequestBody.builder()
                             .receive_id(self.receive_id).msg_type(msg_type)
                             .content(json.dumps(content, ensure_ascii=False))
                             .build())
               .build())
        resp = client.im.v1.message.create(req)
        self._ensure_ok(resp, f"发送 {msg_type} 消息失败")
        return resp.data.message_id

    @staticmethod
    def _ensure_ok(resp, what: str) -> None:
        if not resp.success():
            raise RuntimeError(
                f"{what}: code={resp.code} msg={resp.msg} "
                f"log_id={getattr(resp, 'get_log_id', lambda: '')()}")
