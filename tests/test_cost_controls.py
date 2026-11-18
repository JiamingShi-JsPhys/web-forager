"""Cost controls: the search cache and the compact MCP payload."""

from __future__ import annotations

from typing import Any

from scripts import engine
import mcp_server


def test_repeated_search_is_served_from_the_cache(monkeypatch, tmp_path: object) -> None:
    calls: list[str] = []

    def fake_search_one(
        name: str, query: str, config: Any, limit: int, fetcher: Any, pages: int = 1
    ) -> list[dict[str, str]]:
        calls.append(name)
        return [
            {
                "title": "q result",
                "url": "https://example.org/a",
                "snippet": "snippet",
                "source": name,
            }
        ]

    monkeypatch.setattr(engine, "_search_one", fake_search_one)
    config = engine.FetchConfig(
        delay=0.0, timeout=5.0, max_chars=0, render="never",
        cache=True, cache_dir=str(tmp_path) + "/cache",  # type: ignore[operator]
    )
    first = engine.search("q", config)
    after_first = len(calls)
    second = engine.search("q", config)

    assert first and second
    assert [item["url"] for item in first] == [item["url"] for item in second]
    assert len(calls) == after_first, "the second search should not touch an engine"


def test_a_different_query_is_not_served_the_cached_list(monkeypatch, tmp_path: object) -> None:
    calls: list[str] = []

    def fake_search_one(
        name: str, query: str, config: Any, limit: int, fetcher: Any, pages: int = 1
    ) -> list[dict[str, str]]:
        calls.append(query)
        return [{"title": query, "url": f"https://example.org/{len(calls)}", "snippet": "", "source": name}]

    monkeypatch.setattr(engine, "_search_one", fake_search_one)
    config = engine.FetchConfig(
        delay=0.0, timeout=5.0, max_chars=0, render="never",
        cache=True, cache_dir=str(tmp_path) + "/cache",  # type: ignore[operator]
    )
    engine.search("first", config)
    before = len(calls)
    engine.search("second", config)
    assert len(calls) > before


def test_compact_payload_drops_the_engine_report_and_long_snippets() -> None:
    payload = {
        "search_results": [
            {
                "title": "A page",
                "url": "https://example.org/a",
                "snippet": "x" * 500,
                "relevance": True,
            }
        ],
        "search_quality": {"returned": 1, "relevant": 1, "engines_answered": ["360"], "ephemeral": 0},
        "engine_report": [{"engine": "360", "ok": True, "results": 1}],
    }
    compact = mcp_server._compact_search_payload(payload)

    assert "engine_report" not in compact
    assert compact["search_quality"] == {
        "returned": 1,
        "relevant": 1,
        "engines_answered": ["360"],
        "cache_hit": False,
        "parser_drift": [],
        "risk": {},
        "evidence": {},
        "qa_dump": None,
        "official_backfill": None,
    }
    result = compact["search_results"][0]
    assert len(result["snippet"]) == 160
    assert result["domain"] == "example.org"
