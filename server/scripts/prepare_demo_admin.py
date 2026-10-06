"""Create one controlled development admin account without storing its password.

The command is intended for a configured, disposable or controlled demo
database. It prompts for the password without echoing it and never logs or
prints the password.
"""

from __future__ import annotations

import argparse
import getpass
import logging
from pathlib import Path
import secrets
import sys

import pyodbc

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.sqlserver import get_connection
from app.services.auth_service import hash_password


LOGGER = logging.getLogger("reasonix.prepare_demo_admin")


def parse_args() -> argparse.Namespace:
    """Parse the account fields that are safe to pass on the command line."""
    parser = argparse.ArgumentParser(description="准备受控开发环境管理员账号")
    parser.add_argument("--username", required=True, help="管理员登录名")
    parser.add_argument("--name", required=True, help="管理员显示名称")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="确认这是受控演示数据库；不提供则拒绝写入",
    )
    return parser.parse_args()


def main() -> int:
    """Prompt for a password and insert a unique admin account."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args()
    if not args.confirm:
        LOGGER.error("未提供 --confirm，拒绝写入数据库")
        return 2
    if not 3 <= len(args.username) <= 50 or not 1 <= len(args.name) <= 50:
        LOGGER.error("username 必须为 3-50 个字符，name 必须为 1-50 个字符")
        return 2

    password = getpass.getpass("演示管理员密码（不回显）：")
    password_again = getpass.getpass("再次输入演示管理员密码（不回显）：")
    if len(password) < 6:
        LOGGER.error("密码至少需要 6 个字符")
        return 2
    if password != password_again:
        LOGGER.error("两次输入的密码不一致")
        return 2

    user_id = f"adm_{secrets.token_hex(4)}"
    try:
        with get_connection() as connection:
            cursor = connection.cursor()
            cursor.execute("SELECT 1 FROM dbo.users WHERE username = ?", args.username)
            if cursor.fetchone() is not None:
                LOGGER.error("username 已存在，未写入任何数据")
                return 3
            cursor.execute(
                """
                INSERT INTO dbo.users
                    (user_id, username, password_hash, name, role, is_active)
                VALUES (?, ?, ?, ?, 'admin', 1)
                """,
                user_id,
                args.username,
                hash_password(password),
                args.name,
            )
            connection.commit()
    except pyodbc.Error:
        LOGGER.exception("管理员账号准备失败，数据库事务未提交")
        return 1

    LOGGER.info("管理员演示账号已创建：username=%s, user_id=%s", args.username, user_id)
    LOGGER.info("密码未记录；请通过安全渠道交给演示人员")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
