#!/usr/bin/env python3
"""
批量并发生成 gpt-image-2 图片：先一次性创建所有 job，再并发轮询、完成即下载。
用法: python3 gen_batch.py specs.json --output DIR --max-wait 280
specs.json: [{"name":..., "prompt":..., "aspect":"16:9", "resolution":"1K"}, ...]
密钥从 ../media_key.txt 读取，绝不打印。
"""
import argparse, json, os, sys, time, uuid, re
import urllib.request, urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), "media_key.txt")
BASE_URL = "https://socheap.ai"


def get_key():
    with open(KEY_FILE) as f:
        c = f.read()
    m = re.search(r"Bearer\s+(sk-[a-zA-Z0-9]+)", c)
    return m.group(1) if m else c.strip().split("\n")[0].strip()


def api(method, path, body=None):
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=json.dumps(body).encode() if body else None,
        headers={"Authorization": f"Bearer {get_key()}", "Content-Type": "application/json"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()[:300]}
    except Exception as e:
        return {"error": "exc", "body": str(e)}


def create(spec):
    res = spec.get("resolution", "1K")
    asp = spec.get("aspect", "16:9")
    if asp == "auto" and res != "1K":
        asp = "16:9"
    if res == "4K" and asp == "1:1":
        asp = "4:3"
    body = {"model": "gpt-image-2", "mode": "standard",
            "client_request_id": f"gpt-image-2-{uuid.uuid4()}",
            "prompt": spec["prompt"], "resolution": res, "aspect_ratio": asp}
    return api("POST", "/media/image/generations", body)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("specs")
    ap.add_argument("--output", default="./output")
    ap.add_argument("--max-wait", type=int, default=280)
    args = ap.parse_args()
    specs = json.load(open(args.specs))
    os.makedirs(args.output, exist_ok=True)

    jobs = {}   # name -> job_id
    for s in specs:
        r = create(s)
        jid = (r.get("data") or {}).get("id") or r.get("id")
        if jid:
            jobs[s["name"]] = jid
            print(f"[create] {s['name']} -> {jid}", file=sys.stderr)
        else:
            print(f"[create-FAIL] {s['name']}: {json.dumps(r)[:200]}", file=sys.stderr)
    pending = dict(jobs)
    done = {}
    elapsed = 0
    while pending and elapsed < args.max_wait:
        time.sleep(6); elapsed += 6
        for name, jid in list(pending.items()):
            st = api("GET", f"/media/image/generations/{jid}")
            state = (st.get("data") or {}).get("status") or st.get("status", "?")
            if state == "completed":
                outs = ((st.get("data") or {}).get("result") or {}).get("outputs", [])
                saved = []
                for i, o in enumerate(outs):
                    url = o if isinstance(o, str) else o.get("url", "")
                    if not url:
                        continue
                    fp = os.path.join(args.output, f"{name}.png" if len(outs) == 1
                                      else f"{name}-{i}.png")
                    try:
                        urllib.request.urlretrieve(url, fp); saved.append(fp)
                    except Exception as e:
                        print(f"  dl-fail {name}: {e}", file=sys.stderr)
                done[name] = saved
                del pending[name]
                print(f"[done {elapsed}s] {name}: {saved}", file=sys.stderr)
            elif state in ("failed", "cancelled"):
                done[name] = {"status": state, "err": (st.get("data") or {}).get("error", {})}
                del pending[name]
                print(f"[{state}] {name}", file=sys.stderr)
        print(f"  ... {len(done)}/{len(jobs)} done, {len(pending)} pending @{elapsed}s",
              file=sys.stderr)
    result = {"done": {k: v for k, v in done.items() if isinstance(v, list)},
              "failed": {k: v for k, v in done.items() if not isinstance(v, list)},
              "pending": pending}
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
