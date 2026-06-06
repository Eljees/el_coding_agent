from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import metadata as _metadata


@dataclass(frozen=True)
class Capability:
    id: str
    title: str
    description: str
    examples: tuple[str, ...]
    keywords: tuple[str, ...]
    required_inputs: tuple[str, ...]
    safety_level: str
    requires_apply: bool
    requires_exec: bool
    cli_equivalent: str


@dataclass(frozen=True)
class CapabilitySource:
    """Where a Capability came from.

    ``kind == "builtin"`` -- shipped in ``default_capabilities()``.
    ``kind == "plugin"`` -- contributed via an entry_points provider;
    ``name`` carries the entry-point name (i.e. the key from the
    consumer's ``pyproject.toml``).
    """

    kind: str
    name: str = ""


def _builtin_source() -> CapabilitySource:
    return CapabilitySource(kind="builtin", name="")


def default_capabilities() -> list[Capability]:
    return [
        Capability(
            id="run.preview",
            title="Preview code changes",
            description="Build a plan and patch preview without touching files.",
            examples=("исправь баг в patcher.py", "preview a small code fix"),
            keywords=("preview", "fix", "bug", "patch", "исправь", "ошибка", "код"),
            required_inputs=("task",),
            safety_level="safe",
            requires_apply=False,
            requires_exec=False,
            cli_equivalent='python -m local_codex_lite preview "<task>"',
        ),
        Capability(
            id="run.apply",
            title="Apply code changes",
            description="Run the coding loop and write validated changes to disk.",
            examples=("добавь README и примени", "apply the generated patch"),
            keywords=("apply", "write", "change", "создай", "сделай", "добавь", "примени"),
            required_inputs=("task",),
            safety_level="guarded",
            requires_apply=True,
            requires_exec=False,
            cli_equivalent='python -m local_codex_lite run "<task>" --apply',
        ),
        Capability(
            id="run.exec",
            title="Apply and execute follow-up commands",
            description="Run the coding loop, apply the patch, and allow suggested commands.",
            examples=("почини и запусти тесты", "apply and execute"),
            keywords=("exec", "execute", "tests", "pytest", "запусти", "проверь", "тест"),
            required_inputs=("task",),
            safety_level="guarded",
            requires_apply=True,
            requires_exec=True,
            cli_equivalent='python -m local_codex_lite run "<task>" --apply --exec',
        ),
        Capability(
            id="review.code",
            title="Review code changes",
            description="Review diffs or pull requests without modifying files.",
            examples=("обзор кода", "code review", "review pull request"),
            keywords=("review", "code review", "pull request", "ревью", "обзор кода"),
            required_inputs=(),
            safety_level="safe",
            requires_apply=False,
            requires_exec=False,
            cli_equivalent="python -m local_codex_lite review",
        ),
        Capability(
            id="logs.latest",
            title="Show latest logs",
            description="Inspect the latest run log output without rerunning the model.",
            examples=("покажи последние логи", "show latest logs"),
            keywords=("logs", "latest", "логи", "последние"),
            required_inputs=(),
            safety_level="safe",
            requires_apply=False,
            requires_exec=False,
            cli_equivalent="python -m local_codex_lite logs latest",
        ),
        Capability(
            id="evidence.json_compare",
            title="Compare JSON artifacts",
            description="Compare two JSON files and summarize their differences.",
            examples=("сравни left.json и right.json", "compare two json files"),
            keywords=("json", "compare", "diff", "сравни"),
            required_inputs=("left_path", "right_path"),
            safety_level="safe",
            requires_apply=False,
            requires_exec=False,
            cli_equivalent='python -m local_codex_lite evidence json-compare "left.json" "right.json"',
        ),
        Capability(
            id="evidence.artifacts.inspect",
            title="Inspect and unpack artifact archives",
            description="Inventory supported archive files and optionally extract them into an evidence bundle.",
            examples=(
                r"проведи анализ артефактов отсюда D:\path\to\artifacts",
                "проверь архивы и разархивируй",
            ),
            keywords=(
                "artifact",
                "artifacts",
                "archive",
                "archives",
                "unpack",
                "extract",
                "zip",
                "rar",
                "7z",
                "артефакт",
                "артефакты",
                "архив",
                "архивы",
                "разархив",
                "распак",
                "извлеки",
                "отсюда",
            ),
            required_inputs=("input_root",),
            safety_level="safe",
            requires_apply=False,
            requires_exec=False,
            cli_equivalent='python -m local_codex_lite evidence artifacts inspect "<input_root>" ["<extract_to>"] --extract',
        ),
        Capability(
            id="evidence.trufflehog.analyze",
            title="Analyze TruffleHog results",
            description="Summarize an existing TruffleHog output directory.",
            examples=("проанализируй trufflehog результаты",),
            keywords=("trufflehog", "analyze", "results", "результаты", "проанализируй"),
            required_inputs=("input_root",),
            safety_level="safe",
            requires_apply=False,
            requires_exec=False,
            cli_equivalent='python -m local_codex_lite evidence trufflehog analyze "<input_root>"',
        ),
        Capability(
            id="evidence.trufflehog.scan",
            title="Run TruffleHog scan",
            description="Run a TruffleHog scan for one repo or a repo list.",
            examples=("запусти trufflehog scan",),
            keywords=("trufflehog", "scan", "repo", "gitlab"),
            required_inputs=("repo_url_or_file",),
            safety_level="guarded",
            requires_apply=False,
            requires_exec=True,
            cli_equivalent='python -m local_codex_lite evidence trufflehog scan --repo-url "<repo>"',
        ),
        Capability(
            id="evidence.trufflehog.compare",
            title="Compare TruffleHog outputs",
            description="Compare two TruffleHog output roots and summarize the delta.",
            examples=("сравни два trufflehog прогона",),
            keywords=("trufflehog", "compare", "baseline", "сравни"),
            required_inputs=("left", "right"),
            safety_level="safe",
            requires_apply=False,
            requires_exec=False,
            cli_equivalent='python -m local_codex_lite evidence trufflehog compare "<left>" "<right>"',
        ),
        Capability(
            id="doctor",
            title="Run doctor checks",
            description="Inspect local agent, dependency, or endpoint health.",
            examples=("проверь doctor", "run doctor"),
            keywords=("doctor", "check", "diagnose", "проверь"),
            required_inputs=(),
            safety_level="safe",
            requires_apply=False,
            requires_exec=False,
            cli_equivalent="python -m local_codex_lite doctor",
        ),
        Capability(
            id="config.show",
            title="Show config",
            description="Print the current agent configuration with redacted secrets.",
            examples=("покажи конфиг",),
            keywords=("config", "show", "конфиг", "настройки"),
            required_inputs=(),
            safety_level="safe",
            requires_apply=False,
            requires_exec=False,
            cli_equivalent="python -m local_codex_lite config show",
        ),
        Capability(
            id="evidence.cve_scan",
            title="CVE scan on artifact directory",
            description=(
                "Unpack archives and run cve-bin-tool to detect known CVEs in binary artifacts. "
                "Saves raw JSON, severity summary, and Markdown report as evidence."
            ),
            examples=(
                r"проверь на cve артефакты из D:\\path\\to\\artifacts",
                "scan artifacts for CVEs",
                "run cve-bin-tool on extracted binaries",
                "найди уязвимости в архивах",
            ),
            keywords=(
                "cve",
                "cve-bin-tool",
                "vulnerability",
                "vulnerabilities",
                "уязвимост",
                "уязвим",
                "cve-scan",
                "security scan",
                "binary scan",
                "проверь на cve",
                "найди уязвимости",
                "сканируй на cve",
            ),
            required_inputs=("input_root",),
            safety_level="safe",
            requires_apply=False,
            requires_exec=False,
            cli_equivalent='python -m local_codex_lite evidence cve-scan "<input_root>"',
        ),
        Capability(
            id="appsechub.issues",
            title="AppSecHub issues & scan analysis",
            description=(
                "Read-only AppSecHub queries: issue counts, severity/source breakdowns, "
                "TruffleHog secret types, quality metrics, scan history, and "
                "scan-to-scan deltas/trends."
            ),
            examples=(
                "посмотри issues проекта https://appsechub.ssdlc.soc.rt.ru/#/appprofile/89",
                "сколько срабатываний у проекта 89",
                "определи типы срабатываний trufflehog у appprofile 89",
                "качество срабатываний и доля false positive",
            ),
            keywords=(
                "appsechub",
                "апсекхаб",
                "аппсекхаб",
                "appprofile",
                "issues",
                "issues проекта",
                "посмотри issues",
                "срабатыван",
                "типы срабатываний",
                "качество срабатываний",
                "уязвимости приложения",
                "уязвимостей приложения",
                "секрет",
                "trufflehog",
            ),
            required_inputs=("app",),
            safety_level="read_only",
            requires_apply=False,
            requires_exec=False,
            cli_equivalent=('python skills/appsechub/appsechub_client.py breakdown "<app_id|url>"'),
        ),
    ]


def capability_brief_lines(capabilities: list[Capability]) -> list[str]:
    return [f"{item.id} - {item.title}" for item in capabilities]


# Entry-point group name for third-party capability plugins.  A plugin
# registers a callable that returns either a Capability or a list of
# Capability:
#
#   # in the plugin's pyproject.toml:
#   [project.entry-points."local_codex_lite.capabilities"]
#   my_team_helpers = "my_team_lcl_plugins.capabilities:provide"
#
#   # in my_team_lcl_plugins/capabilities.py:
#   def provide() -> list[Capability]:
#       return [Capability(id="my_team.foo", ...)]
#
# Built-in capabilities always win on id collisions; plugins cannot
# override the safety-critical names like run.apply or evidence.cve_scan.
CAPABILITY_ENTRY_POINT_GROUP = "local_codex_lite.capabilities"

_LOG = logging.getLogger(__name__)


def _load_plugin_capabilities_with_source() -> list[tuple[CapabilitySource, Capability]]:
    """Walk the entry_points group and load every registered provider,
    tagging each result with its source plugin name.

    A provider that raises, returns a non-Capability, or otherwise
    misbehaves is skipped with a warning -- a broken plugin must not
    take the agent down.
    """
    discovered: list[tuple[CapabilitySource, Capability]] = []
    try:
        eps = _metadata.entry_points(group=CAPABILITY_ENTRY_POINT_GROUP)
    except TypeError:  # pragma: no cover -- Python <3.10 selectable API
        eps = _metadata.entry_points().get(CAPABILITY_ENTRY_POINT_GROUP, [])  # type: ignore
    for ep in eps:
        source = CapabilitySource(kind="plugin", name=ep.name)
        try:
            provider = ep.load()
            items = provider() if callable(provider) else provider
        except Exception as exc:
            _LOG.warning("Capability plugin %r failed to load: %s", ep.name, exc)
            continue
        if isinstance(items, Capability):
            items = [items]
        if not isinstance(items, (list, tuple)):
            _LOG.warning(
                "Capability plugin %r returned %r (expected Capability or list); ignoring.",
                ep.name,
                type(items).__name__,
            )
            continue
        for item in items:
            if isinstance(item, Capability):
                discovered.append((source, item))
            else:
                _LOG.warning(
                    "Capability plugin %r yielded %r; expected Capability instance.",
                    ep.name,
                    type(item).__name__,
                )
    return discovered


def _load_plugin_capabilities() -> list[Capability]:
    """Backward-compatible alias used by callers that don't need source
    metadata.  See ``_load_plugin_capabilities_with_source``."""
    return [cap for _src, cap in _load_plugin_capabilities_with_source()]


def discover_capabilities_with_source() -> list[tuple[CapabilitySource, Capability]]:
    """Like ``discover_capabilities``, but each Capability is paired with
    its ``CapabilitySource``.  Used by ``local-codex-lite plugins list``
    to show users where a capability came from.

    Built-ins always win on id collisions.  A plugin that tries to
    redefine a reserved id (e.g. ``run.apply``) is dropped with a log
    message and never appears in the output.
    """
    builtins = [(_builtin_source(), cap) for cap in default_capabilities()]
    builtin_ids = {cap.id for _src, cap in builtins}
    merged: list[tuple[CapabilitySource, Capability]] = list(builtins)
    for src, extra in _load_plugin_capabilities_with_source():
        if extra.id in builtin_ids:
            _LOG.info(
                "Capability plugin %r tried to register reserved id %r; "
                "ignoring in favour of built-in.",
                src.name,
                extra.id,
            )
            continue
        merged.append((src, extra))
        builtin_ids.add(extra.id)
    return merged


def discover_capabilities() -> list[Capability]:
    """Return built-in capabilities plus any registered via entry_points.

    Built-ins take precedence on id collisions: a third-party plugin that
    happens to use ``run.apply`` (or any other safety-critical id) is
    silently dropped in favour of the built-in.
    """
    return [cap for _src, cap in discover_capabilities_with_source()]
