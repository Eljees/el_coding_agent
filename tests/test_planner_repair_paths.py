"""Coverage for planner.py repair/revise/helper paths not reached by other tests.

Targeted lines (as of 2026-06-11 audit):
  223-262  _make_runtime_fix_patch: HTTP error path + full_file_rewrite fallback
  347-348  _make_standard_patch: non-context_too_large error on attempt 3 → raise
  432-433  repair_patch_with_error: same-patch continue in inner loop
  435-466  repair_patch_with_error: fallback_messages path (all variants exhausted)
  502      suggest_commands: non-runtime_fix return path
  592-612  revise_plan_with_assumptions
  615-655  revise_plan_with_answers
  812-813  _build_failed_file_context: OSError on read
  829-838  _build_repair_fallback_context: targeted vs compact context branches
  852-860  _runtime_fix_context_block: secondary_files non-empty
  883-885  _repair_via_full_file_rewrite: runtime_fix not None path
  889      _repair_via_full_file_rewrite: len(paths) != 1 → return None
  893      _repair_via_full_file_rewrite: path.is_file() False → return None
  933      _repair_via_full_file_rewrite: same content → return None
  952      _repair_via_intended_target: target is None → return None
  974      _repair_via_intended_target: patch_paths don't match target → return None
  976      _repair_via_intended_target: target.exists=False but path exists → return None
  983-985  _strip_fences: backtick-wrapped content
  1036-37  _extract_failed_paths: path found in error string
  1113-16  _retry_with_context_variants: non-context_too_large error → sleep + break
  1161     _response_text_from_exception: exc has no response → return None
  1165     _response_text_from_exception: response.text is not str → return None
  1175     _format_exception: exc has no response attribute
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

import local_codex_lite.planner as planner
from local_codex_lite.config import AgentConfig
from local_codex_lite.llm_client import LLMResponse
from local_codex_lite.patcher import RuntimeFixContext

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PLAN = {"summary": "fix foo", "files_to_inspect": ["foo.py"], "implementation_steps": []}
_PLAN_JSON = json.dumps(_PLAN)

_VALID_DIFF = "\n".join(
    [
        "diff --git a/foo.py b/foo.py",
        "--- a/foo.py",
        "+++ b/foo.py",
        "@@ -1 +1,2 @@",
        "+# new",
        " print('hi')",
    ]
)

_PLAN_JSON_FULL = json.dumps(
    {
        "summary": "fix foo",
        "files_to_inspect": ["foo.py"],
        "implementation_steps": [],
        "risks": [],
        "needs_clarification": False,
        "clarifying_questions": ["What is the bug?"],
    }
)


def _make_ws(tmp_path: Path, content: str = "print('hi')\n") -> Path:
    (tmp_path / "foo.py").write_text(content, encoding="utf-8")
    return tmp_path


def _rfx(tmp_path: Path, secondary: bool = False) -> RuntimeFixContext:
    target = tmp_path / "foo.py"
    target.write_text("print('hi')\n", encoding="utf-8")
    sec = []
    if secondary:
        helper = tmp_path / "helper.py"
        helper.write_text("def helper(): pass\n", encoding="utf-8")
        sec = [(helper, "def helper(): pass\n")]
    return RuntimeFixContext(
        target_path=target,
        traceback_text="Traceback: ValueError",
        current_text=target.read_text(encoding="utf-8"),
        secondary_files=sec,
    )


def _non_context_http_error():
    req = httpx.Request("POST", "http://localhost:8015/v1/chat/completions")
    resp = httpx.Response(500, request=req, text='{"detail":"internal server error"}')
    return httpx.HTTPStatusError("server error", request=req, response=resp)


class _StaticStub:
    def __init__(self, responses):
        self._responses = iter(responses)

    def chat(self, messages, max_tokens=None, status_label=None):
        return next(self._responses)


# ---------------------------------------------------------------------------
# _make_runtime_fix_patch: HTTP error path + full_file_rewrite fallback (223-262)
# ---------------------------------------------------------------------------


def test_make_runtime_fix_patch_http_error_triggers_rewrite(tmp_path: Path, monkeypatch) -> None:
    """HTTP errors on all 3 runtime-fix attempts → _repair_via_full_file_rewrite called."""
    ws = _make_ws(tmp_path)
    rfx = _rfx(tmp_path)

    class _FailThenRewrite:
        def __init__(self, cfg=None):
            self._calls = 0

        def chat(self, messages, max_tokens=None, status_label=None):
            self._calls += 1
            if self._calls <= 3:
                raise _non_context_http_error()
            return LLMResponse(text="print('hi')\n# rewritten", raw={})

    monkeypatch.setattr(planner, "OpenAICompatibleClient", _FailThenRewrite)
    result = planner.make_patch("fix bug", _PLAN, ws, AgentConfig(), runtime_fix=rfx)
    assert result is not None


def test_make_runtime_fix_patch_all_fail_raises(tmp_path: Path, monkeypatch) -> None:
    """All HTTP errors + full_file_rewrite returns None → RuntimeError (lines 262-264)."""
    ws = _make_ws(tmp_path)
    rfx = _rfx(tmp_path)

    class _FailThenSame:
        def __init__(self, cfg=None):
            self._calls = 0

        def chat(self, messages, max_tokens=None, status_label=None):
            self._calls += 1
            if self._calls <= 3:
                raise _non_context_http_error()
            # 4th call (from _repair_via_full_file_rewrite): return same content → None
            return LLMResponse(text="print('hi')\n", raw={})

    monkeypatch.setattr(planner, "OpenAICompatibleClient", _FailThenSame)
    with pytest.raises(RuntimeError, match="patch generation failed"):
        planner.make_patch("fix bug", _PLAN, ws, AgentConfig(), runtime_fix=rfx)


# ---------------------------------------------------------------------------
# _make_standard_patch: non-context_too_large error raises at attempt 3 (347-348)
# ---------------------------------------------------------------------------


def test_make_standard_patch_non_ctx_error_raises_with_message(tmp_path, monkeypatch) -> None:
    """Non-context_too_large HTTP error on all attempts → raise with last_error in message."""
    ws = _make_ws(tmp_path)

    class _InternalError:
        def __init__(self, cfg=None):
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            raise _non_context_http_error()

    monkeypatch.setattr(planner, "OpenAICompatibleClient", _InternalError)
    monkeypatch.setattr(planner.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError) as exc_info:
        planner.make_patch("fix foo", _PLAN, ws, AgentConfig())
    assert "patch generation failed" in str(exc_info.value)


# ---------------------------------------------------------------------------
# repair_patch_with_error: fallback path (432-466)
# ---------------------------------------------------------------------------


def _no_diagnosis(*a, **kw):
    return planner.RepairDiagnosis(intended_target=None, touched_paths=(), drifted=False)


def test_repair_patch_fallback_succeeds(tmp_path: Path, monkeypatch) -> None:
    """All repair-loop variants return same patch → fallback call returns different patch."""
    ws = _make_ws(tmp_path)
    different_diff = _VALID_DIFF + "\n+# fallback line"
    state = {"calls": 0}

    class _Stub:
        def chat(self, messages, max_tokens=None, status_label=None):
            state["calls"] += 1
            if state["calls"] == 1:
                return LLMResponse(text=_VALID_DIFF, raw={})  # same → continue
            return LLMResponse(text=different_diff, raw={})  # fallback → different

    monkeypatch.setattr(planner, "_repair_context_variants", lambda *a, **kw: ["ctx1"])
    monkeypatch.setattr(planner, "_build_repair_diagnosis", _no_diagnosis)
    result = planner.repair_patch_with_error(
        "fix foo",
        _PLAN,
        _VALID_DIFF,
        "path mismatch",
        "path_mismatch",
        ws,
        AgentConfig(),
        client=_Stub(),
    )
    assert result is not None


def test_repair_patch_fallback_exception_raises(tmp_path: Path, monkeypatch) -> None:
    """Fallback client.chat() raises → RuntimeError (lines 464-466)."""
    ws = _make_ws(tmp_path)

    class _Stub:
        def __init__(self):
            self._calls = 0

        def chat(self, messages, max_tokens=None, status_label=None):
            self._calls += 1
            if self._calls == 1:
                return LLMResponse(text=_VALID_DIFF, raw={})  # same → loop continues
            raise RuntimeError("fallback boom")

    monkeypatch.setattr(planner, "_repair_context_variants", lambda *a, **kw: ["ctx1"])
    monkeypatch.setattr(planner, "_build_repair_diagnosis", _no_diagnosis)
    with pytest.raises(RuntimeError):
        planner.repair_patch_with_error(
            "fix foo",
            _PLAN,
            _VALID_DIFF,
            "path mismatch",
            "path_mismatch",
            ws,
            AgentConfig(),
            client=_Stub(),
        )


def test_repair_patch_fallback_same_patch_raises(tmp_path: Path, monkeypatch) -> None:
    """Fallback also returns same patch as previous → RuntimeError (line 466)."""
    ws = _make_ws(tmp_path)

    class _AlwaysSame:
        def chat(self, messages, max_tokens=None, status_label=None):
            return LLMResponse(text=_VALID_DIFF, raw={})

    monkeypatch.setattr(planner, "_repair_context_variants", lambda *a, **kw: ["ctx1"])
    monkeypatch.setattr(planner, "_build_repair_diagnosis", _no_diagnosis)
    with pytest.raises(RuntimeError):
        planner.repair_patch_with_error(
            "fix foo",
            _PLAN,
            _VALID_DIFF,
            "path mismatch",
            "path_mismatch",
            ws,
            AgentConfig(),
            client=_AlwaysSame(),
        )


# ---------------------------------------------------------------------------
# suggest_commands: non-runtime_fix path (line 502)
# ---------------------------------------------------------------------------


def test_suggest_commands_no_runtime_fix(tmp_path: Path, monkeypatch) -> None:
    """suggest_commands without runtime_fix calls _retry_with_context_variants (line 502)."""
    ws = _make_ws(tmp_path)

    class _Stub:
        def __init__(self, cfg=None):
            pass

        def chat(self, messages, max_tokens=None, status_label=None):
            return LLMResponse(text='{"commands": ["pytest"]}', raw={})

    monkeypatch.setattr(planner, "OpenAICompatibleClient", _Stub)
    result = planner.suggest_commands("run tests", _PLAN, ws, AgentConfig())
    assert "commands" in result


# ---------------------------------------------------------------------------
# revise_plan_with_assumptions (592-612)
# ---------------------------------------------------------------------------


def test_revise_plan_with_assumptions_success(tmp_path: Path) -> None:
    """revise_plan_with_assumptions returns a plan dict on valid JSON response."""
    ws = _make_ws(tmp_path)

    class _Stub:
        def chat(self, messages, max_tokens=None, status_label=None):
            return LLMResponse(text=_PLAN_JSON_FULL, raw={})

    result = planner.revise_plan_with_assumptions(
        "fix the bug", _PLAN, ws, AgentConfig(), client=_Stub()
    )
    assert isinstance(result, dict)


def test_revise_plan_with_assumptions_invalid_json_triggers_repair(tmp_path: Path) -> None:
    """When response is not valid JSON, repair_json_response is called."""
    ws = _make_ws(tmp_path)
    state = {"calls": 0}

    class _Stub:
        def chat(self, messages, max_tokens=None, status_label=None):
            state["calls"] += 1
            if state["calls"] == 1:
                return LLMResponse(text="not json {{", raw={})
            return LLMResponse(text=_PLAN_JSON_FULL, raw={})

    result = planner.revise_plan_with_assumptions(
        "fix the bug", _PLAN, ws, AgentConfig(), client=_Stub()
    )
    assert isinstance(result, dict)
    assert state["calls"] >= 2


def test_revise_plan_with_assumptions_no_clarifying_questions(tmp_path: Path) -> None:
    """Plan without clarifying_questions key is handled gracefully (questions=[])."""
    ws = _make_ws(tmp_path)

    class _Stub:
        def chat(self, messages, max_tokens=None, status_label=None):
            return LLMResponse(text=_PLAN_JSON_FULL, raw={})

    plan_no_q = {"summary": "fix", "files_to_inspect": []}
    result = planner.revise_plan_with_assumptions(
        "fix it", plan_no_q, ws, AgentConfig(), client=_Stub()
    )
    assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# revise_plan_with_answers (615-655)
# ---------------------------------------------------------------------------


def test_revise_plan_with_answers_success(tmp_path: Path) -> None:
    """revise_plan_with_answers returns dict on valid JSON response."""
    ws = _make_ws(tmp_path)

    class _Stub:
        def chat(self, messages, max_tokens=None, status_label=None):
            return LLMResponse(text=_PLAN_JSON_FULL, raw={})

    result = planner.revise_plan_with_answers(
        "fix the bug",
        _PLAN,
        [("What is broken?", "The loop")],
        ws,
        AgentConfig(),
        client=_Stub(),
    )
    assert isinstance(result, dict)


def test_revise_plan_with_answers_invalid_json_triggers_repair(tmp_path: Path) -> None:
    """Invalid JSON response triggers repair_json_response fallback."""
    ws = _make_ws(tmp_path)
    state = {"calls": 0}

    class _Stub:
        def chat(self, messages, max_tokens=None, status_label=None):
            state["calls"] += 1
            if state["calls"] == 1:
                return LLMResponse(text="not json {{", raw={})
            return LLMResponse(text=_PLAN_JSON_FULL, raw={})

    result = planner.revise_plan_with_answers(
        "fix the bug",
        _PLAN,
        [("Q?", "A")],
        ws,
        AgentConfig(),
        client=_Stub(),
    )
    assert isinstance(result, dict)
    assert state["calls"] >= 2


# ---------------------------------------------------------------------------
# _build_failed_file_context: OSError branch (812-813)
# ---------------------------------------------------------------------------


def test_build_failed_file_context_oserror_skips_file(tmp_path: Path, monkeypatch) -> None:
    """OSError reading a file that exists is silently skipped (lines 812-813)."""
    ws = _make_ws(tmp_path)

    def _bad_read(encoding, errors):
        raise OSError("permission denied")

    monkeypatch.setattr(
        Path, "read_text", lambda self, **kw: (_ for _ in ()).throw(OSError("denied"))
    )
    result = planner._build_failed_file_context(
        ws,
        previous_patch=_VALID_DIFF,
        error="patch does not apply",
        max_chars_per_file=1000,
    )
    assert result == ""


# ---------------------------------------------------------------------------
# _build_repair_fallback_context: targeted vs compact context (829-838)
# ---------------------------------------------------------------------------


def test_build_repair_fallback_context_with_targeted(tmp_path: Path) -> None:
    """Returns focused context when target file exists."""
    ws = _make_ws(tmp_path)
    ctx = planner._build_repair_fallback_context(
        ws,
        "fix foo",
        AgentConfig(),
        previous_patch=_VALID_DIFF,
        error="patch failed",
    )
    assert isinstance(ctx, str)
    assert len(ctx) > 0


def test_build_repair_fallback_context_no_target(tmp_path: Path) -> None:
    """Falls back to compact_context when no target file is extractable."""
    ws = tmp_path  # foo.py does NOT exist, so _build_failed_file_context returns ""
    ctx = planner._build_repair_fallback_context(
        ws,
        "fix foo",
        AgentConfig(),
        previous_patch=_VALID_DIFF,
        error="patch failed",
        diagnosis=None,
    )
    assert isinstance(ctx, str)


# ---------------------------------------------------------------------------
# _runtime_fix_context_block: secondary_files non-empty (852-860)
# ---------------------------------------------------------------------------


def test_runtime_fix_context_block_with_secondary_files(tmp_path: Path) -> None:
    """_runtime_fix_context_block includes secondary file snippets."""
    ws = _make_ws(tmp_path)
    rfx = _rfx(tmp_path, secondary=True)
    block = planner._runtime_fix_context_block(rfx, ws)
    assert "helper.py" in block
    assert "Related files" in block


def test_runtime_fix_context_block_secondary_outside_workspace(tmp_path: Path) -> None:
    """Secondary file outside workspace_root → uses str(p) path (lines 856-857)."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "foo.py").write_text("print('hi')\n", encoding="utf-8")
    outside = tmp_path / "external.py"
    outside.write_text("# external\n", encoding="utf-8")
    rfx = RuntimeFixContext(
        target_path=ws / "foo.py",
        traceback_text="err",
        current_text="print('hi')\n",
        secondary_files=[(outside, "# external\n")],
    )
    block = planner._runtime_fix_context_block(rfx, ws)
    assert "external.py" in block


# ---------------------------------------------------------------------------
# _repair_via_full_file_rewrite: various branch paths
# ---------------------------------------------------------------------------


def test_repair_via_full_file_rewrite_with_runtime_fix(tmp_path: Path) -> None:
    """runtime_fix path: reads target from RuntimeFixContext (lines 883-885)."""
    ws = _make_ws(tmp_path)
    rfx = _rfx(tmp_path)

    class _Stub:
        def chat(self, messages, max_tokens=None, status_label=None):
            return LLMResponse(text="print('hi')\n# rewritten\n", raw={})

    result = planner._repair_via_full_file_rewrite(
        _Stub(),
        "fix",
        _PLAN,
        ws,
        AgentConfig(),
        previous_patch="",
        error="oops",
        issue_type="malformed_diff",
        repair_attempt=1,
        runtime_fix=rfx,
    )
    assert result is not None
    assert "foo.py" in result


def test_repair_via_full_file_rewrite_multiple_paths_returns_none(tmp_path: Path) -> None:
    """When diff references multiple files → return None (line 889)."""
    ws = _make_ws(tmp_path)
    multi_diff = "\n".join(
        [
            "diff --git a/foo.py b/foo.py",
            "--- a/foo.py",
            "+++ b/foo.py",
            "@@ -1 +1 @@",
            "+x",
            "diff --git a/bar.py b/bar.py",
            "--- a/bar.py",
            "+++ b/bar.py",
            "@@ -1 +1 @@",
            "+y",
        ]
    )

    class _Stub:
        def chat(self, messages, max_tokens=None, status_label=None):
            return LLMResponse(text="content", raw={})

    result = planner._repair_via_full_file_rewrite(
        _Stub(),
        "fix",
        _PLAN,
        ws,
        AgentConfig(),
        previous_patch=multi_diff,
        error="oops",
        issue_type="context_mismatch",
        repair_attempt=1,
        runtime_fix=None,
    )
    assert result is None


def test_repair_via_full_file_rewrite_missing_file_returns_none(tmp_path: Path) -> None:
    """Extracted path doesn't exist on disk → return None (line 893)."""
    ws = tmp_path  # foo.py NOT created in ws

    class _Stub:
        def chat(self, messages, max_tokens=None, status_label=None):
            return LLMResponse(text="content", raw={})

    result = planner._repair_via_full_file_rewrite(
        _Stub(),
        "fix",
        _PLAN,
        ws,
        AgentConfig(),
        previous_patch=_VALID_DIFF,
        error="oops",
        issue_type="context_mismatch",
        repair_attempt=1,
        runtime_fix=None,
    )
    assert result is None


def test_repair_via_full_file_rewrite_same_content_returns_none(tmp_path: Path) -> None:
    """LLM returns unchanged content → return None (line 933)."""
    content = "print('hi')\n"
    ws = _make_ws(tmp_path, content)

    class _Stub:
        def chat(self, messages, max_tokens=None, status_label=None):
            return LLMResponse(text=content, raw={})

    result = planner._repair_via_full_file_rewrite(
        _Stub(),
        "fix",
        _PLAN,
        ws,
        AgentConfig(),
        previous_patch=_VALID_DIFF,
        error="oops",
        issue_type="context_mismatch",
        repair_attempt=1,
        runtime_fix=None,
    )
    assert result is None


# ---------------------------------------------------------------------------
# _repair_via_intended_target: branch paths (952, 974, 976)
# ---------------------------------------------------------------------------


def test_repair_via_intended_target_no_target_returns_none(tmp_path: Path) -> None:
    """diagnosis.intended_target is None → return None immediately (line 952)."""
    ws = _make_ws(tmp_path)
    from local_codex_lite.targeting import TaskTarget

    diagnosis = planner.RepairDiagnosis(intended_target=None, touched_paths=(), drifted=False)

    class _Stub:
        def chat(self, messages, max_tokens=None, status_label=None):
            return LLMResponse(text=_VALID_DIFF, raw={})

    result = planner._repair_via_intended_target(
        _Stub(),
        "fix",
        _PLAN,
        ws,
        AgentConfig(),
        previous_patch=_VALID_DIFF,
        error="oops",
        issue_type="path_mismatch",
        repair_attempt=1,
        diagnosis=diagnosis,
    )
    assert result is None


def test_repair_via_intended_target_patch_paths_dont_match(tmp_path: Path) -> None:
    """Patch targets wrong file → return None (line 974)."""
    ws = _make_ws(tmp_path)
    (tmp_path / "other.py").write_text("pass\n", encoding="utf-8")
    from local_codex_lite.targeting import TaskTarget

    target = TaskTarget(path="foo.py", mode="patch", exists=True)
    diagnosis = planner.RepairDiagnosis(
        intended_target=target, touched_paths=("foo.py",), drifted=False
    )

    wrong_diff = "\n".join(
        [
            "diff --git a/other.py b/other.py",
            "--- a/other.py",
            "+++ b/other.py",
            "@@ -1 +1 @@",
            "+# changed",
        ]
    )

    class _Stub:
        def chat(self, messages, max_tokens=None, status_label=None):
            return LLMResponse(text=wrong_diff, raw={})

    result = planner._repair_via_intended_target(
        _Stub(),
        "fix",
        _PLAN,
        ws,
        AgentConfig(),
        previous_patch=_VALID_DIFF,
        error="oops",
        issue_type="path_mismatch",
        repair_attempt=1,
        diagnosis=diagnosis,
    )
    assert result is None


def test_repair_via_intended_target_exists_false_but_path_exists(tmp_path: Path) -> None:
    """target.exists=False but file already on disk → return None (line 976)."""
    ws = _make_ws(tmp_path)
    from local_codex_lite.targeting import TaskTarget

    target = TaskTarget(path="foo.py", mode="patch", exists=False)
    diagnosis = planner.RepairDiagnosis(
        intended_target=target, touched_paths=("foo.py",), drifted=False
    )

    class _Stub:
        def chat(self, messages, max_tokens=None, status_label=None):
            return LLMResponse(text=_VALID_DIFF, raw={})

    result = planner._repair_via_intended_target(
        _Stub(),
        "fix",
        _PLAN,
        ws,
        AgentConfig(),
        previous_patch=_VALID_DIFF,
        error="oops",
        issue_type="path_mismatch",
        repair_attempt=1,
        diagnosis=diagnosis,
    )
    assert result is None


# ---------------------------------------------------------------------------
# _strip_fences: backtick-wrapped content (983-985)
# ---------------------------------------------------------------------------


def test_strip_fences_removes_backtick_wrapper() -> None:
    text = "```python\nprint('hi')\n```"
    result = planner._strip_fences(text)
    assert result == "print('hi')"


def test_strip_fences_passthrough_no_fences() -> None:
    text = "print('hi')"
    assert planner._strip_fences(text) == text


def test_strip_fences_too_short_no_strip() -> None:
    text = "``````"
    result = planner._strip_fences(text)
    assert result == text


# ---------------------------------------------------------------------------
# _extract_failed_paths: path found in error string (1036-37)
# ---------------------------------------------------------------------------


def test_extract_failed_paths_from_error_string(tmp_path: Path) -> None:
    """Paths not in the diff but in error string are included."""
    diff = ""
    error = "NameError in bar.py:12 — name 'x' not defined"
    paths = planner._extract_failed_paths(diff, error)
    assert "bar.py" in paths


def test_extract_failed_paths_deduplicates(tmp_path: Path) -> None:
    """Path already found in diff is not duplicated when also in error."""
    error = "context mismatch in foo.py:5"
    paths = planner._extract_failed_paths(_VALID_DIFF, error)
    assert paths.count("foo.py") == 1


# ---------------------------------------------------------------------------
# _retry_with_context_variants: non-context_too_large → sleep + break (1113-16)
# ---------------------------------------------------------------------------


def test_retry_with_context_variants_non_ctx_error_sleeps_then_raises(
    tmp_path: Path, monkeypatch
) -> None:
    """Non-context_too_large errors on all attempts → sleep called, then RuntimeError."""
    ws = _make_ws(tmp_path)
    sleep_calls = []
    monkeypatch.setattr(planner.time, "sleep", lambda s: sleep_calls.append(s))

    class _Fails:
        def chat(self, messages, max_tokens=None, status_label=None):
            raise _non_context_http_error()

    with pytest.raises(RuntimeError, match="generation failed"):
        planner._retry_with_context_variants(
            client=_Fails(),
            task="fix foo",
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
    assert len(sleep_calls) > 0


# ---------------------------------------------------------------------------
# _response_text_from_exception: edge paths (1161, 1165)
# ---------------------------------------------------------------------------


def test_response_text_from_exception_no_response() -> None:
    """Exception without .response attribute → return None (line 1161)."""
    exc = ValueError("no response attr")
    result = planner._response_text_from_exception(exc)
    assert result is None


def test_response_text_from_exception_text_not_str() -> None:
    """Exception.response.text is not a str → return None (line 1165)."""

    class _FakeResp:
        text = 42

    class _FakeExc(Exception):
        response = _FakeResp()

    result = planner._response_text_from_exception(_FakeExc())
    assert result is None


# ---------------------------------------------------------------------------
# _format_exception: no response attribute (1175)
# ---------------------------------------------------------------------------


def test_format_exception_no_response() -> None:
    """Exception without .response → formats as ClassName: message (line 1175)."""
    exc = ValueError("something went wrong")
    result = planner._format_exception(exc)
    assert "ValueError" in result
    assert "something went wrong" in result
