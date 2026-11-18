"""Risk flags, authority tiers and partial skip entries."""

from __future__ import annotations

from typing import Any

from scripts import engine


def _result(url: str, title: str = "title", snippet: str = "snippet") -> dict[str, Any]:
    return {"url": url, "title": title, "snippet": snippet, "source": "360"}


def test_a_list_with_no_authoritative_source_is_flagged() -> None:
    quality = engine.search_quality(
        "some question",
        [_result("https://blog.csdn.net/a"), _result("https://php.cn/b")],
    )
    assert quality["high_authority"] == 0
    assert quality["risk"]["no_authoritative_source"] is True


def test_one_official_source_clears_the_flag() -> None:
    quality = engine.search_quality(
        "some question",
        [_result("https://blog.csdn.net/a"), _result("https://www.gov.cn/b")],
    )
    assert quality["risk"]["no_authoritative_source"] is False
    assert quality["high_authority"] >= 1


def test_a_wechat_heavy_list_is_flagged() -> None:
    quality = engine.search_quality(
        "q",
        [
            _result("https://mp.weixin.qq.com/s/1"),
            _result("https://mp.weixin.qq.com/s/2"),
            _result("https://mp.weixin.qq.com/s/3"),
        ],
    )
    assert quality["risk"]["wechat_heavy"] is True


def test_risk_is_visible_in_compact_payloads() -> None:
    import mcp_server

    compact = mcp_server._compact_search_payload(
        {
            "search_results": [_result("https://example.org/a")],
            "search_quality": {
                "returned": 1,
                "relevant": 1,
                "engines_answered": ["360"],
                "risk": {"no_authoritative_source": True},
            },
        }
    )
    assert compact["search_quality"]["risk"]["no_authoritative_source"] is True


def test_expanded_authority_domains_are_classified() -> None:
    assert engine.authority_for("docs.aws.amazon.com")["tier"] == "primary"
    assert engine.authority_for("pkg.go.dev")["tier"] == "primary"
    assert engine.authority_for("stats.gov.cn")["tier"] == "official"
    assert engine.authority_for("juejin.cn")["tier"] == "community"
    assert engine.authority_for("sohu.com")["tier"] == "low"


def test_a_skipped_result_keeps_the_title_and_snippet_it_saw() -> None:
    entry = engine._skipped_entry(
        {"url": "https://mp.weixin.qq.com/s/x", "title": "An article", "snippet": "glimpse"},
        "robots_denied",
        "robots.txt disallows it",
    )
    assert entry["title"] == "An article"
    assert entry["snippet"] == "glimpse"
    assert entry["partial"] is True
    assert entry["code"] == "robots_denied"


def test_search_warns_when_no_authoritative_source_is_present(
    monkeypatch,
) -> None:
    results = [
        _result("https://blog.csdn.net/a", "weak one"),
        _result("https://php.cn/b", "weak two"),
    ]
    monkeypatch.setattr(engine, "search", lambda *args, **kwargs: results)
    config = engine.FetchConfig(
        delay=0.0, timeout=5.0, max_chars=0, render="never", max_pages=0
    )
    payload = engine.fetch_by_query("2026年某公司营收多少", config)
    assert any(
        "no official, primary or academic source" in warning
        for warning in payload["warnings"]
    )
