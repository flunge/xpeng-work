#!/usr/bin/env python3
"""
GPT Image 2 generation — via SoCheap Media API.
Usage: python3 gen_image.py --prompt "..." [--aspect 16:9] [--resolution 1K|2K|4K]
                            [--image-url URL] [--output ./output] [--name NAME] [--max-wait 240]
密钥从 ../media_key.txt 读取，绝不打印。
"""
import argparse, json, os, sys, time, uuid, re
import urllib.request, urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), "media_key.txt")
BASE_URL = "https://socheap.ai"


def get_key():
    with open(KEY_FILE) as f:
        content = f.read()
    m = re.search(r"Bearer\s+(sk-[a-zA-Z0-9]+)", content)
    return m.group(1) if m else content.strip().split("\n")[0].strip()


def api_request(method, path, body=None):
    url = f"{BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {get_key()}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()}


def create_job(prompt, resolution, aspect_ratio, image_urls=None):
    # 规则：auto 仅 1K；4K 不支持 1:1
    if aspect_ratio == "auto" and resolution != "1K":
        aspect_ratio = "16:9"
    if resolution == "4K" and aspect_ratio == "1:1":
        aspect_ratio = "4:3"
    body = {
        "model": "gpt-image-2",
        "mode": "standard",
        "client_request_id": f"gpt-image-2-{uuid.uuid4()}",
        "prompt": prompt,
        "resolution": resolution,
        "aspect_ratio": aspect_ratio,
    }
    if image_urls:
        body["image_urls"] = image_urls
    return api_request("POST", "/media/image/generations", body)


def poll_job(job_id):
    return api_request("GET", f"/media/image/generations/{job_id}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--aspect", default="16:9")
    ap.add_argument("--resolution", default="1K", choices=["1K", "2K", "4K"])
    ap.add_argument("--image-url")
    ap.add_argument("--output", default="./output")
    ap.add_argument("--name", help="输出文件名(不含扩展名)")
    ap.add_argument("--max-wait", type=int, default=240)
    args = ap.parse_args()

    image_urls = [args.image_url] if args.image_url else None
    print(f"[create] res={args.resolution} aspect={args.aspect} prompt='{args.prompt[:50]}...'",
          file=sys.stderr)
    job = create_job(args.prompt, args.resolution, args.aspect, image_urls)
    if "error" in job:
        print(json.dumps(job, indent=2)); sys.exit(1)
    job_id = job.get("data", {}).get("id") or job.get("id")
    if not job_id:
        print(json.dumps(job, indent=2)); sys.exit(1)
    print(f"[job] {job_id}", file=sys.stderr)

    elapsed = 0
    while elapsed < args.max_wait:
        time.sleep(5); elapsed += 5
        st = poll_job(job_id)
        state = st.get("data", {}).get("status") or st.get("status", "unknown")
        print(f"  [{elapsed}s] {state}", file=sys.stderr)
        if state == "completed":
            outputs = st.get("data", {}).get("result", {}).get("outputs", [])
            os.makedirs(args.output, exist_ok=True)
            files = []
            for i, out in enumerate(outputs):
                url = out if isinstance(out, str) else out.get("url", "")
                if not url:
                    continue
                base = args.name or f"gpt-{job_id[:10]}"
                fp = os.path.join(args.output, f"{base}{'' if len(outputs)==1 else f'-{i}'}.png")
                urllib.request.urlretrieve(url, fp)
                files.append(fp)
                print(f"  saved: {fp}", file=sys.stderr)
            print(json.dumps({"job_id": job_id, "status": "completed", "files": files},
                             ensure_ascii=False))
            return
        if state in ("failed", "cancelled"):
            print(json.dumps({"job_id": job_id, "status": state,
                              "error": st.get("data", {}).get("error", {})}))
            sys.exit(1)
    print(json.dumps({"job_id": job_id, "status": "timeout", "elapsed": elapsed}))
    sys.exit(2)


if __name__ == "__main__":
    main()
