"""Generate docs/cli-reference.md from the project's argparse definitions.

The reference document keeps a hand-written introduction; everything between
``<!-- BEGIN GENERATED -->`` and ``<!-- END GENERATED -->`` is produced by this
script from ``local_codex_lite.cli_parser.build_parser`` so the documentation
can never drift from the actual CLI surface.

Usage::

    python scripts/gen_cli_reference.py          # rewrite docs/cli-reference.md
    python scripts/gen_cli_reference.py --check  # exit 1 if the doc is stale
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC_PATH = REPO_ROOT / "docs" / "cli-reference.md"
BEGIN_MARKER = "<!-- BEGIN GENERATED -->"
END_MARKER = "<!-- END GENERATED -->"

# ``build_parser()`` reads these at construction time to seed argument
# defaults.  Scrub them while building so the generated document is
# deterministic and records the canonical (env-unset) defaults.
_ENV_DEFAULT_VARS = (
    "GITLAB_USER",
    "GITLAB_TOKEN",
    "TRUFFLEHOG_IMAGE",
    "TRUFFLEHOG_CACHE_ROOT",
    "TRUFFLEHOG_OUT_ROOT",
)


def _build_canonical_parser() -> argparse.ArgumentParser:
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))
    from local_codex_lite.cli_parser import build_parser

    saved = {name: os.environ.pop(name) for name in _ENV_DEFAULT_VARS if name in os.environ}
    try:
        return build_parser()
    finally:
        os.environ.update(saved)


def _subparsers_action(parser: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _own_arguments(parser: argparse.ArgumentParser) -> list[argparse.Action]:
    return [
        action
        for action in parser._actions
        if not isinstance(action, argparse._HelpAction | argparse._SubParsersAction)
    ]


def _argument_syntax(action: argparse.Action) -> str:
    if action.option_strings:
        option = max(action.option_strings, key=len)
        if action.nargs == 0:
            return option
        metavar = action.metavar if isinstance(action.metavar, str) else action.dest.upper()
        return f"{option} {metavar}"
    name = action.metavar if isinstance(action.metavar, str) else action.dest
    if action.nargs == "?":
        return f"[{name}]"
    return f"<{name}>"


def _describe(action: argparse.Action) -> str:
    parts: list[str] = []
    if action.help:
        parts.append(str(action.help))
    if action.choices is not None:
        rendered = ", ".join(f"`{choice}`" for choice in action.choices)
        parts.append(f"choices: {rendered}")
    default = action.default
    if default not in (None, False, "", argparse.SUPPRESS) and default != []:
        parts.append(f"default: `{default}`")
    if isinstance(action, argparse._AppendAction):
        parts.append("repeatable")
    return "; ".join(parts).replace("|", "\\|")


def _usage_line(path: list[str], parser: argparse.ArgumentParser) -> str:
    parts = ["local-codex-lite", *path]
    own = _own_arguments(parser)
    for action in own:
        if not action.option_strings:
            parts.append(_argument_syntax(action))
    sub = _subparsers_action(parser)
    if sub is not None:
        names = "|".join(sub.choices)
        parts.append(f"<{names}>" if sub.required else f"[{names}]")
    if any(action.option_strings for action in own):
        parts.append("[options]")
    return " ".join(parts)


def _anchor(path: list[str]) -> str:
    return "-".join(path)


def _emit_command(
    path: list[str],
    parser: argparse.ArgumentParser,
    help_text: str | None,
    lines: list[str],
) -> None:
    lines.append(f"### `{' '.join(path)}`")
    lines.append("")
    if help_text:
        sentence = help_text[0].upper() + help_text[1:]
        if not sentence.endswith("."):
            sentence += "."
        lines.append(sentence)
        lines.append("")
    lines.append(f"Usage: `{_usage_line(path, parser)}`")
    lines.append("")
    own = _own_arguments(parser)
    if own:
        lines.append("| Argument | Description |")
        lines.append("|----------|-------------|")
        for action in own:
            lines.append(f"| `{_argument_syntax(action)}` | {_describe(action)} |")
        lines.append("")
    sub = _subparsers_action(parser)
    if sub is None:
        return
    helps = {pseudo.dest: pseudo.help or "" for pseudo in sub._choices_actions}
    lines.append("| Subcommand | Description |")
    lines.append("|------------|-------------|")
    for name in sub.choices:
        link = f"[`{' '.join([*path, name])}`](#{_anchor([*path, name])})"
        lines.append(f"| {link} | {helps.get(name, '')} |")
    lines.append("")
    for name, sub_parser in sub.choices.items():
        _emit_command([*path, name], sub_parser, helps.get(name), lines)


def build_generated_section() -> str:
    parser = _build_canonical_parser()
    root_sub = _subparsers_action(parser)
    if root_sub is None:  # pragma: no cover - the CLI always has subcommands
        raise RuntimeError("top-level parser has no subcommands")
    helps = {pseudo.dest: pseudo.help or "" for pseudo in root_sub._choices_actions}
    lines: list[str] = [
        "_Everything below is generated by `scripts/gen_cli_reference.py` — do not edit by hand._",
        "",
        "## Command index",
        "",
        "| Command | Description |",
        "|---------|-------------|",
    ]
    for name in root_sub.choices:
        lines.append(f"| [`{name}`](#{_anchor([name])}) | {helps.get(name, '')} |")
    lines.append("")
    for name, sub_parser in root_sub.choices.items():
        _emit_command([name], sub_parser, helps.get(name), lines)
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def render_document(existing: str) -> str:
    """Return ``existing`` with the generated section replaced by a fresh one."""
    if BEGIN_MARKER not in existing or END_MARKER not in existing:
        raise ValueError(
            f"{DOC_PATH} is missing the {BEGIN_MARKER} / {END_MARKER} markers; "
            "restore them before regenerating"
        )
    head, rest = existing.split(BEGIN_MARKER, 1)
    _, tail = rest.split(END_MARKER, 1)
    return f"{head}{BEGIN_MARKER}\n\n{build_generated_section()}\n\n{END_MARKER}{tail}"


def main(argv: list[str] | None = None) -> int:
    cli = argparse.ArgumentParser(
        description="Regenerate docs/cli-reference.md from local_codex_lite.cli_parser."
    )
    cli.add_argument(
        "--check",
        action="store_true",
        help="do not write; exit 1 if docs/cli-reference.md is out of date",
    )
    args = cli.parse_args(argv)

    existing = DOC_PATH.read_text(encoding="utf-8").replace("\r\n", "\n")
    rendered = render_document(existing)
    if args.check:
        if rendered != existing:
            print(
                f"{DOC_PATH} is out of date; run: python scripts/gen_cli_reference.py",
                file=sys.stderr,
            )
            return 1
        print(f"{DOC_PATH} is up to date")
        return 0
    if rendered != existing:
        DOC_PATH.write_text(rendered, encoding="utf-8", newline="\n")
        print(f"wrote {DOC_PATH}")
    else:
        print(f"{DOC_PATH} already up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
