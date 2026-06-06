#!/usr/bin/env python3
"""Deterministic AppSecHub client + analysis runner for local-codex-lite.

Data layer for the ``appsechub`` skill. Talks to the AppSecHub REST API
(``/hub/rest``) and exposes a small, predictable CLI plus importable helpers.

Endpoints used (from the AppSecHub OpenAPI spec, server ``/hub/rest``):
  * GET /issue/v2?dto=<json>        -- paginated brief issue list (the workhorse)
  * GET /issue/summary?application= -- severity rollup for one application
  * GET /tool/scanner               -- list of scanner tools
  * GET /releaseObject/{id}/scans   -- scan history of one application

Authentication mirrors the existing ``eltriage.hub_api`` conventions so the same
environment variables work in both projects:
  * Token (tried first): HUB_API_TOKEN | APPSECHUB_API_TOKEN | APPSECHUB_TOKEN | HUB_TOKEN
      header  HUB_API_TOKEN_HEADER (default "Authorization")
      scheme  HUB_API_TOKEN_SCHEME (default "Bearer")
  * Login/password fallback (form POST /auth/login, session cookies):
      HUB_login | HUB_LOGIN | HUB_USERNAME | HUB_USER
      HUB_pwd   | HUB_PWD   | HUB_PASSWORD | HUB_PASS
    Used automatically when a request gets 401/403 (many Hub builds reject
    static Bearer tokens and require an authenticated session).
  * Base URL: HUB_URL | APPSECHUB_URL | APPSEC_HUB_URL
      default https://appsechub.ssdlc.soc.rt.ru/hub/rest
  * TLS verify: HUB_VERIFY_TLS = 1/0 (default 1)

This module never executes anything it fetches; it only reads issues.

CLI:
  python appsechub_client.py parse-url   "<appprofile url>"
  python appsechub_client.py scanners     [--with-issue]
  python appsechub_client.py summary       <app_id|url>
  python appsechub_client.py issues        <app_id|url> [--source trufflehog] [--severity HIGH ...] [--max 1000]
  python appsechub_client.py breakdown     <app_id|url> [--source trufflehog] [--by source,type,severity]
  python appsechub_client.py scans         <app_id|url> [--raw]
  python appsechub_client.py trend         <app_id|url> --scans id1,id2,... [--source trufflehog]
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from typing import Any

import requests

try:  # silence noisy TLS warnings when verify is disabled on internal hosts
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:  # pragma: no cover
    pass


DEFAULT_BASE_URL = "https://appsechub.ssdlc.soc.rt.ru/hub/rest"
DEFAULT_TIMEOUT = int(os.getenv("APPSECHUB_HTTP_TIMEOUT", os.getenv("ELTRIAGE_HTTP_TIMEOUT", "60")))

# Possible keys for the paged entity list across Hub builds.
# "filteredEntities"/"totalEntitiesCount" confirmed live on appsechub.ssdlc.soc.rt.ru (2026-06).
_ENTITY_KEYS = ("entities", "filteredEntities", "content", "items", "data", "elements")
_TOTAL_KEYS = ("totalElements", "totalEntitiesCount", "total", "totalCount", "count")


# --------------------------------------------------------------------------- #
# Configuration / auth
# --------------------------------------------------------------------------- #
def _env_first(names: Iterable[str], default: str = "") -> str:
    for n in names:
        v = os.getenv(n)
        if v is not None and str(v).strip():
            return str(v).strip()
    return default


def base_url() -> str:
    raw = _env_first(["HUB_URL", "APPSECHUB_URL", "APPSEC_HUB_URL"], DEFAULT_BASE_URL)
    return raw.rstrip("/")


def verify_tls() -> bool:
    return _env_first(["HUB_VERIFY_TLS", "APPSECHUB_VERIFY_TLS"], "1").lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def _auth_headers() -> dict[str, str]:
    token = _env_first(["HUB_API_TOKEN", "APPSECHUB_API_TOKEN", "APPSECHUB_TOKEN", "HUB_TOKEN"], "")
    if not token:
        return {}
    header = _env_first(["HUB_API_TOKEN_HEADER"], "Authorization")
    scheme = _env_first(["HUB_API_TOKEN_SCHEME"], "Bearer")
    # Preserve an explicit scheme already baked into the token.
    if re.match(r"^(bearer|token)\s+", token, flags=re.IGNORECASE):
        return {header: token}
    if header.lower() == "authorization" and scheme:
        return {header: f"{scheme} {token}"}
    return {header: token}


def _credentials() -> tuple[str, str]:
    """Login/password pair for the form-based fallback (mirrors eltriage.hub_api)."""
    user = _env_first(["HUB_login", "HUB_LOGIN", "HUB_USERNAME", "HUB_USER"], "")
    pwd = _env_first(["HUB_pwd", "HUB_PWD", "HUB_PASSWORD", "HUB_PASS"], "")
    return user, pwd


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    s.headers.update(_auth_headers())
    return s


class AppSecHubError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, url: str = "", body: str = ""):
        super().__init__(message)
        self.status = status
        self.url = url
        self.body = body


AUTH_PATH = "/auth/login"


def login(session: requests.Session) -> None:
    """Authenticate *session* via the Hub's form login (``POST /auth/login``).

    Mirrors ``eltriage.hub_api.authenticate`` password mode: form-urlencoded
    ``username``/``password`` plus the ``X-Login-Ajax-Call`` header; the JSESSION
    cookie stored on the session carries auth for subsequent requests.
    """
    user, pwd = _credentials()
    if not user or not pwd:
        raise AppSecHubError(
            "No credentials for form login: set HUB_login + HUB_pwd (or a working HUB_API_TOKEN)."
        )
    # Drop the (rejected) token header: leaving a stale ``Authorization`` on the
    # session makes some Hub builds 401 even with a valid login cookie.
    token_header = _env_first(["HUB_API_TOKEN_HEADER"], "Authorization")
    getattr(session, "headers", {}).pop(token_header, None)
    url = f"{base_url()}{AUTH_PATH}"
    resp = session.post(
        url,
        data={"username": user, "password": pwd},
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "X-Login-Ajax-Call": "true",
        },
        timeout=DEFAULT_TIMEOUT,
        verify=verify_tls(),
    )
    if resp.status_code >= 400:
        raise AppSecHubError(
            f"HTTP {resp.status_code} for {AUTH_PATH} (form login)",
            resp.status_code,
            url,
            (resp.text or "")[:500],
        )
    session._hub_authenticated = True  # type: ignore[attr-defined]


def _get(session: requests.Session, path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{base_url()}{path}"
    resp = session.get(url, params=params, timeout=DEFAULT_TIMEOUT, verify=verify_tls())
    if resp.status_code in (401, 403) and not getattr(session, "_hub_authenticated", False):
        user, pwd = _credentials()
        if user and pwd:
            login(session)
            resp = session.get(url, params=params, timeout=DEFAULT_TIMEOUT, verify=verify_tls())
    if resp.status_code >= 400:
        raise AppSecHubError(
            f"HTTP {resp.status_code} for {path}", resp.status_code, url, (resp.text or "")[:500]
        )
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "json" in ctype or resp.text.strip().startswith(("{", "[")):
        return resp.json()
    return resp.text


# --------------------------------------------------------------------------- #
# Pure helpers (no network -- unit tested)
# --------------------------------------------------------------------------- #
_APP_ID_PATTERNS = (
    r"appprofile/(\d+)",
    r"app-profile/(\d+)",
    r"application/(\d+)",
    r"applications?/(\d+)",
    r"\bapp(?:Id|_id)?=(\d+)",
)


def parse_app_url(url_or_id: str) -> int:
    """Extract a numeric application id from an AppSecHub URL or a bare id.

    >>> parse_app_url("https://appsechub.ssdlc.soc.rt.ru/#/appprofile/89/issues")
    89
    >>> parse_app_url("89")
    89
    """
    s = str(url_or_id).strip()
    if s.isdigit():
        return int(s)
    for pat in _APP_ID_PATTERNS:
        m = re.search(pat, s, flags=re.IGNORECASE)
        if m:
            return int(m.group(1))
    raise ValueError(f"Could not find an application id in: {url_or_id!r}")


def _entities(page: Any) -> list[dict[str, Any]]:
    if isinstance(page, list):
        return page
    if isinstance(page, dict):
        for k in _ENTITY_KEYS:
            v = page.get(k)
            if isinstance(v, list):
                return v
    return []


def _total(page: Any) -> int | None:
    if isinstance(page, dict):
        for k in _TOTAL_KEYS:
            v = page.get(k)
            if isinstance(v, int):
                return v
    return None


def build_issue_dto(
    app_id: int,
    *,
    source: str | None = None,
    source_exact: str | None = None,
    tools: list[str] | None = None,
    severities: list[str] | None = None,
    statuses: list[str] | None = None,
    types: list[str] | None = None,
    category: str | None = None,
    state: str | None = None,
    scan_ids: list[int] | None = None,
    page_index: int = 0,
    page_size: int = 200,
) -> dict[str, Any]:
    """Build the IssueBriefDataRequestDto field set for /issue/v2.

    Spring binds the DTO from individual query parameters (see
    :func:`_dto_query_params`); ``sort`` is the only field the live Hub marks
    ``NotNull``, so it is always present.
    """
    dto: dict[str, Any] = {
        "appIds": [int(app_id)],
        "sort": 1,
        "pageIndex": page_index,
        "pageSize": page_size,
    }
    if scan_ids:
        dto["scanIds"] = [int(s) for s in scan_ids]
    if source:
        dto["source"] = source
    if source_exact:
        dto["sourceExact"] = source_exact
    if tools:
        dto["tools"] = list(tools)
    if severities:
        dto["severities"] = list(severities)
    if statuses:
        dto["statuses"] = list(statuses)
    if types:
        dto["types"] = list(types)
    if category:
        dto["category"] = category
    if state:
        dto["state"] = state
    return dto


# Known TruffleHog secret detectors -> human-friendly group.
# TruffleHog reports the detector in the issue's ``type`` / ``category`` field.
_TRUFFLEHOG_LABELS = {
    "aws": "AWS access key",
    "awssessionkey": "AWS session key",
    "gcp": "GCP service account",
    "azure": "Azure credential",
    "github": "GitHub token",
    "githubapp": "GitHub App key",
    "gitlab": "GitLab token",
    "slack": "Slack token",
    "slackwebhook": "Slack webhook",
    "privatekey": "Private key (PEM)",
    "jdbc": "JDBC connection string",
    "postgres": "Postgres credential",
    "mysql": "MySQL credential",
    "mongodb": "MongoDB credential",
    "jwt": "JWT",
    "telegram": "Telegram bot token",
    "dockerhub": "Docker Hub credential",
    "npmtoken": "npm token",
    "pypi": "PyPI token",
    "generic": "Generic / high-entropy secret",
    "genericapikey": "Generic API key",
}


def _norm(s: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(s or "").lower())


def trufflehog_label(detector: Any) -> str:
    key = _norm(detector)
    if key in _TRUFFLEHOG_LABELS:
        return _TRUFFLEHOG_LABELS[key]
    for k, label in _TRUFFLEHOG_LABELS.items():
        if k and k in key:
            return label
    return str(detector or "unknown")


# ``type`` values that are scan-kind buckets, not detectors (live Hub returns
# type=SAST/SCA_S for every issue; the TruffleHog detector then lives in
# ``category``: URI, Alchemy, Postgres, JWT, ...).
_TYPE_BUCKETS = {"sast", "sca", "scas", "scasecurity", "scalicense", "scal", "dast", "iast"}

# Numeric severity codes used by the live Hub (mapping confirmed against
# /issue/summary on appsechub.ssdlc.soc.rt.ru: counts match exactly).
_SEVERITY_CODES = {"0": "LOW", "1": "MEDIUM", "2": "HIGH", "3": "CRITICAL"}


def normalize_severity(value: Any) -> str:
    """Render a Hub severity (numeric code or string) as a canonical label."""
    s = str(value if value is not None else "UNKNOWN").strip() or "UNKNOWN"
    return _SEVERITY_CODES.get(s, s.upper())


def _detector_of(issue: dict[str, Any]) -> str:
    type_v = str(issue.get("type") or "")
    candidates = (
        ("category", "type", "threatGroup")
        if _norm(type_v) in _TYPE_BUCKETS
        else ("type", "category", "threatGroup")
    )
    for f in candidates:
        v = issue.get(f)
        if v:
            return str(v)
    return "unknown"


def breakdown(
    issues: list[dict[str, Any]], by: Iterable[str] = ("source", "severity")
) -> dict[str, Any]:
    """Count issues grouped by one or more fields. Returns {field: {value: count}}."""
    out: dict[str, dict[str, int]] = {}
    for field in by:
        c: Counter = Counter()
        for it in issues:
            if field == "severity":
                c[normalize_severity(it.get("severity"))] += 1
            else:
                c[str(it.get(field, "unknown") or "unknown")] += 1
        out[field] = dict(c.most_common())
    return out


def trufflehog_types(issues: list[dict[str, Any]]) -> dict[str, int]:
    """Group TruffleHog (secret-scanner) findings by detector type, friendly labels."""
    c: Counter = Counter()
    for it in issues:
        src = _norm(it.get("source")) + _norm(it.get("tool"))
        if "trufflehog" not in src:
            continue
        c[trufflehog_label(_detector_of(it))] += 1
    return dict(c.most_common())


def quality_metrics(issues: list[dict[str, Any]]) -> dict[str, Any]:
    """Lightweight quality signals over a fetched issue set."""
    total = len(issues)
    sev = Counter(normalize_severity(i.get("severity")) for i in issues)
    status = Counter(str(i.get("state", i.get("status", "?")) or "?") for i in issues)
    # FP proxy: issues whose status normalizes to a false-positive-like state
    # ("Accepted risk" is the live Hub's wont-fix analogue).
    fp = sum(
        1
        for i in issues
        if any(
            t in _norm(i.get("state")) + _norm(i.get("status"))
            for t in ("falsepositive", "fp", "notanissue", "wontfix", "acceptedrisk")
        )
    )
    return {
        "total": total,
        "by_severity": dict(sev.most_common()),
        "by_state": dict(status.most_common()),
        "false_positive_like": fp,
        "false_positive_rate": round(fp / total, 4) if total else 0.0,
    }


# Fields used to build a composite identity when an issue has no stable ``id``.
_KEY_FIELDS = ("appId", "source", "type", "category", "cveId", "lineNumber", "branch")


def issue_key(issue: dict[str, Any]) -> str:
    """Stable identity for an issue across scans.

    Prefers the Hub's persistent ``id`` (the same finding keeps its id between
    scans); falls back to a composite of descriptive fields when ``id`` is
    missing, so two snapshots can still be diffed.
    """
    iid = issue.get("id")
    if iid not in (None, "", 0):
        return f"id:{iid}"
    return "k:" + "|".join(str(issue.get(f, "")) for f in _KEY_FIELDS)


def _sev_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    c = Counter(normalize_severity(i.get("severity")) for i in items)
    return dict(c.most_common())


def diff_issues(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> dict[str, Any]:
    """Delta between two issue snapshots (e.g. two scans of the same app).

    ``added`` are issues present only in ``new`` (newly introduced), ``removed``
    only in ``old`` (fixed / no longer detected).  Identity is by
    :func:`issue_key`.  Returns counts, per-severity breakdowns, and the full
    added/removed lists.
    """
    old_by = {issue_key(i): i for i in old}
    new_by = {issue_key(i): i for i in new}
    added_keys = new_by.keys() - old_by.keys()
    removed_keys = old_by.keys() - new_by.keys()
    added = [new_by[k] for k in added_keys]
    removed = [old_by[k] for k in removed_keys]
    return {
        "old_total": len(old),
        "new_total": len(new),
        "added_count": len(added),
        "removed_count": len(removed),
        "unchanged_count": len(new_by.keys() & old_by.keys()),
        "net_change": len(new) - len(old),
        "added_by_severity": _sev_counts(added),
        "removed_by_severity": _sev_counts(removed),
        "added": added,
        "removed": removed,
    }


# The exact shape of /releaseObject/{id}/scans is not pinned down across Hub
# builds, so normalization is defensive: probe several plausible key names per
# field and keep ``None`` for whatever is absent instead of raising.
_SCAN_ID_KEYS = ("id", "scanId", "scanTaskId", "taskId")
_SCAN_TS_KEYS = (
    "ts",
    "timestamp",
    "date",
    "created",
    "createdAt",
    "startTime",
    "startedAt",
    "finishTime",
    "finishedAt",
    "scanDate",
    "lastScanTs",
)
_SCAN_TOOL_KEYS = ("tool", "toolName", "scanner", "scannerName", "source", "engine")
_SCAN_STATUS_KEYS = ("status", "state", "scanStatus", "result")


def _first_field(d: dict[str, Any], keys: Iterable[str]) -> Any:
    for k in keys:
        v = d.get(k)
        if v not in (None, ""):
            return v
    return None


def normalize_scan(raw: Any) -> dict[str, Any]:
    """Reduce one raw scan record to {id, ts, tool, status}.

    Missing or unrecognized fields become ``None`` -- never raises on a
    partial or unexpected record.
    """
    if not isinstance(raw, dict):
        return {"id": None, "ts": None, "tool": None, "status": None}
    return {
        "id": _first_field(raw, _SCAN_ID_KEYS),
        "ts": _first_field(raw, _SCAN_TS_KEYS),
        "tool": _first_field(raw, _SCAN_TOOL_KEYS),
        "status": _first_field(raw, _SCAN_STATUS_KEYS),
    }


# --------------------------------------------------------------------------- #
# Network calls
# --------------------------------------------------------------------------- #
def list_scanners(
    session: requests.Session | None = None, with_issue: bool = False
) -> list[dict[str, Any]]:
    session = session or make_session()
    data = _get(session, "/tool/scanner", params={"withIssue": str(bool(with_issue)).lower()})
    return data if isinstance(data, list) else []


def get_app_summary(app_id: int, session: requests.Session | None = None) -> dict[str, Any]:
    session = session or make_session()
    return _get(session, "/issue/summary", params={"application": int(app_id)})


def _dto_query_params(dto: dict[str, Any]) -> dict[str, Any]:
    """Flatten a DTO dict into /issue/v2 query parameters.

    The live Hub does **not** accept ``?dto=<json>``: Spring binds the
    ``IssueBriefDataRequestDto`` from individual query params, with list
    fields passed comma-separated (confirmed live; matches
    ``eltriage/hub/issue_fetch.py``).
    """
    params: dict[str, Any] = {}
    for key, value in dto.items():
        if isinstance(value, (list, tuple)):
            params[key] = ",".join(str(v) for v in value)
        else:
            params[key] = value
    return params


def iter_issues(
    app_id: int,
    *,
    session: requests.Session | None = None,
    page_size: int = 200,
    max_items: int | None = None,
    **filters: Any,
) -> Iterator[dict[str, Any]]:
    """Yield brief issue dicts from /issue/v2, following pagination."""
    session = session or make_session()
    page_index = 0
    seen = 0
    while True:
        dto = build_issue_dto(app_id, page_index=page_index, page_size=page_size, **filters)
        page = _get(session, "/issue/v2", params=_dto_query_params(dto))
        rows = _entities(page)
        if not rows:
            break
        for r in rows:
            yield r
            seen += 1
            if max_items and seen >= max_items:
                return
        if len(rows) < page_size:
            break
        page_index += 1


def list_issues(app_id: int, **kwargs: Any) -> list[dict[str, Any]]:
    return list(iter_issues(app_id, **kwargs))


def fetch_scan_issues(
    app_id: int,
    scan_id: int,
    *,
    session: requests.Session | None = None,
    max_items: int | None = None,
    **filters: Any,
) -> list[dict[str, Any]]:
    """All issues an application had in one specific scan (via the scanIds filter)."""
    return list_issues(
        app_id, session=session, scan_ids=[int(scan_id)], max_items=max_items, **filters
    )


def list_release_objects(
    app_id: int,
    *,
    session: requests.Session | None = None,
) -> list[dict[str, Any]]:
    """Release objects of an application via GET /releaseObject?appIds=<id>.

    A release object is the Hub's unit that owns scan history (an application
    has one or more); ``/releaseObject/{id}/scans`` takes a *release object*
    id, not an application id.
    """
    session = session or make_session()
    data = _get(
        session,
        "/releaseObject",
        params={"appIds": int(app_id), "pageIndex": 0, "pageSize": 200},
    )
    rows = _entities(data)
    if not rows and isinstance(data, list):
        rows = data
    return [r for r in rows if isinstance(r, dict)]


def list_app_scans(
    app_id: int,
    *,
    session: requests.Session | None = None,
    include_raw: bool = False,
) -> dict[str, Any]:
    """Scan history of an application.

    Resolves the app's release objects (``/releaseObject?appIds=``) and
    aggregates ``GET /releaseObject/{roId}/scans`` for each; every scan row is
    normalized to ``{id, ts, tool, status, release_object_id}`` (see
    :func:`normalize_scan`).  If no release objects are found, falls back to
    treating *app_id* as a release object id directly.  With
    ``include_raw=True`` the untouched per-release-object responses are
    attached under ``raw``.
    """
    session = session or make_session()
    release_objects = list_release_objects(app_id, session=session)
    ro_ids = [ro.get("id") for ro in release_objects if ro.get("id") is not None]
    if not ro_ids:
        ro_ids = [int(app_id)]  # fallback: caller may have passed a releaseObject id
    scans: list[dict[str, Any]] = []
    raw: dict[str, Any] = {}
    for ro_id in ro_ids:
        data = _get(session, f"/releaseObject/{int(ro_id)}/scans")
        if include_raw:
            raw[str(ro_id)] = data
        rows = _entities(data)
        if not rows and isinstance(data, dict) and any(k in data for k in _SCAN_ID_KEYS):
            rows = [data]  # tolerate a single-object response
        for r in rows:
            scan = normalize_scan(r)
            scan["release_object_id"] = ro_id
            scans.append(scan)
    out: dict[str, Any] = {
        "app_id": int(app_id),
        "release_object_ids": ro_ids,
        "count": len(scans),
        "scans": scans,
    }
    if include_raw:
        out["raw"] = raw
    return out


def scan_trend(
    app_id: int,
    scan_ids: list[int],
    *,
    session: requests.Session | None = None,
    source: str | None = None,
    max_items: int | None = None,
) -> dict[str, Any]:
    """Issue trend across 2+ scans of one application (oldest first).

    Fetches each scan's snapshot once and diffs adjacent pairs with
    :func:`diff_issues` -- the same engine :func:`compare_scans` uses, without
    re-fetching shared snapshots.  Returns one row per scan: ``total``,
    ``by_severity``, and ``added``/``removed``/``net_change`` against the
    previous scan (``None`` on the first row).
    """
    ids = [int(s) for s in scan_ids]
    if len(ids) < 2:
        raise ValueError("trend needs at least two scan ids (chronological order)")
    session = session or make_session()
    snapshots = [
        fetch_scan_issues(app_id, sid, session=session, source=source, max_items=max_items)
        for sid in ids
    ]
    rows: list[dict[str, Any]] = []
    for pos, (sid, issues) in enumerate(zip(ids, snapshots, strict=True)):
        row: dict[str, Any] = {
            "scan_id": sid,
            "total": len(issues),
            "by_severity": _sev_counts(issues),
            "added": None,
            "removed": None,
            "net_change": None,
        }
        if pos > 0:
            d = diff_issues(snapshots[pos - 1], issues)
            row["added"] = d["added_count"]
            row["removed"] = d["removed_count"]
            row["net_change"] = d["net_change"]
            row["added_by_severity"] = d["added_by_severity"]
            row["removed_by_severity"] = d["removed_by_severity"]
        rows.append(row)
    return {"app_id": int(app_id), "scan_ids": ids, "trend": rows}


def scan_dynamic(
    app_id: int,
    *,
    session: requests.Session | None = None,
    from_date: int | None = None,
) -> dict[str, Any]:
    """Scan dynamics time series via GET /metrics/scanDynamic (confirmed live).

    The Hub aggregates per-day scan results (qgPassed/qgFailed/qgSkipped/broken
    and similar series) for the application -- the native "trend" source on
    builds where release objects are unused.  *from_date* is epoch millis.
    """
    session = session or make_session()
    params: dict[str, Any] = {"appIds": int(app_id)}
    if from_date is not None:
        params["fromDate"] = int(from_date)
    data = _get(session, "/metrics/scanDynamic", params=params)
    return {"app_id": int(app_id), "dynamic": data}


def compare_scans(
    app_id: int,
    old_scan: int,
    new_scan: int,
    *,
    session: requests.Session | None = None,
    source: str | None = None,
    max_items: int | None = None,
) -> dict[str, Any]:
    """Compute the issue delta between two scans of the same application."""
    session = session or make_session()
    old = fetch_scan_issues(app_id, old_scan, session=session, source=source, max_items=max_items)
    new = fetch_scan_issues(app_id, new_scan, session=session, source=source, max_items=max_items)
    return {
        "app_id": int(app_id),
        "old_scan": int(old_scan),
        "new_scan": int(new_scan),
        **diff_issues(old, new),
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _emit(obj: Any) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _resolve(app: str) -> int:
    return parse_app_url(app)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="AppSecHub client / analysis runner")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("parse-url", help="Extract application id from a URL")
    sp.add_argument("url")

    sp = sub.add_parser("scanners", help="List scanner tools")
    sp.add_argument("--with-issue", action="store_true")

    sp = sub.add_parser("summary", help="Severity rollup for an application")
    sp.add_argument("app")

    sp = sub.add_parser("issues", help="Fetch issues for an application")
    sp.add_argument("app")
    sp.add_argument("--source")
    sp.add_argument("--source-exact")
    sp.add_argument("--tool", action="append", dest="tools")
    sp.add_argument("--severity", action="append", dest="severities")
    sp.add_argument("--status", action="append", dest="statuses")
    sp.add_argument("--type", action="append", dest="types")
    sp.add_argument("--page-size", type=int, default=200)
    sp.add_argument("--max", type=int, dest="max_items")

    sp = sub.add_parser("breakdown", help="Aggregate issues (counts + trufflehog types + quality)")
    sp.add_argument("app")
    sp.add_argument("--source")
    sp.add_argument("--by", default="source,severity,type")
    sp.add_argument("--max", type=int, dest="max_items", default=5000)

    sp = sub.add_parser("scans", help="List scans of an application (releaseObject/{id}/scans)")
    sp.add_argument("app")
    sp.add_argument("--raw", action="store_true", help="Attach the unmodified API response")

    sp = sub.add_parser("trend", help="Issue trend across 2+ scans (oldest scan id first)")
    sp.add_argument("app")
    sp.add_argument("--scans", required=True, help="Comma-separated scan ids, oldest first")
    sp.add_argument("--source")
    sp.add_argument("--max", type=int, dest="max_items", default=5000)

    sp = sub.add_parser("dynamic", help="Per-day scan dynamics (metrics/scanDynamic)")
    sp.add_argument("app")
    sp.add_argument("--from-date", type=int, dest="from_date", help="Epoch millis lower bound")

    sp = sub.add_parser("compare", help="Delta of issues between two scans of an application")
    sp.add_argument("app")
    sp.add_argument("--old-scan", type=int, required=True, dest="old_scan")
    sp.add_argument("--new-scan", type=int, required=True, dest="new_scan")
    sp.add_argument("--source")
    sp.add_argument("--max", type=int, dest="max_items", default=5000)

    args = p.parse_args(argv)

    try:
        if args.cmd == "parse-url":
            _emit({"app_id": parse_app_url(args.url)})
            return 0
        if args.cmd == "scanners":
            _emit(list_scanners(with_issue=args.with_issue))
            return 0
        if args.cmd == "summary":
            _emit(get_app_summary(_resolve(args.app)))
            return 0
        if args.cmd == "issues":
            rows = list_issues(
                _resolve(args.app),
                source=args.source,
                source_exact=args.source_exact,
                tools=args.tools,
                severities=args.severities,
                statuses=args.statuses,
                types=args.types,
                page_size=args.page_size,
                max_items=args.max_items,
            )
            _emit({"count": len(rows), "issues": rows})
            return 0
        if args.cmd == "breakdown":
            rows = list_issues(_resolve(args.app), source=args.source, max_items=args.max_items)
            _emit(
                {
                    "app_id": _resolve(args.app),
                    "total_fetched": len(rows),
                    "breakdown": breakdown(
                        rows, by=[b.strip() for b in args.by.split(",") if b.strip()]
                    ),
                    "trufflehog_types": trufflehog_types(rows),
                    "quality": quality_metrics(rows),
                }
            )
            return 0
        if args.cmd == "scans":
            _emit(list_app_scans(_resolve(args.app), include_raw=args.raw))
            return 0
        if args.cmd == "trend":
            ids = [int(s) for s in str(args.scans).split(",") if s.strip()]
            _emit(
                scan_trend(
                    _resolve(args.app),
                    ids,
                    source=args.source,
                    max_items=args.max_items,
                )
            )
            return 0
        if args.cmd == "dynamic":
            _emit(scan_dynamic(_resolve(args.app), from_date=args.from_date))
            return 0
        if args.cmd == "compare":
            _emit(
                compare_scans(
                    _resolve(args.app),
                    args.old_scan,
                    args.new_scan,
                    source=args.source,
                    max_items=args.max_items,
                )
            )
            return 0
    except AppSecHubError as e:
        _emit({"error": str(e), "status": e.status, "body": e.body})
        return 2
    except Exception as e:
        _emit({"error": f"{type(e).__name__}: {e}"})
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
