"""M10 安全配置和迁移执行器的无外部依赖测试。"""

from pathlib import Path

import pytest

from app.config.security import mask_secret, redact_sensitive_text
from app.config.settings import Settings


def test_production_default_secret_is_rejected():
    """生产模式不能使用示例 JWT Secret。"""
    with pytest.raises(ValueError, match="生产环境禁止"):
        Settings(
            DEBUG=False,
            ENVIRONMENT="production",
            SECRET_KEY="change-me-to-a-random-secret",
        )


def test_production_secret_requires_sufficient_length():
    """生产模式拒绝过短密钥。"""
    with pytest.raises(ValueError, match="至少 32 个字符"):
        Settings(DEBUG=False, ENVIRONMENT="production", SECRET_KEY="short-secret")


def test_mask_secret_never_returns_the_full_value():
    """配置展示只保留末尾少量字符。"""
    value = "sk-live-example-123456"
    masked = mask_secret(value)
    assert masked.endswith("3456")
    assert masked != value


def test_log_redaction_removes_credentials():
    """日志中的 Bearer、API key 和密码值必须被替换。"""
    message = (
        'Authorization: Bearer token-value api_key=secret-value '
        'password=pwd-value {"api_key": "json-secret"}'
    )
    redacted = redact_sensitive_text(message)
    assert "token-value" not in redacted
    assert "secret-value" not in redacted
    assert "pwd-value" not in redacted
    assert "json-secret" not in redacted
    assert "[REDACTED]" in redacted


def test_migration_files_are_named_and_non_destructive():
    """版本化迁移目录可被执行器 dry-run 校验。"""
    from sql.migrate import migration_files, validate_migration

    directory = Path(__file__).parents[1] / "sql" / "migrations"
    files = list(migration_files(directory))
    assert files
    for _, path in files:
        validate_migration(path.read_text(encoding="utf-8"), path)


def test_credential_scan_flags_documented_instance_password(tmp_path):
    """低熵但明确的实例密码陈述也必须被凭证门禁拦截。"""
    from scripts.check_secrets import scan_documented_password_claims

    path = tmp_path / "delivery.md"
    text = "当前 Neo4j " + "实例密码为 " + ("9" * 8)
    assert scan_documented_password_claims(path, text)


def test_credential_scan_allows_secret_management_guidance(tmp_path):
    """只描述密钥管理方式、不暴露具体值的文档应通过。"""
    from scripts.check_secrets import scan_documented_password_claims

    path = tmp_path / "delivery.md"
    text = "Neo4j 实例密码不得写入文档，应由密钥管理器注入。"
    assert scan_documented_password_claims(path, text) == []
