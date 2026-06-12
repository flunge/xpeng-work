#!/usr/bin/env python3
"""
Grok Image Generation — via SoCheap Media API
Usage: python3 gen_image.py --prompt "..." [--mode standard|quality] [--aspect 16:9] [--image-url URL] [--output ./output]
"""
import argparse, json, os, sys, time, uuid, subprocess
import urllib.request, urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KEY_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), "media_key.txt")
BASE_URL = "https://socheap.ai"

def get_key():
    with open(KEY_FILE) as f:
        content = f.read()
    # Extract Bearer token from curl-style key file
    import re
    match = re.search(r'Bearer\s+(sk-[a-zA-Z0-9]+)', content)
    if match:
        return match.group(1)
    # Fallback: return first line stripped
    return content.strip().split('\n')[0].strip()

def api_request(method, path, body=None):
    url = f"{BASE_URL}{path}"
    headers = {
        "Authorization": f"Bearer {get_key()}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": e.code, "body": e.read().decode()}

def create_job(prompt, mode="standard", aspect_ratio="16:9", image_urls=None):
    body = {
        "model": "grok-imagine-image",
        "mode": mode,
        "client_request_id": f"grok-image-{uuid.uuid4()}",
        "prompt": prompt,
        "aspect_ratio": aspect_ratio,
    }
    if image_urls:
        body["image_urls"] = image_urls
    return api_request("POST", "/media/image/generations", body)

def poll_job(job_id):
    return api_request("GET", f"/media/image/generations/{job_id}")

def download_image(url, filepath):
    urllib.request.urlretrieve(url, filepath)
    return filepath

def main():
    parser = argparse.ArgumentParser(description="Grok Image Generation via SoCheap")
    parser.add_argument("--prompt", required=True, help="Image generation prompt")
    parser.add_argument("--mode", default="standard", choices=["standard", "quality"])
    parser.add_argument("--aspect", default="16:9", help="Aspect ratio: 1:1, 16:9, 9:16, 3:2, 2:3")
    parser.add_argument("--image-url", help="Reference image URL (image-to-image, standard mode only)")
    parser.add_argument("--output", default="./output", help="Output directory")
    parser.add_argument("--max-wait", type=int, default=600, help="Max wait seconds (default 600)")
    parser.add_argument("--feishu-doc", help="Feishu wiki/doc URL to upload generated images to")
    parser.add_argument("--feishu-block-id", help="Block ID to insert image after (for block_insert_after)")
    args = parser.parse_args()

    image_urls = [args.image_url] if args.image_url else None

    print(f"Creating job: prompt='{args.prompt[:60]}...' mode={args.mode} aspect={args.aspect}", file=sys.stderr)
    job = create_job(args.prompt, args.mode, args.aspect, image_urls)

    if "error" in job:
        print(json.dumps(job, indent=2))
        sys.exit(1)

    job_id = job.get("data", {}).get("id") or job.get("id")
    print(f"Job ID: {job_id}", file=sys.stderr)

    # Poll
    elapsed = 0
    while elapsed < args.max_wait:
        time.sleep(5)
        elapsed += 5
        status = poll_job(job_id)
        state = status.get("data", {}).get("status") or status.get("status", "unknown")
        print(f"  [{elapsed}s] {state}", file=sys.stderr)

        if state == "completed":
            outputs = status.get("data", {}).get("result", {}).get("outputs", [])
            os.makedirs(args.output, exist_ok=True)
            downloaded = []
            for i, out in enumerate(outputs):
                url = out if isinstance(out, str) else out.get("url", "")
                if url:
                    ext = ".png"
                    fpath = os.path.join(args.output, f"grok-{job_id[:12]}-{i}{ext}")
                    download_image(url, fpath)
                    downloaded.append(fpath)
                    print(f"  Downloaded: {fpath}", file=sys.stderr)

            # Upload to Feishu wiki if requested
            feishu_blocks = []
            if args.feishu_doc and args.feishu_block_id:
                # Step 1: Get document_id from wiki URL
                doc_info = subprocess.run(
                    ["lark-cli", "docs", "+fetch", "--api-version", "v2", "--doc", args.feishu_doc, "--format", "json"],
                    capture_output=True, text=True, timeout=30
                )
                doc_id = None
                try:
                    doc_id = json.loads(doc_info.stdout)["data"]["document"]["document_id"]
                except:
                    pass

                if doc_id:
                    for fpath in downloaded:
                        # Step 2: Copy to cwd (lark-cli requires relative path)
                        local_name = os.path.basename(fpath)
                        subprocess.run(["cp", fpath, local_name], check=True)

                        # Step 3: Upload to doc media library
                        upload = subprocess.run(
                            ["lark-cli", "docs", "+media-upload", "--file", local_name,
                             "--doc-id", doc_id, "--parent-node", args.feishu_block_id,
                             "--parent-type", "docx_image", "--format", "json"],
                            capture_output=True, text=True, timeout=30
                        )
                        file_token = None
                        try:
                            file_token = json.loads(upload.stdout)["data"]["file_token"]
                        except:
                            pass

                        # Step 4: Insert image block after the target block
                        if file_token:
                            insert = subprocess.run(
                                ["lark-cli", "docs", "+update", "--api-version", "v2",
                                 "--doc", args.feishu_doc,
                                 "--command", "block_insert_after",
                                 "--block-id", args.feishu_block_id,
                                 "--content", f'<p><img src="{file_token}" mime="image/png"/></p>',
                                 "--format", "json"],
                                capture_output=True, text=True, timeout=30
                            )
                            try:
                                ok = json.loads(insert.stdout).get("ok")
                            except:
                                ok = False

                        # Cleanup local copy
                        subprocess.run(["rm", "-f", local_name])

                        if file_token and ok:
                            feishu_blocks.append({"file": fpath, "uploaded": True, "file_token": file_token})
                            print(f"  Inserted into doc: {fpath}", file=sys.stderr)
                        else:
                            feishu_blocks.append({"file": fpath, "uploaded": False})
                else:
                    print(f"  Could not get document_id for {args.feishu_doc}", file=sys.stderr)

            # Output JSON result
            result = {
                "job_id": job_id,
                "status": "completed",
                "mode": args.mode,
                "prompt": args.prompt,
                "files": downloaded,
                "urls": outputs,
            }
            if feishu_blocks:
                result["feishu_uploads"] = feishu_blocks
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return

        elif state in ("failed", "cancelled"):
            error_info = status.get("data", {}).get("error", {})
            result = {"job_id": job_id, "status": state, "error": error_info}
            print(json.dumps(result, indent=2))
            sys.exit(1)

    result = {"job_id": job_id, "status": "timeout", "elapsed": elapsed}
    print(json.dumps(result, indent=2))
    sys.exit(1)

if __name__ == "__main__":
    main()
