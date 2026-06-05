#!/usr/bin/env python3
"""Stdlib-only smoke runner for the subset of tests that don't pull pydantic/httpx.

The full test suite needs the ``[dev]`` extras (pytest, pydantic, httpx,
hypothesis).  But the safety-critical core -- ``safety.py``,
``patch_errors.py``, ``capabilities.py``, ``intent.py``, ``targeting.py``,
``path_filters.py``, ``container_errors.py``, ``prompts.py``,
``evidence.py`` -- has no third-party imports at all.  This script gives
you a 1-second yes/no on whether those modules are healthy, without
needing a venv.

Usage:
    python tools/stdlib_smoke.py                # run the default set
    python tools/stdlib_smoke.py tests/foo.py   # run specific files
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import sys
import tempfile
import traceback
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

DEFAULT_FILES = (
    "tests/test_safety.py",
    "tests/test_capabilities_discovery.py",
    "tests/test_capabilities_intent.py",
    "tests/test_intent.py",
    "tests/test_targeting.py",
    "tests/test_path_filters.py",
    "tests/test_container_errors.py",
    "tests/test_prompts.py",
    "tests/test_evidence.py",
    "tests/test_sample_plugin_example.py",
    "tests/test_plugins_cmd.py",
)


# --- tiny pytest shim ----------------------------------------------------


class _SkipException(Exception):
    pass


def _skip(reason: str = "", *, allow_module_level: bool = False) -> None:
    raise _SkipException(reason)


class _Raises:
    def __init__(self, exc_type, match=None):
        self.exc_type = exc_type
        self.match = match
        self.value = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            raise AssertionError(f"expected {self.exc_type.__name__}, got none")
        if not issubclass(exc_type, self.exc_type):
            return False
        self.value = exc
        return True


def _fixture(*a, **kw):
    if a and callable(a[0]):
        return a[0]

    def deco(fn):
        return fn

    return deco


def _install_pytest_shim() -> None:
    if "pytest" in sys.modules:
        return
    m = types.ModuleType("pytest")
    m.skip = _skip
    m.raises = _Raises
    m.fixture = _fixture
    m.fail = lambda msg="": (_ for _ in ()).throw(AssertionError(msg))
    mark = types.SimpleNamespace()
    mark.parametrize = lambda *a, **kw: lambda fn: fn
    mark.skipif = lambda *a, **kw: lambda fn: fn
    m.mark = mark
    sys.modules["pytest"] = m


_install_pytest_shim()


# --- fixtures ------------------------------------------------------------


class _Missing:
    pass


_MISSING = _Missing()


def _resolve_dotted(path: str):
    """``a.b.c.d`` -> (parent_obj, last_attr).  Walks the longest importable
    module prefix, then attribute-walks the rest.  This mirrors
    pytest.monkeypatch.setattr's dotted-string form."""
    parts = path.split(".")
    for n in range(len(parts) - 1, 0, -1):
        try:
            mod = importlib.import_module(".".join(parts[:n]))
        except ImportError:
            continue
        obj = mod
        for p in parts[n:-1]:
            obj = getattr(obj, p)
        return obj, parts[-1]
    raise ImportError(f"cannot resolve {path}")


class MonkeyPatch:
    def __init__(self) -> None:
        self._undo: list = []

    def setattr(self, target, name, value=None, raising=True):
        if isinstance(target, str):
            obj, attr = _resolve_dotted(target)
            old = getattr(obj, attr) if hasattr(obj, attr) else _MISSING
            self._undo.append(("setattr", obj, attr, old))
            setattr(obj, attr, name)
        else:
            old = getattr(target, name) if hasattr(target, name) else _MISSING
            self._undo.append(("setattr", target, name, old))
            setattr(target, name, value)

    def setenv(self, name, value):
        old = os.environ.get(name, _MISSING)
        self._undo.append(("setenv", name, old))
        os.environ[name] = value

    def delenv(self, name, raising=True):
        old = os.environ.get(name, _MISSING)
        self._undo.append(("setenv", name, old))
        os.environ.pop(name, None)

    def chdir(self, path):
        old = os.getcwd()
        self._undo.append(("chdir", old))
        os.chdir(path)

    def syspath_prepend(self, path):
        self._undo.append(("syspath", sys.path[:]))
        sys.path.insert(0, str(path))

    def undo(self):
        for entry in reversed(self._undo):
            kind = entry[0]
            if kind == "setattr":
                _, obj, attr, old = entry
                if old is _MISSING:
                    if hasattr(obj, attr):
                        try:
                            delattr(obj, attr)
                        except AttributeError:
                            pass
                else:
                    setattr(obj, attr, old)
            elif kind == "setenv":
                _, name, old = entry
                if old is _MISSING:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = old
            elif kind == "chdir":
                _, old = entry
                os.chdir(old)
            elif kind == "syspath":
                _, old = entry
                sys.path[:] = old
        self._undo.clear()


# --- runner --------------------------------------------------------------


def _load_module(path: Path):
    spec = importlib.util.spec_from_file_location(f"_stdlib_smoke_{path.stem}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _run_test(fn):
    sig = inspect.signature(fn)
    kwargs = {}
    cleanups = []
    for pname in sig.parameters:
        if pname == "tmp_path":
            td = tempfile.TemporaryDirectory()
            cleanups.append(td.cleanup)
            kwargs[pname] = Path(td.name)
        elif pname == "monkeypatch":
            mp = MonkeyPatch()
            cleanups.append(mp.undo)
            kwargs[pname] = mp
        else:
            return ("skip", f"unsupported fixture: {pname}")
    try:
        fn(**kwargs)
    except _SkipException as exc:
        return ("skip", str(exc))
    except AssertionError:
        return ("fail", traceback.format_exc())
    except Exception:
        return ("error", traceback.format_exc())
    finally:
        for c in reversed(cleanups):
            try:
                c()
            except Exception:
                pass
    return ("pass", "")


def _run_file(path: Path):
    counts = {"pass": 0, "fail": 0, "error": 0, "skip": 0}
    failures: list = []
    try:
        module = _load_module(path)
    except Exception:
        return {
            "counts": {"pass": 0, "fail": 0, "error": 1, "skip": 0},
            "failures": [(path.name, "<import>", traceback.format_exc())],
        }
    tests = [
        (n, o)
        for n, o in inspect.getmembers(module, inspect.isfunction)
        if n.startswith("test_") and o.__module__ == module.__name__
    ]
    for name, fn in tests:
        outcome, detail = _run_test(fn)
        counts[outcome] += 1
        if outcome in ("fail", "error"):
            failures.append((path.name, name, detail))
    return {"counts": counts, "failures": failures}


def main(argv):
    sys.path.insert(0, str(REPO_ROOT))
    paths = [Path(a) for a in argv] if argv else [REPO_ROOT / p for p in DEFAULT_FILES]
    total = {"pass": 0, "fail": 0, "error": 0, "skip": 0}
    all_failures: list = []
    for path in paths:
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.is_file():
            print(f"{path}: not a file", file=sys.stderr)
            total["error"] += 1
            continue
        result = _run_file(path)
        c = result["counts"]
        for k, v in c.items():
            total[k] += v
        all_failures.extend(result["failures"])
        print(f"{path.name}: pass={c['pass']} fail={c['fail']} error={c['error']} skip={c['skip']}")
    print()
    print(
        f"TOTAL: pass={total['pass']} fail={total['fail']} "
        f"error={total['error']} skip={total['skip']}"
    )
    if all_failures:
        print()
        print("=== FAILURES ===")
        for fname, tname, detail in all_failures:
            print(f"\n--- {fname}::{tname} ---")
            print(detail)
    return 0 if total["fail"] == 0 and total["error"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
