"""How a search fills its readable pages and schedules its engines."""

from __future__ import annotations

import time
from typing import Any

from scripts import engine


def local_config(**overrides: Any) -> engine.FetchConfig:
    values: dict[str, Any] = dict(delay=0.0, timeout=10.0, max_chars=0, render="never", verbose=False)
    values.update(overrides)
    return engine.FetchConfig(**values)  # type: ignore[arg-type]


def test_fetch_by_query_keeps_looking_after_a_robots_denial(site: str, monkeypatch) -> None:
    results = [
        {
            "title": "private",
            "url": f"{site}/private/secret.html",
            "snippet": "",
            "source": "360",
        },
        {
            "title": "index",
            "url": f"{site}/index.html",
            "snippet": "",
            "source": "360",
        },
    ]
    monkeypatch.setattr(engine, "search", lambda *args, **kwargs: results)

    payload = engine.fetch_by_query("example", local_config(max_pages=1))

    assert len(payload["pages"]) == 1
    assert payload["pages"][0]["url"].endswith("/index.html")
    assert payload["pages_attempted"] == 2
    assert payload["skipped"][0]["code"] == "robots_denied"
    assert any("skipped while filling" in warning for warning in payload["warnings"])
    assert any("Do not silently switch" in warning for warning in payload["warnings"])


def test_engines_overlap_when_no_external_fetcher_is_injected(monkeypatch) -> None:
    def slow_engine(name, query, config, limit, fetcher, pages=1):
        time.sleep(0.5)
        return [
            {"title": f"{name}-{index}", "url": f"https://{name}.example/{index}", "snippet": "", "source": name}
            for index in range(3)
        ]

    monkeypatch.setattr(engine, "_search_one", slow_engine)
    started = time.monotonic()
    results = engine.search("parallel engines test", local_config(parallel_engines=True))
    elapsed = time.monotonic() - started

    assert len(results) >= 3
    # Two engines at 0.5 s each: serial would be 1.0 s or more.
    assert elapsed < 0.9


def test_serial_engines_add_up_when_requested(monkeypatch) -> None:
    def slow_engine(name, query, config, limit, fetcher, pages=1):
        time.sleep(0.2)
        return [
            {"title": f"{name}-{index}", "url": f"https://{name}.example/{index}", "snippet": "", "source": name}
            for index in range(3)
        ]

    monkeypatch.setattr(engine, "_search_one", slow_engine)
    started = time.monotonic()
    engine.search("serial engines test", local_config(parallel_engines=False))
    elapsed = time.monotonic() - started

    # Two engines at 0.2 s each; even with timer jitter this stays above a
    # single engine's 0.2 s.
    assert elapsed >= 0.35


def test_latin_dictionary_page_is_dropped_when_it_matches_one_token() -> None:
    lookup = {
        "title": "reinforcement（英语单词）_百度百科",
        "url": "https://baike.baidu.com/item/reinforcement",
        "snippet": "",
    }
    assert engine.looks_like_dictionary_page(
        lookup, "reinforcement learning survey"
    )

    article = {
        "title": "Reinforcement learning - Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Reinforcement_learning",
        "snippet": "A survey of reinforcement learning.",
    }
    assert not engine.looks_like_dictionary_page(
        article, "reinforcement learning survey"
    )


def test_all_denied_results_suggest_another_source(site: str, monkeypatch) -> None:
    results = [
        {
            "title": "private",
            "url": f"{site}/private/secret.html",
            "snippet": "",
            "source": "360",
        }
    ]
    monkeypatch.setattr(engine, "search", lambda *args, **kwargs: results)

    payload = engine.fetch_by_query("example", local_config(max_pages=2))

    assert payload["pages"] == []
    assert any("--action find" in warning for warning in payload["warnings"])
    assert any("--action feed" in warning for warning in payload["warnings"])
