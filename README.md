# local-codex-lite

`local-codex-lite` is a minimal local coding agent MVP for Windows / PowerShell.
It is designed to work against a local OpenAI-compatible vLLM backend and to stay small, readable, and safe.

Repository root for this agent:

```text
el_coding_agent/
```

## What it can do

- inspect the current workspace
- rank and select relevant files for a task
- ask a local model for a plan
- generate a unified diff
- validate, normalize, and repair patches
- preview changes before applying them
- apply changes only with `--apply`
- run suggested commands only with `--exec`
- review diffs and pull requests with a read-only `review` command
- keep logs for every run under `.local-codex-lite/runs/<timestamp>/`
- store evidence separately from fixes under `runs/<timestamp>/evidence/`
- compare JSON artifacts
- analyze TruffleHog outputs
- run TruffleHog scans through Docker for GitLab repositories
- show run logs with `logs latest`

## Quick start

PowerShell:

```powershell
cd D:\!ya_drive_sync\YandexDisk\rostel\code\el_coding_agent
.\setup.ps1
.\doctor.ps1
```

Manual setup:

```powershell
cd D:\!ya_drive_sync\YandexDisk\rostel\code\el_coding_agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Proxy for `pip install` (optional)

If `pip` on your machine has to go through a local proxy (for example
[v2rayN](https://github.com/2dust/v2rayN) listening on `127.0.0.1:10809`),
the repo ships a small helper instead of hard-coding the proxy:

```powershell
cd D:\!ya_drive_sync\YandexDisk\rostel\code\el_coding_agent
copy tools\proxy.local.ps1.example tools\proxy.local.ps1
notepad tools\proxy.local.ps1   # set the actual port
.\setup.ps1 -WithPipIni
```

`tools\proxy.local.ps1` is `.gitignored` (machine-specific).  When it
exists, `setup.ps1` dot-sources it before `pip install`, which routes the
install through your proxy.  Passing `-WithPipIni` also copies
`tools\pip.ini.template` to `.venv\pip.ini`, so subsequent `pip install`
calls inside the venv reuse the proxy automatically.

If your shell already has `HTTP_PROXY`/`HTTPS_PROXY` set, you do not need
this helper - pip will pick those up directly.

## Local model

The default configuration expects:

- Base URL: `http://localhost:8015/v1`
- Model: `qwen25-coder-14b-awq`

The agent uses only the local OpenAI-compatible endpoint and does not need a real OpenAI API key.

If your local model is not reachable, `doctor` will report the failure and `run` / `preview` will not be able to continue.

## Main commands

```powershell
cd D:\!ya_drive_sync\YandexDisk\rostel\code\el_coding_agent
python -m local_codex_lite init
python -m local_codex_lite doctor
python -m local_codex_lite doctor deps
python -m local_codex_lite status
python -m local_codex_lite recognize "покажи последние логи"
python -m local_codex_lite ui
python -m local_codex_lite config show
python -m local_codex_lite ask "Что это за проект?"
python -m local_codex_lite preview "Добавь короткий README"
python -m local_codex_lite run "Добавь короткий README" --dry-run
python -m local_codex_lite run "Добавь короткий README" --assume-clarification --dry-run
python -m local_codex_lite run "Добавь короткий README" --apply
python -m local_codex_lite run "Добавь короткий README" --apply --exec
python -m local_codex_lite review --base origin/main --head HEAD
python -m local_codex_lite preview "Create a Tkinter calculator app"
python -m local_codex_lite run "Сделай GUI калькулятор" --apply
python -m local_codex_lite logs latest
```

## PowerShell helpers

```powershell
cd D:\!ya_drive_sync\YandexDisk\rostel\code\el_coding_agent
.\doctor.ps1
.\ask.ps1 "Что это за проект?"
.\run.ps1 "Добавь короткий README" -DryRun
.\run.ps1 "Добавь короткий README" -Apply
```

## Command center

The agent now exposes a small safe command center:

```powershell
python -m local_codex_lite recognize "сравни left.json и right.json"
python -m local_codex_lite ui
```

`recognize` classifies the request without executing anything.

`ui` opens a tkinter window for task entry, intent analysis, preview, and log inspection. It is not a separate agent and it still respects the same `run` / `preview` / `--apply` / `--exec` safety model.
Available skills in the GUI are now labeled from `SKILL.md` frontmatter when `name` / `description` metadata is present.

The window also includes an `Evidence / traceback` box. You can paste a Python traceback or log there, then run `Preview` or `Apply` so the agent repairs against the pasted evidence instead of guessing.

## Run flow

The agent follows a small, predictable loop:

1. load config
2. index the workspace
3. rank files relevant to the task
4. ask the model for a plan
5. optionally continue from clarification with `--assume-clarification`
6. ask for a unified diff
7. normalize and validate the diff
8. preview the patch
9. apply only when `--apply` is present
10. run suggested commands only when `--exec` is present
11. write logs and evidence to the run folder

Dry-run mode is plan-only and does not apply patches.

When a task clearly looks like creating a new app, GUI, calculator, tool, or project, the agent now creates a dated workspace under `generated_projects/` and performs `preview` / `run` there instead of mixing the new project into the agent's own repository root.

Example generated folder:

```text
generated_projects/20260508-153500_create-a-tkinter-calculator-app/
```

## Evidence-first workflows

The agent keeps findings and fixes separate.

Useful commands:

```powershell
python -m local_codex_lite evidence json-compare left.json right.json
python -m local_codex_lite evidence artifacts inspect "D:\path\to\artifacts" --extract
python -m local_codex_lite evidence cve-scan status
python -m local_codex_lite evidence cve-scan update-db
python -m local_codex_lite evidence cve-scan "D:\path\to\artifacts" --format json,md,high-critical-md --min-severity HIGH
python -m local_codex_lite evidence cve-scan "D:\path\to\artifacts" --format json,md --min-severity MEDIUM
python -m local_codex_lite evidence trufflehog analyze "D:\!ya_drive_sync\YandexDisk\rostel\to__issledovat\TruffelHog"
python -m local_codex_lite evidence trufflehog scan --repo-url "https://gitlab.example.com/group/project.git"
python -m local_codex_lite logs latest
```

`logs latest` is the quickest way to inspect the last run's `events.jsonl`.

### Sending app errors back to the agent

If a generated app crashes, copy the traceback and pipe it into `run`, `preview`, or `ask` as stdin evidence:

```powershell
@'
Traceback (most recent call last):
  ...
'@ | python -m local_codex_lite run "Исправь ошибку в созданном приложении" --evidence-stdin --apply
```

You can also use `--evidence-file <path>` for saved logs or reports.

## RAG v0

`local-codex-lite` now has a small keyword-based RAG provider.

It can:

- build a local keyword index
- retrieve relevant chunks with file paths and line ranges
- inject retrieved context into `ask` and `preview`
- stay offline and avoid extra embedding/vector dependencies

Use these commands:

```powershell
python -m local_codex_lite doctor rag
python -m local_codex_lite rag index
python -m local_codex_lite rag query "patch repair"
python -m local_codex_lite ask --rag "как работает patch repair?"
python -m local_codex_lite preview --rag "улучши logs latest"
```

Notes:

- RAG does not apply patches by itself.
- The default provider is `keyword`.
- `chroma` is reserved for a future/optional build and currently fails with a clear message.
- If you want RAG context to be included in `ask` or `preview`, pass `--rag`.

## Evidence Mode v1

Each run can keep a structured evidence bundle under:

```text
.local-codex-lite/runs/<timestamp>/evidence/
```

The bundle keeps:

- `metadata.json`
- `status.json`
- `raw/`
- `summaries/`
- `reports/`

Raw evidence is preserved as-is.
Summaries and reports stay separate from raw artifacts.
`status.json` stores the current classification, retryability, and a short next action.

## Artifact archive inspection

For artifact folders that may contain archives, use:

```powershell
python -m local_codex_lite evidence artifacts inspect "D:\path\to\artifacts"
python -m local_codex_lite evidence artifacts inspect "D:\path\to\artifacts" --extract
python -m local_codex_lite evidence artifacts inspect "D:\path\to\artifacts" "D:\path\to\unpacked" --extract
```

The command inventories supported archives and writes evidence under `.local-codex-lite/runs/<timestamp>/evidence/`.
With `--extract`, files are unpacked next to the archive source by default, into per-archive subdirectories.
When a second path is provided, files are unpacked under that directory instead.
Raw inventory, summaries, reports, and status still stay in the evidence bundle.

Supported formats:

- `.zip`
- `.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tbz2`, `.tar.xz`, `.txz`
- `.gz`
- `.7z` and `.rar` when `7z`, `7za`, or `7zz` is installed

Archive member path traversal and unsupported unsafe tar members are blocked and recorded as evidence.

## CVE scan tool

The `cve-bin-tool` workflow is now a deterministic tool path with explicit actions:

```powershell
python -m local_codex_lite evidence cve-scan status
python -m local_codex_lite evidence cve-scan install
python -m local_codex_lite evidence cve-scan update-db
python -m local_codex_lite evidence cve-scan "D:\path\to\artifacts"
python -m local_codex_lite evidence cve-scan scan "D:\path\to\artifacts" --format json,md,high-critical-md --min-severity HIGH
python -m local_codex_lite evidence cve-scan "D:\already\extracted" --skip-unpack
```

The runner prefers the `cve-bin-tool` executable and falls back to module mode only if it actually works in the current environment.

Default outputs:

- `cve_raw.json`
- `cve_summary.json`
- `status.json`
- `cve_report.md`
- `high_critical_report_<date>.md`

The high/critical report is shaped for quick triage and mirrors the older CYBERSEC-style report layout:

- artifact section
- summary section
- table of HIGH / CRITICAL findings
- notes section

Default CVE triage uses `--min-severity HIGH`. Use `--min-severity MEDIUM` only when the task explicitly asks for a broader report. `json` and `json2` exports have different internal shapes, so compare them with care.

## Container error classification

TruffleHog and other container-style workflows now classify failures into small typed buckets.

Common codes:

- `docker_unavailable`
- `docker_image_missing`
- `container_timeout`
- `mount_path_error`
- `cache_permission_error`
- `auth_missing`
- `clone_failed`
- `scan_no_inventory`
- `malformed_report`
- `db_snapshot_drift`
- `tool_execution_failed`
- `unknown`

Example failure output:

```text
Scan failed: clone_failed
Reason: The repository checkout step returned a non-zero exit code.
Next: Check the repo URL, credentials, and network access, then rerun.
Evidence: .local-codex-lite/runs/<timestamp>/evidence/status.json
```

## Logs

Use these when you want a quick look at the last run:

```powershell
python -m local_codex_lite logs latest
python -m local_codex_lite logs tail --lines 50
python -m local_codex_lite logs show latest
```

- `logs latest` prints the latest raw `events.jsonl`
- `logs tail` shows the tail of `events.jsonl` or falls back to a compact run summary
- `logs show` prints a compact run summary with available artifacts and evidence status

## TruffleHog scans for GitLab repos

If you want to reproduce TruffleHog scans from a list of GitLab repositories, use the helper script:

```powershell
$env:GITLAB_USER="your.user"
$env:GITLAB_TOKEN="your-token"
.\trufflehog.ps1 -RepoUrl "https://gitlab.example.com/group/project.git"
.\trufflehog.ps1 -RepoFile .\repos.txt
```

The helper:

- clones each repo with `git`
- runs `trufflesecurity/trufflehog:3.94.1` in Docker
- writes per-repo JSON plus `baseline_summary.csv` and `baseline_total.json`
- stores outputs under `.local-codex-lite\trufflehog_runs\<timestamp>\baseline`

The agent also exposes direct evidence-first commands for TruffleHog analysis and scan reproduction.

## Config

Running `init` creates:

```text
.local-codex-lite/config.yaml
```

You can preseed values from `config.example.yaml`.

Important config values:

- `NEUROHARBOUR_BASE_URL` equivalent: `llm.base_url`
- `llm.model`
- `llm.temperature`
- `llm.max_tokens`
- workspace includes/excludes
- safety flags for `--apply` and `--exec`

## Safety

- stays inside the workspace
- blocks path traversal
- skips secrets by default
- requires `--apply` for file changes
- requires `--exec` for command execution
- blocks common dangerous shell patterns
- backs up files before apply

## Patch repair classification

Patch failures are classified before repair attempts.

Supported classes:

- `malformed_diff`
- `context_mismatch`
- `file_already_exists`
- `path_mismatch`
- `unsafe_path`
- `empty_patch`
- `unknown`

Typical behavior:

- `malformed_diff` re-prompts for a strict unified diff only
- `context_mismatch` asks the model to rebuild the patch from current file contents
- `file_already_exists` keeps the idempotent path if the created file already matches
- `path_mismatch` asks for repo-relative paths only
- `unsafe_path` fails closed and does not retry through the model
- `empty_patch` rejects no-op patches
- `unknown` falls back to the older repair path

Patch failures are logged per run, together with the retry attempt and a suggested action.

## Tests

```powershell
cd D:\!ya_drive_sync\YandexDisk\rostel\code\el_coding_agent
python -m pytest -q
```

## Good prompts

Short and concrete prompts work best. For example:

```text
Создай в этой подпапке запускаемый Tkinter-калькулятор в файле local_codex_lite/calculator.py. Нужны окно, дисплей, кнопки 0-9, +, -, *, /, =, C, CE, +/-, и рабочий запуск через отдельную точку входа. Не трогай README, если это не нужно для запуска.
```

If you want the agent to continue after clarification questions, add `--assume-clarification`.
