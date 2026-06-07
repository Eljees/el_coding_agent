"""``rules`` subcommands: inspect or bootstrap the user's ``AGENT_RULES.md``.

``AGENT_RULES.md`` is the hand-edited style guide whose bullet lines are
injected into every plan/patch prompt (see :mod:`local_codex_lite.lessons`).
Split out of ``cli.py`` like the other per-command modules; re-exported from
``cli`` so the dispatcher and the test-suite reach the handlers unchanged.
"""

from __future__ import annotations

import argparse

from .cli_utils import console, workspace_root
from .lessons import RULES_FILENAME, load_user_rules

RULES_TEMPLATE = """\
# AGENT_RULES.md

Personal style guide for the coding agent. Every bullet line ("- " or "* ")
becomes a rule the model must follow; headings and prose are ignored.
Keep each rule short (max 200 chars); only the first 10 bullets are used.

Личный стиль-гайд для агента: каждая строка-буллет становится правилом для
модели. Примеры / examples:

- Пиши комментарии и docstrings на русском
- Не добавляй внешних зависимостей без явного запроса
- Для GUI используй только tkinter
"""


def cmd_rules_show(args: argparse.Namespace) -> int:
    root = workspace_root()
    rules = load_user_rules(root)
    if not rules:
        if (root / RULES_FILENAME).exists():
            console.print(f"{RULES_FILENAME} exists but contains no rules (bullet lines).")
        else:
            console.print(f"no {RULES_FILENAME}; create one with: local-codex-lite rules init")
        return 0
    console.print(f"[bold]User rules ({len(rules)})[/bold]")
    for rule in rules:
        console.print(f"- {rule}")
    return 0


def cmd_rules_init(args: argparse.Namespace) -> int:
    root = workspace_root()
    path = root / RULES_FILENAME
    if path.exists():
        console.print(f"{RULES_FILENAME} already exists at {path}; edit it directly.")
        return 1
    path.write_text(RULES_TEMPLATE, encoding="utf-8", newline="\n")
    console.print(f"Created {path}; edit it to add your own rules.")
    return 0
