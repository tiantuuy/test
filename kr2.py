#!/usr/bin/env python3

import os
import re
import json
import tarfile
import asyncio
from pathlib import Path
from telethon import TelegramClient


# ============================================================
# Configuration
# ============================================================

# 当前需要长期维护的 LTS 系列
# 这里只限制“大版本系列”，具体 patch/release 完全动态获取。
LTS_SERIES = (
    "6.1",
    "6.12",
    "6.18",
)

# Telegram 最近扫描多少条消息
# 只要频道没有几千条相关文件，500 已经足够。
SCAN_LIMIT = 100

# 每个系列至少需要找到多少个文件
# 不写死，因为不同 kernel 系列文件数量可能不同。
MIN_FILES = 1

STATE_FILE = "latest.json"
DOWNLOAD_ROOT = Path("dl")
OUTPUT_ROOT = Path("release")


# ============================================================
# Logging
# ============================================================

def log(message):
    print(f"[KR] {message}", flush=True)


# ============================================================
# Version parsing
# ============================================================

def extract_version(filename):
    """
    从 Telegram 文件名中提取完整 Flippy kernel 版本。

    例如：

    header-6.1.157-rk35xx-flippy-2609a.tar.gz
        ->
    6.1.157-rk35xx-flippy-2609a

    modules-6.12.104-flippy-95+o.tar.gz
        ->
    6.12.104-flippy-95+o

    dtb-amlogic-6.18.46-flippy-95+.tar.gz
        ->
    6.18.46-flippy-95+
    """

    if not filename:
        return None

    name = Path(filename).name

    # 去掉常见压缩后缀
    name = re.sub(r"\.tar\.gz$", "", name)

    # 版本必须以数字三段开头
    # 后面允许出现 rk35xx / rk3588 / 95+o / 95+ 等内容
    match = re.search(
        r"(?P<version>\d+\.\d+\.\d+(?:-[A-Za-z0-9+._-]+)*-flippy-[A-Za-z0-9+._-]+)$",
        name
    )

    if not match:
        return None

    return match.group("version")


def get_series(version):
    """
    取得 kernel 主系列。

    6.1.157-rk35xx-flippy-2609a -> 6.1
    6.12.104-flippy-95+o        -> 6.12
    6.18.46-flippy-95+           -> 6.18
    """

    if not version:
        return None

    match = re.match(r"^(\d+\.\d+)\.", version)

    if not match:
        return None

    return match.group(1)


def kernel_version_tuple(version):
    """
    用数字版本进行排序。

    例如：

    6.18.46 -> (6, 18, 46)
    6.18.45 -> (6, 18, 45)
    """

    if not version:
        return (0, 0, 0)

    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)

    if not match:
        return (0, 0, 0)

    return tuple(int(x) for x in match.groups())


# ============================================================
# State
# ============================================================

def load_state():
    """
    读取上一次成功保存的版本。

    latest.json 示例：

    {
        "6.1": "6.1.157-rk35xx-flippy-2609a",
        "6.12": "6.12.104-flippy-95+o",
        "6.18": "6.18.46-flippy-95+"
    }
    """

    if not os.path.exists(STATE_FILE):
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            return {}

        return data

    except Exception as e:
        log(f"Unable to read {STATE_FILE}: {e}")
        return {}


def save_state(state):
    """
    原子方式保存状态。
    """

    temp_file = f"{STATE_FILE}.tmp"

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(
            state,
            f,
            indent=2,
            ensure_ascii=False,
            sort_keys=True
        )

    os.replace(temp_file, STATE_FILE)


# ============================================================
# Telegram scanning
# ============================================================

async def scan_latest_versions(client, chat_id):
    """
    一次扫描 Telegram，动态寻找所有 LTS 系列的最新版本。

    不再只寻找 6.18。

    返回：

    {
        "6.1":  "...",
        "6.12": "...",
        "6.18": "..."
    }
    """

    log(f"Scanning latest {SCAN_LIMIT} Telegram messages")

    latest = {}

    async for msg in client.iter_messages(chat_id, limit=SCAN_LIMIT):

        if not msg.file:
            continue

        filename = msg.file.name or ""

        version = extract_version(filename)

        if not version:
            continue

        series = get_series(version)

        if series not in LTS_SERIES:
            continue

        old_version = latest.get(series)

        if (
            old_version is None
            or kernel_version_tuple(version)
            > kernel_version_tuple(old_version)
        ):
            latest[series] = version

            log(
                f"Found {series} latest candidate: "
                f"{version}"
            )

    return latest


# ============================================================
# Collect files
# ============================================================

async def collect_files(client, chat_id, target_version):
    """
    收集指定版本的所有文件。

    重点：
    不限制文件数量。

    因此：

    6.1 可能是 8 个
    6.12 可能是 6 个
    6.18 可能是 6 个
    以后如果出现 10 个，也可以自动处理。
    """

    log(f"Collecting files for {target_version}")

    files = {}

    async for msg in client.iter_messages(
        chat_id,
        limit=SCAN_LIMIT
    ):

        if not msg.file:
            continue

        filename = msg.file.name or ""

        version = extract_version(filename)

        if version != target_version:
            continue

        # 只保存有明确文件名的文件
        if filename not in files:
            files[filename] = msg

            log(f"Matched: {filename}")

    log(
        f"Collected {len(files)} files "
        f"for {target_version}"
    )

    return files


# ============================================================
# Download
# ============================================================

async def download_files(files, target_version):
    """
    下载指定版本的全部文件。
    """

    version_dir = DOWNLOAD_ROOT / target_version

    version_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    downloaded = []

    for filename, msg in sorted(files.items()):

        output_file = version_dir / filename

        # 已经存在并且不是空文件，则跳过
        if output_file.exists() and output_file.stat().st_size > 0:
            log(f"Already exists: {filename}")
            downloaded.append(output_file)
            continue

        log(f"Downloading: {filename}")

        temp_file = output_file.with_suffix(
            output_file.suffix + ".part"
        )

        try:

            await msg.download_media(
                file=str(temp_file)
            )

            if (
                not temp_file.exists()
                or temp_file.stat().st_size == 0
            ):
                raise RuntimeError(
                    "Downloaded file is empty"
                )

            os.replace(
                temp_file,
                output_file
            )

            downloaded.append(output_file)

            log(f"Downloaded: {filename}")

        except Exception:

            if temp_file.exists():
                temp_file.unlink()

            raise

    return downloaded


# ============================================================
# Package
# ============================================================

def package_version(target_version, files):
    """
    将某个 kernel 系列的全部文件打包。

    输出固定为：

    release/kernel-6.1.tar.gz
    release/kernel-6.12.tar.gz
    release/kernel-6.18.tar.gz

    这样 GitHub Release 长期更新时不会无限产生：

    kernel-6.1.156...
    kernel-6.1.157...
    kernel-6.1.158...

    而是始终覆盖同一个稳定资产。
    """

    OUTPUT_ROOT.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file = OUTPUT_ROOT / (
        f"kernel-{get_series(target_version)}.tar.gz"
    )

    source_dir = DOWNLOAD_ROOT / target_version

    log(
        f"Packing {output_file}"
    )

    with tarfile.open(
        output_file,
        "w:gz"
    ) as tar:

        for filename in sorted(files):

            source_file = source_dir / filename

            if not source_file.exists():
                raise FileNotFoundError(
                    f"Missing downloaded file: {source_file}"
                )

            # 压缩包内部保持：
            #
            # 6.1.157-rk35xx...
            # 6.1.157-rk3588...
            #
            # 不把 dl/ 路径暴露进去。
            tar.add(
                source_file,
                arcname=filename
            )

    log(
        f"Created {output_file} "
        f"({output_file.stat().st_size} bytes)"
    )

    return output_file


# ============================================================
# Main
# ============================================================

async def main():

    api_id = int(os.environ["API_ID"])
    api_hash = os.environ["API_HASH"]
    chat_id = int(os.environ["CHAT_ID"])

    state = load_state()

    log(f"Previous state: {state}")

    # --------------------------------------------------------
    # Telegram
    # --------------------------------------------------------

    client = TelegramClient(
        "tg",
        api_id,
        api_hash
    )

    await client.start()

    log("Telegram connected")

    try:

        # ----------------------------------------------------
        # 1. Find latest versions
        # ----------------------------------------------------

        latest_versions = await scan_latest_versions(
            client,
            chat_id
        )

        log(
            f"Latest versions: {latest_versions}"
        )

        if not latest_versions:
            raise RuntimeError(
                "No supported LTS kernel version found"
            )

        # ----------------------------------------------------
        # 2. Process each LTS series
        # ----------------------------------------------------

        new_state = dict(state)

        changed = []

        for series in LTS_SERIES:

            target_version = latest_versions.get(series)

            if not target_version:
                log(
                    f"{series}: no version found, skip"
                )
                continue

            previous_version = state.get(series)

            log(
                f"{series}: "
                f"previous={previous_version}, "
                f"latest={target_version}"
            )

            # ------------------------------------------------
            # Same version
            # ------------------------------------------------

            if previous_version == target_version:

                archive = OUTPUT_ROOT / (
                    f"kernel-{series}.tar.gz"
                )

                if archive.exists():
                    log(
                        f"{series}: unchanged, skip"
                    )
                    continue

                # 状态相同但 Release 文件不存在，
                # 仍然重新收集并打包。
                log(
                    f"{series}: state exists "
                    f"but archive missing, rebuild"
                )

            # ------------------------------------------------
            # Collect
            # ------------------------------------------------

            files = await collect_files(
                client,
                chat_id,
                target_version
            )

            if len(files) < MIN_FILES:
                raise RuntimeError(
                    f"{series}: incomplete release, "
                    f"only {len(files)} file(s)"
                )

            # ------------------------------------------------
            # Download
            # ------------------------------------------------

            await download_files(
                files,
                target_version
            )

            # ------------------------------------------------
            # Package
            # ------------------------------------------------

            package_version(
                target_version,
                files
            )

            new_state[series] = target_version

            changed.append(series)

            log(
                f"{series}: update completed"
            )

        # ----------------------------------------------------
        # 3. Save state
        # ----------------------------------------------------

        if changed:
            save_state(new_state)

            log(
                f"Updated series: {', '.join(changed)}"
            )
        else:
            log("No LTS kernel update")

        # ----------------------------------------------------
        # 4. Generate workflow information
        # ----------------------------------------------------

        with open(
            "kernel-result.json",
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                {
                    "changed": changed,
                    "versions": new_state
                },
                f,
                indent=2,
                ensure_ascii=False,
                sort_keys=True
            )

        log("kernel-result.json written")

    finally:

        await client.disconnect()

        log("Telegram disconnected")


if __name__ == "__main__":
    asyncio.run(main())
