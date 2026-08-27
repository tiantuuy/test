#!/usr/bin/env python3

import asyncio
import json
import os
import re
import shutil
import tarfile
from pathlib import Path

from telethon import TelegramClient


# =========================================================
# 基础配置
# =========================================================

CHANNEL_SCAN_LIMIT = int(
    os.environ.get("CHANNEL_SCAN_LIMIT", "500")
)

DOWNLOAD_ROOT = Path("dl")
STATE_FILE = Path("latest.json")
RESULT_FILE = Path("kernel.json")


# =========================================================
# 需要长期维护的 kernel 分支
#
# 注意：
# 这里没有写具体版本号。
#
# 以后：
#
# 6.1.157-rk35xx-flippy-2609a
# 6.1.157-rk35xx-flippy-2610a
# 6.1.158-rk35xx-flippy-2701a
#
# 都可以自动识别。
# =========================================================

BRANCHES = {
    "6.1": {
        "required": 8,
    },

    "6.12": {
        "required": 6,
    },

    "6.18": {
        "required": 6,
    },
}


# =========================================================
# 6.1 文件格式
#
# 6.1 有两个平台：
#
# rk35xx:
#   header
#   modules
#   boot
#   dtb-rockchip
#
# rk3588:
#   header
#   modules
#   boot
#   dtb-rockchip
#
# 共 8 个文件。
# =========================================================

RE_61 = re.compile(
    r"^(?P<type>"
    r"header|modules|boot|dtb-rockchip"
    r")"
    r"-6\.1\.(?P<patch>\d+)"
    r"-(?P<platform>rk35xx|rk3588)"
    r"-flippy-(?P<suffix>.+?)"
    r"\.tar\.gz$"
)


# =========================================================
# 6.12 / 6.18 文件格式
#
# 每个版本：
#
# modules
# header
# boot
# dtb-rockchip
# dtb-allwinner
# dtb-amlogic
#
# 共 6 个文件。
# =========================================================

RE_STANDARD = re.compile(
    r"^(?P<type>"
    r"modules|header|boot|dtb-rockchip|"
    r"dtb-allwinner|dtb-amlogic"
    r")"
    r"-(?P<version>"
    r"6\.(?:12|18)\.\d+-flippy-.+?"
    r")"
    r"\.tar\.gz$"
)


# =========================================================
# 日志
# =========================================================

def log(message):
    print(f"[KR] {message}", flush=True)


# =========================================================
# 版本排序
# =========================================================

def version_sort_key(version):
    """
    用于比较：

    6.1.157-flippy-2609a
    6.1.158-flippy-2609a

    6.12.104-flippy-95+o
    6.12.105-flippy-95+o

    不依赖具体 suffix。
    """

    match = re.search(
        r"^(\d+)\.(\d+)\.(\d+)",
        version
    )

    if not match:
        return (0, 0, 0, version)

    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3))

    return (
        major,
        minor,
        patch,
        version,
    )


# =========================================================
# 解析 Telegram 文件名
# =========================================================

def parse_filename(name):
    """
    返回：

    {
        "branch": "6.1",
        "version": "6.1.157-flippy-2609a",
        "type": "header",
        "platform": "rk35xx"
    }

    或：

    {
        "branch": "6.18",
        "version": "6.18.46-flippy-95+",
        "type": "header",
        "platform": None
    }
    """

    if not name:
        return None

    # -----------------------------------------------------
    # 6.1
    # -----------------------------------------------------

    match = RE_61.fullmatch(name)

    if match:

        file_type = match.group("type")
        patch = match.group("patch")
        platform = match.group("platform")
        suffix = match.group("suffix")

        version = (
            f"6.1.{patch}"
            f"-flippy-{suffix}"
        )

        return {
            "branch": "6.1",
            "version": version,
            "type": file_type,
            "platform": platform,
        }

    # -----------------------------------------------------
    # 6.12 / 6.18
    # -----------------------------------------------------

    match = RE_STANDARD.fullmatch(name)

    if match:

        version = match.group("version")

        branch = (
            "6.12"
            if version.startswith("6.12.")
            else "6.18"
        )

        return {
            "branch": branch,
            "version": version,
            "type": match.group("type"),
            "platform": None,
        }

    return None


# =========================================================
# 计算一个版本需要的文件 key
# =========================================================

def file_key(parsed):
    """
    6.1：

        rk35xx/header
        rk35xx/modules
        rk35xx/boot
        rk35xx/dtb-rockchip

        rk3588/header
        ...

    6.12/6.18：

        header
        modules
        boot
        ...
    """

    branch = parsed["branch"]
    file_type = parsed["type"]
    platform = parsed["platform"]

    if branch == "6.1":

        return (
            f"{platform}/{file_type}"
        )

    return file_type


# =========================================================
# 判断一个版本是否完整
# =========================================================

def is_complete(branch, files):
    """
    files:
        {
            file_key: {
                "name": ...,
                "msg": ...
            }
        }
    """

    if branch == "6.1":

        required = {
            "rk35xx/header",
            "rk35xx/modules",
            "rk35xx/boot",
            "rk35xx/dtb-rockchip",

            "rk3588/header",
            "rk3588/modules",
            "rk3588/boot",
            "rk3588/dtb-rockchip",
        }

    else:

        required = {
            "header",
            "modules",
            "boot",
            "dtb-rockchip",
            "dtb-allwinner",
            "dtb-amlogic",
        }

    return required.issubset(
        set(files.keys())
    )


# =========================================================
# 读取历史状态
# =========================================================

def read_state():

    # -----------------------------------------------------
    # 新格式
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # 兼容旧版 latest.txt
    #
    # 如果你之前只有 6.18：
    #
    # latest.txt
    #
    # 自动迁移到：
    #
    # {
    #   "6.18": "..."
    # }
    # -----------------------------------------------------

    old_file = Path("latest.txt")

    if old_file.exists():

        try:

            old_version = (
                old_file.read_text(
                    encoding="utf-8"
                ).strip()
            )

            if old_version.startswith("6.18."):

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


# =========================================================
# 原子保存状态
# =========================================================

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
            indent=2
        )

        f.write("\n")

    temp_file.replace(
        STATE_FILE
    )


# =========================================================
# 扫描 Telegram
#
# 关键：
#
# 不是简单找“最新一条文件”。
#
# 而是：
#
# 1. 把消息按 branch/version 分组
# 2. 检查每个版本是否完整
# 3. 只选择完整版本
# 4. 从完整版本里选择最新的
#
# 这样 Telegram 刚发出一半文件时不会误判。
# =========================================================

async def scan_channel(
    client,
    chat_id
):

    log(
        f"Scanning latest "
        f"{CHANNEL_SCAN_LIMIT} Telegram messages..."
    )

    releases = {
        branch: {}
        for branch in BRANCHES
    }

    async for msg in client.iter_messages(
        chat_id,
        limit=CHANNEL_SCAN_LIMIT
    ):

        if not msg.file:
            continue

        name = (
            msg.file.name or ""
        ).strip()

        parsed = parse_filename(
            name
        )

        if not parsed:
            continue

        branch = parsed["branch"]
        version = parsed["version"]
        key = file_key(parsed)

        branch_releases = releases[
            branch
        ]

        if version not in branch_releases:

            branch_releases[
                version
            ] = {
                "files": {},
                "latest_msg_id": msg.id,
                "latest_date": msg.date,
            }

        release = branch_releases[
            version
        ]

        # -------------------------------------------------
        # 同一个 key 如果出现多次：
        #
        # iter_messages 是倒序，
        # 第一条就是更新的消息。
        # -------------------------------------------------

        if key not in release["files"]:

            release["files"][key] = {
                "name": name,
                "msg": msg,
            }

        # -------------------------------------------------
        # 记录这个版本最后出现的位置
        # -------------------------------------------------

        if msg.id > release["latest_msg_id"]:

            release["latest_msg_id"] = msg.id
            release["latest_date"] = msg.date

    # =====================================================
    # 从每个 branch 中选择最新的“完整版本”
    # =====================================================

    result = {}

    for branch in BRANCHES:

        candidates = []

        for version, release in releases[
            branch
        ].items():

            files = release["files"]

            if not is_complete(
                branch,
                files
            ):
                log(
                    f"[{branch}] "
                    f"Ignore incomplete "
                    f"{version}: "
                    f"{len(files)}/"
                    f"{BRANCHES[branch]['required']}"
                )

                continue

            candidates.append(
                (
                    version_sort_key(
                        version
                    ),
                    release["latest_msg_id"],
                    version,
                    files,
                )
            )

        if not candidates:

            log(
                f"[{branch}] "
                f"No complete release found"
            )

            continue

        # -------------------------------------------------
        # 首先按版本号排序
        # 如果版本号相同，再按 Telegram message id
        # -------------------------------------------------

        candidates.sort(
            key=lambda item: (
                item[0],
                item[1],
            ),
            reverse=True
        )

        _, _, version, files = (
            candidates[0]
        )

        result[branch] = {
            "version": version,
            "files": files,
        }

        log(
            f"[{branch}] Latest complete: "
            f"{version} "
            f"({len(files)} files)"
        )

    return result


# =========================================================
# 清理某个版本的旧下载目录
# =========================================================

def clean_version_dir(version):

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


# =========================================================
# 下载一个完整版本
# =========================================================

async def download_release(
    branch,
    version,
    files
):

    log(
        f"[{branch}] Preparing "
        f"{version}"
    )

    # -----------------------------------------------------
    # 每次重新下载新版本时，
    # 先删除可能残留的不完整目录。
    # -----------------------------------------------------

    clean_version_dir(
        version
    )

    directory = (
        DOWNLOAD_ROOT / version
    )

    directory.mkdir(
        parents=True,
        exist_ok=True
    )

    downloaded = []

    try:

        for key, item in files.items():

            name = item["name"]
            msg = item["msg"]

            output = (
                directory / name
            )

            log(
                f"[{branch}] "
                f"Downloading {name}"
            )

            await msg.download_media(
                file=str(output)
            )

            # -------------------------------------------------
            # 基本检查
            # -------------------------------------------------

            if not output.exists():

                raise RuntimeError(
                    f"Download failed: "
                    f"{name}"
                )

            if output.stat().st_size == 0:

                raise RuntimeError(
                    f"Downloaded file is empty: "
                    f"{name}"
                )

            downloaded.append(
                output
            )

        # -----------------------------------------------------
        # 最终确认数量
        # -----------------------------------------------------

        if len(downloaded) != len(files):

            raise RuntimeError(
                f"Downloaded "
                f"{len(downloaded)}/"
                f"{len(files)} files"
            )

        # -----------------------------------------------------
        # 打包
        # -----------------------------------------------------

        tar_path = Path(
            f"{version}.tar.gz"
        )

        if tar_path.exists():

            tar_path.unlink()

        log(
            f"[{branch}] Packing "
            f"{tar_path.name}"
        )

        with tarfile.open(
            tar_path,
            "w:gz"
        ) as tar:

            tar.add(
                directory,
                arcname=version
            )

        if not tar_path.exists():

            raise RuntimeError(
                f"Archive was not created: "
                f"{tar_path}"
            )

        if tar_path.stat().st_size == 0:

            raise RuntimeError(
                f"Archive is empty: "
                f"{tar_path}"
            )

        log(
            f"[{branch}] Successfully created "
            f"{tar_path.name}"
        )

        return tar_path

    except Exception:

        # -------------------------------------------------
        # 下载/打包任何一步失败：
        # 删除不完整目录。
        # -------------------------------------------------

        if directory.exists():

            shutil.rmtree(
                directory
            )

        raise


# =========================================================
# 写 GitHub Actions 结果
# =========================================================

def write_result(
    updated,
    current_versions
):

    data = {
        "updated": bool(updated),
        "updated_versions": updated,
        "current_versions": current_versions,
    }

    with RESULT_FILE.open(
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            ensure_ascii=False,
            indent=2
        )

        f.write("\n")


# =========================================================
# 主程序
# =========================================================

async def main():

    # -----------------------------------------------------
    # 环境变量
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # 历史版本
    # -----------------------------------------------------

    local_state = read_state()

    log(
        f"Local state: "
        f"{json.dumps(local_state, ensure_ascii=False)}"
    )

    # -----------------------------------------------------
    # Telegram
    # -----------------------------------------------------

    client = TelegramClient(
        "tg",
        api_id,
        api_hash
    )

    try:

        await client.start()

        log(
            "Telegram connected"
        )

        # -------------------------------------------------
        # 扫描频道
        # -------------------------------------------------

        releases = await scan_channel(
            client,
            chat_id
        )

        current_versions = {}

        for branch, release in releases.items():

            current_versions[
                branch
            ] = release["version"]

        log(
            "Current versions: "
            f"{json.dumps(current_versions, ensure_ascii=False)}"
        )

        # -------------------------------------------------
        # 找出需要更新的分支
        # -------------------------------------------------

        updated = {}

        for branch in BRANCHES:

            release = releases.get(
                branch
            )

            if not release:

                log(
                    f"[{branch}] "
                    f"No usable release"
                )

                continue

            version = release[
                "version"
            ]

            local_version = (
                local_state.get(branch)
            )

            if local_version == version:

                log(
                    f"[{branch}] "
                    f"{version} already current"
                )

                continue

            log(
                f"[{branch}] "
                f"NEW VERSION: {version}"
            )

            # -------------------------------------------------
            # 下载并打包
            # -------------------------------------------------

            await download_release(
                branch,
                version,
                release["files"]
            )

            updated[
                branch
            ] = version

        # -----------------------------------------------------
        # 只有成功完成下载和打包后，
        # 才更新 latest.json
        # -----------------------------------------------------

        if updated:

            new_state = dict(
                local_state
            )

            new_state.update(
                updated
            )

            save_state(
                new_state
            )

            log(
                f"State updated: "
                f"{json.dumps(new_state, ensure_ascii=False)}"
            )

        else:

            log(
                "No new kernel versions"
            )

        # -----------------------------------------------------
        # GitHub Actions 结果
        # -----------------------------------------------------

        write_result(
            updated,
            current_versions
        )

    finally:

        await client.disconnect()

        log(
            "Telegram disconnected"
        )


# =========================================================
# Entry
# =========================================================

if __name__ == "__main__":

    try:

        asyncio.run(
            main()
        )

    except Exception as exc:

        log(
            f"FATAL: {exc}"
        )

        # GitHub Actions 必须识别为失败
        raise
