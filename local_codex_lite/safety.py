from __future__ import annotations

import fnmatch
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

DISALLOWED_PATTERNS = [
    "rm -rf",
    "del /s",
    "remove-item -recurse",
    "format",
    "shutdown",
    "curl | iex",
    "invoke-expression",
]

SENSITIVE_GLOBS = [
    ".env",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
    "*secret*",
    "*token*",
    "*password*",
    "*credential*",
]


def normalize_path(path: Path) -> Path:
    return path.resolve()


def is_inside_workspace(path: Path, workspace_root: Path) -> bool:
    try:
        path.resolve().relative_to(workspace_root.resolve())
        return True
    except Exception:
        return False


def is_sensitive_path(path: Path) -> bool:
    name = path.name.lower()
    return any(fnmatch.fnmatch(name, pattern.lower()) for pattern in SENSITIVE_GLOBS)


def can_read_path(path: Path, workspace_root: Path, allow_sensitive_read: bool = False) -> bool:
    if not is_inside_workspace(path, workspace_root):
        return False
    if not allow_sensitive_read and is_sensitive_path(path):
        return False
    return True


def is_dangerous_command(cmd: str) -> bool:
    lowered = cmd.lower()
    return any(pattern in lowered for pattern in DISALLOWED_PATTERNS)


def ensure_safe_command(cmd: str) -> None:
    if is_dangerous_command(cmd):
        raise ValueError(f"Refusing dangerous command: {cmd}")


@dataclass(frozen=True)
class SuggestedCommand:
    cmd: str
    reason: str
    risk: str = "low"


def run_command(cmd: str, cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    ensure_safe_command(cmd)
    return subprocess.run(cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout, check=False)
