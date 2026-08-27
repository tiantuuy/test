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

# ============================================================
# 五个独立 Release
#
# 1. 6.1-rk35xx
# 2. 6.1-rk3588
# 3. 6.1 通用平台
# 4. 6.12
# 5. 6.18
#
# 注意：
#
# 6.1-rk35xx 与 6.1-rk3588 是完全独立的平台。
#
# 例如：
#
# 6.1.157-rk35xx
# 6.1.157-rk3588
#
# 不能放在同一个 Release。
#
# 同时：
#
# 6.1.163-flippy-94+o
#
# 没有 rk35xx/rk3588 后缀，
# 属于新的通用 6.1 Release。
# ============================================================

RELEASE_GROUPS = (
    "6.1-rk35xx",
    "6.1-rk3588",
    "6.1",
    "6.12",
    "6.18",
)


# Telegram 扫描消息数量
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
    print(
        f"[KR] {message}",
        flush=True
    )


# ============================================================
# 文件名正则
# ============================================================


# ------------------------------------------------------------
# 6.1 rk35xx / rk3588
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
# ------------------------------------------------------------

RE_61_TARGET = re.compile(
    r"^(?P<type>"
    r"header|modules|boot|dtb-rockchip"
    r")"
    r"-(?P<patch>6\.1\.\d+)"
    r"-(?P<target>rk35xx|rk3588)"
    r"-flippy-(?P<flippy>.+)"
    r"\.tar\.gz$"
)


# ------------------------------------------------------------
# 6.1 通用平台
#
# 示例：
#
# boot-6.1.163-flippy-94+o.tar.gz
# header-6.1.163-flippy-94+o.tar.gz
# modules-6.1.163-flippy-94+o.tar.gz
# dtb-rockchip-6.1.163-flippy-94+o.tar.gz
# dtb-allwinner-6.1.163-flippy-94+o.tar.gz
# dtb-amlogic-6.1.163-flippy-94+o.tar.gz
#
# 注意：
#
# 这里没有 rk35xx / rk3588。
#
# 因此不能与：
#
# 6.1.x-rk35xx
# 6.1.x-rk3588
#
# 混合。
# ------------------------------------------------------------

RE_61_GENERIC = re.compile(
    r"^(?P<type>"
    r"header|modules|boot|"
    r"dtb-rockchip|dtb-allwinner|dtb-amlogic"
    r")"
    r"-(?P<version>"
    r"6\.1\.\d+"
    r"-flippy-.+"
    r")"
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
    返回统一格式：

    {
        "group": "6.1-rk35xx",
        "series": "6.1",
        "version": "6.1.157-flippy-2609a",
        "type": "header",
        "target": "rk35xx"
    }

    或：

    {
        "group": "6.1",
        "series": "6.1",
        "version": "6.1.163-flippy-94+o",
        "type": "header",
        "target": None
    }

    或：

    {
        "group": "6.12",
        "series": "6.12",
        "version": "6.12.105-flippy-95+o",
        "type": "header",
        "target": None
    }
    """

    if not filename:
        return None

    filename = Path(
        filename
    ).name

    # ========================================================
    # 1. 6.1 rk35xx / rk3588
    # ========================================================

    match = RE_61_TARGET.fullmatch(
        filename
    )

    if match:

        patch = match.group(
            "patch"
        )

        target = match.group(
            "target"
        )

        flippy = match.group(
            "flippy"
        )

        file_type = match.group(
            "type"
        )

        version = (
            f"{patch}-flippy-{flippy}"
        )

        if target == "rk35xx":

            group = "6.1-rk35xx"

        elif target == "rk3588":

            group = "6.1-rk3588"

        else:

            return None

        return {
            "group": group,
            "series": "6.1",
            "version": version,
            "type": file_type,
            "target": target,
        }

    # ========================================================
    # 2. 6.1 通用平台
    #
    # 必须放在 target 解析之后。
    # ========================================================

    match = RE_61_GENERIC.fullmatch(
        filename
    )

    if match:

        version = match.group(
            "version"
        )

        file_type = match.group(
            "type"
        )

        return {
            "group": "6.1",
            "series": "6.1",
            "version": version,
            "type": file_type,
            "target": None,
        }

    # ========================================================
    # 3. 6.12 / 6.18
    # ========================================================

    match = RE_STANDARD.fullmatch(
        filename
    )

    if match:

        version = match.group(
            "version"
        )

        file_type = match.group(
            "type"
        )

        series_match = re.match(
            r"^(6\.(?:12|18))\.",
            version
        )

        if not series_match:
            return None

        series = series_match.group(
            1
        )

        return {
            "group": series,
            "series": series,
            "version": version,
            "type": file_type,
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
    6.1.163-flippy-94+o

    返回：

    (6, 1, 157)
    (6, 1, 163)
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
    每个 Release 内部独立使用 Key。

    6.1-rk35xx：

        header
        modules
        boot
        dtb-rockchip

    6.1-rk3588：

        header
        modules
        boot
        dtb-rockchip

    6.1：

        header
        modules
        boot
        dtb-rockchip
        dtb-allwinner
        dtb-amlogic

    6.12：

        header
        modules
        boot
        dtb-rockchip
        dtb-allwinner
        dtb-amlogic

    6.18：

        header
        modules
        boot
        dtb-rockchip
        dtb-allwinner
        dtb-amlogic
    """

    return parsed[
        "type"
    ]


# ============================================================
# 每个 Release 的完整文件要求
# ============================================================

def required_keys(group):
    """
    返回一个 Release 必须具备的文件集合。
    """

    # --------------------------------------------------------
    # rk35xx
    # --------------------------------------------------------

    if group == "6.1-rk35xx":

        return {
            "header",
            "modules",
            "boot",
            "dtb-rockchip",
        }

    # --------------------------------------------------------
    # rk3588
    # --------------------------------------------------------

    if group == "6.1-rk3588":

        return {
            "header",
            "modules",
            "boot",
            "dtb-rockchip",
        }

    # --------------------------------------------------------
    # 通用 6.1
    # --------------------------------------------------------

    if group == "6.1":

        return {
            "header",
            "modules",
            "boot",
            "dtb-rockchip",
            "dtb-allwinner",
            "dtb-amlogic",
        }

    # --------------------------------------------------------
    # 6.12 / 6.18
    # --------------------------------------------------------

    if group in (
        "6.12",
        "6.18",
    ):

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

def check_complete(
    group,
    files
):
    """
    检查一个版本是否完整。
    """

    required = required_keys(
        group
    )

    actual = set(
        files.keys()
    )

    missing = (
        required - actual
    )

    if missing:

        return (
            False,
            sorted(missing)
        )

    return (
        True,
        []
    )


# ============================================================
# Release 文件名
# ============================================================

def release_filename(group):
    """
    五个最终 Release 包：

        kernel-6.1-rk35xx.tar.gz
        kernel-6.1-rk3588.tar.gz
        kernel-6.1.tar.gz
        kernel-6.12.tar.gz
        kernel-6.18.tar.gz
    """

    return (
        RELEASE_ROOT
        / f"kernel-{group}.tar.gz"
    )


# ============================================================
# 下载目录名称
# ============================================================

def download_directory(
    group,
    version
):
    """
    不同平台使用不同目录。

    防止：

        6.1.157-rk35xx
        6.1.157-rk3588
        6.1.163

    互相覆盖。
    """

    safe_group = (
        group.replace(
            "/",
            "_"
        )
    )

    return (
        DOWNLOAD_ROOT
        / safe_group
        / version
    )


# ============================================================
# 读取状态
# ============================================================

def load_state():
    """
    latest.json 示例：

    {
      "6.1": "6.1.163-flippy-94+o",
      "6.1-rk35xx": "6.1.157-flippy-2609a",
      "6.1-rk3588": "6.1.157-flippy-2609a",
      "6.12": "6.12.105-flippy-95+o",
      "6.18": "6.18.46-flippy-95+"
    }
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

                data = json.load(
                    f
                )

            if isinstance(
                data,
                dict
            ):

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

            if old_version:

                log(
                    "Migrating old "
                    "latest.txt to latest.json"
                )

                return {
                    "6.18": old_version
                }

        except Exception as exc:

            log(
                f"WARNING: failed to migrate "
                f"{old_file}: {exc}"
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

    重点逻辑：

    Telegram：

        6.1.163
        6.1.157-rk35xx
        6.1.157-rk3588
        6.12.x
        6.18.x

    会被分成五个完全独立的 Release Group。

    --------------------------------------------------------

    Group：

        6.1-rk35xx

    只接受：

        *-6.1.xxx-rk35xx-*

    --------------------------------------------------------

    Group：

        6.1-rk3588

    只接受：

        *-6.1.xxx-rk3588-*

    --------------------------------------------------------

    Group：

        6.1

    只接受：

        *-6.1.xxx-flippy-*

    且不能有：

        -rk35xx-
        -rk3588-

    --------------------------------------------------------

    因此三个 6.1 平台完全不会混淆。
    """

    log(
        f"Scanning latest "
        f"{SCAN_LIMIT} Telegram messages..."
    )

    releases = {
        group: {}
        for group in RELEASE_GROUPS
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

        group = parsed[
            "group"
        ]

        version = parsed[
            "version"
        ]

        if group not in RELEASE_GROUPS:
            continue

        key = get_file_key(
            parsed
        )

        # ----------------------------------------------------
        # 建立版本
        # ----------------------------------------------------

        if version not in releases[
            group
        ]:

            releases[
                group
            ][version] = {
                "files": {},
                "latest_msg_id": msg.id,
            }

        release = releases[
            group
        ][version]

        # ----------------------------------------------------
        # 同一个文件 Key 只保存最新消息
        #
        # iter_messages 默认从新到旧。
        #
        # 第一次遇到的同名文件就是最新消息。
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
        # 保存该版本最新消息 ID
        # ----------------------------------------------------

        if msg.id > release[
            "latest_msg_id"
        ]:

            release[
                "latest_msg_id"
            ] = msg.id

    # ========================================================
    # 五个 Release 分别选择最新完整版本
    # ========================================================

    result = {}

    for group in RELEASE_GROUPS:

        candidates = []

        for (
            version,
            release
        ) in releases[
            group
        ].items():

            files = release[
                "files"
            ]

            complete, missing = (
                check_complete(
                    group,
                    files
                )
            )

            if not complete:

                log(
                    f"[{group}] "
                    f"Ignore incomplete "
                    f"{version}: "
                    f"{len(files)}/"
                    f"{len(required_keys(group))}"
                )

                if missing:

                    log(
                        f"[{group}] "
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
                f"[{group}] "
                f"No complete release found"
            )

            continue

        # ----------------------------------------------------
        # Linux 版本号最大者优先
        #
        # 例如：
        #
        # 6.1.163
        #
        # 大于：
        #
        # 6.1.157
        #
        # 但是这里只在同一个 group 内比较。
        #
        # 因此不会出现：
        #
        # 6.1.163
        #
        # 把：
        #
        # 6.1.157-rk35xx
        #
        # 顶掉的问题。
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

        result[group] = {
            "version": version,
            "files": files,
        }

        log(
            f"[{group}] "
            f"Latest complete: "
            f"{version} "
            f"({len(files)} files)"
        )

    return result


# ============================================================
# 删除旧下载目录
# ============================================================

def clean_download_directory(
    group,
    version
):

    directory = download_directory(
        group,
        version
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
# 下载完整版本
# ============================================================

async def download_release(
    group,
    version,
    files
):
    """
    下载一个完整 Release。

    6.1-rk35xx：

        4 文件

    6.1-rk3588：

        4 文件

    6.1：

        6 文件

    6.12：

        6 文件

    6.18：

        6 文件
    """

    clean_download_directory(
        group,
        version
    )

    version_dir = download_directory(
        group,
        version
    )

    version_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    downloaded = []

    try:

        for key in sorted(files):

            item = files[
                key
            ]

            filename = item[
                "filename"
            ]

            msg = item[
                "msg"
            ]

            output_dir = (
                version_dir
            )

            output_dir.mkdir(
                parents=True,
                exist_ok=True
            )

            output_file = (
                output_dir
                / filename
            )

            temp_file = Path(
                f"{output_file}.part"
            )

            log(
                f"[{group}] "
                f"Downloading: "
                f"{filename}"
            )

            try:

                await msg.download_media(
                    file=str(
                        temp_file
                    )
                )

                # --------------------------------------------
                # 下载完整性检查
                # --------------------------------------------

                if not temp_file.exists():

                    raise RuntimeError(
                        f"Download failed: "
                        f"{filename}"
                    )

                if (
                    temp_file.stat().st_size
                    == 0
                ):

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
                    f"[{group}] "
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

        if (
            len(downloaded)
            != len(files)
        ):

            raise RuntimeError(
                f"[{group}] "
                f"Downloaded "
                f"{len(downloaded)}/"
                f"{len(files)} files"
            )

        # ----------------------------------------------------
        # 再次检查磁盘上的文件
        # ----------------------------------------------------

        for key in files:

            filename = files[
                key
            ][
                "filename"
            ]

            path = (
                version_dir
                / filename
            )

            if not path.exists():

                raise RuntimeError(
                    f"[{group}] "
                    f"Missing downloaded file: "
                    f"{path}"
                )

            if not path.is_file():

                raise RuntimeError(
                    f"[{group}] "
                    f"Not a regular file: "
                    f"{path}"
                )

            if (
                path.stat().st_size
                == 0
            ):

                raise RuntimeError(
                    f"[{group}] "
                    f"Empty downloaded file: "
                    f"{path}"
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
    group,
    version,
    version_dir,
    files
):
    """
    创建最终 Release。

    五个包：

        kernel-6.1-rk35xx.tar.gz
        kernel-6.1-rk3588.tar.gz
        kernel-6.1.tar.gz
        kernel-6.12.tar.gz
        kernel-6.18.tar.gz


    --------------------------------------------------------

    6.1-rk35xx：

        6.1.157-flippy-2609a/
        ├── boot-...
        ├── dtb-rockchip-...
        ├── header-...
        └── modules-...


    --------------------------------------------------------

    6.1-rk3588：

        6.1.157-flippy-2609a/
        ├── boot-...
        ├── dtb-rockchip-...
        ├── header-...
        └── modules-...


    --------------------------------------------------------

    6.1 通用：

        6.1.163-flippy-94+o/
        ├── boot-...
        ├── dtb-allwinner-...
        ├── dtb-amlogic-...
        ├── dtb-rockchip-...
        ├── header-...
        └── modules-...


    --------------------------------------------------------

    6.12 / 6.18：

        同样为对应版本目录。
    """

    RELEASE_ROOT.mkdir(
        parents=True,
        exist_ok=True
    )

    output_file = release_filename(
        group
    )

    # --------------------------------------------------------
    # 删除旧 Release
    # --------------------------------------------------------

    if output_file.exists():

        log(
            f"[{group}] "
            f"Removing old archive: "
            f"{output_file}"
        )

        output_file.unlink()

    log(
        f"[{group}] "
        f"Packing {output_file}"
    )

    with tarfile.open(
        output_file,
        "w:gz"
    ) as tar:

        # ----------------------------------------------------
        # 所有五种 Release 都使用：
        #
        # version/
        #     filename
        #
        # 不再把 rk35xx/rk3588 混在一起。
        # ----------------------------------------------------

        for key in sorted(files):

            item = files[
                key
            ]

            filename = item[
                "filename"
            ]

            source_file = (
                version_dir
                / filename
            )

            log(
                f"[{group}] "
                f"Adding file: "
                f"{source_file}"
            )

            # ------------------------------------------------
            # 文件必须存在
            # ------------------------------------------------

            if not source_file.exists():

                raise RuntimeError(
                    f"[{group}] "
                    f"Missing file: "
                    f"{source_file}"
                )

            if not source_file.is_file():

                raise RuntimeError(
                    f"[{group}] "
                    f"Expected regular file, "
                    f"but found: "
                    f"{source_file}"
                )

            # ------------------------------------------------
            # 文件不能是空文件
            # ------------------------------------------------

            file_size = (
                source_file.stat().st_size
            )

            if file_size == 0:

                raise RuntimeError(
                    f"[{group}] "
                    f"File is empty: "
                    f"{source_file}"
                )

            # ------------------------------------------------
            # 添加到：
            #
            # version/filename
            # ------------------------------------------------

            tar.add(
                source_file,
                arcname=(
                    f"{version}/{filename}"
                )
            )

    # ========================================================
    # 最终检查
    # ========================================================

    if not output_file.exists():

        raise RuntimeError(
            f"[{group}] "
            f"Archive was not created"
        )

    size = output_file.stat().st_size

    if size == 0:

        raise RuntimeError(
            f"[{group}] "
            f"Archive is empty"
        )

    log(
        f"[{group}] "
        f"Created {output_file} "
        f"({size} bytes)"
    )

    return output_file


# ============================================================
# GitHub Actions 输出
# ============================================================

def write_result(
    changed,
    versions,
    current_versions
):

    result = {
        "changed": changed,
        "versions": versions,
        "current_versions": current_versions,
        "release_groups": list(
            RELEASE_GROUPS
        ),
        "release_files": {
            group: str(
                release_filename(group)
            )
            for group in RELEASE_GROUPS
        },
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


# ============================================================
# 主程序
# ============================================================

async def main():

    # ========================================================
    # Environment
    # ========================================================

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

    # ========================================================
    # Load state
    # ========================================================

    state = load_state()

    log(
        f"Local state: {state}"
    )

    # ========================================================
    # Telegram
    # ========================================================

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
            group: release[
                "version"
            ]
            for group, release
            in releases.items()
        }

        log(
            f"Latest versions: "
            f"{current_versions}"
        )

        # ====================================================
        # 2. Process five Release groups
        # ====================================================

        new_state = dict(
            state
        )

        changed = []

        for group in RELEASE_GROUPS:

            release = releases.get(
                group
            )

            # ------------------------------------------------
            # 没有完整版本
            # ------------------------------------------------

            if not release:

                log(
                    f"[{group}] "
                    f"No complete release found, skip"
                )

                continue

            target_version = release[
                "version"
            ]

            previous_version = state.get(
                group
            )

            log(
                f"[{group}] "
                f"previous={previous_version}, "
                f"latest={target_version}"
            )

            archive = release_filename(
                group
            )

            # =================================================
            # 已经是最新
            # =================================================

            if (
                previous_version
                == target_version
            ):

                if archive.exists():

                    log(
                        f"[{group}] "
                        f"{target_version} "
                        f"already current"
                    )

                    continue

                log(
                    f"[{group}] "
                    f"State is current but archive "
                    f"is missing, rebuild"
                )

            # =================================================
            # 再次检查完整性
            # =================================================

            files = release[
                "files"
            ]

            complete, missing = (
                check_complete(
                    group,
                    files
                )
            )

            if not complete:

                raise RuntimeError(
                    f"[{group}] "
                    f"Release is incomplete. "
                    f"Missing: "
                    f"{', '.join(missing)}"
                )

            log(
                f"[{group}] "
                f"Complete release verified: "
                f"{len(files)} files"
            )

            # =================================================
            # 下载
            # =================================================

            version_dir = (
                await download_release(
                    group,
                    target_version,
                    files
                )
            )

            # =================================================
            # 打包
            # =================================================

            package_release(
                group,
                target_version,
                version_dir,
                files
            )

            # =================================================
            # 只有下载和打包都成功，
            # 才更新状态。
            # =================================================

            new_state[
                group
            ] = target_version

            changed.append(
                group
            )

            log(
                f"[{group}] "
                f"Update completed"
            )

        # ====================================================
        # 3. 保存状态
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
        # 4. 写 GitHub Actions 结果
        # ====================================================

        write_result(
            changed,
            new_state,
            current_versions
        )

        # ====================================================
        # 5. 显示五个 Release
        # ====================================================

        log(
            "================================================"
        )

        log(
            "Five Release packages:"
        )

        for group in RELEASE_GROUPS:

            archive = release_filename(
                group
            )

            if archive.exists():

                size = (
                    archive.stat().st_size
                )

                version = new_state.get(
                    group,
                    "N/A"
                )

                log(
                    f"{group}: "
                    f"{version} -> "
                    f"{archive} "
                    f"({size} bytes)"
                )

            else:

                log(
                    f"{group}: "
                    f"NOT GENERATED"
                )

        log(
            "================================================"
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

    asyncio.run(
        main()
    )
