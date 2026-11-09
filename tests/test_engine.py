"""Unit tests for the parsing and extraction layer (no network)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts import engine

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# URLs
# ---------------------------------------------------------------------------


def test_normalize_url_adds_scheme_and_strips_fragment() -> None:
    assert engine.normalize_url("example.com/page#section") == "https://example.com/page"
    assert engine.normalize_url("https://example.com:443/a?b=1#x") == "https://example.com/a?b=1"
    assert engine.normalize_url("/a", base="https://example.com/b/c") == "https://example.com/a"


def test_normalize_url_rejects_dangerous_schemes() -> None:
    for bad in ("javascript:alert(1)", "file:///etc/passwd", "data:text/html,hi"):
        with pytest.raises(engine.InvalidURLError):
            engine.normalize_url(bad)


def test_absolute_url_requires_base_for_relative_links() -> None:
    assert engine.absolute_url("/a", None) == ""
    assert engine.absolute_url("/a", "https://example.org/x") == "https://example.org/a"
    assert engine.absolute_url("https://example.org/a", None) == "https://example.org/a"


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------


def test_robots_allow_and_disallow() -> None:
    policy = engine.parse_robots(
        "User-agent: *\nDisallow: /private/\nAllow: /private/public/\n",
        "WebForager/0.1",
    )
    assert policy.allowed("https://example.org/index.html") is True
    assert policy.allowed("https://example.org/private/secret") is False
    assert policy.allowed("https://example.org/private/public/ok") is True


def test_robots_wildcard_and_end_anchor() -> None:
    policy = engine.parse_robots("User-agent: *\nDisallow: /*.pdf$\n", "WebForager/0.1")
    assert policy.allowed("https://example.org/paper.pdf") is False
    assert policy.allowed("https://example.org/docs/paper.pdf") is False
    assert policy.allowed("https://example.org/docs/paper.pdf?download=1") is True
    assert policy.allowed("https://example.org/docs/paper.html") is True


def test_robots_specific_user_agent_wins() -> None:
    text = (
        "User-agent: *\nDisallow: /\n\n"
        "User-agent: WebForager\nAllow: /\n"
    )
    assert engine.parse_robots(text, "WebForager/0.1").allowed("https://example.org/a") is True
    assert engine.parse_robots(text, "OtherBot/1.0").allowed("https://example.org/a") is False


def test_robots_empty_disallow_allows_all() -> None:
    policy = engine.parse_robots("User-agent: *\nDisallow:\n", "WebForager/0.1")
    assert policy.allowed("https://example.org/anything") is True


def test_robots_ties_favour_allow() -> None:
    policy = engine.parse_robots("User-agent: *\nDisallow: /a\nAllow: /a\n", "WebForager/0.1")
    assert policy.allowed("https://example.org/a") is True


def test_robots_crawl_delay_is_parsed() -> None:
    policy = engine.parse_robots("User-agent: *\nCrawl-delay: 2.5\n", "WebForager/0.1")
    assert policy.crawl_delay == 2.5


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_metadata_from_citation_tags() -> None:
    metadata = engine.extract_metadata(fixture("article.html"), url="https://example.org/articles/polite-crawling")
    assert metadata["title"] == "Polite Crawling for Research"
    assert metadata["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert metadata["journal"] == "Journal of Ethical Web Research"
    assert metadata["published"] == "2025-03-14"
    assert metadata["doi"] == "10.1234/jewr.2025.0042"
    assert metadata["volume"] == "12"
    assert metadata["issue"] == "3"
    assert metadata["first_page"] == "101"
    assert metadata["last_page"] == "118"
    assert metadata["keywords"] == ["web crawling", "robots.txt", "research ethics"]
    assert metadata["language"] == "en"
    assert metadata["site_name"] == "Example Journal"
    assert metadata["canonical_url"] == "https://example.org/articles/polite-crawling"


def test_metadata_jsonld_fallback() -> None:
    html = """<html><head>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@graph":[
      {"@type":"ScholarlyArticle","headline":"Graph paper",
       "author":[{"@type":"Person","name":"Grace Hopper"}],
       "datePublished":"2024-01-02","description":"From @graph",
       "isPartOf":{"name":"Graph Journal"}}
    ]}
    </script></head><body></body></html>"""
    metadata = engine.extract_metadata(html)
    assert metadata["title"] == "Graph paper"
    assert metadata["authors"] == ["Grace Hopper"]
    assert metadata["journal"] == "Graph Journal"
    assert metadata["abstract"] == "From @graph"


def test_doi_is_cleaned_of_trailing_punctuation() -> None:
    html = '<html><head><meta name="citation_doi" content="10.1000/xyz.123)."></head></html>'
    assert engine.extract_metadata(html)["doi"] == "10.1000/xyz.123"


# ---------------------------------------------------------------------------
# Tables and Markdown
# ---------------------------------------------------------------------------


def test_tables_are_extracted_as_rows_and_markdown() -> None:
    tables = engine.extract_tables(fixture("table.html"))
    assert len(tables) == 1
    table = tables[0]
    assert table["caption"] == "样本测量结果"
    assert table["headers"] == ["样本", "温度 / K", "压力 / kPa"]
    assert table["rows"][0] == ["A", "298", "101.3"]
    assert "| --- |" in table["markdown"]


def test_bs4_markdown_fallback_preserves_structure() -> None:
    markdown = engine._bs4_to_markdown(
        fixture("article.html"),
        url="https://example.org/articles/polite-crawling",
        include_tables=True,
        keep_links=True,
        include_images=False,
    )
    assert "# Polite Crawling for Research" in markdown
    assert "## Method" in markdown
    assert "- Respect crawl-delay." in markdown
    assert "> Politeness is a research method" in markdown
    assert "```" in markdown
    assert "| Project | Requests/min | robots.txt |" in markdown
    assert "[ethical crawling practices](https://example.org/ethics)" in markdown


def test_html_to_markdown_returns_text() -> None:
    markdown = engine.html_to_markdown(fixture("article.html"), url="https://example.org/")
    assert "Polite Crawling for Research" in markdown
    assert "robots.txt" in markdown.lower()


def test_looks_dynamic_detects_spa_shell() -> None:
    spa = (
        '<html><head><title>App</title></head><body><div id="root"></div>'
        '<script src="a.js"></script><script src="b.js"></script><script src="c.js"></script>'
        "</body></html>"
    )
    assert engine.looks_dynamic(spa) is True
    assert engine.looks_dynamic(fixture("article.html")) is False


# ---------------------------------------------------------------------------
# Search parsers
# ---------------------------------------------------------------------------


def test_parse_bing_rss() -> None:
    results = engine.parse_bing_rss(fixture("bing.xml"), limit=10)
    assert [item["url"] for item in results] == [
        "https://example.org/a",
        "https://example.org/b",
        "https://example.org/a",
    ]
    assert results[0]["title"] == "Robots Exclusion Protocol"
    assert results[0]["source"] == "bing"


def test_parse_bing_rss_refuses_doctype() -> None:
    payload = '<!DOCTYPE x [<!ENTITY a "b">]><rss><channel><item><link>https://x/a</link></item></channel></rss>'
    assert engine.parse_bing_rss(payload) == []


def test_parse_bing_html_unwraps_redirect() -> None:
    results = engine.parse_bing_html(fixture("bing.html"), limit=10)
    assert [item["url"] for item in results] == ["https://example.org/a", "https://example.org/b"]


def test_parse_ddg_html_unwraps_redirect() -> None:
    results = engine.parse_ddg_html(fixture("ddg.html"), limit=10)
    assert [item["url"] for item in results] == ["https://example.org/a", "https://example.org/b"]
    assert results[0]["source"] == "duckduckgo"


def test_dedupe_results_preserves_order() -> None:
    results = [
        {"url": "https://a", "title": "A"},
        {"url": "https://b", "title": "B"},
        {"url": "https://a", "title": "A again"},
    ]
    deduped = engine.dedupe_results(results, limit=5)
    assert [item["url"] for item in deduped] == ["https://a", "https://b"]


# ---------------------------------------------------------------------------
# Compliance constants
# ---------------------------------------------------------------------------


def test_disclaimer_text_is_exact() -> None:
    expected = (
        "本插件仅供学习与信息收集使用。使用者需遵守目标网站的 Terms of Service 及相关版权法律。"
        "禁止用于抓取个人隐私数据或进行恶意并发攻击。"
    )
    assert engine.DISCLAIMER == expected


def test_default_user_agent_is_identifiable() -> None:
    agent = engine.DEFAULT_USER_AGENT
    assert agent.startswith("WebForager/")
    assert f"WebForager/{engine.__version__}" in agent
    assert "Information Gathering" in agent
    assert "github.com/JiamingShi-JsPhys/web-forager" in agent
