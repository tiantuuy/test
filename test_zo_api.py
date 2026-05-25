#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


def get_token() -> str:
    token = os.environ.get("ZO_API_KEY") or os.environ.get("ZO_ACCESS_TOKEN")
    if not token:
        raise SystemExit("Missing ZO_API_KEY in environment. Set it in Settings > Advanced.")
    return token


def request_json(base_url: str, method: str, path: str, token: str, payload: dict | None = None):
    url = base_url.rstrip("/") + path
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", "replace")
            return resp.status, dict(resp.headers), body
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        return e.code, dict(e.headers), body


def print_response(title: str, status: int, headers: dict[str, str], body: str):
    print(f"=== {title} ===")
    print(f"STATUS {status}")
    for key in ("content-type", "x-conversation-id"):
        for h_key, h_val in headers.items():
            if h_key.lower() == key:
                print(f"{h_key}: {h_val}")
                break
    try:
        parsed = json.loads(body)
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
    except json.JSONDecodeError:
        print(body)
    print()


def stream_ask(base_url: str, token: str, payload: dict):
    url = base_url.rstrip("/") + "/zo/ask"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
    }
    req = urllib.request.Request(url, method="POST", headers=headers, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    with urllib.request.urlopen(req, timeout=300) as resp:
        print(f"=== ask POST /zo/ask (stream) ===")
        print(f"STATUS {resp.status}")
        conv_id = resp.headers.get("x-conversation-id")
        if conv_id:
            print(f"x-conversation-id: {conv_id}")
        event_type = None
        for raw in resp:
            line = raw.decode("utf-8", "replace").strip()
            if not line:
                continue
            if line.startswith("event: "):
                event_type = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
                if event_type == "FrontendModelResponse":
                    print(data.get("content", ""), end="", flush=True)
                elif event_type == "End":
                    if "output" in data and isinstance(data["output"], (str, dict, list)):
                        print()
                        print(json.dumps(data["output"], ensure_ascii=False, indent=2) if not isinstance(data["output"], str) else data["output"])
                    else:
                        print()
                elif event_type == "Error":
                    print(f"\nERROR: {data.get('message', '')}")
        print()


def main():
    parser = argparse.ArgumentParser(description="Test Zo API endpoints: /models/available, /personas/available, /zo/ask")
    parser.add_argument("--base-url", default="https://api.zo.computer")
    parser.add_argument("--input", default="Hello, Zo!")
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--persona-id", default=None)
    parser.add_argument("--stream", action="store_true")
    args = parser.parse_args()

    token = get_token()
    base_url = args.base_url

    status, headers, body = request_json(base_url, "GET", "/models/available", token)
    print_response("models GET /models/available", status, headers, body)

    status, headers, body = request_json(base_url, "GET", "/personas/available", token)
    print_response("personas GET /personas/available", status, headers, body)

    payload: dict[str, object] = {
        "messages": [
            {
                "role": "user",
                "content": args.input
            }
        ]
    }
    if args.model_name:
        payload["model_name"] = args.model_name
    if args.persona_id:
        payload["persona_id"] = args.persona_id
    if args.stream:
        payload["stream"] = True
        stream_ask(base_url, token, payload)
    else:
        status, headers, body = request_json(base_url, "POST", "/zo/ask", token, payload)
        print_response("ask POST /zo/ask", status, headers, body)


if __name__ == "__main__":
    main()
