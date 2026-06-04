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
