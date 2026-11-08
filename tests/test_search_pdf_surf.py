"""Search backends, PDF extraction, link discovery and surf sessions."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from scripts import engine, pdf

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


# ---------------------------------------------------------------------------
# Search backends
# ---------------------------------------------------------------------------


def test_parse_360_filters_internal_hosts_and_duplicates() -> None:
    html = (FIXTURES / "search_360.html").read_text(encoding="utf-8")
    results = engine.parse_360_html(html, limit=8)
    urls = [item["url"] for item in results]
    assert urls == [
        "https://example.org/python-tutorial",
        "https://docs.python.org/3/tutorial/",
    ]
    assert all("so.com" not in url for url in urls)
    assert results[0]["source"] == "360"
    assert "入门" in results[0]["snippet"]


def test_merge_search_results_ranks_by_query_coverage() -> None:
    groups = [
        (
            "360",
            [
                {"title": "unrelated", "url": "https://a.example/", "snippet": ""},
                {"title": "Python 教程", "url": "https://b.example/", "snippet": ""},
            ],
        ),
        (
            "bing",
            [
                {"title": "Python 教程 official", "url": "https://c.example/", "snippet": ""},
                {"title": "other", "url": "https://d.example/", "snippet": ""},
            ],
        ),
    ]
    merged = engine.merge_search_results(groups, "Python 教程", limit=8)
    assert merged[0]["url"] == "https://b.example/"
    assert {item["source"] for item in merged} == {"360", "bing"}
    assert engine.dedupe_results(
        [{"url": "https://x/"}, {"url": "https://x/"}, {"url": "https://y/"}]
    ) == [{"url": "https://x/"}, {"url": "https://y/"}]


def test_parse_sogou_skips_hintbox_and_keeps_wrapped_links() -> None:
    html = (FIXTURES / "search_sogou.html").read_text(encoding="utf-8")
    results = engine.parse_sogou_html(html, limit=8)
    assert len(results) == 2
    assert results[0]["url"].startswith("https://www.sogou.com/link?url=")
    assert all("hint" not in item["url"] for item in results)
    assert results[1]["snippet"] == "Python 标准库 文档。"


def test_sogou_antispider_detection() -> None:
    assert engine.is_sogou_blocked("<html><body>请输入验证码</body></html>")
    assert engine.is_sogou_blocked("<div class='antispider'>blocked</div>")
    assert not engine.is_sogou_blocked("<div class='vrwrap'>normal results</div>")


def test_sogou_link_wrapper_is_resolved(site: str) -> None:
    html = (FIXTURES / "search_sogou.html").read_text(encoding="utf-8")
    results = engine.parse_sogou_html(html, base=site, limit=8)
    config = engine.FetchConfig(delay=0)
    fetcher = engine.HttpFetcher(config)
    try:
        resolved = engine.resolve_sogou_results(results, fetcher, limit=1)
    finally:
        fetcher.close()
    assert resolved[0]["url"] == f"{site}/surf/two.html"


def test_engine_choices_exposed_on_cli() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    for name in ("auto", "all", "360", "bing", "sogou", "duckduckgo"):
        assert name in result.stdout


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def test_pdf_extract_and_markdown() -> None:
    extracted = pdf.extract((FIXTURES / "sample.pdf").read_bytes())
    assert extracted["page_count"] == 1
    assert "Hello web-forager PDF" in extracted["text"]
    assert extracted["metadata"]["title"] == "Sample PDF"
    markdown = pdf.to_markdown(extracted, url="https://example.org/paper.pdf")
    assert markdown.startswith("# Sample PDF")
    assert "页数：1" in markdown
    metadata = pdf.to_metadata(extracted)
    assert metadata["authors"] == ["web-forager tests"]
    assert metadata["og_type"] == "pdf"


def test_pdf_unavailable_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "pypdf", None)
    with pytest.raises(pdf.PdfUnavailable) as info:
        pdf.extract((FIXTURES / "sample.pdf").read_bytes())
    assert "pip install pypdf" in str(info.value)


def test_fetch_page_extracts_pdf(site: str) -> None:
    page = engine.fetch_page(f"{site}/sample.pdf", engine.FetchConfig(delay=0))
    assert page["content_type"] == "application/pdf"
    assert "Hello web-forager PDF" in page["markdown"]
    assert any("PDF text extracted" in warning for warning in page["warnings"])


def test_cli_clean_pdf_input() -> None:
    result = run_cli(
        "--action", "clean",
        "--input", str(FIXTURES / "sample.pdf"),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["action"] == "clean"
    assert payload["content_type"] == "application/pdf"
    assert payload["page_count"] == 1
    assert "Hello web-forager PDF" in payload["markdown"]


@pytest.mark.skipif(importlib.util.find_spec("pypdf") is None, reason="pypdf not installed")
def test_cli_fetch_pdf_url(site: str) -> None:
    result = run_cli(
        "--action", "fetch",
        "--url", f"{site}/sample.pdf",
        "--delay", "0",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["results"][0]["content_type"] == "application/pdf"
    assert "Hello web-forager PDF" in payload["markdown"]


# ---------------------------------------------------------------------------
# Link discovery, surf and sessions
# ---------------------------------------------------------------------------


def test_extract_links_scores_and_filters() -> None:
    html = (FIXTURES / "surf_start.html").read_text(encoding="utf-8")
    links = engine.extract_links(
        html, "https://example.org/surf/index.html", query="Python 教程", same_site=True
    )
    assert all("example.org" in link["url"] for link in links)
    assert links[0]["score"] > 0
    # robots.txt is enforced by the fetcher, not by link discovery: /private/ is
    # still discovered here and then rejected during the surf walk.
    assert any("private" in link["url"] for link in links)


def test_surf_walks_one_level(site: str) -> None:
    config = engine.FetchConfig(delay=0, max_pages=4, max_links=10, follow="same-site")
    payload = engine.surf_web(
        f"{site}/surf/index.html", config, depth=1, max_pages=4
    )
    urls = [page["url"] for page in payload["pages"]]
    assert f"{site}/surf/one.html" in urls
    assert f"{site}/surf/two.html" in urls
    assert not any("example.org/external" in url for url in urls)
    assert any("error" in page and "private" in page["url"] for page in payload["pages"])
    assert len(payload["trail"]) == len(payload["pages"])


def test_surf_depth_two_reaches_grandchild(site: str) -> None:
    config = engine.FetchConfig(delay=0, max_pages=6, max_links=10, follow="same-site")
    payload = engine.surf_web(
        f"{site}/surf/index.html", config, depth=2, max_pages=6
    )
    urls = [page["url"] for page in payload["pages"]]
    assert f"{site}/surf/three.html" in urls
    levels = {entry["url"]: entry["level"] for entry in payload["trail"]}
    assert levels[f"{site}/surf/three.html"] == 2


def test_surf_session_resumes(site: str) -> None:
    name = f"pytest-surf-{uuid.uuid4().hex[:8]}"
    config = engine.FetchConfig(delay=0, max_pages=2, max_links=10, follow="same-site")
    try:
        first = engine.surf_web(f"{site}/surf/index.html", config, depth=1, session=name)
        assert len(first["pages"]) == 2
        assert engine.session_path(name).is_file()

        second = engine.surf_web(f"{site}/surf/index.html", config, depth=1, session=name)
        assert second["pages"] == []
        assert f"{site}/surf/index.html" in second["visited"]
        assert len(second["trail"]) >= len(first["trail"])
    finally:
        engine.session_path(name).unlink(missing_ok=True)


def test_cli_surf_and_agent_envelope(site: str) -> None:
    result = run_cli(
        "--action", "surf",
        "--url", f"{site}/surf/index.html",
        "--depth", "1",
        "--max-pages", "3",
        "--delay", "0",
        "--agent",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    data = payload["data"]
    assert data["action"] == "surf"
    assert data["mode"] == "surf"
    assert len(data["pages"]) == 3
    assert data["trail"]


def test_agent_error_envelope() -> None:
    result = run_cli("--action", "fetch", "--agent")
    assert result.returncode == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_argument"
    assert payload["error"]["hint"] == ""
    assert "Traceback" not in result.stderr


def test_agent_success_envelope_for_clean() -> None:
    result = run_cli(
        "--action", "clean",
        "--input", str(FIXTURES / "article.html"),
        "--agent",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["data"]["action"] == "clean"
    assert payload["data"]["markdown"]


# ---------------------------------------------------------------------------
# Language-aware routing and result hygiene (1.0.2)
# ---------------------------------------------------------------------------


def _fake_engine(monkeypatch, failing: set[str] | None = None):
    calls: list[str] = []
    failing = failing or set()

    def fake_search_one(name, query, config, limit, fetcher, pages=1):
        calls.append(name)
        if name in failing:
            raise engine.FetchError(f"{name} returned a verification page")
        return [
            {
                "title": f"{name} 结果",
                "url": f"https://{name}.example/result",
                "snippet": "",
                "source": name,
            }
        ]

    monkeypatch.setattr(engine, "_search_one", fake_search_one)
    return calls


def test_auto_routes_chinese_queries_away_from_bing(monkeypatch) -> None:
    calls = _fake_engine(monkeypatch)
    config = engine.FetchConfig(delay=0.0)
    fetcher = engine.HttpFetcher(config)
    try:
        engine.search("杭州西湖一日游攻略", config, fetcher=fetcher)
    finally:
        fetcher.close()
    assert calls == ["360", "sogou"]
    assert "bing" not in calls


def test_auto_keeps_bing_for_latin_queries(monkeypatch) -> None:
    calls = _fake_engine(monkeypatch)
    config = engine.FetchConfig(delay=0.0)
    fetcher = engine.HttpFetcher(config)
    try:
        engine.search("reinforcement learning", config, fetcher=fetcher)
    finally:
        fetcher.close()
    assert calls == ["360", "bing"]


def test_chinese_query_still_falls_back_to_bing(monkeypatch) -> None:
    calls = _fake_engine(monkeypatch, failing={"360", "sogou"})
    config = engine.FetchConfig(delay=0.0)
    fetcher = engine.HttpFetcher(config)
    try:
        results = engine.search("杭州西湖一日游攻略", config, fetcher=fetcher)
    finally:
        fetcher.close()
    assert calls == ["360", "sogou", "bing"]
    assert results and results[0]["source"] == "bing"


def test_dedupe_drops_garbled_titles() -> None:
    items = [
        {"title": "\ufffd\ufffd\ufffd\ufffd", "url": "https://a.example/"},
        {"title": "正常标题", "url": "https://b.example/"},
        {"title": "???", "url": "https://c.example/"},
        {"url": "https://d.example/"},
    ]
    kept = engine.dedupe_results(items, limit=8)
    assert [item["url"] for item in kept] == ["https://b.example/", "https://d.example/"]


def test_prefers_chinese_engines_threshold() -> None:
    assert engine.prefers_chinese_engines("杭州西湖一日游攻略") is True
    assert engine.prefers_chinese_engines("Python 教程") is False
    assert engine.prefers_chinese_engines("reinforcement learning") is False
    assert engine.prefers_chinese_engines("") is False
