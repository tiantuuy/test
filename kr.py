#!/usr/bin/env python3
import re
import os
import json
import asyncio
from telethon import TelegramClient

def log(msg):
    print(f"[KR] {msg}", flush=True)

async def main():
    api_id = int(os.environ["API_ID"])
    api_hash = os.environ["API_HASH"]
    chat_id = int(os.environ["CHAT_ID"])

    log(f"Start kernel fetch")
    log(f"API_ID={api_id}")
    log(f"CHAT_ID={chat_id}")

    client = TelegramClient("tg", api_id, api_hash)
    await client.start()
    log("Telegram connected")

    targets = {
        "header": "header-",
        "modules": "modules-",
        "boot": "boot-",
        "dtb-amlogic": "dtb-amlogic-"
    }

    files = {}
    ver_latest = None

    log("Scanning messages...")

    async for msg in client.iter_messages(chat_id, limit=200):
        if not msg.file:
            continue

        name = msg.file.name or ""
        log(f"Found file: {name}")

        m = re.search(r'(\d+\.\d+\.\d+-flippy-\d+\+)', name)
        if not m:
            log("  -> skip: version not match")
            continue

        ver = m.group(1)
        log(f"  -> version detected: {ver}")

        if "6.18." not in ver:
            log("  -> skip: not 6.18.x")
            continue

        if ver_latest is None or ver > ver_latest:
            ver_latest = ver
            files = {}
            log(f"NEW LATEST VERSION: {ver_latest}")

        if ver != ver_latest:
            log("  -> skip: not latest")
            continue

        for key, prefix in targets.items():
            if name.startswith(prefix):
                files[key] = msg
                log(f"  -> matched {key}")

        if len(files) == 4:
            log("All required files found")
            break

    if len(files) != 4:
        log("ERROR: Kernel incomplete")
        return

    log(f"Latest kernel: {ver_latest}")

    with open("kernel.json", "w") as f:
        json.dump({"version": ver_latest}, f)
    log("kernel.json written")

    base_dir = f"dl/{ver_latest}"
    os.makedirs(base_dir, exist_ok=True)
    log(f"Download dir: {base_dir}")

    for key, msg in files.items():
        out = f"{base_dir}/{msg.file.name}"
        log(f"Downloading {msg.file.name}")
        await msg.download_media(out)

    tar_name = f"{ver_latest}.tar.gz"
    log(f"Packing {tar_name}")
    os.system(f"tar -czf {tar_name} -C dl {ver_latest}")

    log("Done")

if __name__ == "__main__":
    asyncio.run(main())
