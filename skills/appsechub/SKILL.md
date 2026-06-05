---
name: appsechub
description: Query AppSecHub for an application's issues and analyze them — counts, severity mix, scanner/source breakdown, TruffleHog secret-detector types, and quality metrics (false-positive rate, dynamics). Use when asked to look at issues/findings/srabatyvaniya for an AppSecHub app profile URL or id, count them, classify TruffleHog/secret findings, or assess scan quality. Триггеры: "посмотри issues проекта", "сколько срабатываний", "типы trufflehog", "качество срабатываний", appsechub appprofile.
---

# AppSecHub issues & analysis skill

Use this skill when the user pastes an AppSecHub link (e.g.
`https://appsechub.ssdlc.soc.rt.ru/#/appprofile/89/issues`) or names an
application, and wants to **read and analyze its issues** — count them, break
them down by scanner/severity/type, classify TruffleHog secret findings, or
judge scan quality.

This skill is **read-only**. It fetches and aggregates issues; it never changes
status, severity, or anything in AppSecHub.

## Trigger phrases

- "посмотри количество issues у проекта <url>", "сколько срабатываний"
- "определи типы срабатываний trufflehog / трюфельхога", "какие секреты нашли"
- "разбивка по сканерам / severity", "качество срабатываний", "доля false positive"
- "appsechub", "appprofile", "issues проекта 89"

## Configuration (once)

Set these environment variables before calling the tools:

| Variable | Meaning | Default |
|---|---|---|
| `HUB_API_TOKEN` | API token (also accepts `APPSECHUB_TOKEN`/`HUB_TOKEN`) | — (required) |
| `HUB_URL` | API base, ends with `/hub/rest` | `https://appsechub.ssdlc.soc.rt.ru/hub/rest` |
| `HUB_VERIFY_TLS` | `0` to skip cert check on internal hosts | `1` |

The token is sent as `Authorization: Bearer <token>`. Override header/scheme with
`HUB_API_TOKEN_HEADER` / `HUB_API_TOKEN_SCHEME` if the Hub build expects something
else. These are the same variables the `eltriage` project uses.

## Tool actions (deterministic runner)

```powershell
python skills\appsechub\appsechub_client.py parse-url "<appprofile url>"
python skills\appsechub\appsechub_client.py scanners --with-issue
python skills\appsechub\appsechub_client.py summary  <app_id|url>
python skills\appsechub\appsechub_client.py issues   <app_id|url> --source trufflehog --max 1000
python skills\appsechub\appsechub_client.py breakdown <app_id|url> --by source,severity,type
python skills\appsechub\appsechub_client.py compare  <app_id|url> --old-scan <id> --new-scan <id> [--source trufflehog]
```

The same operations are exposed over MCP (`appsechub` server) as
`parse_app_url`, `list_scanners`, `get_app_summary`, `list_issues`,
`breakdown_issues`, `compare_scans` — prefer those tools when the MCP server is
connected; fall back to the CLI runner otherwise.

## Comparing scans (delta)

`compare <app> --old-scan A --new-scan B` returns the issue delta between two
scans of the same application: `added` (new findings), `removed` (fixed / no
longer detected), `unchanged`, per-severity breakdowns, and `net_change`.
Identity is the Hub's persistent issue `id` (composite fallback when absent).
Get scan ids from `releaseObject/{id}/scans` or the scan history in the GUI; use
this to track whether a release introduced or cleared findings.

## Workflow

For a request like *"посмотри количество issues у проекта 89 и определи типы
срабатываний trufflehog"*:

1. **Resolve the app id** from the pasted URL (`parse-url` → `89`). Never guess it.
2. **Quick counts** with `summary <id>` — severity rollup (critical/high/medium/low).
3. **Fetch the relevant issues** with `issues <id> --source trufflehog` (omit
   `--source` for all scanners). Paging is automatic.
4. **Aggregate** with `breakdown <id> --source trufflehog`, or read the
   `trufflehog_types` / `breakdown` / `quality` blocks it returns.
5. **Report**: total count, severity mix, and the TruffleHog detector-type table.
   State which scanner(s) and how many issues were actually fetched.

For "all scanners" requests, run `breakdown <id>` without `--source` and present
`breakdown.source` (per-scanner counts) plus `breakdown.severity`.

## Issue fields you can rely on (from /issue/v2)

`id`, `appId`, `appName`, `type`, `source`, `category`, `severity`, `tool`,
`cveId`, `cvss`, `state` (NEW/REPEATED), `lastScanTs`, `lastScanTaskId`,
`branch`. The scanner is in `source`/`tool`; the TruffleHog detector is in
`type` (fallback `category`).

## TruffleHog detector classification

`trufflehog_types` groups secret findings by detector into friendly labels
(AWS access key, GitHub token, Private key (PEM), Generic / high-entropy
secret, etc.). Unknown detectors are passed through verbatim — report them as-is
rather than forcing a bucket. If a finding's `source`/`tool` does not contain
`trufflehog`, it is excluded from this view.

## Quality metrics

`quality_metrics` returns over the fetched set:

- `by_severity` — severity distribution (signal of risk concentration).
- `by_state` — NEW vs REPEATED (REPEATED-heavy = recurring, not triaged).
- `false_positive_like` / `false_positive_rate` — issues in FP-like states
  (false-positive, won't-fix, not-an-issue). A **proxy**, not ground truth:
  state taxonomy varies per Hub config — verify the actual status names with
  `scanners`/a small `issues` sample before quoting the rate as authoritative.

For **dynamics between scans**, fetch with `--source`/no filter twice (or use
`lastScanTaskId`) and compare counts; the API also exposes
`/metrics/scanDynamic` if deeper trend data is needed.

## Red flags

- Do **not** invent the app id — always derive it from the URL via `parse-url`.
- `total_fetched` is capped by `--max`; if it equals the cap, the real total may
  be higher — raise `--max` or note the cap in the answer.
- The FP rate is a heuristic proxy; label it as such.
- Internal host: if requests fail with TLS errors, set `HUB_VERIFY_TLS=0`.
- 401/403 → token missing or expired; 404 → wrong base URL (must end `/hub/rest`).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `error ... 401/403` | `HUB_API_TOKEN` missing/expired |
| `error ... 404` | `HUB_URL` wrong; must end with `/hub/rest` |
| TLS / SSL error | set `HUB_VERIFY_TLS=0` for the internal host |
| Empty `issues` but app has findings | wrong `--source` spelling; check `scanners --with-issue` for exact names |
| `Could not find an application id` | URL had no `appprofile/<n>`; pass the numeric id directly |
