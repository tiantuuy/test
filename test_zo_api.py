#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request


USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/17.0 Safari/605.1.15"
    ),
]


PROMPTS = [
    "hello",
    "how are you",
    "write a haiku",
    "what is python",
    "say hello from github actions",
]


MODELS = [
    "zo:zai/glm-5",
    "zo:minimax/minimax-m2.5",
    "zo:minimax/minimax-m2.7",
]


def get_token() -> str:
    token = os.environ.get("ZO_API_KEY") or os.environ.get("ZO_ACCESS_TOKEN")

    if not token:
        raise SystemExit(
            "Missing ZO_API_KEY environment variable.\n"
            "Configure it in GitHub Repository Settings -> Secrets -> Actions."
        )

    return token


def print_json(data):
    print(json.dumps(data, ensure_ascii=False, indent=2))


def request_json(
    base_url: str,
    method: str,
    path: str,
    token: str,
    payload: dict | None = None,
):
    url = base_url.rstrip("/") + path

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    data = None

    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = urllib.request.Request(
        url,
        method=method,
        headers=headers,
        data=data,
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", "replace")

            return (
                resp.status,
                dict(resp.headers),
                body,
            )

    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")

        return (
            e.code,
            dict(e.headers),
            body,
        )

    except Exception as e:
        return (
            599,
            {},
            json.dumps({"error": str(e)}),
        )


def print_response(title: str, status: int, headers: dict, body: str):
    print(f"\n=== {title} ===")
    print(f"STATUS {status}")

    for key in ("content-type", "x-conversation-id"):
        for h_key, h_val in headers.items():
            if h_key.lower() == key:
                print(f"{h_key}: {h_val}")

    try:
        parsed = json.loads(body)
        print_json(parsed)
    except Exception:
        print(body)


def test_models(base_url: str, token: str):
    status, headers, body = request_json(
        base_url,
        "GET",
        "/models/available",
        token,
    )

    print_response(
        "models GET /models/available",
        status,
        headers,
        body,
    )

    return status == 200


def test_personas(base_url: str, token: str):
    status, headers, body = request_json(
        base_url,
        "GET",
        "/personas/available",
        token,
    )

    print_response(
        "personas GET /personas/available",
        status,
        headers,
        body,
    )

    return status == 200


def test_ask(base_url: str, token: str):
    model = random.choice(MODELS)
    prompt = random.choice(PROMPTS)

    payload: dict[str, object] = {
        "input": prompt,
        "model_name": model,
    }

    print("\nREQUEST PAYLOAD:")
    print_json(payload)

    status, headers, body = request_json(
        base_url,
        "POST",
        "/zo/ask",
        token,
        payload,
    )

    print_response(
        "ask POST /zo/ask",
        status,
        headers,
        body,
    )

    if status >= 500:
        print("\nServer-side inference failure detected.")
        return False

    return status == 200


def visit_website(url: str):
    print(f"\n=== WEBSITE VISIT ===")
    print(f"URL: {url}")

    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": (
            "text/html,application/xhtml+xml,"
            "application/xml;q=0.9,image/webp,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
    }

    req = urllib.request.Request(
        url,
        headers=headers,
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            status = resp.status

            print(f"STATUS {status}")

            html = resp.read(500).decode("utf-8", "replace")

            print("\nPAGE PREVIEW:")
            print(html[:500])

            return status == 200

    except urllib.error.HTTPError as e:
        print(f"HTTP ERROR: {e.code}")
        return False

    except Exception as e:
        print(f"VISIT ERROR: {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="ZO API + Website Keepalive"
    )

    parser.add_argument(
        "--api-base-url",
        default="https://api.zo.computer",
    )

    parser.add_argument(
        "--website-url",
        default="https://sub-store-selino9.zocomputer.io",
    )

    args = parser.parse_args()

    token = get_token()

    print("ZO keepalive started.")

    ok_models = False
    ok_personas = False
    ok_ask = False
    ok_website = False

    # API keepalive
    try:
        ok_models = test_models(args.api_base_url, token)
    except Exception as e:
        print(f"models endpoint error: {e}")

    time.sleep(random.uniform(1, 3))

    try:
        ok_personas = test_personas(args.api_base_url, token)
    except Exception as e:
        print(f"personas endpoint error: {e}")

    time.sleep(random.uniform(1, 3))

    try:
        ok_ask = test_ask(args.api_base_url, token)
    except Exception as e:
        print(f"ask endpoint error: {e}")

    time.sleep(random.uniform(1, 3))

    # Website keepalive
    try:
        ok_website = visit_website(args.website_url)
    except Exception as e:
        print(f"website visit error: {e}")

    print("\n=== FINAL RESULT ===")

    print(f"models     : {ok_models}")
    print(f"personas   : {ok_personas}")
    print(f"ask        : {ok_ask}")
    print(f"website    : {ok_website}")

    if ok_models or ok_personas or ok_website:
        print("\nKeepalive successful.")
        sys.exit(0)

    print("\nKeepalive failed.")
    sys.exit(1)


if __name__ == "__main__":
    main()
