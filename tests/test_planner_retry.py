from __future__ import annotations

import json
from pathlib import Path
from typing import ClassVar

import httpx

import local_codex_lite.planner as planner
from local_codex_lite.config import AgentConfig
from local_codex_lite.llm_client import LLMResponse
from local_codex_lite.patcher import RuntimeFixContext


class RetryClient:
    def __init__(self, *args, **kwargs):
        self.calls = 0

    def chat(self, messages, max_tokens=None, status_label=None):
        self.calls += 1
        if self.calls == 1:
            request = httpx.Request("POST", "http://localhost:8015/v1/chat/completions")
            response = httpx.Response(400, request=request, text='{"detail":"context too large"}')
            raise httpx.HTTPStatusError("bad request", request=request, response=response)
        return LLMResponse(
            text="\n".join(
                [
                    "diff --git a/foo.py b/foo.py",
                    "--- a/foo.py",
                    "+++ b/foo.py",
                    "@@ -0,0 +1,1 @@",
                    "+print('ok')",
                ]
            ),
            raw={"model": "qwen25-coder-14b-awq"},
        )


def test_make_patch_retries_and_logs_events(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "foo.py").write_text("print('old')", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = AgentConfig()
    monkeypatch.setattr(planner, "OpenAICompatibleClient", RetryClient)

    patch = planner.make_patch(
        "update foo.py", {"summary": "ok"}, tmp_path, config, run_dir=run_dir
    )

    assert "print('ok')" in patch
    events_path = run_dir / "events.jsonl"
    assert events_path.exists()
    events = [
        json.loads(line)
        for line in events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(item["status"] == "request_error" for item in events)
    assert any(item["status"] == "success" for item in events)


class CaptureBudgetClient:
    def __init__(self, *args, **kwargs):
        self.calls: list[int | None] = []

    def chat(self, messages, max_tokens=None, status_label=None):
        self.calls.append(max_tokens)
        return LLMResponse(
            text=json.dumps(
                {
                    "summary": "ok",
                    "files_to_inspect": [],
                    "implementation_steps": [],
                    "risks": [],
                    "needs_clarification": False,
                    "clarifying_questions": [],
                }
            ),
            raw={"model": "qwen25-coder-14b-awq"},
        )


def test_make_plan_uses_context_budget(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (tmp_path / "README.md").write_text("x" * 20000, encoding="utf-8")
    config = AgentConfig()
    captured = {}

    class Client(CaptureBudgetClient):
        def chat(self, messages, max_tokens=None, status_label=None):
            captured["max_tokens"] = max_tokens
            captured["messages"] = messages
            return super().chat(messages, max_tokens=max_tokens, status_label=status_label)

    monkeypatch.setattr(planner, "OpenAICompatibleClient", Client)

    plan = planner.make_plan(
        "update the README",
        tmp_path,
        config,
        run_dir=run_dir,
        extra_context="rag context " * 4000,
    )

    assert plan["summary"] == "ok"
    assert isinstance(captured["max_tokens"], int)
    assert captured["max_tokens"] == planner._budget_for_messages(
        captured["messages"], config.llm.max_tokens
    )
    assert captured["max_tokens"] < config.llm.max_tokens


class RepairClient:
    def __init__(self, *args, **kwargs):
        self.calls = 0

    def chat(self, messages, max_tokens=None, status_label=None):
        self.calls += 1
        if self.calls == 1:
            text = "\n".join(
                [
                    "diff --git a/foo.py b/foo.py",
                    "--- a/foo.py",
                    "+++ b/foo.py",
                    "@@ -1 +1 @@",
                    "-print('old')",
                    "+print('same')",
                ]
            )
        else:
            text = "\n".join(
                [
                    "diff --git a/foo.py b/foo.py",
                    "--- a/foo.py",
                    "+++ b/foo.py",
                    "@@ -1 +1 @@",
                    "-print('old')",
                    "+print('new')",
                ]
            )
        return LLMResponse(text=text, raw={"model": "qwen25-coder-14b-awq"})


def test_repair_patch_with_error_retries_when_model_repeats_same_patch(
    tmp_path: Path, monkeypatch
) -> None:
    (tmp_path / "foo.py").write_text("print('old')\n", encoding="utf-8")
    config = AgentConfig()
    monkeypatch.setattr(planner, "OpenAICompatibleClient", RepairClient)
    previous_patch = "\n".join(
        [
            "diff --git a/foo.py b/foo.py",
            "--- a/foo.py",
            "+++ b/foo.py",
            "@@ -1 +1 @@",
            "-print('old')",
            "+print('same')",
        ]
    )

    repaired = planner.repair_patch_with_error(
        "fix foo.py",
        {"summary": "ok"},
        previous_patch,
        "error: patch failed: foo.py:1 error: foo.py: patch does not apply",
        "generic_retry",
        tmp_path,
        config,
        repair_attempt=1,
    )

    assert "+print('new')" in repaired


class RuntimeFixMalformedThenValidClient:
    def __init__(self, *args, **kwargs):
        self.calls = 0

    def chat(self, messages, max_tokens=None, status_label=None):
        self.calls += 1
        if self.calls == 1:
            text = "\n".join(
                [
                    "diff --git a/foo.py b/foo.py",
                    "--- a/foo.py",
                    "+++ b/foo.py",
                    "@@ -1 +1 @@",
                    "this is not a diff hunk line",
                    "-print('old')",
                    "+print('fixed')",
                ]
            )
        else:
            text = "\n".join(
                [
                    "diff --git a/foo.py b/foo.py",
                    "--- a/foo.py",
                    "+++ b/foo.py",
                    "@@ -1 +1 @@",
                    "-print('old')",
                    "+print('fixed')",
                ]
            )
        return LLMResponse(text=text, raw={"model": "qwen25-coder-14b-awq"})


def test_make_patch_runtime_fix_recovers_from_malformed_diff(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "foo.py"
    target.write_text("print('old')\n", encoding="utf-8")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    config = AgentConfig()
    monkeypatch.setattr(planner, "OpenAICompatibleClient", RuntimeFixMalformedThenValidClient)

    patch = planner.make_patch(
        "Fix runtime traceback in foo.py",
        {"summary": "ok"},
        tmp_path,
        config,
        run_dir=run_dir,
        runtime_fix=RuntimeFixContext(
            target_path=target,
            traceback_text='Traceback (most recent call last):\n  File "foo.py", line 1, in <module>',
            current_text=target.read_text(encoding="utf-8"),
        ),
    )

    assert "+print('fixed')" in patch
    events = [
        json.loads(line)
        for line in (run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert any(item["status"] == "parse_error" for item in events)
    assert any(item["status"] == "success" for item in events)


class RuntimeFixTimeoutCaptureClient:
    timeouts: ClassVar[list[float]] = []

    def __init__(self, config, *args, **kwargs):
        self.config = config

    def chat(self, messages, max_tokens=None, status_label=None):
        self.__class__.timeouts.append(float(self.config.timeout))
        if len(self.__class__.timeouts) == 1:
            raise ValueError("Unexpected empty line inside unified diff hunk")
        return LLMResponse(
            text="\n".join(
                [
                    "diff --git a/foo.py b/foo.py",
                    "--- a/foo.py",
                    "+++ b/foo.py",
                    "@@ -1 +1 @@",
                    "-print('old')",
                    "+print('fixed')",
                ]
            ),
            raw={"model": "qwen25-coder-14b-awq"},
        )


def test_make_patch_runtime_fix_uses_shorter_timeout_for_repair_attempts(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "foo.py"
    target.write_text("print('old')\n", encoding="utf-8")
    config = AgentConfig()
    config.llm.timeout = 120.0
    RuntimeFixTimeoutCaptureClient.timeouts = []
    monkeypatch.setattr(planner, "OpenAICompatibleClient", RuntimeFixTimeoutCaptureClient)

    patch = planner.make_patch(
        "Fix runtime traceback in foo.py",
        {"summary": "ok"},
        tmp_path,
        config,
        runtime_fix=RuntimeFixContext(
            target_path=target,
            traceback_text='Traceback (most recent call last):\n  File "foo.py", line 1, in <module>',
            current_text=target.read_text(encoding="utf-8"),
        ),
    )

    assert "+print('fixed')" in patch
    assert RuntimeFixTimeoutCaptureClient.timeouts == [120.0, 45.0]


class TargetDriftRepairClient:
    seen_messages: ClassVar[list] = []

    def __init__(self, *args, **kwargs):
        pass

    def chat(self, messages, max_tokens=None, status_label=None):
        self.__class__.seen_messages.append(messages)
        return LLMResponse(
            text="\n".join(
                [
                    "diff --git a/calculator.py b/calculator.py",
                    "--- /dev/null",
                    "+++ b/calculator.py",
                    "@@ -0,0 +1,2 @@",
                    "+def add(a, b):",
                    "+    return a + b",
                ]
            ),
            raw={"model": "qwen25-coder-14b-awq"},
        )


_REVISED_PLAN_JSON = json.dumps(
    {
        "summary": "revised with answers",
        "files_to_inspect": ["foo.py"],
        "implementation_steps": [],
        "risks": [],
        "needs_clarification": False,
        "clarifying_questions": [],
    }
)


class AnswersCaptureClient:
    seen: ClassVar[list[tuple[list[dict[str, str]], str | None]]] = []

    def __init__(self, *args, **kwargs):
        pass

    def chat(self, messages, max_tokens=None, status_label=None):
        self.__class__.seen.append((messages, status_label))
        return LLMResponse(text=_REVISED_PLAN_JSON, raw={"model": "qwen25-coder-14b-awq"})


def test_revise_plan_with_answers_sends_qa_pairs(tmp_path: Path, monkeypatch) -> None:
    config = AgentConfig()
    AnswersCaptureClient.seen = []
    monkeypatch.setattr(planner, "OpenAICompatibleClient", AnswersCaptureClient)
    plan = {
        "summary": "old",
        "needs_clarification": True,
        "clarifying_questions": ["Which file?", "Which style?"],
    }

    revised = planner.revise_plan_with_answers(
        "do the task",
        plan,
        [("Which file?", "foo.py"), ("Which style?", "PEP 8")],
        tmp_path,
        config,
        extra_context="user evidence",
    )

    assert revised["needs_clarification"] is False
    assert revised["summary"] == "revised with answers"
    messages, status_label = AnswersCaptureClient.seen[0]
    assert status_label == "Revising plan with answers"
    user_text = messages[1]["content"]
    assert "Q: Which file?" in user_text
    assert "A: foo.py" in user_text
    assert "Q: Which style?" in user_text
    assert "A: PEP 8" in user_text
    assert "strictly following the user's answers" in user_text


class AnswersBadThenGoodClient:
    def __init__(self, *args, **kwargs):
        self.calls = 0

    def chat(self, messages, max_tokens=None, status_label=None):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(text="not json at all", raw={"model": "qwen25-coder-14b-awq"})
        return LLMResponse(text=_REVISED_PLAN_JSON, raw={"model": "qwen25-coder-14b-awq"})


def test_revise_plan_with_answers_repairs_invalid_json(tmp_path: Path, monkeypatch) -> None:
    config = AgentConfig()
    monkeypatch.setattr(planner, "OpenAICompatibleClient", AnswersBadThenGoodClient)

    revised = planner.revise_plan_with_answers(
        "do the task",
        {"summary": "old"},
        [("Which file?", "foo.py")],
        tmp_path,
        config,
    )

    assert revised["summary"] == "revised with answers"


def test_repair_patch_with_error_retargets_to_intended_file(tmp_path: Path, monkeypatch) -> None:
    config = AgentConfig()
    TargetDriftRepairClient.seen_messages = []
    monkeypatch.setattr(planner, "OpenAICompatibleClient", TargetDriftRepairClient)
    previous_patch = "\n".join(
        [
            "diff --git a/local_codex_lite/cli.py b/local_codex_lite/cli.py",
            "--- a/local_codex_lite/cli.py",
            "+++ b/local_codex_lite/cli.py",
            "@@ -1 +1 @@",
            "-print('old')",
            "+print('wrong target')",
        ]
    )

    repaired = planner.repair_patch_with_error(
        "Create a new Python file named calculator.py and add tests",
        {"summary": "ok"},
        previous_patch,
        "error: patch failed: local_codex_lite/cli.py:10\nerror: local_codex_lite/cli.py: patch does not apply",
        "context_mismatch",
        tmp_path,
        config,
        repair_attempt=1,
    )

    assert "+++ b/calculator.py" in repaired
    prompt_text = "\n".join(
        message["content"] for message in TargetDriftRepairClient.seen_messages[0]
    )
    assert "target path: calculator.py" in prompt_text.lower()
    assert "previous patch touched" in prompt_text.lower()
