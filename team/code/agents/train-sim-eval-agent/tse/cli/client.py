import os
import httpx

# 控制 API 默认地址（hardcode 到代码中；如需临时覆盖可设环境变量 TSE_ENDPOINT）
# 台架 agentd 默认不配 TLS（config.py 中 tls_cert/tls_key 默认 None），即纯 HTTP；
# 故默认端点用 http://。若台架启用了 TLS，再用 TSE_ENDPOINT 覆盖为 https://。
DEFAULT_ENDPOINT = "http://10.99.75.210:8443"


class ControlClient:
    def __init__(self, endpoint: str | None = None):
        self.endpoint = endpoint or os.environ.get("TSE_ENDPOINT") or DEFAULT_ENDPOINT
        self._c = httpx.Client(base_url=self.endpoint, timeout=30)

    def run(self, **body):
        return self._c.post("/run", json=body).raise_for_status().json()

    def status(self, eid: str):
        return self._c.get(f"/status/{eid}").raise_for_status().json()

    def list(self):
        return self._c.get("/list").raise_for_status().json()
