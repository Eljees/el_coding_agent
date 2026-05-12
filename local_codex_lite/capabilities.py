from __future__ import annotations

from dataclasses import dataclass


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
                r'проведи анализ артефактов отсюда D:\path\to\artifacts',
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
                r'проверь на cve артефакты из D:\\path\\to\\artifacts',
                "scan artifacts for CVEs",
                "run cve-bin-tool on extracted binaries",
                "найди уязвимости в архивах",
            ),
            keywords=(
                "cve", "cve-bin-tool", "vulnerability", "vulnerabilities",
                "уязвимост", "уязвим", "cve-scan",
                "security scan", "binary scan",
                "проверь на cve", "найди уязвимости", "сканируй на cve",
            ),
            required_inputs=("input_root",),
            safety_level="safe",
            requires_apply=False,
            requires_exec=False,
            cli_equivalent='python -m local_codex_lite evidence cve-scan "<input_root>"',
        ),
    ]


def capability_brief_lines(capabilities: list[Capability]) -> list[str]:
    return [f"{item.id} - {item.title}" for item in capabilities]
