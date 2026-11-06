"""1.0 features: scholarly APIs, office documents, feeds, sitemaps, cache, MCP."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import mcp_server
from scripts import documents, engine, feeds, pdf, scholar, sitemap

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


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


class FakeFetcher:
    def __init__(self, html: str) -> None:
        self.html = html
        self.calls: list[str] = []

    def fetch(self, url: str, *, check_robots: bool = True) -> engine.HttpResponse:
        self.calls.append(url)
        return engine.HttpResponse(
            url=url,
            final_url=url,
            status=200,
            headers={},
            content=self.html.encode("utf-8"),
            text=self.html,
            encoding="utf-8",
            content_type="text/html",
        )


# ---------------------------------------------------------------------------
# Scholarly APIs
# ---------------------------------------------------------------------------


def test_parse_arxiv_records() -> None:
    records = scholar.parse_arxiv((FIXTURES / "arxiv.xml").read_text(encoding="utf-8"))
    assert len(records) == 2
    first = records[0]
    assert first["id"] == "2501.01234v1"
    assert first["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert first["doi"] == "10.1234/arxiv.2501.01234"
    assert first["pdf_url"].endswith("/pdf/2501.01234v1")
    assert first["keywords"] == ["cs.IR", "cs.AI"]
    assert "rate limiting" in first["abstract"]


def test_parse_crossref_records() -> None:
    payload = json.loads((FIXTURES / "crossref.json").read_text(encoding="utf-8"))
    records = scholar.parse_crossref(payload)
    assert len(records) == 2
    assert records[0]["title"] == "Polite Crawling for Research"
    assert records[0]["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert records[0]["published"] == "2025-03-14"
    assert records[0]["volume"] == "12"
    assert "polite crawling" in records[0]["abstract"]
    assert records[1]["authors"] == ["Grace Hopper"]


def test_parse_pubmed_records() -> None:
    search_payload = json.loads((FIXTURES / "pubmed_search.json").read_text(encoding="utf-8"))
    summary = json.loads((FIXTURES / "pubmed_summary.json").read_text(encoding="utf-8"))
    abstracts = scholar._pubmed_abstracts(
        (FIXTURES / "pubmed_efetch.xml").read_text(encoding="utf-8")
    )
    records = scholar.parse_pubmed(search_payload, summary, abstracts)
    assert len(records) == 2
    assert records[0]["id"] == "39000001"
    assert records[0]["doi"] == "10.1234/jbwr.2025.0042"
    assert "polite retrieval" in records[0]["abstract"]
    assert records[0]["url"].endswith("/39000001/")
    assert "Clinical sitemaps" in records[1]["abstract"]


def test_scholar_markdown_rendering() -> None:
    payload = {
        "source": "crossref",
        "query": "crawling",
        "count": 1,
        "results": scholar.parse_crossref(
            json.loads((FIXTURES / "crossref.json").read_text(encoding="utf-8"))
        )[:1],
    }
    markdown = scholar.to_markdown(payload)
    assert "# crossref: crawling" in markdown
    assert "**DOI:** 10.1234/jewr.2025.0042" in markdown


# ---------------------------------------------------------------------------
# Office documents and CSV
# ---------------------------------------------------------------------------


def test_document_detection_and_extraction() -> None:
    expectations = {
        "sample.docx": "docx",
        "sample.xlsx": "xlsx",
        "sample.epub": "epub",
        "table.csv": "csv",
    }
    for name, kind in expectations.items():
        data = (FIXTURES / name).read_bytes()
        assert documents.detect(data, url=name) == kind
        extracted = documents.extract(data, kind, url=name)
        assert extracted["kind"] == kind
        assert extracted["markdown"].strip()

    docx = documents.extract((FIXTURES / "sample.docx").read_bytes())
    assert "# Sample DOCX" in docx["markdown"]
    assert "# Introduction" in docx["markdown"]
    assert "- Respect robots.txt" in docx["markdown"]
    assert docx["tables"][0]["headers"] == ["Name", "Value"]
    assert documents.to_metadata(docx)["authors"] == ["Ada Lovelace"]

    xlsx = documents.extract((FIXTURES / "sample.xlsx").read_bytes())
    assert xlsx["tables"][0]["rows"] == [["alpha", "42"], ["beta", "7"]]

    epub = documents.extract((FIXTURES / "sample.epub").read_bytes())
    assert "# Chapter One" in epub["markdown"]
    assert "# Chapter Two" in epub["markdown"]
    assert "Sitemap discovery" in epub["markdown"]
    assert epub["metadata"]["authors"] == ["Ada Lovelace"]


def test_fetch_docx_and_feed_from_local_site(site: str) -> None:
    docx_page = engine.fetch_page(f"{site}/sample.docx", engine.FetchConfig(delay=0))
    assert docx_page["document_kind"] == "docx"
    assert "# Sample DOCX" in docx_page["markdown"]

    feed_page = engine.fetch_page(f"{site}/rss.xml", engine.FetchConfig(delay=0))
    assert feed_page["feed_format"] == "rss"
    assert "Robots.txt in practice" in feed_page["markdown"]
    assert feed_page["metadata"]["title"] == "Web Research Notes"

    # Some servers label XML as application/octet-stream; magic/root detection
    # must still recognise the feed.
    octet_feed = engine.fetch_page(f"{site}/feed.bin", engine.FetchConfig(delay=0))
    assert octet_feed["content_type"] == "application/octet-stream"
    assert octet_feed["feed_format"] == "rss"


def test_feed_parsing_and_detection() -> None:
    rss = feeds.extract((FIXTURES / "rss.xml").read_text(encoding="utf-8"))
    assert rss["format"] == "rss"
    assert rss["count"] == 2
    assert rss["items"][0]["authors"] == ["Ada Lovelace"]
    assert rss["items"][0]["url"] == "https://example.org/blog/robots"

    atom = feeds.extract((FIXTURES / "atom.xml").read_text(encoding="utf-8"))
    assert atom["format"] == "atom"
    assert atom["items"][0]["title"] == "Chunking long pages"
    assert atom["items"][0]["authors"] == ["Grace Hopper"]

    assert not feeds.is_feed((FIXTURES / "sitemap.xml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Sitemaps
# ---------------------------------------------------------------------------


def test_parse_sitemap_urlset_and_index() -> None:
    urlset = sitemap.parse_sitemap((FIXTURES / "sitemap.xml").read_text(encoding="utf-8"))
    assert len(urlset["urls"]) == 3
    assert urlset["urls"][0]["lastmod"] == "2025-02-01"
    assert urlset["urls"][0]["priority"] == "1.0"

    index = sitemap.parse_sitemap((FIXTURES / "sitemap_index.xml").read_text(encoding="utf-8"))
    assert [entry["url"] for entry in index["sitemaps"]] == [
        "https://example.org/sitemap-posts.xml",
        "https://example.org/sitemap-pages.xml",
    ]


def test_sitemap_discovery_reads_robots_and_files(site: str) -> None:
    payload = sitemap.discover(site, engine.FetchConfig(delay=0))
    assert payload["count"] == 3
    assert any(item.endswith("/static_sitemap.xml") for item in payload["sitemaps_read"])
    assert payload["urls"][0]["url"] == "https://example.org/"
    markdown = sitemap.to_markdown(payload)
    assert "# Sitemap:" in markdown


# ---------------------------------------------------------------------------
# Cache, pagination, chunking
# ---------------------------------------------------------------------------


def test_cache_serves_second_fetch(site: str, tmp_path: Path) -> None:
    config = engine.FetchConfig(delay=0, cache=True, cache_dir=str(tmp_path), cache_ttl=60)
    first = engine.fetch_page(f"{site}/index.html", config)
    assert first["cached"] is False
    cache_files = list(tmp_path.glob("*.bin"))
    assert len(cache_files) == 1
    assert b"Researchers should identify" in cache_files[0].read_bytes()

    second = engine.fetch_page(f"{site}/index.html", config)
    assert second["cached"] is True
    assert second["markdown"] == first["markdown"]


def test_search_pagination_requests_each_page() -> None:
    html = (FIXTURES / "search_360.html").read_text(encoding="utf-8")
    fetcher = FakeFetcher(html)
    config = engine.FetchConfig(search_pages=2, delay=0)
    results = engine._search_one("360", "Python 教程", config, 8, fetcher, pages=2)
    assert len(fetcher.calls) == 2
    assert "pn=1" in fetcher.calls[0]
    assert "pn=2" in fetcher.calls[1]
    assert len(results) == 2  # duplicates across pages are removed


def test_chunk_markdown_respects_headings_and_size() -> None:
    markdown = "# Alpha\n\n" + ("paragraph one. " * 20) + "\n\n# Beta\n\n" + ("paragraph two. " * 20)
    chunks = engine.chunk_markdown(markdown, size=120)
    assert len(chunks) >= 2
    assert any(chunk["heading"] == "Alpha" for chunk in chunks)
    assert any(chunk["heading"] == "Beta" for chunk in chunks)
    assert all(chunk["chars"] <= 140 for chunk in chunks)
    assert [chunk["index"] for chunk in chunks] == list(range(1, len(chunks) + 1))


def test_clean_docx_cli_emits_chunks() -> None:
    result = run_cli(
        "--action", "clean",
        "--input", str(FIXTURES / "sample.docx"),
        "--chunk-size", "60",
        "--agent",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    data = payload["data"]
    assert data["content_type"] == "docx"
    assert data["chunks"]
    assert data["metadata"]["authors"] == ["Ada Lovelace"]


def test_pdf_still_works_after_document_branch() -> None:
    assert pdf.is_pdf((FIXTURES / "sample.pdf").read_bytes())
    result = run_cli("--action", "clean", "--input", str(FIXTURES / "sample.pdf"))
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["content_type"] == "application/pdf"


def test_repeated_extraction_keeps_the_opening_paragraph() -> None:
    """Regression: trafilatura's global dedup cache used to eat sentences."""

    html = (FIXTURES / "article.html").read_text(encoding="utf-8")
    for _ in range(6):
        markdown = engine.html_to_markdown(html, url="https://example.org/article")
        assert "Researchers should identify" in markdown


def test_parse_xml_allows_bare_doctype_but_rejects_entities() -> None:
    pubMed = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle//EN" '
        '"https://dtd.nlm.nih.gov/ncbi/pubmed/out/pubmed_250101.dtd">'
        "<PubmedArticleSet><PMID>1</PMID></PubmedArticleSet>"
    )
    root = engine.parse_xml(pubMed)
    assert root.findtext("PMID") == "1"

    with pytest.raises(engine.FetchError):
        engine.parse_xml('<!DOCTYPE x [<!ENTITY e "boom">]><x>&e;</x>')
    with pytest.raises(engine.FetchError):
        engine.parse_xml('<!ENTITY e "boom"><x>&e;</x>')


# ---------------------------------------------------------------------------
# MCP
# ---------------------------------------------------------------------------


def test_mcp_initialize_and_tools_list() -> None:
    init = mcp_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )
    assert init["result"]["serverInfo"]["name"] == "web-forager"
    assert init["result"]["capabilities"]["tools"] == {}

    listed = mcp_server.handle_request(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    names = {tool["name"] for tool in listed["result"]["tools"]}
    assert names == {
        "web_fetch",
        "web_search",
        "web_surf",
        "web_scholar",
        "web_map",
        "web_bilibili",
        "web_clean",
    }


def test_mcp_clean_tool_and_error_shape() -> None:
    response = mcp_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "web_clean",
                "arguments": {"path": str(FIXTURES / "article.html")},
            },
        }
    )
    content = json.loads(response["result"]["content"][0]["text"])
    assert content["action"] == "clean"
    assert "Polite Crawling" in content["markdown"]

    missing = mcp_server.handle_request(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "web_clean", "arguments": {"path": "does-not-exist.html"}},
        }
    )
    assert missing["result"]["isError"] is True
    error = json.loads(missing["result"]["content"][0]["text"])
    assert error["ok"] is False
    assert error["error"]["code"] == "ValueError"
