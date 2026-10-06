"""Scan the repository for common committed credential signatures.

This is a conservative gate: it detects high-confidence token/private-key
patterns, non-placeholder values in dotenv files, and explicit documentation
claims that expose an instance password. It does not claim to be a complete
secret scanner, so production repositories should also use the hosting
platform's native secret scanning when available.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, List


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {
    ".git",
    ".pytest_cache",
    "node_modules",
    "dist",
    "__pycache__",
    ".uni",
}
TEXT_SUFFIXES = {
    ".env",
    ".example",
    ".json",
    ".js",
    ".md",
    ".py",
    ".ps1",
    ".sql",
    ".toml",
    ".ts",
    ".txt",
    ".vue",
    ".yml",
    ".yaml",
}
SECRET_PATTERNS = (
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("OpenAI-style API key", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("Slack token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b")),
)
DOCUMENTED_PASSWORD_PATTERN = re.compile(
    r"(?i)(?:当前|current)\s*(?:neo4j\s*)?(?:实例|instance)\s*"
    r"(?:密码|password)\s*(?:为|is|[:=])\s*"
    r"(?!<|your[_-]|change-me|example)(?P<value>[^\s，。,.;；]+)"
)
PLACEHOLDER_PREFIXES = (
    "your_",
    "your-",
    "change-me",
    "replace-",
    "example",
    "<",
    "***",
)


def iter_text_files(root: Path) -> Iterable[Path]:
    """Yield small text files while skipping generated/dependency directories."""
    for path in root.rglob("*"):
        if not path.is_file() or (
            path.name != ".env" and path.suffix.lower() not in TEXT_SUFFIXES
        ):
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if is_git_ignored(path):
            continue
        if path.stat().st_size > 2_000_000:
            continue
        yield path


def is_git_ignored(path: Path) -> bool:
    """Skip local ignored files while still scanning tracked dotenv files."""
    try:
        relative_path = path.relative_to(PROJECT_ROOT)
        result = subprocess.run(
            ["git", "check-ignore", "--quiet", "--", str(relative_path)],
            cwd=PROJECT_ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except (OSError, ValueError):
        return False
    return result.returncode == 0


def scan_dotenv_values(path: Path, text: str) -> List[str]:
    """Find non-placeholder values on sensitive dotenv keys."""
    findings: List[str] = []
    if not (path.name == ".env" or path.name.startswith(".env.")):
        return findings
    if path.name == ".env.example" or path.name.endswith(".example"):
        return findings
    for line_number, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if not re.search(r"(?:PASSWORD|SECRET|API_KEY|TOKEN|PRIVATE_KEY)", key, re.I):
            continue
        normalized = value.strip().strip('"').strip("'").lower()
        if normalized and not normalized.startswith(PLACEHOLDER_PREFIXES):
            findings.append(f"{path.relative_to(PROJECT_ROOT)}:{line_number}: dotenv secret value")
    return findings


def scan_documented_password_claims(path: Path, text: str) -> List[str]:
    """Find explicit claims that a concrete password is an instance password."""
    if path.suffix.lower() not in TEXT_SUFFIXES:
        return []
    match = DOCUMENTED_PASSWORD_PATTERN.search(text)
    if not match:
        return []
    value = match.group("value").strip("`\"'")
    if not re.search(r"[A-Za-z0-9][A-Za-z0-9._-]{2,}", value):
        return []
    line_number = text.count("\n", 0, match.start()) + 1
    try:
        display_path = path.relative_to(PROJECT_ROOT)
    except ValueError:
        display_path = path
    return [f"{display_path}:{line_number}: documented instance password"]


def scan_repository(root: Path = PROJECT_ROOT) -> List[str]:
    """Return high-confidence credential findings."""
    findings: List[str] = []
    for path in iter_text_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        findings.extend(scan_dotenv_values(path, text))
        findings.extend(scan_documented_password_claims(path, text))
        for label, pattern in SECRET_PATTERNS:
            match = pattern.search(text)
            if match:
                line_number = text.count("\n", 0, match.start()) + 1
                findings.append(
                    f"{path.relative_to(root)}:{line_number}: {label} signature"
                )
    return findings


def main() -> int:
    """Print findings and return a CI-friendly exit code."""
    findings = scan_repository()
    if findings:
        print("Potential credentials found:")
        print("\n".join(f"- {finding}" for finding in findings))
        return 1
    print("Credential scan passed: no high-confidence committed credential signatures found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
