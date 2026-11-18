"""Politeness and parallel-batch behaviour added for 1.3.2."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from scripts import engine


def local_config(**overrides: Any) -> engine.FetchConfig:
    values: dict[str, Any] = dict(delay=0.0, timeout=10.0, max_chars=0, render="never", verbose=False)
    values.update(overrides)
    return engine.FetchConfig(**values)  # type: ignore[arg-type]


def test_a_throttled_origin_backs_off_and_recovers() -> None:
    limiter = engine.RateLimiter(1.0)
    url = "https://example.org/a"
    assert limiter.delay_for(url) == pytest.approx(1.0)

    limiter.penalize(url)
    assert limiter.delay_for(url) == pytest.approx(2.0)
    limiter.penalize(url)
    assert limiter.delay_for(url) == pytest.approx(4.0)

    limiter.relax(url)
    limiter.relax(url)
    assert limiter.delay_for(url) == pytest.approx(1.0)
    # The penalty is per origin, never global.
    assert limiter.delay_for("https://other.example/a") == pytest.approx(1.0)


def test_crawl_delay_applies_to_every_later_request_on_that_origin() -> None:
    limiter = engine.RateLimiter(1.0)
    limiter.remember("https://slow.example/a", 5.0)

    assert limiter.delay_for("https://slow.example/b") == pytest.approx(5.0)
    assert limiter.delay_for("https://fast.example/a") == pytest.approx(1.0)


def test_batch_fetch_runs_distinct_origins_at_the_same_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = [
        {"title": f"p{i}", "url": f"https://h{i}.example/page", "snippet": "s"}
        for i in range(3)
    ]
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_fetch_page(url: str, config: Any, fetcher: Any = None, **_: Any) -> dict[str, Any]:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.15)
        with lock:
            active -= 1
        return {
            "url": url,
            "status": 200,
            "markdown": "# page\n\n" + "body " * 20,
            "tables": [],
            "warnings": [],
            "cached": False,
        }

    monkeypatch.setattr(engine, "search", lambda *args, **kwargs: results)
    monkeypatch.setattr(engine, "fetch_page", fake_fetch_page)

    payload = engine.fetch_by_query("query", local_config(max_pages=3))

    assert len(payload["pages"]) == 3
    assert peak >= 2, "distinct origins should be read concurrently"
    # Ranks decide page order, not whichever request finished first.
    assert [page["url"] for page in payload["pages"]] == [row["url"] for row in results]


def test_batch_fetch_keeps_one_request_at_a_time_per_origin(
    monkeypatch: pytest.MonkeyPatch, site: str
) -> None:
    results = [
        {"title": f"p{i}", "url": f"{site}/page-{i}.html", "snippet": "s"}
        for i in range(3)
    ]
    active: dict[str, int] = {}
    overlaps: list[str] = []
    lock = threading.Lock()

    def fake_fetch_page(url: str, config: Any, fetcher: Any = None, **_: Any) -> dict[str, Any]:
        origin = engine.origin_of(url)
        with lock:
            active[origin] = active.get(origin, 0) + 1
            if active[origin] > 1:
                overlaps.append(url)
        time.sleep(0.05)
        with lock:
            active[origin] -= 1
        return {
            "url": url,
            "status": 200,
            "markdown": "# page\n\n" + "body " * 20,
            "tables": [],
            "warnings": [],
            "cached": False,
        }

    monkeypatch.setattr(engine, "search", lambda *args, **kwargs: results)
    monkeypatch.setattr(engine, "fetch_page", fake_fetch_page)

    engine.fetch_by_query("query", local_config(max_pages=3))

    assert overlaps == [], "two requests to one origin were in flight at once"
