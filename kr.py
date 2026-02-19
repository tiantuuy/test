#!/usr/bin/env python3
import re
import os
import json
import asyncio
from telethon import TelegramClient

def log(msg):
    print(f"[KR] {msg}", flush=True)

def read_local_version():
    if os.path.exists("latest.txt"):
        with open("latest.txt") as f:
            v = f.read().strip()
            if v:
                return v
    return None

def extract_ver(name):
    m = re.search(r'(\d+\.\d+\.\d+-flippy-\d+\+)', name or "")
    return m.group(1) if m else None

async def detect_latest_version(client, chat_id):
    """极速检测：只看最近10条"""
    log("Fast check latest version (last 10 msgs)")
    latest = None

    async for msg in client.iter_messages(chat_id, limit=5):
        if not msg.file:
            continue

        ver = extract_ver(msg.file.name)
        if not ver:
            continue

        if "6.18." not in ver:
            continue

        if latest is None or ver > latest:
            latest = ver

    return latest

async def collect_files(client, chat_id, target_ver):
    """完整扫描：收集4件套"""
    log(f"Full scan for version {target_ver}")

    targets = {
        "header": "header-",
        "modules": "modules-",
        "boot": "boot-",
        "dtb-amlogic": "dtb-amlogic-"
    }

    files = {}

    async for msg in client.iter_messages(chat_id, limit=30):
        if not msg.file:
            continue

        name = msg.file.name or ""
        ver = extract_ver(name)

        if ver != target_ver:
            continue

        for key, prefix in targets.items():
            if name.startswith(prefix):
                files[key] = msg
                log(f"Matched {key}: {name}")

        if len(files) == 4:
            break

    return files

async def main():
    api_id = int(os.environ["API_ID"])
    api_hash = os.environ["API_HASH"]
    chat_id = int(os.environ["CHAT_ID"])

    local_ver = read_local_version()
    log(f"Local version: {local_ver}")

    client = TelegramClient("tg", api_id, api_hash)
    await client.start()
    log("Telegram connected")

    # ====== 阶段1：极速检测 ======
    channel_ver = await detect_latest_version(client, chat_id)

    if not channel_ver:
        log("No kernel version found in recent messages")
        return

    log(f"Channel latest: {channel_ver}")

    if local_ver == channel_ver:
        log("Same as release → exit fast")
        return

    log("New version detected → need download")

    # ====== 阶段2：完整扫描 ======
    files = await collect_files(client, chat_id, channel_ver)

    if len(files) != 4:
        log("ERROR: Kernel incomplete")
        return

    with open("kernel.json", "w") as f:
        json.dump({"version": channel_ver}, f)
    log("kernel.json written")

    base_dir = f"dl/{channel_ver}"
    os.makedirs(base_dir, exist_ok=True)

    for key, msg in files.items():
        out = f"{base_dir}/{msg.file.name}"
        log(f"Downloading {msg.file.name}")
        await msg.download_media(out)

    tar_name = f"{channel_ver}.tar.gz"
    log(f"Packing {tar_name}")
    os.system(f"tar -czf {tar_name} -C dl {channel_ver}")

    log("Done")

if __name__ == "__main__":
    asyncio.run(main())
