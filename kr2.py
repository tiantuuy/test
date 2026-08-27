#!/usr/bin/env python3

import asyncio
import json
import os
import re
import shutil
import tarfile
from pathlib import Path

from telethon import TelegramClient


# ============================================================
# 基础配置
# ============================================================

# 长期维护的 Kernel LTS 系列
LTS_SERIES = (
    "6.1",
    "6.12",
    "6.18",
)

# Telegram 扫描最近多少条消息
#
# 不建议太小。
# 频道如果以后增加其他消息，50 条可能不够。
#
# 300 条通常已经比较安全。
SCAN_LIMIT = int(
    os.environ.get("SCAN_LIMIT", "300")
)

# 状态文件
STATE_FILE = Path("latest.json")

# 下载目录
DOWNLOAD_ROOT = Path("dl")

# 最终 Release 文件目录
RELEASE_ROOT = Path("release")


# ============================================================
# 日志
# ============================================================

def log(message):
    print(f"[KR] {message}", flush=True)


# ============================================================
# 文件名解析
# ============================================================

# ------------------------------------------------------------
# 6.1
#
# 示例：
#
# header-6.1.157-rk35xx-flippy-2609a.tar.gz
# modules-6.1.157-rk35xx-flippy-2609a.tar.gz
# boot-6.1.157-rk35xx-flippy-2609a.tar.gz
# dtb-rockchip-6.1.157-rk35xx-flippy-2609a.tar.gz
#
# header-6.1.157-rk3588-flippy-2609a.tar.gz
# modules-6.1.157-rk3588-flippy-2609a.tar.gz
# boot-6.1.157-rk3588-flippy-2609a.tar.gz
# dtb-rockchip-6.1.157-rk3588-flippy-2609a.tar.gz
#
# 这里：
#
# Kernel release =
#   6.1.157-flippy-2609a
#
# Hardware =
#   rk35xx / rk3588
#
# ------------------------------------------------------------

RE_61 = re.compile(
    r"^(?P<type>"
    r"header|modules|boot|dtb-rockchip"
    r")"
    r"-(?P<patch>6\.1\.\d+)"
    r"-(?P<target>rk35xx|rk3588)"
    r"-flippy-(?P<flippy>.+)"
    r"\.tar\.gz$"
)


# ------------------------------------------------------------
# 6.12 / 6.18
#
# 示例：
#
# header-6.12.105-flippy-95+o.tar.gz
# modules-6.12.105-flippy-95+o.tar.gz
#
# header-6.18.46-flippy-95+.tar.gz
# modules-6.18.46-flippy-95+.tar.gz
#
# ------------------------------------------------------------

RE_STANDARD = re.compile(
    r"^(?P<type>"
    r"header|modules|boot|"
    r"dtb-rockchip|dtb-allwinner|dtb-amlogic"
    r")"
    r"-(?P<version>"
    r"6\.(?:12|18)\.\d+"
    r"-flippy-.+"
    r")"
    r"\.tar\.gz$"
)


# ============================================================
# 解析文件名
# ============================================================

def parse_filename(filename):
    """
    返回：

    6.1：

    {
        "series": "6.1",
        "version": "6.1.157-flippy-2609a",
        "type": "header",
        "target": "rk35xx"
    }

    6.12 / 6.18：

    {
        "series": "6.12",
        "version": "6.12.105-flippy-95+o",
        "type": "header",
        "target": None
    }
    """

    if not filename:
        return None

    filename = Path(filename).name

    # --------------------------------------------------------
    # 6.1
    # --------------------------------------------------------

    match = RE_61.fullmatch(filename)

    if match:

        patch = match.group("patch")
        target = match.group("target")
        flippy = match.group("flippy")
        file_type = match.group("type")

        version = (
            f"{patch}-flippy-{flippy}"
        )

        return {
            "series": "6.1",
            "version": version,
            "type": file_type,
            "target": target,
        }

    # --------------------------------------------------------
    # 6.12 / 6.18
    # --------------------------------------------------------

    match = RE_STANDARD.fullmatch(filename)

    if match:

        version = match.group("version")

        series_match = re.match(
            r"^(6\.(?:12|18))\.",
            version
        )

        if not series_match:
            return None

        series = series_match.group(1)

        return {
            "series": series,
            "version": version,
            "type": match.group("type"),
            "target": None,
        }

    return None


# ============================================================
# 版本排序
# ============================================================

def version_key(version):
    """
    只根据真正的 Linux 版本号排序。

    例如：

    6.1.157-flippy-2609a
    6.1.158-flippy-2609a

    返回：

    (6, 1, 157)
    (6, 1, 158)
    """

    match = re.match(
        r"^(\d+)\.(\d+)\.(\d+)",
        version or ""
    )

    if not match:
        return (
            0,
            0,
            0,
        )

    return tuple(
        int(x)
        for x in match.groups()
    )


# ============================================================
# 获取文件 Key
# ============================================================

def get_file_key(parsed):
    """
    6.1：

        rk35xx/header
        rk35xx/modules
        rk35xx/boot
        rk35xx/dtb-rockchip

        rk3588/header
        rk3588/modules
        rk3588/boot
        rk3588/dtb-rockchip

    6.12 / 6.18：

        header
        modules
        boot
        dtb-rockchip
        dtb-allwinner
        dtb-amlogic
    """

    series = parsed["series"]
    file_type = parsed["type"]
    target = parsed["target"]

    if series == "6.1":

        return (
            f"{target}/{file_type}"
        )

    return file_type


# ============================================================
# 每个 LTS 的完整文件要求
# ============================================================

def required_keys(series):
    """
    返回一个 LTS release 必须具备的文件集合。
    """

    if series == "6.1":

        return {
            "rk35xx/header",
            "rk35xx/modules",
            "rk35xx/boot",
            "rk35xx/dtb-rockchip",

            "rk3588/header",
            "rk3588/modules",
            "rk3588/boot",
            "rk3588/dtb-rockchip",
        }

    if series in ("6.12", "6.18"):

        return {
            "header",
            "modules",
            "boot",
            "dtb-rockchip",
            "dtb-allwinner",
            "dtb-amlogic",
        }

    return set()


# ============================================================
# 检查完整性
# ============================================================

def check_complete(series, files):
    """
    检查一个版本是否完整。

    files：

        {
            file_key: {
                "filename": ...,
                "msg": ...
            }
        }
    """

    required = required_keys(
        series
    )

    actual = set(
        files.keys()
    )

    missing = required - actual

    if missing:

        return False, sorted(
            missing
        )

    return True, []


# ============================================================
# 读取状态
# ============================================================

def load_state():
    """
    读取 latest.json。

    示例：

    {
      "6.1": "6.1.157-flippy-2609a",
      "6.12": "6.12.105-flippy-95+o",
      "6.18": "6.18.46-flippy-95+"
    }

    同时兼容旧版 latest.txt。
    """

    # --------------------------------------------------------
    # 新状态文件
    # --------------------------------------------------------

    if STATE_FILE.exists():

        try:

            with STATE_FILE.open(
                "r",
                encoding="utf-8"
            ) as f:

                data = json.load(f)

            if isinstance(data, dict):

                return data

        except Exception as exc:

            log(
                f"WARNING: failed to read "
                f"{STATE_FILE}: {exc}"
            )

    # --------------------------------------------------------
    # 兼容旧 latest.txt
    # --------------------------------------------------------

    old_file = Path(
        "latest.txt"
    )

    if old_file.exists():

        try:

            old_version = (
                old_file.read_text(
                    encoding="utf-8"
                ).strip()
            )

            if old_version.startswith(
                "6.18."
            ):

                log(
                    "Migrating old latest.txt "
                    "to latest.json"
                )

                return {
                    "6.18": old_version
                }

        except Exception as exc:

            log(
                f"WARNING: failed to migrate "
                f"latest.txt: {exc}"
            )

    return {}


# ============================================================
# 保存状态
# ============================================================

def save_state(state):

    temp_file = Path(
        f"{STATE_FILE}.tmp"
    )

    with temp_file.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            state,
            f,
            ensure_ascii=False,
            indent=2,
            sort_keys=True
        )

        f.write("\n")

    os.replace(
        temp_file,
        STATE_FILE
    )


# ============================================================
# 扫描 Telegram
# ============================================================

async def scan_channel(
    client,
    chat_id
):
    """
    扫描 Telegram 最近消息。

    重点：

    不是：

        找到第一个 6.1 就停止

    而是：

        先把所有候选版本分组
        ↓
        检查每个版本是否完整
        ↓
        从完整版本中选择最新版本

    因此 Telegram 正在分批发布文件时，
    不会误把半套文件当成正式版本。
    """

    log(
        f"Scanning latest "
        f"{SCAN_LIMIT} Telegram messages..."
    )

    releases = {
        series: {}
        for series in LTS_SERIES
    }

    async for msg in client.iter_messages(
        chat_id,
        limit=SCAN_LIMIT
    ):

        if not msg.file:
            continue

        filename = (
            msg.file.name or ""
        ).strip()

        parsed = parse_filename(
            filename
        )

        if not parsed:
            continue

        series = parsed[
            "series"
        ]

        version = parsed[
            "version"
        ]

        if series not in LTS_SERIES:
            continue

        key = get_file_key(
            parsed
        )

        # ----------------------------------------------------
        # 建立版本
        # ----------------------------------------------------

        if version not in releases[
            series
        ]:

            releases[
                series
            ][version] = {
                "files": {},
                "latest_msg_id": msg.id,
            }

        release = releases[
            series
        ][version]

        # ----------------------------------------------------
        # 同一个文件 Key 只保存最新消息
        #
        # iter_messages 默认从新到旧。
        # 因此第一次遇到的就是最新文件。
        # ----------------------------------------------------

        if key not in release[
            "files"
        ]:

            release[
                "files"
            ][key] = {
                "filename": filename,
                "msg": msg,
            }

        # ----------------------------------------------------
        # 保存这个版本最新出现的消息 ID
        # ----------------------------------------------------

        if msg.id > release[
            "latest_msg_id"
        ]:

            release[
                "latest_msg_id"
            ] = msg.id

    # ========================================================
    # 每个 LTS 选择最新完整版本
    # ========================================================

    result = {}

    for series in LTS_SERIES:

        candidates = []

        for version, release in releases[
            series
        ].items():

            files = release[
                "files"
            ]

            complete, missing = (
                check_complete(
                    series,
                    files
                )
            )

            if not complete:

                log(
                    f"[{series}] "
                    f"Ignore incomplete "
                    f"{version}: "
                    f"{len(files)}/"
                    f"{len(required_keys(series))}"
                )

                if missing:
                    log(
                        f"[{series}] "
                        f"Missing: "
                        f"{', '.join(missing)}"
                    )

                continue

            candidates.append(
                (
                    version_key(
                        version
                    ),
                    release[
                        "latest_msg_id"
                    ],
                    version,
                    files,
                )
            )

        # ----------------------------------------------------
        # 没有完整版本
        # ----------------------------------------------------

        if not candidates:

            log(
                f"[{series}] "
                f"No complete release found"
            )

            continue

        # ----------------------------------------------------
        # 版本号最大者为最新
        # ----------------------------------------------------

        candidates.sort(
            key=lambda x: (
                x[0],
                x[1],
            ),
            reverse=True
        )

        (
            _version_sort,
            _message_id,
            version,
            files,
        ) = candidates[0]

        result[series] = {
            "version": version,
            "files": files,
        }

        log(
            f"[{series}] "
            f"Latest complete: "
            f"{version} "
            f"({len(files)} files)"
        )

    return result


# ============================================================
# 删除旧下载目录
# ============================================================

def clean_download_directory(
    version
):

    directory = (
        DOWNLOAD_ROOT / version
    )

    if directory.exists():

        log(
            f"Removing old directory: "
            f"{directory}"
        )

        shutil.rmtree(
            directory
        )


# ============================================================
# 下载一个完整版本
# ============================================================

async def download_release(
    series,
    version,
    files
):
    """
    下载一个完整 release。

    6.1：

        8 文件

    6.12：

        6 文件

    6.18：

        6 文件
    """

    clean_download_directory(
        version
    )

    version_dir = (
        DOWNLOAD_ROOT / version
    )

    version_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    downloaded = []

    try:

        for key in sorted(files):

            item = files[key]

            filename = item[
                "filename"
            ]

            msg = item[
                "msg"
            ]

            # ------------------------------------------------
            # 6.1 按硬件目标分目录
            # ------------------------------------------------

            parsed = parse_filename(
                filename
            )

            if (
                series == "6.1"
                and parsed
            ):

                target = parsed[
                    "target"
                ]

                output_dir = (
                    version_dir / target
                )

            else:

                output_dir = (
                    version_dir
                )

            output_dir.mkdir(
                parents=True,
                exist_ok=True
            )

            output_file = (
                output_dir / filename
            )

            temp_file = Path(
                f"{output_file}.part"
            )

            log(
                f"[{series}] "
                f"Downloading: "
                f"{filename}"
            )

            try:

                await msg.download_media(
                    file=str(temp_file)
                )

                # --------------------------------------------
                # 下载完整性检查
                # --------------------------------------------

                if not temp_file.exists():

                    raise RuntimeError(
                        f"Download failed: "
                        f"{filename}"
                    )

                if temp_file.stat().st_size == 0:

                    raise RuntimeError(
                        f"Downloaded file is empty: "
                        f"{filename}"
                    )

                # --------------------------------------------
                # 原子移动
                # --------------------------------------------

                os.replace(
                    temp_file,
                    output_file
                )

                downloaded.append(
                    output_file
                )

                log(
                    f"[{series}] "
                    f"Downloaded: "
                    f"{filename}"
                )

            except Exception:

                if temp_file.exists():
                    temp_file.unlink()

                raise

        # ----------------------------------------------------
        # 最终数量检查
        # ----------------------------------------------------

        if len(downloaded) != len(files):

            raise RuntimeError(
                f"[{series}] "
                f"Downloaded "
                f"{len(downloaded)}/"
                f"{len(files)} files"
            )

        return version_dir

    except Exception:

        if version_dir.exists():
            shutil.rmtree(
                version_dir
            )

        raise


# ============================================================
# 打包
# ============================================================

def package_release(
    series,
    version,
    version_dir,
    files
):
    """
    打包：

    release/kernel-6.1.tar.gz
    release/kernel-6.12.tar.gz
    release/kernel-6.18.tar.gz

    6.1 内部：

        6.1.157-flippy-2609a/
        ├── rk35xx/
        │   ├── header...
        │   ├── modules...
        │   ├── boot...
        │   └── dtb-rockchip...
        │
        └── rk3588/
            ├── header...
            ├── modules...
            ├── boot...
            └── dtb-rockchip...
    """

    RELEASE_ROOT.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file = (
        RELEASE_ROOT
        / f"kernel-{series}.tar.gz"
    )

    # --------------------------------------------------------
    # 如果已有旧包，先删除
    # --------------------------------------------------------

    if output_file.exists():
        output_file.unlink()

    log(
        f"[{series}] "
        f"Packing {output_file}"
    )

    with tarfile.open(
        output_file,
        "w:gz"
    ) as tar:

        # ----------------------------------------------------
        # 6.1
        #
        # 明确保留 rk35xx / rk3588
        # ----------------------------------------------------

        if series == "6.1":

            for target in (
                "rk35xx",
                "rk3588",
            ):

                target_dir = (
                    version_dir / target
                )

                if not target_dir.exists():

                    raise RuntimeError(
                        f"[{series}] "
                        f"Missing target directory: "
                        f"{target}"
                    )

                # 包内结构：
                #
                # 6.1.157-flippy-2609a/rk35xx/
                # 6.1.157-flippy-2609a/rk3588/

                tar.add(
                    target_dir,
                    arcname=(
                        f"{version}/{target}"
                    )
                )

        # ----------------------------------------------------
        # 6.12 / 6.18
        # ----------------------------------------------------

        else:

            for filename in sorted(files):

                source_file = (
                    version_dir / filename
                )

                if not source_file.exists():

                    raise RuntimeError(
                        f"[{series}] "
                        f"Missing file: "
                        f"{source_file}"
                    )

                tar.add(
                    source_file,
                    arcname=(
                        f"{version}/{filename}"
                    )
                )

    # --------------------------------------------------------
    # 最终检查
    # --------------------------------------------------------

    if not output_file.exists():

        raise RuntimeError(
            f"[{series}] "
            f"Archive was not created"
        )

    size = output_file.stat().st_size

    if size == 0:

        raise RuntimeError(
            f"[{series}] "
            f"Archive is empty"
        )

    log(
        f"[{series}] "
        f"Created {output_file} "
        f"({size} bytes)"
    )

    return output_file


# ============================================================
# 主程序
# ============================================================

async def main():

    # --------------------------------------------------------
    # Environment
    # --------------------------------------------------------

    try:

        api_id = int(
            os.environ["API_ID"]
        )

        api_hash = os.environ[
            "API_HASH"
        ]

        chat_id = int(
            os.environ["CHAT_ID"]
        )

    except KeyError as exc:

        raise RuntimeError(
            f"Missing environment variable: "
            f"{exc}"
        )

    # --------------------------------------------------------
    # Load state
    # --------------------------------------------------------

    state = load_state()

    log(
        f"Local state: {state}"
    )

    # --------------------------------------------------------
    # Telegram
    # --------------------------------------------------------

    client = TelegramClient(
        "tg",
        api_id,
        api_hash
    )

    await client.start()

    log(
        "Telegram connected"
    )

    try:

        # ====================================================
        # 1. Scan channel
        # ====================================================

        releases = await scan_channel(
            client,
            chat_id
        )

        current_versions = {
            series: release["version"]
            for series, release
            in releases.items()
        }

        log(
            f"Latest versions: "
            f"{current_versions}"
        )

        # ====================================================
        # 2. Process each LTS independently
        # ====================================================

        new_state = dict(state)

        changed = []

        for series in LTS_SERIES:

            release = releases.get(
                series
            )

            if not release:

                log(
                    f"[{series}] "
                    f"No complete release found, skip"
                )

                continue

            target_version = release[
                "version"
            ]

            previous_version = state.get(
                series
            )

            log(
                f"[{series}] "
                f"previous={previous_version}, "
                f"latest={target_version}"
            )

            # ------------------------------------------------
            # 已经是最新
            # ------------------------------------------------

            if (
                previous_version
                == target_version
            ):

                archive = (
                    RELEASE_ROOT
                    / f"kernel-{series}.tar.gz"
                )

                if archive.exists():

                    log(
                        f"[{series}] "
                        f"{target_version} "
                        f"already current"
                    )

                    continue

                log(
                    f"[{series}] "
                    f"State is current but archive "
                    f"is missing, rebuild"
                )

            # ------------------------------------------------
            # 收集文件
            # ------------------------------------------------

            files = release[
                "files"
            ]

            complete, missing = (
                check_complete(
                    series,
                    files
                )
            )

            if not complete:

                raise RuntimeError(
                    f"[{series}] "
                    f"Release is incomplete. "
                    f"Missing: "
                    f"{', '.join(missing)}"
                )

            log(
                f"[{series}] "
                f"Complete release verified: "
                f"{len(files)} files"
            )

            # ------------------------------------------------
            # 下载
            # ------------------------------------------------

            version_dir = (
                await download_release(
                    series,
                    target_version,
                    files
                )
            )

            # ------------------------------------------------
            # 打包
            # ------------------------------------------------

            package_release(
                series,
                target_version,
                version_dir,
                files
            )

            # ------------------------------------------------
            # 只有下载 + 打包都成功，
            # 才更新状态。
            # ------------------------------------------------

            new_state[
                series
            ] = target_version

            changed.append(
                series
            )

            log(
                f"[{series}] "
                f"Update completed"
            )

        # ====================================================
        # 3. Save state
        # ====================================================

        if changed:

            save_state(
                new_state
            )

            log(
                f"State updated: "
                f"{new_state}"
            )

        else:

            log(
                "No kernel updates"
            )

        # ====================================================
        # 4. GitHub Actions result
        # ====================================================

        result = {
            "changed": changed,
            "versions": new_state,
            "current_versions": current_versions,
        }

        with open(
            "kernel-result.json",
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                result,
                f,
                ensure_ascii=False,
                indent=2,
                sort_keys=True
            )

            f.write("\n")

        log(
            "kernel-result.json written"
        )

    finally:

        await client.disconnect()

        log(
            "Telegram disconnected"
        )


# ============================================================
# Entry
# ============================================================

if __name__ == "__main__":
    asyncio.run(main())
