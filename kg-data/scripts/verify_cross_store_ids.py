"""Verify SQL Server knowledge-point references against Neo4j IDs.

The relationship between SQL Server and Neo4j is intentionally application-level
because the two stores cannot share a physical foreign key. This check is safe
and read-only: it only selects distinct IDs from both stores.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Dict, Set

import pyodbc
from neo4j import GraphDatabase
from neo4j.exceptions import Neo4jError, ServiceUnavailable


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOTENV_PATH = PROJECT_ROOT / "server" / ".env"
LOGGER = logging.getLogger("reasonix.cross_store_check")


def parse_args() -> argparse.Namespace:
    """Parse optional, read-only verification probes."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--simulate-sql-id",
        metavar="ID",
        help="仅用于隔离负例：将一个未写入数据库的 ID 加入 SQL 集合并预期返回 2",
    )
    return parser.parse_args()


def load_dotenv(path: Path) -> Dict[str, str]:
    """Read simple KEY=VALUE pairs from the backend dotenv file."""
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


def env_value(key: str, dotenv: Dict[str, str], default: str = "") -> str:
    """Resolve environment variables before server/.env values."""
    return os.environ[key] if key in os.environ else dotenv.get(key, default)


def sql_connection_string(dotenv: Dict[str, str]) -> str:
    """Build a SQL Server connection string without logging its password."""
    driver = env_value("SQLSERVER_DRIVER", dotenv, "ODBC Driver 17 for SQL Server")
    host = env_value("SQLSERVER_HOST", dotenv, "localhost")
    port = env_value("SQLSERVER_PORT", dotenv, "1433")
    database = env_value("SQLSERVER_DATABASE", dotenv, "adaptive_learning")
    values = [
        f"DRIVER={{{driver}}}",
        f"SERVER={host},{port}",
        f"DATABASE={database}",
        f"Encrypt={env_value('SQLSERVER_ENCRYPT', dotenv, 'no')}",
        "TrustServerCertificate="
        + env_value("SQLSERVER_TRUST_SERVER_CERTIFICATE", dotenv, "yes"),
    ]
    if env_value("SQLSERVER_TRUSTED_CONNECTION", dotenv, "no").lower() == "yes":
        values.append("Trusted_Connection=yes")
    else:
        values.extend(
            [
                f"UID={env_value('SQLSERVER_USER', dotenv, 'sa')}",
                f"PWD={env_value('SQLSERVER_PASSWORD', dotenv)}",
            ]
        )
    return ";".join(values)


def read_sql_knowledge_point_ids(connection: pyodbc.Connection) -> Set[str]:
    """Read all cross-store knowledge-point IDs used by SQL Server."""
    cursor = connection.cursor()
    rows = cursor.execute(
        """
        SELECT knowledge_point_id FROM dbo.q_matrix
        UNION
        SELECT knowledge_point_id FROM dbo.user_kp_mastery
        """
    )
    return {str(row[0]) for row in rows if row[0]}


def read_neo4j_knowledge_point_ids(driver) -> Set[str]:
    """Read KnowledgePoint IDs from Neo4j."""
    with driver.session() as session:
        record = session.run(
            "MATCH (k:KnowledgePoint) RETURN collect(k.id) AS ids"
        ).single()
    return {str(value) for value in (record["ids"] if record else []) if value}


def main() -> int:
    """Run the read-only cross-store consistency check."""
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    dotenv = load_dotenv(DOTENV_PATH)
    neo4j_uri = env_value("NEO4J_URI", dotenv, "bolt://localhost:7687")
    neo4j_user = env_value("NEO4J_USER", dotenv, "neo4j")
    neo4j_password = env_value("NEO4J_PASSWORD", dotenv)

    sql_connection = None
    driver = None
    try:
        sql_connection = pyodbc.connect(sql_connection_string(dotenv), timeout=10)
        driver = GraphDatabase.driver(
            neo4j_uri, auth=(neo4j_user, neo4j_password)
        )
        sql_ids = read_sql_knowledge_point_ids(sql_connection)
        neo4j_ids = read_neo4j_knowledge_point_ids(driver)
        if args.simulate_sql_id:
            sql_ids.add(args.simulate_sql_id)
            LOGGER.info("已注入只读负例 ID（未写入任何数据库）：%s", args.simulate_sql_id)
    except (pyodbc.Error, Neo4jError, ServiceUnavailable) as exc:
        LOGGER.error("跨库一致性检查无法连接或查询数据：%s", exc)
        return 1
    finally:
        if sql_connection is not None:
            sql_connection.close()
        if driver is not None:
            driver.close()

    missing_in_neo4j = sorted(sql_ids - neo4j_ids)
    unused_in_sql = sorted(neo4j_ids - sql_ids)
    LOGGER.info("SQL Server 使用的知识点 ID: %d", len(sql_ids))
    LOGGER.info("Neo4j KnowledgePoint ID: %d", len(neo4j_ids))
    if missing_in_neo4j:
        LOGGER.error("SQL Server 引用了不存在于 Neo4j 的 ID: %s", missing_in_neo4j)
    if unused_in_sql:
        LOGGER.info("Neo4j 中尚未被 SQL Server 业务表引用的 ID: %d", len(unused_in_sql))
    if missing_in_neo4j:
        return 2
    LOGGER.info("跨库知识点 ID 一致性检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
