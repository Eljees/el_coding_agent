#!/usr/bin/env python3
"""Deterministic AppSecHub client + analysis runner for local-codex-lite.

Data layer for the ``appsechub`` skill. Talks to the AppSecHub REST API
(``/hub/rest``) and exposes a small, predictable CLI plus importable helpers.

Endpoints used (from the AppSecHub OpenAPI spec, server ``/hub/rest``):
  * GET /issue/v2?dto=<json>        -- paginated brief issue list (the workhorse)
  * GET /issue/summary?application= -- severity rollup for one application
  * GET /tool/scanner               -- list of scanner tools

Authentication mirrors the existing ``eltriage.hub_api`` conventions so the same
environment variables work in both projects:
  * Token (preferred): HUB_API_TOKEN | APPSECHUB_API_TOKEN | APPSECHUB_TOKEN | HUB_TOKEN
      header  HUB_API_TOKEN_HEADER (default "Authorization")
      scheme  HUB_API_TOKEN_SCHEME (default "Bearer")
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
_ENTITY_KEYS = ("entities", "content", "items", "data", "elements")
_TOTAL_KEYS = ("totalElements", "total", "totalCount", "count")


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


def _get(session: requests.Session, path: str, params: dict[str, Any] | None = None) -> Any:
    url = f"{base_url()}{path}"
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
    page_index: int = 0,
    page_size: int = 200,
) -> dict[str, Any]:
    """Build the IssueBriefDataRequestDto payload sent as ?dto=<json>."""
    dto: dict[str, Any] = {"appIds": [int(app_id)], "pageIndex": page_index, "pageSize": page_size}
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


def _detector_of(issue: dict[str, Any]) -> str:
    for f in ("type", "category", "threatGroup"):
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
    sev = Counter(str(i.get("severity", "UNKNOWN") or "UNKNOWN").upper() for i in issues)
    status = Counter(str(i.get("state", i.get("status", "?")) or "?") for i in issues)
    # FP proxy: issues whose status normalizes to a false-positive-like state.
    fp = sum(
        1
        for i in issues
        if any(
            t in _norm(i.get("state")) + _norm(i.get("status"))
            for t in ("falsepositive", "fp", "notanissue", "wontfix")
        )
    )
    return {
        "total": total,
        "by_severity": dict(sev.most_common()),
        "by_state": dict(status.most_common()),
        "false_positive_like": fp,
        "false_positive_rate": round(fp / total, 4) if total else 0.0,
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
        page = _get(session, "/issue/v2", params={"dto": json.dumps(dto)})
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
    except AppSecHubError as e:
        _emit({"error": str(e), "status": e.status, "body": e.body})
        return 2
    except Exception as e:
        _emit({"error": f"{type(e).__name__}: {e}"})
        return 2
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
