# Evidence-first workflow

Every run is recorded. **Proof is kept separate from fixes** so a change and the
evidence that justified it can be audited independently.

## Run directories

Each invocation writes to `.local-codex-lite/runs/<timestamp>/`:

```
runs/<ts>/
  events.jsonl        # structured event log
  plan.json           # the model's plan
  result.json         # machine-readable outcome
  task.txt            # the task text
  backups/            # pre-apply copies of touched files
  evidence/           # evidence bundle (separate from the fix)
```

Manage them with `logs`, `runs archive|prune|export`, `replay` and `undo`.

## Watching the model learn

- `logs attempts [run_id|latest]` renders a per-run attempt timeline from
  `events.jsonl`: every plan/patch attempt, what failed and why, and the final
  outcome (e.g. `result: applied after 2 repairs`).
- `lessons stats` cross-references `lessons.jsonl` with all past runs: per
  lesson it counts how often its error signature occurred before vs after the
  lesson was recorded (`✓ holding` when it never came back, `✗ recurring`).
- The GUI **Runs** tab shows the same timelines for the latest 30 runs of the
  active workspace (`run_report.py` + `ui_commands.runs_overview`).

## Evidence bundles

`evidence_mode` / `evidence` write a self-contained bundle with raw inputs,
summaries and a `status` file (`ok` / `partial` / `failed`). Incomplete unpacks
or missing evidence are classified as not-`ok`.

## CVE scanning (`cve-bin-tool`)

```
evidence cve-scan status         # is cve-bin-tool installed?
evidence cve-scan install        # auto-install if missing
evidence cve-scan update-db      # refresh the CVE database
evidence cve-scan <input_root>   # scan a directory (may contain archives)
evidence cve-scan-history        # list past scans
```

Defaults to `--update never` to avoid network stalls; `--min-severity` defaults
to `HIGH`. Output formats are configurable (`json`, `md`, `high-critical-md`).
Note: `cve-bin-tool`'s `json` and `json2` payloads are different shapes — do not
parse them interchangeably.

## Secret scanning (TruffleHog)

```
evidence trufflehog scan --repo-url <url> --git-user <u> --git-token <t>
evidence trufflehog analyze <input_root>
evidence trufflehog compare <left> <right>
```

Runs TruffleHog through Docker for GitLab repositories. Authorization headers
are redacted from any surfaced subprocess args so tokens never leak into logs
or exceptions.

## Artifact unpacking

`evidence artifacts inspect <root>` inventories archives
(zip/tar/gz/7z/rar/nupkg/jar/war/ear/whl/rpm). Inventory-only is the safe
default; extraction happens next to the source or into an explicit destination,
with evidence metadata stored under the run folder.

## Post-apply smoke testing

After a successful `--apply`, pass `--smoke` to let the agent execute every
entrypoint script that the patch touched and verify it starts cleanly:

```
local-codex-lite run "task" --apply --smoke
```

The script is launched in a subprocess with a configurable timeout (default
10 s, set `safety.smoke_timeout_seconds` in `config.yaml`).  If the process
exits non-zero or its stderr contains a traceback, the output is captured as
evidence and fed automatically back into the repair loop — the same way a
hand-pasted traceback from the "Evidence / traceback" panel would be.

```
safety:
  smoke_run_default: false        # enable smoke on every apply without the flag
  smoke_timeout_seconds: 10
```

In the GUI, tick **Smoke after apply** before clicking *Apply* to enable for
that run.  The smoke result is recorded in `runs/<ts>/smoke.json` and the run
directory's `events.jsonl` for auditing.
