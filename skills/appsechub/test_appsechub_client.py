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
    dto = hub.build_issue_dto(89, source="trufflehog", severities=["HIGH"], page_index=2, page_size=50)
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
        {"source": "trufflehog", "type": "AWS", "severity": "HIGH", "state": "NEW", "status": "False Positive"},
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


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"PASS  {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests passed")
