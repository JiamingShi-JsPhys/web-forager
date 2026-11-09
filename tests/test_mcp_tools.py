"""MCP tool plumbing: the switches an agent can pass and the warnings it gets."""

from __future__ import annotations

import mcp_server
from scripts import engine


def test_config_checks_robots_by_default() -> None:
    assert mcp_server._config({}).respect_robots is True
    assert mcp_server._config({"respect_robots": False}).respect_robots is False


def test_search_tool_keeps_max_pages_zero_from_becoming_one() -> None:
    # _config floors max_pages for the fetch path, but web_search reads the raw
    # argument: zero must mean "results only, no page bodies".
    config = mcp_server._config({"max_pages": 0})
    assert config.max_pages >= 1


def test_search_tool_warns_when_results_ignore_the_query(monkeypatch) -> None:
    monkeypatch.setattr(
        engine,
        "search",
        lambda *args, **kwargs: [
            {
                "title": "词典释义",
                "url": "https://dict.example/x",
                "snippet": "",
                "source": "360",
            }
        ],
    )
    payload = mcp_server._tool_search({"query": "张三", "max_pages": 0})
    assert payload["pages"] == []
    assert payload["warnings"]
    assert "unrelated" in payload["warnings"][0]


def test_search_tool_warns_when_nothing_comes_back(monkeypatch) -> None:
    monkeypatch.setattr(engine, "search", lambda *args, **kwargs: [])
    payload = mcp_server._tool_search({"query": "张三", "max_pages": 0})
    assert payload["warnings"]
    assert "no results" in payload["warnings"][0]
