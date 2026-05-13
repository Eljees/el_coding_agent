from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata, util
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from .config import LLMConfig, load_config
from .llm_client import OpenAICompatibleClient, extract_json
from .rag import (
    RagProviderError,
    ensure_rag_provider_supported,
    format_retrieved_context,
    index_workspace,
    query_index,
    resolve_store_dir,
)
from .rich_compat import make_console, make_table


@dataclass(frozen=True)
class DoctorProbeResult:
    endpoint_ok: bool
    latency_s: float | None
    response_model: str | None
    model_ok: bool | None
    json_ok: bool
    json_payload: dict | None
    error: str | None
    json_error: str | None


@dataclass(frozen=True)
class DependencyProbe:
    name: str
    required: bool
    installed: bool
    version: str | None
    module: str


_DEPENDENCIES = [
    ("httpx", True, "httpx"),
    ("pydantic", True, "pydantic"),
    ("PyYAML", True, "yaml"),
    ("rich", False, "rich"),
    ("pytest", False, "pytest"),
]


def build_doctor_probe_client(config: LLMConfig) -> OpenAICompatibleClient:
    probe_config = config.model_copy(
        update={
            "timeout": min(float(config.timeout), 10.0),
            "retries": 0,
        }
    )
    return OpenAICompatibleClient(probe_config)


def probe_local_llm_health(client: OpenAICompatibleClient, expected_model: str) -> DoctorProbeResult:
    start = time.perf_counter()
    messages = [
        {
            "role": "system",
            "content": 'Return only strict JSON in the shape {"ok": true, "component": "doctor"}.',
        },
        {"role": "user", "content": "Respond with strict JSON only."},
    ]
    try:
        response = client.chat(messages, max_tokens=32)
    except Exception as exc:  # noqa: BLE001
        return DoctorProbeResult(
            endpoint_ok=False,
            latency_s=time.perf_counter() - start,
            response_model=None,
            model_ok=False,
            json_ok=False,
            json_payload=None,
            error=str(exc),
            json_error=None,
        )

    latency = time.perf_counter() - start
    response_model = response.raw.get("model") if isinstance(response.raw, dict) else None
    model_ok = None if not response_model else response_model == expected_model
    json_payload = None
    json_error = None
    json_ok = False
    try:
        json_payload = extract_json(response.text)
        json_ok = json_payload.get("ok") is True and json_payload.get("component") == "doctor"
    except Exception as exc:  # noqa: BLE001
        json_error = str(exc)

    return DoctorProbeResult(
        endpoint_ok=True,
        latency_s=latency,
        response_model=response_model,
        model_ok=model_ok,
        json_ok=json_ok,
        json_payload=json_payload,
        error=None,
        json_error=json_error,
    )


def run_doctor(workspace_root: Path) -> int:
    console = make_console(legacy_windows=False)
    config = load_config(workspace_root)
    table = make_table(title="local-codex-lite doctor")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")

    config_path = workspace_root / ".local-codex-lite" / "config.yaml"
    table.add_row("config.yaml", "OK" if config_path.exists() else "MISSING", str(config_path))
    table.add_row("workspace", "OK" if workspace_root.exists() else "MISSING", str(workspace_root))
    git_path = shutil.which("git")
    table.add_row("git", "OK" if git_path else "MISSING", git_path or "git not found")

    probe_client = build_doctor_probe_client(config.llm)
    probe = probe_local_llm_health(probe_client, config.llm.model)
    overall_ok = True
    if probe.endpoint_ok:
        latency_ms = f"{probe.latency_s * 1000:.0f} ms" if probe.latency_s is not None else "unknown"
        table.add_row("llm endpoint", "OK", f"{config.llm.base_url} / {probe.response_model or 'unknown'}")
        table.add_row("latency", "OK", latency_ms)
    else:
        table.add_row("llm endpoint", "FAIL", probe.error or "request failed")
        table.add_row("latency", "FAIL", "unavailable")
        overall_ok = False

    if not probe.endpoint_ok:
        model_status = "UNAVAILABLE"
        overall_ok = False
    elif probe.model_ok is False:
        model_status = "MISMATCH"
        overall_ok = False
    elif probe.model_ok is True:
        model_status = "OK"
    else:
        model_status = "UNKNOWN"
    model_detail = probe.response_model or "unavailable"
    table.add_row("model", model_status, f"expected {config.llm.model}, got {model_detail}")

    if not probe.endpoint_ok:
        table.add_row("json sanity", "UNAVAILABLE", "endpoint probe did not complete")
        overall_ok = False
    elif probe.json_ok:
        table.add_row("json sanity", "OK", "strict JSON probe passed")
    else:
        detail = probe.json_error or "strict JSON probe failed"
        table.add_row("json sanity", "FAIL", detail)
        overall_ok = False

    console.print(table)
    return 0 if overall_ok else 1


def probe_python_dependencies() -> list[DependencyProbe]:
    probes: list[DependencyProbe] = []
    for distribution, required, module_name in _DEPENDENCIES:
        version = None
        installed = False
        try:
            version = metadata.version(distribution)
            installed = True
        except metadata.PackageNotFoundError:
            installed = util.find_spec(module_name) is not None
            if installed:
                version = "unknown"
        probes.append(
            DependencyProbe(
                name=distribution,
                required=required,
                installed=installed,
                version=version,
                module=module_name,
            )
        )
    return probes


def run_dependency_doctor(workspace_root: Path) -> int:
    console = make_console(legacy_windows=False)
    table = make_table(title="local-codex-lite dependencies")
    table.add_column("Package")
    table.add_column("Required")
    table.add_column("Status")
    table.add_column("Version")
    table.add_column("Module")

    overall_ok = True
    for probe in probe_python_dependencies():
        if probe.installed:
            status = "OK"
        elif probe.required:
            status = "MISSING"
            overall_ok = False
        else:
            status = "OPTIONAL"
        version = probe.version or "-"
        table.add_row(probe.name, "yes" if probe.required else "no", status, version, probe.module)

    console.print(table)
    return 0 if overall_ok else 1


def run_rag_doctor(workspace_root: Path) -> int:
    console = make_console(legacy_windows=False)
    config = load_config(workspace_root)
    table = make_table(title="local-codex-lite RAG")
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Details")

    overall_ok = True
    table.add_row("config", "OK", f"{workspace_root / '.local-codex-lite' / 'config.yaml'}")

    try:
        provider = ensure_rag_provider_supported(config)
        table.add_row("provider", "OK", provider)
    except RagProviderError as exc:
        table.add_row("provider", "FAIL", str(exc))
        console.print(table)
        return 1

    try:
        store_dir = resolve_store_dir(workspace_root, config)
        table.add_row("store_dir", "OK", str(store_dir))
    except RagProviderError as exc:
        table.add_row("store_dir", "FAIL", str(exc))
        overall_ok = False
        console.print(table)
        return 1

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_root = Path(tmp_dir)
        (tmp_root / "README.md").write_text("alpha beta\nline two\n", encoding="utf-8")
        (tmp_root / "secret.env").write_text("API_KEY=123", encoding="utf-8")
        fixture_cfg = config.model_copy(deep=True)
        fixture_cfg.rag.store_dir = str(tmp_root / "rag-store")
        try:
            info = index_workspace(tmp_root, fixture_cfg)
            results = query_index("alpha", tmp_root, fixture_cfg)
            formatted = format_retrieved_context(results, fixture_cfg.rag.max_context_chars)
            sensitive_indexed = any(".env" in item.path.name.lower() for item in results)
            if info.chunk_count > 0 and results and not sensitive_indexed and formatted:
                table.add_row("fixture index", "OK", f"{info.chunk_count} chunks / {info.file_count} files")
                table.add_row("fixture query", "OK", results[0].reason)
                table.add_row("sensitive exclusion", "OK", "secret.env was skipped")
            else:
                table.add_row("fixture index", "FAIL", "keyword fixture did not produce usable results")
                table.add_row("fixture query", "FAIL", "keyword fixture did not produce usable results")
                table.add_row("sensitive exclusion", "FAIL", "secret.env was unexpectedly indexed")
                overall_ok = False
        except Exception as exc:  # noqa: BLE001
            table.add_row("fixture index", "FAIL", str(exc))
            table.add_row("fixture query", "FAIL", str(exc))
            table.add_row("sensitive exclusion", "FAIL", str(exc))
            overall_ok = False

    console.print(table)
    return 0 if overall_ok else 1


def preview_patch(workspace_root: Path, diff_text: str) -> int:
    git_path = shutil.which("git")
    if not git_path:
        raise RuntimeError("git not found")
    patch_file = workspace_root / ".local-codex-lite" / "preview.diff"
    patch_file.parent.mkdir(parents=True, exist_ok=True)
    patch_file.write_text(diff_text, encoding="utf-8")
    result = subprocess.run(
        [git_path, "apply", "--check", "--whitespace=nowarn", str(patch_file)],
        cwd=workspace_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        console = make_console(legacy_windows=False)
        console.print("[green]Patch preview OK[/green]")
        return 0
    console = make_console(legacy_windows=False)
    console.print("[red]Patch preview failed[/red]")
    console.print(result.stderr)
    return result.returncode
