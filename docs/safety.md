# Safety model

Safety is the project's top priority. These gates are **non-negotiable** — do
not remove or weaken them.

## Write & execute gates

- **No writes without `--apply`.** Every patch is previewed; the workspace is
  only modified when you explicitly pass `--apply` (and `safety.require_apply_flag`
  is on by default).
- **No commands without `--exec`.** Suggested shell commands run only with
  `--exec` (and `safety.require_exec_flag`).
- **Dry-run is sacred.** `--dry-run` always stops after preview, writing nothing.

## File-access gates

- **Workspace-only access.** All reads/writes are confined to the workspace
  root; path-traversal is blocked.
- **Sensitive-file blocking.** `.env`, `*secret*`, `*token*`, `*private*` and
  similar are not read unless `safety.allow_sensitive_read` is explicitly enabled.

## Command gates

- **Dangerous-command blocking.** Destructive shell patterns are refused even
  under `--exec`.

## Apply integrity

- **Backup before apply.** Touched files are backed up under the run's
  `backups/` before any change; `undo` restores them.
- **Post-apply AST gate.** After `git apply`, touched `.py` files are
  syntax-checked; syntactically broken Python never "commits" to the workspace.
- **Bounded repair.** Patch repair is capped by `safety.max_patch_attempts`
  (default 4), overridable per run with `--max-patch-attempts`.

## Reporting

Security issues: see [`SECURITY.md`](../SECURITY.md). Do not open public issues
for security-relevant bugs.
