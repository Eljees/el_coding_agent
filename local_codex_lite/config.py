from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, cast

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    base_url: str = "http://localhost:8015/v1"
    model: str = "qwen25-coder-14b-awq"
    api_key: str = "local-not-needed"
    temperature: float = 0.1
    max_tokens: int = 2048
    timeout: float = 120.0
    retries: int = 2


class WorkspaceConfig(BaseModel):
    root: Path = Path(".")
    max_file_bytes: int = 120_000
    include_globs: list[str] = Field(
        default_factory=lambda: [
            "**/*.py",
            "**/*.md",
            "**/*.toml",
            "**/*.yaml",
            "**/*.yml",
            "**/*.json",
        ]
    )
    exclude_globs: list[str] = Field(
        default_factory=lambda: [
            ".git/**",
            ".venv/**",
            "venv/**",
            "__pycache__/**",
            ".pytest_cache/**",
            ".mypy_cache/**",
            "node_modules/**",
            ".local-codex-lite/**",
            ".tmp/**",
            ".vscode/**",
            "__old/**",
            "generated_projects/**",
            "pytest_tmp/**",
            "scan_runs/**",
            "tmp_trufflehog/**",
            "*.egg-info/**",
        ]
    )


class SafetyConfig(BaseModel):
    require_apply_flag: bool = True
    require_exec_flag: bool = True
    allow_sensitive_read: bool = False
    max_patch_attempts: int = 4


class RagConfig(BaseModel):
    provider: Literal["keyword", "chroma"] = "keyword"
    enabled: bool = True
    store_dir: str = ".local-codex-lite/rag/keyword"
    top_k: int = 8
    chunk_chars: int = 1800
    overlap_chars: int = 250
    max_context_chars: int = 12000
    include_globs: list[str] = Field(
        default_factory=lambda: [
            "**/*.py",
            "**/*.md",
            "**/*.toml",
            "**/*.yaml",
            "**/*.yml",
            "**/*.json",
            "**/*.ps1",
        ]
    )
    exclude_globs: list[str] = Field(
        default_factory=lambda: [
            ".git/**",
            ".venv/**",
            "venv/**",
            "__pycache__/**",
            ".pytest_cache/**",
            ".mypy_cache/**",
            "node_modules/**",
            ".local-codex-lite/**",
            ".tmp/**",
            ".vscode/**",
            "__old/**",
            "**/.env",
            "**/*secret*",
            "**/*token*",
            "**/*private*",
        ]
    )


class AgentConfig(BaseModel):
    llm: LLMConfig = Field(default_factory=LLMConfig)
    workspace: WorkspaceConfig = Field(default_factory=WorkspaceConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    rag: RagConfig = Field(default_factory=RagConfig)
    # Optional named LLM profiles.  When set, the CLI ``--profile <name>``
    # flag swaps ``cfg.llm`` for ``cfg.llm_profiles[name]`` for a single
    # invocation.  Empty by default so the existing single-endpoint setup
    # keeps working unchanged.
    llm_profiles: dict[str, LLMConfig] = Field(default_factory=dict)


def _config_dir(workspace_root: Path) -> Path:
    return workspace_root / ".local-codex-lite"


def default_config() -> AgentConfig:
    return AgentConfig()


def config_path(workspace_root: Path) -> Path:
    return _config_dir(workspace_root) / "config.yaml"


def load_config(workspace_root: Path) -> AgentConfig:
    path = config_path(workspace_root)
    if not path.exists():
        return default_config()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return AgentConfig.model_validate(data)


def save_config(workspace_root: Path, config: AgentConfig) -> Path:
    cfg_dir = _config_dir(workspace_root)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "config.yaml"
    path.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False), encoding="utf-8"
    )
    return path


def config_as_dict(config: AgentConfig) -> dict[str, Any]:
    return cast(dict[str, Any], _redact_sensitive_structure(config.model_dump(mode="json")))


def _redact_sensitive_structure(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact_dict_item(str(key), item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_sensitive_structure(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_sensitive_structure(item) for item in value)
    return value


def _redact_dict_item(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        return "<redacted>"
    return _redact_sensitive_structure(value)


def _is_sensitive_key(key: str) -> bool:
    lower = key.lower()
    sensitive_terms = (
        "api_key",
        "token",
        "password",
        "secret",
        "credential",
        "pass",
        "key",
    )
    return any(term in lower for term in sensitive_terms)


class UnknownProfileError(KeyError):
    """Raised when --profile names a profile not present in config.yaml."""


def apply_profile(config: AgentConfig, profile_name: str | None) -> AgentConfig:
    """Return *config* with ``llm`` swapped for the named profile.

    If *profile_name* is falsy, ``config`` is returned unchanged.  If it
    names a profile that does not exist, raises ``UnknownProfileError``
    listing the available names so the CLI can surface a helpful error.
    """
    if not profile_name:
        return config
    profile = config.llm_profiles.get(profile_name)
    if profile is None:
        available = sorted(config.llm_profiles.keys()) or ["(none configured)"]
        raise UnknownProfileError(
            f"Unknown LLM profile '{profile_name}'. Available: {', '.join(available)}"
        )
    return config.model_copy(update={"llm": profile})
