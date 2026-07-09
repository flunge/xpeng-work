import os
import time
import hmac
import hashlib
import requests, json

from urllib.parse import urlparse

ACCOUNT='cloudsim-engine@xiaopeng.com'
SECRETS={
    'cloudsim.xiaopeng.link': '%mMFcTWlzJOe',
    'cloudsim-dev.xiaopeng.link': 'vl@H%KtbzeYa',
    'wl-cloudsim-dev.xiaopeng.link': 'vl@H%KtbzeYa',
    'cloudsim-staging.xiaopeng.link': 'ggvfelQJRMjb',
}

def cloudsim_request(url, data):
    # signature
    domain = urlparse(url).netloc
    secret = SECRETS.get(domain)
    if not secret:
        raise Exception("No secret for domain: " + domain)
    app_key = "simulation-auth"
    version = "1.0"
    sign_message = "/".join([app_key, version, ACCOUNT, str(int(time.time()*1000))])
    sign = generate_hmac_sha256_signature(secret, sign_message)

    # request
    headers = {
        'X-Sign': sign_message + "/" + sign,
    }
    print(f"[INFO] cloudsim request url: {url}, data: {data}")
    rsp = requests.post(url, data=data, headers=headers)

    return json.loads(rsp.text)

def generate_hmac_sha256_signature(secret, message):
    hmac_key = bytes(secret, "utf-8")
    hmac_message = bytes(message, "utf-8")
    signature = hmac.new(hmac_key, hmac_message, hashlib.sha256).hexdigest()
    return signature    