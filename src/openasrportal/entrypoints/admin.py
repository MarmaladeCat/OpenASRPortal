"""Explicit, interactive database-owner password recovery. No password arguments."""

import argparse
import getpass
from pathlib import Path

from ..storage.store import Store


def reset_password(directory):
    directory = Path(directory)
    if not (directory / "portal.db").is_file():
        raise ValueError("指定目录中不存在 Portal 数据库；不会创建新库或切换数据路径")
    password = getpass.getpass("新的 Portal 管理密码（至少 12 字符）：")
    if password != getpass.getpass("再次输入："):
        raise ValueError("两次密码不一致，数据库未修改")
    Store(directory).auth.set_password(password)
    print("管理密码已更新；已有管理会话已失效，识别 Key 和业务数据保留。")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        reset_password(args.data_dir)
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
