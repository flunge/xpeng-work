from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request


def main() -> int:
    parser = argparse.ArgumentParser(description="Bridge lark-cli event stream to local Feishu webhook.")
    parser.add_argument("--event-key", default="im.message.receive_v1")
    parser.add_argument("--webhook-url", default="http://127.0.0.1:8091/webhook/feishu/events")
    parser.add_argument("--as", dest="identity", default="bot")
    args = parser.parse_args()

    command = ["lark-cli", "event", "consume", args.event_key, "--as", args.identity, "--quiet"]
    with subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=None, text=True, bufsize=1) as proc:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                print(line, flush=True)
                continue
            try:
                _post_event(args.webhook_url, event)
            except Exception as exc:
                print(f"failed to forward event {event.get('event_id') or event.get('id')}: {exc}", file=sys.stderr, flush=True)
        return proc.wait()


def _post_event(webhook_url: str, event: dict) -> None:
    data = json.dumps(event, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            body = response.read().decode("utf-8")
            print(f"forwarded {event.get('event_id') or event.get('id')} -> {response.status} {body}", flush=True)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
