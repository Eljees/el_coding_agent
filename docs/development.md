# Development & CI

## Setup

```powershell
.\scripts\setup.ps1                 # creates .venv and installs -e ".[dev]"
# or manually:
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Run tools with `python -m <tool>` so you don't depend on the venv's `.exe`
launchers (which break if the project folder is moved).

## Quality gates

All four are enforced; `make check` (Linux/macOS) runs the exact CI set.

| Gate | Command |
|------|---------|
| Lint | `python -m ruff check local_codex_lite\ tests\` |
| Format | `python -m ruff format --check local_codex_lite\ tests\` |
| Types | `python -m mypy local_codex_lite\` |
| Tests + coverage | `python -m pytest -q --cov=local_codex_lite --cov-fail-under=90` |

`ruff` and `mypy` are pinned to exact versions in **both** `pyproject.toml`
`[dev]` and `.pre-commit-config.yaml` — keep them in lockstep. Coverage floor is
90% (the suite achieves 100% on Windows; headless Linux runners achieve ~91%
because the Tk display tests are skipped).

## Pre-commit

```powershell
pre-commit install
pre-commit run --all-files
```

## CI

`.github/workflows/ci.yml` runs a stdlib-only smoke gate, then a lint+type+test
matrix (Ubuntu 3.11/3.12/3.13 + Windows 3.12), a no-LLM CLI smoke job, a CLI
reference staleness check, and a non-blocking `ruff-canary` job on the latest ruff.
`mutmut.yml` runs scoped mutation testing weekly.

> `.gitlab-ci.yml` mirrors the GitHub Actions gates (lint + format + mypy +
> pytest with the 90% floor) on Python 3.11/3.12/3.13 via parallel matrix.
> Keep tool versions in lockstep across `pyproject.toml`, `.pre-commit-config.yaml`,
> and both CI files.

## Testing notes

- The full suite needs the `[dev]` extras. `tools/stdlib_smoke.py` runs the
  safety-critical core with only the stdlib in ~1s.
- `hypothesis` is optional; its property tests skip when it's absent.
- The planner is unit-testable via the `SupportsChat` client seam — inject a
  fake client instead of monkeypatching the module-level class.
