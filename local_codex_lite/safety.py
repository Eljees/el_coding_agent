from __future__ import annotations

import fnmatch
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

# Each entry is a precompiled regex pattern matching a dangerous command shape.
# We use word boundaries / shell-aware anchors so harmless commands such as
# ``pytest --format=json`` or ``python -c "print(format(x))"`` are not flagged
# by the substring 'format', and so ``--shutdown-on-error`` does not trip the
# 'shutdown' rule.
_DANGEROUS_COMMAND_PATTERNS: tuple[re.Pattern[str], ...] = (
    # POSIX recursive force remove: rm -rf, rm -fr, rm --recursive --force, ...
    re.compile(
        r"\brm\s+(?:-[a-z]*r[a-z]*f|-[a-z]*f[a-z]*r"
        r"|--recursive\b[^|]*--force\b|--force\b[^|]*--recursive\b)",
        re.IGNORECASE,
    ),
    # Windows del with /s (and optional /q, /f) -- destructive recursive delete.
    re.compile(r"\bdel\s+(?:/[sqf]\s+){1,3}", re.IGNORECASE),
    re.compile(r"\bdel\s+/s\b", re.IGNORECASE),
    # PowerShell recursive remove.
    re.compile(r"\bremove-item\s+(?:[^|]*\s)?-recurse\b", re.IGNORECASE),
    # ``format c:`` style disk wipes -- narrowly target ``format <drive>:``.
    re.compile(r"\bformat\s+[a-z]:", re.IGNORECASE),
    # ``shutdown`` invoked as a command, not as a substring inside a flag.
    re.compile(r"(?:^|[\s;&|`(])shutdown(?:\s+[-/]|\s*$)", re.IGNORECASE),
    # ``curl ... | iex`` and friends -- remote-script execution.
    re.compile(r"\b(?:curl|wget|iwr|invoke-webrequest)\b[^\n]*\|\s*iex\b", re.IGNORECASE),
    # Direct invoke-expression call.
    re.compile(r"\binvoke-expression\b", re.IGNORECASE),
)


# Human-readable summary kept for backward compatibility / introspection.
DISALLOWED_PATTERNS: tuple[str, ...] = (
    "rm -rf",
    "del /s",
    "remove-item -recurse",
    "format <drive>:",
    "shutdown",
    "curl | iex",
    "invoke-expression",
)

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
    if not cmd:
        return False
    return any(pattern.search(cmd) for pattern in _DANGEROUS_COMMAND_PATTERNS)


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
    return subprocess.run(
        cmd, cwd=cwd, shell=True, capture_output=True, text=True, timeout=timeout, check=False
    )
