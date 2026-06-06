#!/usr/bin/env python3
"""Offline unit tests for appsechub_client pure logic (no network)."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import appsechub_client as hub


def test_parse_app_url():
    assert hub.parse_app_url("https://appsechub.ssdlc.soc.rt.ru/#/appprofile/89/issues") == 89
    assert hub.parse_app_url("https://appsechub.ssdlc.soc.rt.ru/#/appprofile/89") == 89
    assert hub.parse_app_url("89") == 89
    assert hub.parse_app_url("/application/123/foo") == 123
    assert hub.parse_app_url("https://x/y?appId=77") == 77
    for bad in ("no-numbers-here", "https://example.com/dashboard"):
        try:
            hub.parse_app_url(bad)
            raise AssertionError(f"expected ValueError for {bad!r}")
        except ValueError:
            pass


def test_build_issue_dto():
    dto = hub.build_issue_dto(
        89, source="trufflehog", severities=["HIGH"], page_index=2, page_size=50
    )
    assert dto["appIds"] == [89]
    assert dto["source"] == "trufflehog"
    assert dto["severities"] == ["HIGH"]
    assert dto["pageIndex"] == 2 and dto["pageSize"] == 50
    # optional fields omitted when falsy
    bare = hub.build_issue_dto(1)
    assert "source" not in bare and "tools" not in bare


def test_entities_and_total():
    assert hub._entities({"entities": [1, 2]}) == [1, 2]
    assert hub._entities({"content": [3]}) == [3]
    assert hub._entities([9]) == [9]
    assert hub._entities({"nope": 1}) == []
    assert hub._total({"totalElements": 42}) == 42
    assert hub._total({"total": 7}) == 7
    assert hub._total([]) is None


def test_trufflehog_label():
    assert hub.trufflehog_label("AWS") == "AWS access key"
    assert hub.trufflehog_label("github") == "GitHub token"
    assert hub.trufflehog_label("PrivateKey") == "Private key (PEM)"
    assert hub.trufflehog_label("Generic") == "Generic / high-entropy secret"
    assert hub.trufflehog_label("SomeBrandNewDetector") == "SomeBrandNewDetector"


def _sample():
    return [
        {"source": "trufflehog", "type": "AWS", "severity": "HIGH", "state": "NEW"},
        {"source": "trufflehog", "type": "github", "severity": "CRITICAL", "state": "REPEATED"},
        {
            "source": "trufflehog",
            "type": "AWS",
            "severity": "HIGH",
            "state": "NEW",
            "status": "False Positive",
        },
        {"source": "sca", "type": "CVE-2021-1", "severity": "MEDIUM", "state": "NEW"},
        {"tool": "TruffleHog", "type": "PrivateKey", "severity": "CRITICAL", "state": "NEW"},
    ]


def test_breakdown():
    b = hub.breakdown(_sample(), by=["source", "severity"])
    assert b["source"]["trufflehog"] == 3
    assert b["source"]["sca"] == 1
    assert b["severity"]["HIGH"] == 2
    assert b["severity"]["CRITICAL"] == 2


def test_trufflehog_types():
    t = hub.trufflehog_types(_sample())
    # 'tool: TruffleHog' must be counted too (case-insensitive)
    assert t["AWS access key"] == 2
    assert t["GitHub token"] == 1
    assert t["Private key (PEM)"] == 1
    # sca finding excluded
    assert "CVE-2021-1" not in t


def test_quality_metrics():
    q = hub.quality_metrics(_sample())
    assert q["total"] == 5
    assert q["by_severity"]["HIGH"] == 2
    assert q["false_positive_like"] == 1
    assert 0.19 < q["false_positive_rate"] < 0.21  # 1/5


def test_build_issue_dto_scan_ids():
    dto = hub.build_issue_dto(89, scan_ids=[101, 102])
    assert dto["scanIds"] == [101, 102]
    assert "scanIds" not in hub.build_issue_dto(89)  # omitted when empty


def test_issue_key_prefers_id():
    assert hub.issue_key({"id": 7, "type": "AWS"}) == "id:7"
    # no id -> composite key that is stable for identical descriptive fields
    a = hub.issue_key({"appId": 89, "source": "trufflehog", "type": "AWS"})
    b = hub.issue_key({"appId": 89, "source": "trufflehog", "type": "AWS"})
    c = hub.issue_key({"appId": 89, "source": "trufflehog", "type": "GitHub"})
    assert a == b and a != c and a.startswith("k:")


def test_diff_issues_by_id():
    old = [
        {"id": 1, "severity": "HIGH"},
        {"id": 2, "severity": "LOW"},
        {"id": 3, "severity": "CRITICAL"},
    ]
    new = [
        {"id": 2, "severity": "LOW"},  # unchanged
        {"id": 3, "severity": "CRITICAL"},  # unchanged
        {"id": 4, "severity": "HIGH"},  # added
    ]
    d = hub.diff_issues(old, new)
    assert d["old_total"] == 3 and d["new_total"] == 3
    assert d["added_count"] == 1 and d["removed_count"] == 1
    assert d["unchanged_count"] == 2
    assert d["net_change"] == 0
    assert d["added_by_severity"] == {"HIGH": 1}
    assert d["removed_by_severity"] == {"HIGH": 1}  # id:1 was HIGH
    assert [i["id"] for i in d["added"]] == [4]
    assert [i["id"] for i in d["removed"]] == [1]


def test_diff_issues_empty_old_all_added():
    new = [{"id": 1, "severity": "HIGH"}, {"id": 2, "severity": "LOW"}]
    d = hub.diff_issues([], new)
    assert d["added_count"] == 2 and d["removed_count"] == 0
    assert d["net_change"] == 2


def test_normalize_scan_full_partial_empty():
    # full record, alternative key spellings picked up
    full = hub.normalize_scan(
        {
            "scanId": 101,
            "startedAt": "2026-06-01T10:00:00Z",
            "toolName": "trufflehog",
            "state": "DONE",
        }
    )
    assert full == {"id": 101, "ts": "2026-06-01T10:00:00Z", "tool": "trufflehog", "status": "DONE"}
    # partial record -> missing fields are None, no exception
    part = hub.normalize_scan({"id": 7})
    assert part["id"] == 7
    assert part["ts"] is None and part["tool"] is None and part["status"] is None
    # garbage input -> all-None skeleton
    none_scan = {"id": None, "ts": None, "tool": None, "status": None}
    assert hub.normalize_scan("not-a-dict") == none_scan
    assert hub.normalize_scan({}) == none_scan


def _with_fake_get(fake, fn):
    """Run fn() with hub._get replaced by fake (HTTP layer mocked, no network)."""
    real = hub._get
    hub._get = fake
    try:
        return fn()
    finally:
        hub._get = real


def test_list_app_scans_resolves_release_objects():
    payload = {
        "entities": [
            {"id": 101, "date": "2026-05-01", "tool": "trufflehog", "status": "FINISHED"},
            {"scanTaskId": 102},  # partial record must not break normalization
        ]
    }

    def fake_get(session, path, params=None):
        if path == "/releaseObject":
            assert params == {"appIds": 89, "pageIndex": 0, "pageSize": 200}
            return {"entities": [{"id": 555, "version": "1.0"}]}
        assert path == "/releaseObject/555/scans"
        return payload

    out = _with_fake_get(fake_get, lambda: hub.list_app_scans(89))
    assert out["app_id"] == 89 and out["count"] == 2
    assert out["release_object_ids"] == [555]
    assert out["scans"][0] == {
        "id": 101,
        "ts": "2026-05-01",
        "tool": "trufflehog",
        "status": "FINISHED",
        "release_object_id": 555,
    }
    assert out["scans"][1]["id"] == 102 and out["scans"][1]["release_object_id"] == 555
    assert "raw" not in out
    with_raw = _with_fake_get(fake_get, lambda: hub.list_app_scans(89, include_raw=True))
    assert with_raw["raw"] == {"555": payload}


def test_list_app_scans_fallback_and_empty_response():
    # no release objects found -> id treated as a releaseObject id directly
    def fake_get_bare(session, path, params=None):
        if path == "/releaseObject":
            return {"entities": []}
        assert path == "/releaseObject/1/scans"
        return [{"id": 5}]

    bare = _with_fake_get(fake_get_bare, lambda: hub.list_app_scans(1))
    assert bare["count"] == 1 and bare["scans"][0]["id"] == 5
    assert bare["release_object_ids"] == [1]

    # empty / unrecognized scan body -> empty list, no exception
    def fake_get_empty(session, path, params=None):
        return {} if path != "/releaseObject" else {"entities": []}

    empty = _with_fake_get(fake_get_empty, lambda: hub.list_app_scans(1))
    assert empty["count"] == 0 and empty["scans"] == []


def test_scan_trend_three_scans():
    by_scan = {
        101: [{"id": 1, "severity": "HIGH"}, {"id": 2, "severity": "LOW"}],
        102: [
            {"id": 2, "severity": "LOW"},
            {"id": 3, "severity": "CRITICAL"},
            {"id": 4, "severity": "HIGH"},
        ],
        103: [{"id": 3, "severity": "CRITICAL"}],
    }

    def fake_get(session, path, params=None):
        assert path == "/issue/v2"
        # DTO fields are flattened into query params (lists comma-joined).
        assert params["appIds"] == "89"
        assert params["sort"] == 1
        return {"filteredEntities": by_scan[int(params["scanIds"])]}

    out = _with_fake_get(fake_get, lambda: hub.scan_trend(89, [101, 102, 103]))
    assert out["app_id"] == 89 and out["scan_ids"] == [101, 102, 103]
    first, second, third = out["trend"]
    assert first["scan_id"] == 101 and first["total"] == 2
    assert first["added"] is None and first["removed"] is None and first["net_change"] is None
    assert second == {
        "scan_id": 102,
        "total": 3,
        "by_severity": {"LOW": 1, "CRITICAL": 1, "HIGH": 1},
        "added": 2,
        "removed": 1,
        "net_change": 1,
        "added_by_severity": {"CRITICAL": 1, "HIGH": 1},
        "removed_by_severity": {"HIGH": 1},
    }
    assert third["total"] == 1 and third["added"] == 0 and third["removed"] == 2
    assert third["net_change"] == -2


def test_scan_trend_requires_two_ids():
    for bad in ([], [101]):
        try:
            hub.scan_trend(89, bad)
            raise AssertionError(f"expected ValueError for {bad!r}")
        except ValueError:
            pass


def test_normalize_severity_codes_and_strings():
    # numeric codes (live Hub): 0=LOW 1=MEDIUM 2=HIGH 3=CRITICAL
    assert hub.normalize_severity(0) == "LOW"
    assert hub.normalize_severity("1") == "MEDIUM"
    assert hub.normalize_severity(2) == "HIGH"
    assert hub.normalize_severity(3) == "CRITICAL"
    # string severities pass through upper-cased; unknown stays visible
    assert hub.normalize_severity("High") == "HIGH"
    assert hub.normalize_severity(None) == "UNKNOWN"
    assert hub.normalize_severity(7) == "7"


def test_detector_prefers_category_for_bucket_types():
    # live Hub: type is a scan-kind bucket, detector lives in category
    live = {"type": "SAST", "category": "URI", "tool": "trufflehog", "source": "x.json"}
    assert hub._detector_of(live) == "URI"
    # builds where type carries the detector keep the old behaviour
    classic = {"type": "AWS", "category": "Secrets"}
    assert hub._detector_of(classic) == "AWS"
    assert hub._detector_of({}) == "unknown"


def test_quality_metrics_counts_accepted_risk_as_fp_like():
    issues = [
        {"severity": 3, "status": "False Positive"},
        {"severity": 2, "status": "Accepted risk"},
        {"severity": 0, "status": "To verify"},
        {"severity": 1, "status": "Open"},
    ]
    q = hub.quality_metrics(issues)
    assert q["false_positive_like"] == 2
    assert q["by_severity"] == {"CRITICAL": 1, "HIGH": 1, "LOW": 1, "MEDIUM": 1}


def test_dto_query_params_flatten():
    dto = hub.build_issue_dto(89, source="trufflehog", severities=["HIGH", "LOW"], scan_ids=[1, 2])
    params = hub._dto_query_params(dto)
    assert params["appIds"] == "89"
    assert params["severities"] == "HIGH,LOW"
    assert params["scanIds"] == "1,2"
    assert params["sort"] == 1
    assert params["source"] == "trufflehog"


def test_scan_dynamic():
    def fake_get(session, path, params=None):
        assert path == "/metrics/scanDynamic"
        assert params == {"appIds": 89, "fromDate": 123}
        return {"scanResultsTrend": {"qgPassed": [{"value": 1}]}}

    out = _with_fake_get(fake_get, lambda: hub.scan_dynamic(89, from_date=123))
    assert out["app_id"] == 89
    assert "scanResultsTrend" in out["dynamic"]


class _FakeResponse:
    def __init__(self, status_code, body="{}"):
        self.status_code = status_code
        self.text = body
        self.headers = {"Content-Type": "application/json"}

    def json(self):
        import json as _json

        return _json.loads(self.text)


class _FakeSession:
    """Stands in for requests.Session: scripted GET statuses + recorded POSTs."""

    def __init__(self, get_statuses):
        self._get_statuses = list(get_statuses)
        self.post_calls = []
        self.headers = {"Authorization": "Bearer stale-token"}

    def get(self, url, params=None, timeout=None, verify=None):
        return _FakeResponse(self._get_statuses.pop(0), '{"ok": true}')

    def post(self, url, data=None, headers=None, timeout=None, verify=None):
        self.post_calls.append({"url": url, "data": data, "headers": headers})
        return _FakeResponse(200)


def _with_env(env, fn):
    """Run fn() with os.environ patched (and restored afterwards).

    Removals happen *before* assignments: on Windows ``os.environ`` is
    case-insensitive, so popping ``HUB_login`` after setting ``HUB_LOGIN``
    would silently erase the value we just set.
    """
    saved = {k: os.environ.get(k) for k in env}
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
    os.environ.update({k: v for k, v in env.items() if v is not None})
    try:
        return fn()
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


_NO_CRED_ENV = {
    k: None
    for k in (
        "HUB_login",
        "HUB_LOGIN",
        "HUB_USERNAME",
        "HUB_USER",
        "HUB_pwd",
        "HUB_PWD",
        "HUB_PASSWORD",
        "HUB_PASS",
    )
}


def test_login_requires_credentials():
    def check():
        try:
            hub.login(_FakeSession([]))
            raise AssertionError("expected AppSecHubError without credentials")
        except hub.AppSecHubError:
            pass

    _with_env(_NO_CRED_ENV, check)


def test_get_falls_back_to_form_login_on_401():
    env = dict(_NO_CRED_ENV)
    env.update({"HUB_LOGIN": "user@corp", "HUB_PWD": "s3cret"})
    session = _FakeSession([401, 200])  # first GET rejected, retry succeeds

    out = _with_env(env, lambda: hub._get(session, "/tool/scanner"))
    assert out == {"ok": True}
    assert len(session.post_calls) == 1
    call = session.post_calls[0]
    assert call["url"].endswith("/auth/login")
    assert call["data"] == {"username": "user@corp", "password": "s3cret"}
    assert call["headers"]["X-Login-Ajax-Call"] == "true"
    assert getattr(session, "_hub_authenticated", False) is True
    # stale token header must be dropped so the cookie wins on retry
    assert "Authorization" not in session.headers


def test_get_no_retry_without_credentials():
    session = _FakeSession([401])

    def check():
        try:
            hub._get(session, "/tool/scanner")
            raise AssertionError("expected AppSecHubError on 401 without creds")
        except hub.AppSecHubError as exc:
            assert exc.status == 401

    _with_env(_NO_CRED_ENV, check)
    assert session.post_calls == []


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"PASS  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests passed")
