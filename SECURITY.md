# Security policy

## Reporting a vulnerability

Please **do not** open a public issue for security-relevant bugs.  Use
private channels instead:

- email: <3.14hell@gmail.com> with the subject prefix `[lcl-security]`,
- include a minimal reproduction (CLI invocation, run-dir, what you
  expected vs. what happened),
- include the `local-codex-lite` git commit hash you tested against
  (`git rev-parse HEAD`).

You will get an acknowledgement within 72 hours.  A fix or mitigation
plan is committed to within 14 days; if more time is needed you'll be
told why.

## Scope

The agent is explicitly *local-first* and talks to a local
OpenAI-compatible vLLM endpoint by default.  Issues we care about most:

- arbitrary file write outside the workspace (path traversal in patches,
  diff prefixes, archive extraction),
- arbitrary command execution outside the explicit `--exec` /
  `run_command` path,
- credential or secret leak into `events.jsonl`, `result.json`,
  `failure.json`, `cve_*` reports, or any other artifact under
  `.local-codex-lite/runs/<timestamp>/`,
- sensitive-file bypass of the `safety.is_sensitive_path` guard,
- dangerous-command bypass of the `safety.is_dangerous_command` blocklist,
- `git apply` strategies that mangle paths into something outside the
  workspace,
- archive extraction (artifact-unpack) writing outside the extraction
  root or following symlinks.

Out of scope: bugs in the local vLLM server itself, bugs in `cve-bin-tool`
upstream, anything that requires write access to `.local-codex-lite/`
already.

## Hardening practices already in place

- All run state lives under `.local-codex-lite/runs/<timestamp>/` with a
  microsecond-precision run-id so concurrent runs do not collide.
- Patches go through `validate_diff` (workspace boundary, sensitive
  paths, no-op rejection) before `git apply` is invoked.
- LLM responses are pulled through `sanitize_log_text` before being
  persisted in `events.jsonl`; the sanitiser masks values after
  `token=`/`password=`/`Authorization: Basic|Bearer`/`X-Api-Key:` and
  URL-embedded `https://user:pwd@host` patterns.
- TruffleHog clones use `-c http.extraHeader=Authorization: Basic <b64>`
  instead of embedding credentials in the URL; the args list is redacted
  before any `CalledProcessError` is raised.

If a check above does not behave as documented, please report it - that
is exactly the kind of bug this policy covers.
