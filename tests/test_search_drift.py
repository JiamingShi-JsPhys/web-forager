"""Search-layer diagnostics added for 1.3.2: drift, language fallback, diversity."""

from __future__ import annotations

from scripts import engine

BIG_PAGE = "<html><body>" + "<div class='x'>filler</div>" * 1200 + "</body></html>"


def test_a_large_page_without_results_is_reported_as_drift() -> None:
    assert engine.looks_like_parse_drift(BIG_PAGE) is True


def test_a_page_that_says_nothing_was_found_is_not_drift() -> None:
    assert engine.looks_like_parse_drift(BIG_PAGE + "抱歉，没有找到相关结果") is False
    assert engine.looks_like_parse_drift(BIG_PAGE + "No results found") is False


def test_a_small_page_is_never_drift() -> None:
    assert engine.looks_like_parse_drift("<html>tiny</html>") is False


def test_drift_has_its_own_engine_status() -> None:
    error = engine.SearchParseDrift("360 returned 120 KB without a result list")
    assert engine._engine_failure_status(error) == "parser_drift"


def test_a_chinese_query_naming_an_english_api_qualifies_for_a_bing_fallback() -> None:
    assert engine.has_latin_technical_token("Python 3.12 asyncio.TaskGroup 默认异常处理")
    assert engine.has_latin_technical_token("PostgreSQL 和 MySQL 做 OLTP 怎么选")
    # A Latin product name in a Chinese sentence is enough to try the English
    # index when the Chinese ones come back thin.
    assert engine.has_latin_technical_token("手机能连上 WiFi 但打不开网页")
    assert not engine.has_latin_technical_token("苹果最近发布了什么")


def test_overflow_still_fills_the_requested_limit() -> None:
    results = [
        {"url": f"https://a.example/{i}", "title": f"a{i}"} for i in range(5)
    ] + [{"url": f"https://b.example/{i}", "title": f"b{i}"} for i in range(2)]
    picked = engine.diversify_results(results, limit=5, per_host=2)
    hosts = [item["url"].split("/")[2] for item in picked]
    assert len(picked) == 5
    assert set(hosts) == {"a.example", "b.example"}
    assert hosts.count("b.example") == 2


def test_doctor_names_baidu_as_unsupported_and_says_why() -> None:
    report = engine.doctor_report()
    engines = report["search_engines"]
    assert "baidu" not in engines["supported"]
    assert "百度安全验证" in engines["notes"]["baidu"]
