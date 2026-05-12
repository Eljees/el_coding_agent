from local_codex_lite.config import LLMConfig
from local_codex_lite.llm_client import OpenAICompatibleClient, extract_diff, extract_json, normalize_unified_diff


def test_extract_json_from_fenced_block() -> None:
    text = """```json
    {"a": 1}
    ```"""
    assert extract_json(text) == {"a": 1}


def test_extract_diff_from_fenced_block() -> None:
    text = """```diff
    diff --git a/foo.py b/foo.py
    --- a/foo.py
    +++ b/foo.py
    @@ -1 +1 @@
    -print("hi")
    +print("bye")
    ```"""
    diff = extract_diff(text)
    assert "diff --git a/foo.py b/foo.py" in diff
    assert "print(\"bye\")" in diff


def test_normalize_unified_diff_fixes_hunk_sizes() -> None:
    text = "\n".join(
        [
            "diff --git a/foo.py b/foo.py",
            "--- a/foo.py",
            "+++ b/foo.py",
            "@@ -0,0 +1,235 @@",
            '+print("hello")',
            '+print("world")',
        ]
    )
    normalized = normalize_unified_diff(text)
    assert "@@ -0,0 +1,2 @@" in normalized
    assert normalized.endswith('\n')


def test_emit_status_ignores_broken_stderr(monkeypatch) -> None:
    client = OpenAICompatibleClient(LLMConfig())

    class BrokenStderr:
        def write(self, text):  # noqa: ANN001
            raise OSError(22, "Invalid argument")

        def flush(self) -> None:
            raise OSError(22, "Invalid argument")

    monkeypatch.setattr("sys.stderr", BrokenStderr())

    client._emit_status("hello")
