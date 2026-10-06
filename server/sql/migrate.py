"""Run versioned SQL Server migrations without destructive defaults.

Usage from the repository root::

    python server/sql/migrate.py --dry-run
    python server/sql/migrate.py

The runner intentionally does not support a reset/clean flag. Database reset is
an explicit DBA operation outside this migration workflow.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
from pathlib import Path
from typing import Dict, Iterable, List

import pyodbc


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DOTENV_PATH = PROJECT_ROOT / "server" / ".env"
LOGGER = logging.getLogger("reasonix.migrations")
_MIGRATION_NAME = re.compile(r"^(?P<version>\d{4})_[a-z0-9][a-z0-9_-]*\.sql$")
_GO_LINE = re.compile(r"^\s*GO\s*(?:--.*)?$", re.IGNORECASE)
_DESTRUCTIVE_SQL = re.compile(
    r"\bDROP\s+(?:DATABASE|TABLE|SCHEMA|INDEX)\b", re.IGNORECASE
)


def load_dotenv(path: Path) -> Dict[str, str]:
    """Read simple KEY=VALUE entries from a local dotenv file."""
    values: Dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        if key.strip() and value:
            values[key.strip()] = value
    return values


def config_value(key: str, dotenv: Dict[str, str], default: str = "") -> str:
    """Resolve process environment first, then server/.env, then default."""
    return os.environ[key] if key in os.environ else dotenv.get(key, default)


def split_batches(sql: str) -> List[str]:
    """Split SQL Server batches at standalone GO lines."""
    batches: List[str] = []
    current: List[str] = []
    for line in sql.splitlines():
        if _GO_LINE.match(line):
            batch = "\n".join(current).strip()
            if batch:
                batches.append(batch)
            current = []
        else:
            current.append(line)
    batch = "\n".join(current).strip()
    if batch:
        batches.append(batch)
    return batches


def migration_files(directory: Path) -> Iterable[tuple[str, Path]]:
    """Yield validated migration versions in lexical order."""
    found: List[tuple[str, Path]] = []
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION_NAME.match(path.name)
        if not match:
            raise ValueError(
                f"迁移文件名不符合 NNNN_description.sql 规则: {path.name}"
            )
        found.append((match.group("version"), path))
    versions = [version for version, _ in found]
    if len(versions) != len(set(versions)):
        raise ValueError("迁移版本号重复")
    return found


def validate_migration(sql: str, path: Path) -> None:
    """Reject destructive DDL in an incremental migration."""
    non_comment_lines = "\n".join(
        line for line in sql.splitlines() if not line.lstrip().startswith("--")
    )
    if _DESTRUCTIVE_SQL.search(non_comment_lines):
        raise ValueError(f"迁移 {path.name} 包含禁止的破坏性 DROP 操作")


def build_connection_string(dotenv: Dict[str, str]) -> str:
    """Build a pyodbc connection string without logging credentials."""
    driver = config_value("SQLSERVER_DRIVER", dotenv, "ODBC Driver 17 for SQL Server")
    host = config_value("SQLSERVER_HOST", dotenv, "localhost")
    port = config_value("SQLSERVER_PORT", dotenv, "1433")
    database = config_value("SQLSERVER_DATABASE", dotenv, "adaptive_learning")
    trusted = config_value("SQLSERVER_TRUSTED_CONNECTION", dotenv, "no").lower()
    values = [
        f"DRIVER={{{driver}}}",
        f"SERVER={host},{port}",
        f"DATABASE={database}",
        f"Encrypt={config_value('SQLSERVER_ENCRYPT', dotenv, 'no')}",
        "TrustServerCertificate="
        + config_value("SQLSERVER_TRUST_SERVER_CERTIFICATE", dotenv, "yes"),
    ]
    if trusted == "yes":
        values.append("Trusted_Connection=yes")
    else:
        values.extend(
            [
                f"UID={config_value('SQLSERVER_USER', dotenv, 'sa')}",
                f"PWD={config_value('SQLSERVER_PASSWORD', dotenv)}",
            ]
        )
    return ";".join(values)


def ensure_ledger(connection: pyodbc.Connection) -> None:
    """Create the migration ledger if this is its first run."""
    cursor = connection.cursor()
    cursor.execute(
        """
        IF OBJECT_ID('dbo.schema_migrations', 'U') IS NULL
        BEGIN
            CREATE TABLE dbo.schema_migrations (
                version VARCHAR(32) NOT NULL,
                applied_at DATETIME2 NOT NULL CONSTRAINT DF_schema_migrations_applied_at DEFAULT SYSUTCDATETIME(),
                CONSTRAINT PK_schema_migrations PRIMARY KEY CLUSTERED (version)
            );
        END
        """
    )
    connection.commit()


def applied_versions(connection: pyodbc.Connection) -> set[str]:
    """Return migration versions already committed in the target database."""
    cursor = connection.cursor()
    return {str(row[0]) for row in cursor.execute("SELECT version FROM dbo.schema_migrations")}


def apply_migration(connection: pyodbc.Connection, version: str, path: Path) -> None:
    """Apply one migration atomically and record it only after success."""
    sql = path.read_text(encoding="utf-8-sig")
    validate_migration(sql, path)
    batches = split_batches(sql)
    LOGGER.info("应用迁移 %s (%s)，共 %d 个 SQL batch", version, path.name, len(batches))
    try:
        cursor = connection.cursor()
        for batch in batches:
            cursor.execute(batch)
        cursor.execute(
            "INSERT INTO dbo.schema_migrations (version) VALUES (?)", version
        )
        connection.commit()
    except Exception:
        connection.rollback()
        LOGGER.exception("迁移 %s 失败，已回滚当前迁移", version)
        raise


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="执行 SQL Server 版本化迁移")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只检查文件名、顺序和破坏性 SQL，不连接数据库",
    )
    parser.add_argument(
        "--migrations-dir",
        default=str(DEFAULT_MIGRATIONS_DIR),
        help="迁移目录（默认 server/sql/migrations）",
    )
    return parser.parse_args()


def main() -> int:
    """Validate and optionally apply all pending migrations."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    args = parse_args()
    directory = Path(args.migrations_dir).resolve()
    files = list(migration_files(directory))
    for _, path in files:
        validate_migration(path.read_text(encoding="utf-8-sig"), path)
    if args.dry_run:
        for version, path in files:
            LOGGER.info("迁移待检查: %s (%s)", version, path.name)
        LOGGER.info("dry-run 通过：未连接数据库，未修改任何数据")
        return 0

    dotenv = load_dotenv(DOTENV_PATH)
    connection = pyodbc.connect(build_connection_string(dotenv), timeout=10)
    connection.autocommit = False
    try:
        ensure_ledger(connection)
        applied = applied_versions(connection)
        for version, path in files:
            if version in applied:
                LOGGER.info("跳过已应用迁移 %s (%s)", version, path.name)
                continue
            apply_migration(connection, version, path)
    finally:
        connection.close()
    LOGGER.info("迁移完成：未执行任何 DROP 或清库操作")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
