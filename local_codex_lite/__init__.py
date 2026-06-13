"""local_codex_lite package."""

import sys as _sys

# Friendly version guard: the package uses `datetime.UTC` (added in 3.11) and
# other 3.11+ stdlib features. Without this check a 3.10 user gets a cryptic
# `ImportError: cannot import name 'UTC'` from a deep submodule. Fail early with
# an actionable message instead. Keep this above any submodule imports.
if _sys.version_info < (3, 11):  # noqa: UP036 — belt-and-suspenders for non-pip installs  # pragma: no cover
    raise RuntimeError(
        "local_codex_lite requires Python 3.11 or newer "
        f"(running {_sys.version_info.major}.{_sys.version_info.minor}). "
        "Please use a 3.11+ interpreter."
    )

__all__ = ["__version__"]

__version__ = "0.1.0"
