"""Post-apply smoke runner: execute entrypoint scripts touched by a patch.

After a patch passes the AST gate the code is syntactically valid, but a
small local model still produces plenty of *runtime* mistakes (bad imports,
wrong attribute names, type errors on startup).  This module gives the
runner a cheap way to catch those: run every touched script that has a
``if __name__ == "__main__"`` guard and report a failure with the stderr
tail (the traceback) so the repair loop can feed the model its own error.

Executing generated code is inherently risky, so the runner only calls
into this module when smoke runs are explicitly enabled (``--smoke`` or
``safety.smoke_run_default``); see ``docs/safety.md``.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Both quote styles: the model emits either spelling.
_ENTRYPOINT_MARKERS = ('if __name__ == "__main__"', "if __name__ == '__main__'")

_STDERR_TAIL_LINES = 30


@dataclass(frozen=True)
class SmokeResult:
    """Outcome of one smoke run of an entrypoint script."""

    script: Path
    ok: bool
    returncode: int | None  # None when the process was still alive at timeout
    timed_out: bool
    detail: str  # stderr tail (with traceback) for failures, short note otherwise


def find_entrypoint_scripts(touched: list[Path]) -> list[Path]:
    """Return the ``.py`` files among *touched* that look like entrypoints.

    A file qualifies when it exists and contains an
    ``if __name__ == "__main__"`` guard (either quote style).  Library
    modules without a guard are skipped: importing them is the entrypoint's
    job, and running them directly would prove nothing.  Duplicates are
    dropped (the runner's touched-file list carries each path twice, once
    per ``---``/``+++`` diff header).
    """
    scripts: list[Path] = []
    seen: set[Path] = set()
    for path in touched:
        if path.suffix.lower() != ".py":
            continue
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(marker in text for marker in _ENTRYPOINT_MARKERS):
            scripts.append(path)
    return scripts


def smoke_run_script(path: Path, root: Path, timeout_s: float = 10.0) -> SmokeResult:
    """Run ``[sys.executable, path]`` with ``cwd=root`` and classify the outcome.

    - exit 0 before the deadline -> ok;
    - process still alive at the deadline -> killed and treated as ok
      (GUI/mainloop and server scripts run forever by design);
    - non-zero exit -> failed, ``detail`` carries the stderr tail with the
      traceback so the repair loop can hand the model its own error.
    """
    try:
        completed = subprocess.run(
            [sys.executable, str(path)],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        # subprocess.run kills the child before raising; a long-lived script
        # (tkinter mainloop, web server) is normal behaviour, not a failure.
        return SmokeResult(
            script=path,
            ok=True,
            returncode=None,
            timed_out=True,
            detail=f"still running after {timeout_s:g}s; killed and treated as ok",
        )
    if completed.returncode == 0:
        return SmokeResult(script=path, ok=True, returncode=0, timed_out=False, detail="")
    return SmokeResult(
        script=path,
        ok=False,
        returncode=completed.returncode,
        timed_out=False,
        detail=_stderr_tail(completed.stderr),
    )


def _stderr_tail(stderr: str, max_lines: int = _STDERR_TAIL_LINES) -> str:
    lines = (stderr or "").strip().splitlines()
    if not lines:
        return "process exited non-zero without stderr"
    return "\n".join(lines[-max_lines:])
