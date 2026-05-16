# Changelog

All notable changes to this project are documented here.  The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the
project follows [semantic versioning](https://semver.org/) once it cuts a
real release.  Until then everything is pre-1.0 and breaking changes go
straight into `## [Unreleased]`.

## [Unreleased]

### Added
- `tools/proxy.ps1`, `tools/proxy.local.ps1.example` and
  `tools/pip.ini.template` plus a `setup.ps1 -WithPipIni` flag for
  developers who need `pip install` to route through a local proxy
  (e.g. v2rayN at `http://127.0.0.1:10809`).
- `local_codex_lite/runner.py`: dedicated module for the end-to-end
  `run_task` workflow.  `cli._run_task` is now a one-line re-export.
- `patcher.ApplyResult` dataclass replaces the
  `setattr(CompletedProcess, "git_apply_strategy", ...)` hack; the
  strategy is now a first-class field.
- Named `SCORE_*` constants in `workspace.py` for the file-ranking
  weights so every magic number has a documented purpose.
- `LICENSE` (MIT), `CONTRIBUTING.md`, `SECURITY.md`, `CHANGELOG.md`.
- `pyproject.toml` now carries `license`, `authors`, `urls`, `keywords`
  and `classifiers`.
- `.pre-commit-config.yaml`: ruff + ruff-format + mypy + the standard
  pre-commit-hooks set.
- `intent.evidence.trufflehog.scan` now actually validates the
  `repo_url_or_file` input.  Without a URL or path it returns
  `can_do=needs_input` instead of silently routing through.
- CI: matrix gained `windows-latest / py3.12`; pip cache; coverage XML
  upload artifact; a no-LLM `cli-smoke` job (`doctor deps`,
  `config show`, `recognize`).
- `tests/test_intent.py` regression tests for `repo_url_or_file`
  detection (URL, `.txt`/`.list` repo files, Windows path).

### Changed
- `IntentDecision.required_inputs / missing_inputs / risks /
  matched_keywords` are now `tuple[str, ...]` instead of `list[str]` so
  the frozen dataclass is genuinely immutable.
- `safety.is_dangerous_command` switched from substring matching to
  word-boundary regexes.  `pytest --format=json`,
  `--shutdown-on-error`, `python -c "print(format(x))"` no longer trip
  the blocklist; `rm -rf`, `Remove-Item -Recurse`, `format c:`,
  `shutdown -r`, `curl | iex`, `Invoke-Expression` still do.
- `logging_utils.utc_timestamp()` now returns
  `YYYYMMDD-HHMMSS-uuuuuu-xxxxxx` (microseconds + 6 hex chars) so two
  runs in the same second do not share a run-dir.  Format stays
  lexicographically sortable.
- `logging_utils.sanitize_log_text` (moved from `cli_utils`) now does
  real regex masking of the secret value, not just a `<redacted>`
  prefix.  Url-embedded `user:pwd@host` and `Authorization: Basic ...`
  are also masked.
- `planner._log_llm_attempt` pushes `response_text` and `error` through
  `sanitize_log_text` before persisting to `events.jsonl`.
- `patcher.apply_patch` and `patcher.backup_paths` take an optional
  `run_dir` argument and, when given, write the patch file to
  `<run_dir>/patch.diff` and backups to `<run_dir>/backups/` instead of
  the shared `.local-codex-lite/patch.diff` / `backups/current/`.
  `cli._run_task` passes `run_dir` through, so concurrent runs no
  longer race and repair attempts do not clobber previous backups.
- `trufflehog.clone_repo` passes Basic auth via
  `-c http.extraHeader=Authorization: Basic <b64>` instead of embedding
  `user:token` in the URL.  The args list is redacted before any
  `CalledProcessError` is raised.
- `trufflehog._sanitize_error` also masks URL-embedded creds and
  `Authorization` headers as a defense in depth.
- `cli.py` lost ~370 lines: dead imports were removed (`AgentConfig`,
  `evidence_question_prompt`, `make_console`, `RankedWorkspaceFile`,
  `ensure_rag_provider_supported`, `retrieve_rag_context`,
  `PatchErrorClassification`, `append_jsonl`) and the `_run_task` body
  moved to `runner.py`.
- `args.exec` renamed to `args.execute` (via argparse `dest`); the
  `--exec` flag is unchanged and the `result["exec"]` key in
  `result.json` stays for backward compat.
- `config.example.yaml` now mirrors `AgentConfig` (added the `rag`
  section and `safety.max_patch_attempts`).
- pyproject `[tool.ruff]` now has a real rule selection
  (E/F/I/UP/B/SIM/W/RUF) and a paired `[tool.ruff.format]` block; mypy
  config gained `check_untyped_defs` / `no_implicit_optional` /
  `warn_redundant_casts`.  CI dropped `--ignore-missing-imports`.

### Fixed
- `tests/test_cli_evidence.py::test_resolve_cve_skill_script_raises_when_missing`
  now patches a stable module-level helper (`_candidate_exists`)
  instead of `Path.exists` which broke on Path subclass internals.
- `tests/test_config.py::test_save_and_load_config_roundtrip` builds
  the updated config via `model_copy(update=...)` so it survives a
  future `frozen=True` flip and also asserts the `rag` section round-
  trips (which catches `config.example.yaml` drift).

### Removed
- `local_codex_lite/prompts/prompts.md` (stray CLI command saved by
  accident).
- `tmp_review.diff` (untracked scratch file).
- The leaky substring rules `"format"` / `"shutdown"` in
  `safety.DISALLOWED_PATTERNS`; replaced by precise regexes.
- `setattr(subprocess.CompletedProcess, "git_apply_strategy", ...)` in
  `patcher.apply_patch`; replaced by `ApplyResult.strategy`.

### Repo hygiene
- New `.gitattributes` pins `*.py / *.md / *.toml / *.yaml / *.json` to
  LF and `*.ps1 / *.bat` to CRLF so the working tree stops accumulating
  spurious CRLF<->LF diffs.
- `local_codex_lite.egg-info/` confirmed not tracked; `.gitignore`
  already covers `*.egg-info/`.
- `.gitignore` now also covers `tools/proxy.local.ps1`.

## [0.1.0] - prior to the cleanup sweep

Baseline state at commit `8ba6495 GUI improvements + tests`, before the
stages above started.  Original feature surface
(`run / preview / apply / exec`, evidence-first workflows,
`cve-bin-tool` skill, TruffleHog scan helper, Tkinter command center)
is documented in `README.md` and `AGENTS.md`.
