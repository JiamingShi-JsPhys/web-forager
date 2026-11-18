"""MCP tool plumbing: the switches an agent can pass and the warnings it gets."""

from __future__ import annotations

import mcp_server
from scripts import engine


def test_config_never_lets_an_mcp_caller_relax_the_boundary() -> None:
    assert mcp_server._config({}).respect_robots is True
    assert mcp_server._config({"respect_robots": False}).respect_robots is True
    assert mcp_server._config({"robots_policy": "ignore"}).robots_policy == "respect"
    assert mcp_server._config({"input_gate": "off"}).input_gate == "mark"
    assert mcp_server._config({"proxy": "http://127.0.0.1:1"}).proxy == ""


def test_mcp_never_accepts_a_query_robots_override(monkeypatch) -> None:
    monkeypatch.delenv("WEB_FORAGER_QUERY_ROBOTS", raising=False)
    assert mcp_server._config({}).query_robots == "warn"
    assert mcp_server._config({"query_robots": "ignore"}).query_robots == "warn"


def test_mcp_robots_policy_is_an_operator_environment_choice(monkeypatch) -> None:
    monkeypatch.setenv("WEB_FORAGER_ROBOTS_POLICY", "warn")
    config = mcp_server._config({"robots_policy": "ignore"})
    assert config.robots_policy == "warn"
    assert config.respect_robots is True

    monkeypatch.setenv("WEB_FORAGER_ROBOTS_POLICY", "ignore")
    assert mcp_server._config({}).robots_policy == "ignore"

    monkeypatch.setenv("WEB_FORAGER_ROBOTS_POLICY", "not-a-policy")
    assert mcp_server._config({}).robots_policy == "respect"


def test_search_tool_keeps_max_pages_zero_from_becoming_one() -> None:
    # Zero means "results only, no page bodies"; the shared search path now
    # treats max_pages as readable pages, so it must not be floored to one.
    config = mcp_server._config({"max_pages": 0})
    assert config.max_pages == 0


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


def test_hard_call_budget_returns_a_terminal_payload(monkeypatch) -> None:
    import time

    monkeypatch.setattr(mcp_server, "_MAX_CALLS", 2)
    monkeypatch.setattr(
        mcp_server,
        "_SESSION_CALLS",
        {"fetch": 0, "search": 2, "find": 0, "surf": 0, "research": 0},
    )
    monkeypatch.setattr(mcp_server, "_LAST_CALL_AT", time.monotonic())
    payload = mcp_server._budget_stop("web_search")
    assert payload is not None
    assert payload["error"] == "call_budget_exhausted"
    assert payload["stop_recommended"] is True
    assert payload["calls_used"] == 2


def test_call_counters_reset_after_an_idle_gap(monkeypatch) -> None:
    monkeypatch.setattr(
        mcp_server,
        "_SESSION_CALLS",
        {"fetch": 9, "search": 9, "find": 0, "surf": 0, "research": 1},
    )
    monkeypatch.setattr(mcp_server, "_LAST_CALL_AT", 0.0)
    mcp_server._reset_if_idle()
    assert sum(mcp_server._SESSION_CALLS.values()) == 0


def test_no_answer_research_asks_the_agent_to_stop(monkeypatch) -> None:
    import time

    monkeypatch.setattr(mcp_server, "_NO_ANSWER", True)
    monkeypatch.setattr(
        mcp_server,
        "_SESSION_CALLS",
        {"fetch": 0, "search": 7, "find": 0, "surf": 0, "research": 1},
    )
    monkeypatch.setattr(mcp_server, "_LAST_CALL_AT", time.monotonic())
    guidance = mcp_server._call_guidance("search")
    assert "no answerable evidence" in guidance


def test_research_sets_an_intent_specific_call_budget(monkeypatch) -> None:
    import time

    def fake_research(*args, **kwargs):
        return {
            "query": "世界卫生组织总部在哪个城市",
            "intent": {"intent": "factual", "confidence": 0.8, "signals": []},
            "answerability": {"level": "low", "coverage": 0.2},
            "evidence": [{"url": "https://who.int/", "title": "WHO"}],
            "results": [],
        }

    monkeypatch.setattr(mcp_server.research, "research", fake_research)
    monkeypatch.setattr(
        mcp_server,
        "_SESSION_CALLS",
        {"fetch": 0, "search": 0, "find": 0, "surf": 0, "research": 0},
    )
    monkeypatch.setattr(mcp_server, "_MAX_CALLS", 20)
    monkeypatch.setattr(mcp_server, "_LAST_CALL_AT", time.monotonic())
    mcp_server._tool_research({"query": "世界卫生组织总部在哪个城市"})
    assert mcp_server._SESSION_BUDGET == 5
    mcp_server._SESSION_CALLS["research"] = 5
    payload = mcp_server._budget_stop("web_fetch")
    assert payload is not None
    assert payload["call_budget"] == 5
    assert payload["intent_budget"] is True


def test_new_research_question_resets_the_call_budget(monkeypatch) -> None:
    import time

    def fake_research(*args, **kwargs):
        return {
            "query": "新问题",
            "intent": {"intent": "general"},
            "answerability": {"level": "low"},
            "evidence": [{"url": "https://example.com/"}],
            "results": [],
        }

    monkeypatch.setattr(mcp_server.research, "research", fake_research)
    monkeypatch.setattr(
        mcp_server,
        "_SESSION_CALLS",
        {"fetch": 4, "search": 0, "find": 0, "surf": 0, "research": 1},
    )
    monkeypatch.setattr(mcp_server, "_LAST_RESEARCH_QUERY", "旧问题")
    monkeypatch.setattr(mcp_server, "_LAST_CALL_AT", time.monotonic())
    mcp_server._tool_research({"query": "新问题"})
    assert sum(mcp_server._SESSION_CALLS.values()) == 1


def test_mcp_never_inherits_the_private_address_opt_in(monkeypatch) -> None:
    monkeypatch.setenv("WEB_FORAGER_ALLOW_PRIVATE", "1")
    assert mcp_server._config({}).allow_private is False
