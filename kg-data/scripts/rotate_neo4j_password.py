"""Interactively rotate the local Neo4j user's password without exposing it.

The current password is read with hidden input. A strong random replacement is
generated in memory, verified through a fresh Bolt connection, and optionally
stored in the ignored ``server/.env`` file. No password is accepted as a CLI
argument or written to logs.
"""

from __future__ import annotations

import argparse
import getpass
import logging
import re
import secrets
from pathlib import Path

from neo4j import GraphDatabase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_FILE = PROJECT_ROOT / "server" / ".env"
LOGGER = logging.getLogger("reasonix.rotate_neo4j_password")


def parse_args() -> argparse.Namespace:
    """Parse non-sensitive connection and persistence options."""
    parser = argparse.ArgumentParser(description="交互式轮换 Neo4j 当前用户密码")
    parser.add_argument("--uri", default="bolt://localhost:7687", help="Neo4j Bolt URI")
    parser.add_argument("--user", default="neo4j", help="Neo4j 用户名")
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="轮换成功后写入的本地环境文件",
    )
    parser.add_argument(
        "--write-env",
        action="store_true",
        help="将新密码写入被 Git 忽略的环境文件",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="确认这是受控本地实例的凭证轮换",
    )
    parser.add_argument(
        "--recover-auth-disabled",
        action="store_true",
        help="认证已由运维临时关闭时，重置指定用户密码",
    )
    return parser.parse_args()


def update_env_file(path: Path, uri: str, user: str, password: str) -> None:
    """Update only Neo4j connection keys in a local dotenv file."""
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        text = ""

    replacements = {
        "NEO4J_URI": uri,
        "NEO4J_USER": user,
        "NEO4J_PASSWORD": password,
    }
    for key, value in replacements.items():
        line = f"{key}={value}"
        pattern = re.compile(rf"(?m)^\s*{re.escape(key)}\s*=.*$")
        if pattern.search(text):
            text = pattern.sub(line, text, count=1)
        else:
            if text and not text.endswith("\n"):
                text += "\n"
            text += line + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")


def verify_connection(uri: str, user: str, password: str) -> None:
    """Verify authentication using a fresh driver after rotation."""
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as session:
            record = session.run("RETURN 1 AS ok").single()
            if not record or record["ok"] != 1:
                raise RuntimeError("Neo4j 新凭证连接验证未返回预期结果")
    finally:
        driver.close()


def rotate_password(uri: str, user: str, current_password: str) -> str:
    """Rotate the logged-in user's password and return the new value in memory."""
    new_password = secrets.token_urlsafe(32)
    driver = GraphDatabase.driver(uri, auth=(user, current_password))
    try:
        with driver.session(database="system") as session:
            session.run(
                "ALTER CURRENT USER SET PASSWORD "
                "FROM $oldPassword TO $newPassword",
                oldPassword=current_password,
                newPassword=new_password,
            ).consume()
    finally:
        driver.close()
    verify_connection(uri, user, new_password)
    return new_password


def recover_password_with_auth_disabled(uri: str, user: str) -> str:
    """Set a new password while local authentication is temporarily disabled."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", user):
        raise ValueError("Neo4j 用户名包含不安全字符")
    new_password = secrets.token_urlsafe(32)
    driver = GraphDatabase.driver(uri, auth=None)
    try:
        with driver.session(database="system") as session:
            session.run(
                f"ALTER USER {user} SET PASSWORD $newPassword CHANGE NOT REQUIRED",
                newPassword=new_password,
            ).consume()
    finally:
        driver.close()
    return new_password


def main() -> int:
    """Run an explicitly confirmed local password rotation."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args()
    if not args.confirm or not args.write_env:
        LOGGER.error("必须同时提供 --confirm 和 --write-env，拒绝执行轮换")
        return 2

    try:
        if args.recover_auth_disabled:
            new_password = recover_password_with_auth_disabled(args.uri, args.user)
        else:
            current_password = getpass.getpass("当前 Neo4j 密码（不回显）：")
            if not current_password:
                LOGGER.error("当前密码不能为空")
                return 2
            new_password = rotate_password(args.uri, args.user, current_password)
        verify_connection(args.uri, args.user, new_password)
        update_env_file(args.env_file, args.uri, args.user, new_password)
    except Exception:
        LOGGER.exception("Neo4j 凭证轮换失败；未记录任何密码值")
        return 1

    LOGGER.info("Neo4j 用户凭证已轮换，新凭证已写入受 Git 忽略的环境文件：%s", args.env_file)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
