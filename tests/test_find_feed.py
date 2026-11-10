"""Site-scoped search, feed discovery, engine diagnostics and proxy support."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import mcp_server
from scripts import engine

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "run.py"), *args],
        cwd=str(PLUGIN_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )


# ---------------------------------------------------------------------------
# Site-scoped search
# ---------------------------------------------------------------------------


def test_find_within_site_reads_the_site_search_page(site: str) -> None:
    config = engine.FetchConfig(delay=0.0, timeout=10.0, render="never")
    payload = engine.find_within_site(f"{site}/search", "卡片", config, max_pages=1)
    assert payload["mode"] == "site-search"
    assert "?s=" in payload["search_url"]
    assert payload["candidates"], "the search page carries two matching links"
    assert all("卡片" in item["text"] for item in payload["candidates"])
    assert len(payload["pages"]) == 1
    assert payload["pages"][0]["url"].endswith("/surf/one.html")


def test_find_within_site_needs_both_arguments() -> None:
    with pytest.raises(ValueError):
        engine.find_within_site("", "query")
    with pytest.raises(ValueError):
        engine.find_within_site("example.org", "")


def test_find_within_site_reports_when_no_link_matches(site: str) -> None:
    config = engine.FetchConfig(delay=0.0, timeout=10.0, render="never")
    payload = engine.find_within_site(f"{site}/search", "不存在的词", config, max_pages=0)
    assert payload["candidates"], "unfiltered links are still returned"
    assert payload["warnings"]


def test_extract_links_keeps_article_header_links() -> None:
    html = (
        "<html><body>"
        '<header><a href="/nav">Site navigation</a></header>'
        "<main><article><header><h2>"
        '<a href="/post/1">Watermark explained</a>'
        "</h2></header></article></main>"
        "</body></html>"
    )
    links = engine.extract_links(html, "https://example.org/", query="watermark", limit=10)
    urls = [item["url"] for item in links]
    assert "https://example.org/post/1" in urls
    assert "https://example.org/nav" not in urls


# ---------------------------------------------------------------------------
# Feed discovery
# ---------------------------------------------------------------------------


def test_discover_feed_from_a_page_link(site: str) -> None:
    config = engine.FetchConfig(delay=0.0, timeout=10.0, render="never")
    payload = engine.discover_feed(f"{site}/withfeed", config)
    assert payload["mode"] == "feed"
    assert payload["feed_url"].endswith("/rss.xml")
    assert payload["count"] >= 1
    assert payload["items"]


def test_discover_feed_reads_a_direct_feed(site: str) -> None:
    config = engine.FetchConfig(delay=0.0, timeout=10.0, render="never")
    payload = engine.discover_feed(f"{site}/rss.xml", config)
    assert payload["format"] in ("rss", "atom", "rdf")
    assert payload["items"]


def test_discover_feed_explains_a_page_without_a_feed(site: str) -> None:
    config = engine.FetchConfig(delay=0.0, timeout=10.0, render="never")
    with pytest.raises(engine.ExtractionError) as info:
        engine.discover_feed(f"{site}/table.html", config)
    assert "rel=alternate" in str(info.value)


# ---------------------------------------------------------------------------
# Engine diagnostics
# ---------------------------------------------------------------------------


def test_search_report_names_each_engine(monkeypatch) -> None:
    def fake_search_one(name, query, config, limit, fetcher, pages=1):
        if name == "bing":
            raise engine.FetchError("HTTP 503")
        return [{"title": "示例", "url": f"https://{name}.example/", "snippet": "", "source": name}]

    monkeypatch.setattr(engine, "_search_one", fake_search_one)
    config = engine.FetchConfig(delay=0.0)
    fetcher = engine.HttpFetcher(config)
    report: list[dict] = []
    try:
        engine.search("示例", config, engine="all", fetcher=fetcher, report=report)
    finally:
        fetcher.close()
    by_name = {item["engine"]: item for item in report}
    assert by_name["bing"]["ok"] is False
    assert "503" in by_name["bing"]["error"]
    assert by_name["360"]["ok"] is True and by_name["360"]["results"] == 1
    assert all("ms" in item for item in report)


def test_probe_engines_reports_each_backend(monkeypatch) -> None:
    def fake_search_one(name, query, config, limit, fetcher, pages=1):
        if name == "sogou":
            raise engine.FetchError("Sogou returned a verification page (antispider)")
        if name == "360":
            return []
        return [{"title": "示例", "url": f"https://{name}.example/", "snippet": "", "source": name}]

    monkeypatch.setattr(engine, "_search_one", fake_search_one)
    report = engine.probe_engines(engine.FetchConfig(delay=0.0))
    names = [item["engine"] for item in report]
    assert names == ["360", "bing", "sogou", "weixin", "duckduckgo"]
    sogou = next(item for item in report if item["engine"] == "sogou")
    assert sogou["ok"] is False and "verification" in sogou["error"]
    empty = next(item for item in report if item["engine"] == "360")
    assert empty["ok"] is False and "no results" in empty["error"]


# ---------------------------------------------------------------------------
# Proxy
# ---------------------------------------------------------------------------


def test_proxy_is_applied_to_the_session() -> None:
    config = engine.FetchConfig(proxy="http://127.0.0.1:7890")
    fetcher = engine.HttpFetcher(config)
    try:
        assert fetcher.session.proxies["http"] == "http://127.0.0.1:7890"
        assert fetcher.session.proxies["https"] == "http://127.0.0.1:7890"
    finally:
        fetcher.close()


def test_unusual_proxy_scheme_is_rejected() -> None:
    with pytest.raises(ValueError):
        engine.FetchConfig(proxy="ftp://127.0.0.1:21").validate()


def test_doctor_redacts_proxy_credentials() -> None:
    config = engine.FetchConfig(proxy="http://user:secret@127.0.0.1:7890")
    report = engine.doctor_report(config)
    assert report["proxy"]["configured"] is True
    assert report["proxy"]["source"] == "config"
    assert report["proxy"]["url"] == "http://127.0.0.1:7890"
    assert "secret" not in report["proxy"]["url"]


# ---------------------------------------------------------------------------
# CLI and MCP surface
# ---------------------------------------------------------------------------


def test_cli_exposes_the_new_actions_and_switches() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    for token in ("find", "feed", "--site", "--probe", "--proxy"):
        assert token in result.stdout


def test_mcp_registers_find_and_feed() -> None:
    names = [tool["name"] for tool in mcp_server._TOOLS]
    assert "web_find" in names and "web_feed" in names
    doctor = next(tool for tool in mcp_server._TOOLS if tool["name"] == "web_doctor")
    assert "probe" in doctor["inputSchema"]["properties"]


def test_mcp_find_requires_site_and_query() -> None:
    with pytest.raises(ValueError):
        mcp_server._tool_find({"query": "示例"})
    with pytest.raises(ValueError):
        mcp_server._tool_find({"site": "example.org"})
