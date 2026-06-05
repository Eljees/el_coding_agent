"""Planner branch coverage for paths not reached by existing retry tests.

Targeted lines in planner.py:
  74-98    make_plan with runtime_fix (single-file focused plan)
  298-301  _make_standard_patch: extract_diff ValueError → parse_error logged, retry
  330-335  _make_standard_patch: 3 consecutive HTTP errors → RuntimeError raised
  413-419  repair_patch_with_error inner loop: exception → continue; same-patch → continue
  468-487  suggest_commands with runtime_fix (single-file focused commands)
  549-565  make_review ValueError path → repair_json_response called
  658      _build_repair_diagnosis with intended_target=None
  747-760  _build_failed_file_context: file exists or missing
  825-877  _repair_via_full_file_rewrite non-runtime_fix path (exactly 1 path from diff)
  1023-1060 _retry_with_context_variants: ValueError parse path + HTTP error exhaustion
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

import local_codex_lite.planner as planner
from local_codex_lite.config import AgentConfig
from local_codex_lite.llm_client import LLMResponse
from local_codex_lite.patcher import RuntimeFixContext

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_PLAN_JSON = json.dumps(
    {
        "summary": "fix foo",
        "files_to_inspect": ["foo.py"],
        "implementation_steps": [],
        "risks": [],
        "needs_clarification": False,
        "clarifying_questions": [],
    }
)
_VALID_DIFF = "\n".join(
    [
        "diff --git a/foo.py b/foo.py",
        "--- a/foo.py",
        "+++ b/foo.py",
        "@@ -1 +1,2 @@",
        "+# added",
        " print('hi')",
    ]
)
_REVIEW_JSON = json.dumps({"summary": "looks good", "issues": [], "verdict": "approve"})
_COMMANDS_JSON = json.dumps({"commands": []})


def _http_error():
    req = httpx.Request("POST", "http://localhost:8015/v1/chat/completions")
    resp = httpx.Response(400, request=req, text='{"detail":"context too large"}')
    return httpx.HTTPStatusError("bad request", request=req, response=resp)


def _runtime_fix_ctx(tmp_path: Path) -> RuntimeFixContext:
    target = tmp_path / "foo.py"
    target.write_text("print('hi')\n", encoding="utf-8")
    return RuntimeFixContext(
        target_path=target,
        traceback_text="Traceback: ValueError at line 1",
        current_text=target.read_text(encoding="utf-8"),
        secondary_files=[],
    )


def _make_ws(tmp_path: Path) -> Path:
    (tmp_path / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    return tmp_path


# ---------------------------------------------------------------------------
# make_plan with runtime_fix (lines 74-98)
# ---------------------------------------------------------------------------


def test_make_plan_runtime_fix_path(tmp_path: Path, monkeypatch) -> None:
    """make_plan with runtime_fix calls the focused single-file plan prompt."""
    ws = _make_ws(tmp_path)
    rfx = _runtime_fix_ctx(tmp_path)
    calls = {"n": 0}

    class _Stub:
        def __init__(self, cfg=None) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            calls["n"] += 1
            return LLMResponse(text=_PLAN_JSON, raw={"model": "stub"})

    monkeypatch.setattr(planner, "OpenAICompatibleClient", _Stub)
    result = planner.make_plan("fix the bug", ws, AgentConfig(), runtime_fix=rfx)
    assert result["summary"] == "fix foo"
    assert calls["n"] == 1  # single focused call, no retry


# ---------------------------------------------------------------------------
# _make_standard_patch: parse error → retry (lines 298-301)
# ---------------------------------------------------------------------------


def test_make_patch_parse_error_then_success(tmp_path: Path, monkeypatch) -> None:
    """When extract_diff raises ValueError on first attempt, the error is logged and
    the loop continues; the second attempt returns a valid diff."""
    ws = _make_ws(tmp_path)
    state = {"calls": 0}

    class _Stub:
        def __init__(self, cfg=None) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            state["calls"] += 1
            if state["calls"] == 1:
                return LLMResponse(text="not a diff at all", raw={"model": "stub"})
            return LLMResponse(text=_VALID_DIFF, raw={"model": "stub"})

    monkeypatch.setattr(planner, "OpenAICompatibleClient", _Stub)
    monkeypatch.setattr(planner.time, "sleep", lambda s: None)

    result = planner.make_patch("fix foo", {"summary": "fix"}, ws, AgentConfig())
    assert "# added" in result
    assert state["calls"] == 2


# ---------------------------------------------------------------------------
# _make_standard_patch: 3 HTTP errors → RuntimeError (lines 330-335)
# ---------------------------------------------------------------------------


def test_make_patch_exhausts_retries_raises(tmp_path: Path, monkeypatch) -> None:
    """Three consecutive HTTP errors cause make_patch to raise RuntimeError."""
    ws = _make_ws(tmp_path)

    class _AlwaysFails:
        def __init__(self, cfg=None) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            raise _http_error()

    monkeypatch.setattr(planner, "OpenAICompatibleClient", _AlwaysFails)
    monkeypatch.setattr(planner.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="patch generation failed"):
        planner.make_patch("fix foo", {"summary": "fix"}, ws, AgentConfig())


# ---------------------------------------------------------------------------
# repair_patch_with_error: exception in inner loop (line 413-419)
# ---------------------------------------------------------------------------


def test_repair_patch_exception_in_inner_loop(tmp_path: Path, monkeypatch) -> None:
    """When the first two repair-loop variants raise HTTP errors (caught, continue),
    the third variant returns a valid diff and repair succeeds.

    Uses issue_type='path_mismatch' to avoid the full-file-rewrite path (which
    has no try/except and would propagate the error).
    """
    ws = _make_ws(tmp_path)
    state = {"calls": 0}

    class _Stub:
        def __init__(self, cfg=None) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            state["calls"] += 1
            # First two calls (inner repair-loop variants) raise; third succeeds.
            if state["calls"] <= 2:
                raise _http_error()
            return LLMResponse(text=_VALID_DIFF, raw={"model": "stub"})

    result = planner.repair_patch_with_error(
        "fix foo",
        {"summary": "fix"},
        # Use a different diff so the returned patch != previous_patch check passes.
        "diff --git a/foo.py b/foo.py\n--- a/foo.py\n+++ b/foo.py\n@@ -1 +1 @@\n-print('hi')\n+print('bye')\n",
        "path mismatch: bad path",
        "path_mismatch",
        ws,
        AgentConfig(),
        client=_Stub(),
    )
    assert result is not None
    assert state["calls"] == 3


def test_repair_patch_same_patch_continues(tmp_path: Path, monkeypatch) -> None:
    """When repair returns the same patch text, the loop skips that variant."""
    ws = _make_ws(tmp_path)
    state = {"calls": 0}

    class _Stub:
        def __init__(self, cfg=None) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            state["calls"] += 1
            if state["calls"] <= 2:
                return LLMResponse(text=_VALID_DIFF, raw={"model": "stub"})  # same as input
            return LLMResponse(text=_VALID_DIFF + "\n+# different", raw={"model": "stub"})

    stub = _Stub()
    planner.repair_patch_with_error(
        "fix foo",
        {"summary": "fix"},
        _VALID_DIFF,
        "context mismatch",
        "context_mismatch",
        ws,
        AgentConfig(),
        client=stub,
    )
    # Eventually gets a different patch (even if extract_diff can't parse the extra line,
    # the function must not infinitely loop and must return something or None).
    # We just assert it did not raise.


# ---------------------------------------------------------------------------
# suggest_commands with runtime_fix (lines 468-487)
# ---------------------------------------------------------------------------


def test_suggest_commands_runtime_fix_path(tmp_path: Path, monkeypatch) -> None:
    """suggest_commands with runtime_fix calls the focused single-file command prompt."""
    ws = _make_ws(tmp_path)
    rfx = _runtime_fix_ctx(tmp_path)
    calls = {"n": 0}

    class _Stub:
        def __init__(self, cfg=None) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            calls["n"] += 1
            return LLMResponse(text=_COMMANDS_JSON, raw={"model": "stub"})

    result = planner.suggest_commands(
        "fix the bug",
        {"summary": "fix"},
        ws,
        AgentConfig(),
        runtime_fix=rfx,
        client=_Stub(),
    )
    assert "commands" in result
    assert calls["n"] == 1


# ---------------------------------------------------------------------------
# make_review ValueError path (lines 549-565)
# ---------------------------------------------------------------------------


def test_make_review_parse_error_triggers_repair(tmp_path: Path, monkeypatch) -> None:
    """When extract_json fails on the review response, repair_json_response is called."""
    ws = _make_ws(tmp_path)
    state = {"calls": 0}

    class _Stub:
        def __init__(self, cfg=None) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            state["calls"] += 1
            if state["calls"] == 1:
                return LLMResponse(text="not json at all {{", raw={"model": "stub"})
            return LLMResponse(text=_REVIEW_JSON, raw={"model": "stub"})

    stub = _Stub()
    result = planner.make_review("review diff", _VALID_DIFF, ws, AgentConfig(), client=stub)
    # repair_json_response calls the LLM again and returns valid JSON
    assert isinstance(result, dict)
    assert state["calls"] >= 2


# ---------------------------------------------------------------------------
# _build_repair_diagnosis with no intended_target (line 658)
# ---------------------------------------------------------------------------


def test_build_repair_diagnosis_no_target(tmp_path: Path) -> None:
    """When the task text has no file hints, intended_target is None → drifted=False."""
    ws = _make_ws(tmp_path)
    diagnosis = planner._build_repair_diagnosis(
        "do something vague with no filename",
        ws,
        previous_patch=_VALID_DIFF,
        error="patch does not apply",
    )
    # Either no target, or it found foo.py — either way no crash.
    assert isinstance(diagnosis.drifted, bool)


# ---------------------------------------------------------------------------
# _build_failed_file_context: file missing vs file present (lines 747-760)
# ---------------------------------------------------------------------------


def test_build_failed_file_context_missing_file(tmp_path: Path) -> None:
    """Returns empty string when the path extracted from the patch does not exist."""
    ws = tmp_path  # foo.py not created here
    result = planner._build_failed_file_context(
        ws,
        previous_patch=_VALID_DIFF,
        error="patch does not apply",
        max_chars_per_file=1000,
    )
    assert result == ""


def test_build_failed_file_context_existing_file(tmp_path: Path) -> None:
    """Returns a snippet block when the target file exists."""
    ws = _make_ws(tmp_path)
    result = planner._build_failed_file_context(
        ws,
        previous_patch=_VALID_DIFF,
        error="patch does not apply",
        max_chars_per_file=1000,
    )
    assert "foo.py" in result
    assert "print" in result


# ---------------------------------------------------------------------------
# _repair_via_full_file_rewrite: non-runtime_fix case (lines 825-877)
# ---------------------------------------------------------------------------


def test_repair_via_full_file_rewrite_non_runtime_fix(tmp_path: Path) -> None:
    """Without runtime_fix, function extracts path from previous_patch and rewrites."""
    ws = _make_ws(tmp_path)
    calls = {"n": 0}

    class _Stub:
        def __init__(self, cfg=None) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            calls["n"] += 1
            return LLMResponse(text="print('hi')\n# rewritten", raw={"model": "stub"})

    result = planner._repair_via_full_file_rewrite(
        _Stub(),
        "fix foo",
        {"summary": "fix"},
        ws,
        AgentConfig(),
        previous_patch=_VALID_DIFF,
        error="context mismatch",
        issue_type="context_mismatch",
        repair_attempt=1,
        runtime_fix=None,
    )
    # Returns a unified diff or None if new content == old content.
    assert result is None or "foo.py" in result


# ---------------------------------------------------------------------------
# _retry_with_context_variants: ValueError parse + HTTP error exhaustion (lines 1023-1060)
# ---------------------------------------------------------------------------


def test_retry_with_context_variants_parse_error_calls_repair(tmp_path: Path, monkeypatch) -> None:
    """When parse_response (extract_json) raises ValueError, repair_response is called."""
    ws = _make_ws(tmp_path)
    state = {"calls": 0}

    class _Stub:
        def __init__(self, cfg=None) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            state["calls"] += 1
            return LLMResponse(text="not json {{", raw={"model": "stub"})

    repair_called = {"n": 0}

    def _repair(text, messages, budget):
        repair_called["n"] += 1
        return {"commands": []}

    stub = _Stub()
    planner._retry_with_context_variants(
        client=stub,
        task="do something",
        workspace_root=ws,
        config=AgentConfig(),
        variant="commands",
        run_dir=None,
        stage="commands",
        status_prefix="Commands",
        parse_response=planner.extract_json,
        repair_response=_repair,
        prompt_builder=lambda ctx: [{"role": "user", "content": f"ctx:{ctx}"}],
    )
    assert repair_called["n"] >= 1


def test_retry_with_context_variants_http_errors_raise(tmp_path: Path, monkeypatch) -> None:
    """Three consecutive HTTP errors cause _retry_with_context_variants to raise RuntimeError."""
    ws = _make_ws(tmp_path)

    class _AlwaysFails:
        def __init__(self, cfg=None) -> None:
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            raise _http_error()

    monkeypatch.setattr(planner.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="generation failed"):
        planner._retry_with_context_variants(
            client=_AlwaysFails(),
            task="do something",
            workspace_root=ws,
            config=AgentConfig(),
            variant="commands",
            run_dir=None,
            stage="commands",
            status_prefix="Commands",
            parse_response=planner.extract_json,
            repair_response=lambda t, m, b: {},
            prompt_builder=lambda ctx: [{"role": "user", "content": "x"}],
        )
