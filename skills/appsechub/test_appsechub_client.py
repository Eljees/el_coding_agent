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


def test_list_app_scans_normalizes_and_keeps_raw():
    payload = {
        "entities": [
            {"id": 101, "date": "2026-05-01", "tool": "trufflehog", "status": "FINISHED"},
            {"scanTaskId": 102},  # partial record must not break normalization
        ]
    }

    def fake_get(session, path, params=None):
        assert path == "/releaseObject/89/scans"
        return payload

    out = _with_fake_get(fake_get, lambda: hub.list_app_scans(89))
    assert out["app_id"] == 89 and out["count"] == 2
    assert out["scans"][0] == {
        "id": 101,
        "ts": "2026-05-01",
        "tool": "trufflehog",
        "status": "FINISHED",
    }
    assert out["scans"][1] == {"id": 102, "ts": None, "tool": None, "status": None}
    assert "raw" not in out
    with_raw = _with_fake_get(fake_get, lambda: hub.list_app_scans(89, include_raw=True))
    assert with_raw["raw"] == payload


def test_list_app_scans_bare_list_and_empty_response():
    # bare-list body (no paging envelope)
    bare = _with_fake_get(lambda s, p, params=None: [{"id": 5}], lambda: hub.list_app_scans(1))
    assert bare["count"] == 1 and bare["scans"][0]["id"] == 5
    # empty / unrecognized body -> empty list, no exception
    empty = _with_fake_get(lambda s, p, params=None: {}, lambda: hub.list_app_scans(1))
    assert empty["count"] == 0 and empty["scans"] == []


def test_scan_trend_three_scans():
    import json as _json

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
        dto = _json.loads(params["dto"])
        assert dto["appIds"] == [89]
        return {"entities": by_scan[dto["scanIds"][0]]}

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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"PASS  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests passed")
