"""Capability provider entry point.

The ``[project.entry-points."local_codex_lite.capabilities"]`` block in
``pyproject.toml`` points at the ``provide`` callable below.  When the
agent starts up, ``local_codex_lite.capabilities.discover_capabilities()``
walks the group and merges every returned ``Capability`` into the
in-memory list.

Contract:
- ``provide`` MAY return a single ``Capability`` or a ``list[Capability]``.
- Returning anything else (an int, a string, a list with non-``Capability``
  items) is tolerated: the agent logs a warning and skips the bad entry.
- Built-in capabilities always win on id collisions.  Pick a namespaced
  id like ``my_team.foo`` to make life easier for everyone.
- The ``required_inputs`` tuple drives the intent validator.  If your
  capability needs a new kind of input that doesn't fit the existing
  slots (``input_root`` / ``left`` / ``right`` / ``left_path`` /
  ``right_path`` / ``repo_url_or_file`` / ``task``), the agent will
  treat it as 'satisfied by default'; you'll want to either match an
  existing slot or upstream a PR to extend the validator.
"""
from __future__ import annotations

from local_codex_lite.capabilities import Capability


def provide() -> list[Capability]:
    """Return the capabilities this plugin contributes."""
    return [
        Capability(
            id="sample.echo",
            title="Echo a task back to the user",
            description=(
                "Trivial demonstration capability that does not call the "
                "LLM and does not change the workspace.  Use it as a "
                "template for your own plugins."
            ),
            examples=(
                "echo hello world",
                "say back: foo bar",
            ),
            keywords=("echo", "say back", "повтори"),
            required_inputs=("task",),
            safety_level="safe",
            requires_apply=False,
            requires_exec=False,
            cli_equivalent='python -m local_codex_lite recognize "echo <text>"',
        ),
    ]
