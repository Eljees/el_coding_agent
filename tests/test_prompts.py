from local_codex_lite.prompts import (
    command_prompt,
    patch_prompt,
    patch_repair_prompt_for_issue,
    plan_prompt,
    runtime_fix_single_file_command_prompt,
    runtime_fix_single_file_patch_prompt,
    runtime_fix_single_file_plan_prompt,
)


def test_plan_prompt_mentions_json():
    messages = plan_prompt("task", "context")
    assert "JSON" in messages[1]["content"]


def test_patch_prompt_mentions_unified_diff():
    messages = patch_prompt("task", "{}", "context")
    assert "unified diff" in messages[1]["content"].lower()


def test_command_prompt_mentions_commands():
    messages = command_prompt("task", "{}", "context")
    assert "commands" in messages[1]["content"].lower()


def test_command_prompt_requires_literal_shell_commands():
    messages = command_prompt("task", "{}", "context")
    assert "literal executable shell command" in messages[0]["content"].lower()


def test_runtime_fix_plan_prompt_mentions_single_target_file():
    messages = runtime_fix_single_file_plan_prompt("task", "foo.py", "Traceback...", "print('x')")
    assert "exactly one target file" in messages[0]["content"].lower()
    assert "current file content is authoritative" in messages[0]["content"].lower()
    assert "traceback" in messages[1]["content"].lower()


def test_runtime_fix_patch_prompt_requires_direct_fix():
    messages = runtime_fix_single_file_patch_prompt(
        "task", "{}", "foo.py", "Traceback...", "print('x')"
    )
    assert "directly eliminate the reported runtime failure" in messages[0]["content"].lower()
    assert "not present in the current file content" in messages[0]["content"].lower()
    assert "proof requirement" in messages[1]["content"].lower()


def test_runtime_fix_command_prompt_prefers_verification_command():
    messages = runtime_fix_single_file_command_prompt("task", "{}", "foo.py")
    assert "windows powershell" in messages[0]["content"].lower()
    assert "primary verification command" in messages[1]["content"].lower()


def test_plan_prompt_omits_pitfalls_by_default():
    messages = plan_prompt("task", "context")
    assert "Known pitfalls" not in messages[1]["content"]


def test_plan_prompt_injects_pitfalls_before_return_instruction():
    block = "Known pitfalls to avoid:\n- do not invent imports"
    messages = plan_prompt("task", "context", pitfalls=block)
    content = messages[1]["content"]
    assert "do not invent imports" in content
    # The block must sit in front of the trailing "Return JSON" instruction.
    assert content.index("do not invent imports") < content.index("Return JSON")


def test_patch_prompt_injects_pitfalls_before_return_instruction():
    block = "Known pitfalls to avoid:\n- pass encoding to open()"
    messages = patch_prompt("task", "{}", "context", pitfalls=block)
    content = messages[1]["content"]
    assert "pass encoding to open()" in content
    assert content.index("pass encoding to open()") < content.index("Return only unified diff")


def test_patch_repair_prompt_supports_target_drift():
    messages = patch_repair_prompt_for_issue(
        "target_drift",
        "create calculator.py",
        "{}",
        "diff --git a/foo.py b/foo.py",
        "patch does not apply",
        "Target path: calculator.py",
        repair_attempt=1,
    )
    assert "drifted away from the intended target file" in messages[0]["content"].lower()
    assert "target path: calculator.py" in messages[1]["content"].lower()
