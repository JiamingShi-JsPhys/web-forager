"""Bilibili adapter tests (parsing plus a local-server integration test)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import bilibili, engine

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Identifiers and formatting
# ---------------------------------------------------------------------------


def test_extract_bvid_from_url_and_bare_id() -> None:
    assert bilibili.extract_bvid("https://www.bilibili.com/video/BV1xx411c7mD/?p=2") == "BV1xx411c7mD"
    assert bilibili.extract_bvid("BV1zVt3znEc1") == "BV1zVt3znEc1"
    assert bilibili.extract_bvid("av170001") == "av170001"


def test_extract_bvid_rejects_garbage() -> None:
    with pytest.raises(engine.InvalidURLError):
        bilibili.extract_bvid("https://example.org/nothing")


def test_video_url_and_is_video_url() -> None:
    assert bilibili.video_url("BV1xx411c7mD") == "https://www.bilibili.com/video/BV1xx411c7mD/"
    assert bilibili.is_video_url("https://www.bilibili.com/video/BV1xx411c7mD/") is True
    assert bilibili.is_video_url("https://www.bilibili.com/") is False


def test_format_duration() -> None:
    assert bilibili.format_duration(61) == "1:01"
    assert bilibili.format_duration(3661) == "1:01:01"
    assert bilibili.format_duration("bad") == ""


def test_clean_title_strips_bilibili_suffix() -> None:
    assert bilibili.clean_title("某个视频_哔哩哔哩_bilibili") == "某个视频"


# ---------------------------------------------------------------------------
# Embedded state
# ---------------------------------------------------------------------------


def test_extract_initial_state_and_parse_video() -> None:
    state = bilibili.extract_initial_state(fixture("bili_video.html"))
    assert state["videoData"]["bvid"] == "BV1xx411c7mD"

    record = bilibili.parse_video_state(state, "https://www.bilibili.com/video/BV1xx411c7mD/")
    assert record["title"] == "测试视频：robots.txt 与学术抓取"
    assert record["uploader"]["name"] == "测试UP主"
    assert record["duration"] == "34:15"
    assert record["stats"]["view"] == 12345
    assert len(record["parts"]) == 2
    assert record["related"][0]["bvid"] == "BV1zVt3znEc1"
    assert len(record["related"]) == 2  # the "视频已失效" item is filtered out
    assert all("失效" not in item["title"] for item in record["related"])
    assert record["tags"] == ["测试", "学术研究"]
    assert "# 测试视频" in record["markdown"]
    assert "## 相关推荐" in record["markdown"]


def test_extract_initial_state_returns_empty_for_plain_html() -> None:
    assert bilibili.extract_initial_state("<html><body>nothing</body></html>") == {}


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------


def test_parse_video_cards() -> None:
    cards = bilibili.parse_video_cards(fixture("bili_cards.html"), limit=10)
    assert [card["bvid"] for card in cards] == ["BV1xx411c7mD", "BV1zVt3znEc1"]
    assert cards[0]["title"] == "卡片视频一"
    assert cards[0]["uploader"] == "UP主甲"
    assert cards[0]["duration"] == "12:34"
    assert cards[0]["stats_text"][0] == "1.2万"


# ---------------------------------------------------------------------------
# Local-server integration
# ---------------------------------------------------------------------------


def test_fetch_video_from_local_site(site: str) -> None:
    config = engine.FetchConfig(delay=0.0, timeout=10.0, render="never")
    record = bilibili.fetch_video(f"{site}/video/BV1xx411c7mD/index.html", config)
    assert record["bvid"] == "BV1xx411c7mD"
    assert record["title"].startswith("测试视频")
    assert record["metadata"]["journal"] == "bilibili"
    assert record["metadata"]["authors"] == ["测试UP主"]
    assert record["final_url"].endswith("/video/BV1xx411c7mD/index.html")


def test_feed_from_local_page(site: str, monkeypatch: pytest.MonkeyPatch) -> None:
    config = engine.FetchConfig(delay=0.0, timeout=10.0, render="never")
    enriched: list[str] = []

    def fake_fetch_video(url: str, config: engine.FetchConfig, fetcher=None) -> dict:
        # Cards always carry the canonical bilibili.com URL, which is what a
        # caller of feed() wants. Enrichment is stubbed so this suite stays
        # offline; the parsing path itself is real.
        enriched.append(url)
        return {"bvid": "BV1xx411c7mD", "url": url, "title": "测试视频"}

    monkeypatch.setattr(bilibili, "fetch_video", fake_fetch_video)
    payload = bilibili.feed(config, limit=10, enrich=1, url=f"{site}/bili_home.html")
    assert len(payload["cards"]) == 2
    assert len(payload["videos"]) == 1
    assert payload["videos"][0]["bvid"] == "BV1xx411c7mD"
    assert enriched == ["https://www.bilibili.com/video/BV1xx411c7mD/"]


def test_related_from_local_video(site: str) -> None:
    config = engine.FetchConfig(delay=0.0, timeout=10.0, render="never")
    payload = bilibili.related(f"{site}/video/BV1xx411c7mD/index.html", config, limit=1)
    assert payload["related"][0]["bvid"] == "BV1zVt3znEc1"
    assert payload["seed"]["bvid"] == "BV1xx411c7mD"


# ---------------------------------------------------------------------------
# JSON search (direct path)
# ---------------------------------------------------------------------------


class _StubFetcher:
    """Answer the home page and the search API without a network."""

    def __init__(self, api, home="<html></html>") -> None:
        self.api = api
        self.home = home
        self.calls: list[str] = []

    def fetch(
        self, url: str, *, check_robots: bool = True, use_cache: bool = True
    ) -> engine.HttpResponse:
        self.calls.append(url)
        body = self.home if url == bilibili.BILI_HOME else self.api
        return engine.HttpResponse(
            url=url,
            final_url=url,
            status=200,
            headers={},
            content=body.encode("utf-8"),
            text=body,
            encoding="utf-8",
            content_type="application/json",
        )


def test_parse_api_search_maps_cards() -> None:
    payload = {
        "code": 0,
        "data": {
            "result": [
                {
                    "bvid": "BV1xx411c7mD",
                    "title": "<em>示例</em>视频标题",
                    "author": "示例UP主",
                    "duration": "03:45",
                    "play": 12,
                    "danmaku": 3,
                    "pubdate": 1704153600,
                    "pic": "http://i0.hdslb.com/cover.jpg",
                }
            ]
        },
    }
    cards = bilibili.parse_api_search(payload, limit=5)
    assert len(cards) == 1
    card = cards[0]
    assert card["title"] == "示例视频标题"
    assert card["bvid"] == "BV1xx411c7mD"
    assert card["url"] == "https://www.bilibili.com/video/BV1xx411c7mD/"
    assert card["uploader"] == "示例UP主"
    assert card["stats_text"] == ["播放 12", "弹幕 3"]
    assert card["cover"].startswith("https://")


def test_parse_api_search_refuses_an_error_code() -> None:
    with pytest.raises(engine.FetchError) as info:
        bilibili.parse_api_search({"code": -412, "message": "请求被拦截"})
    assert "-412" in str(info.value)


def test_api_search_visits_the_home_page_for_the_cookie_first() -> None:
    response = {"code": 0, "data": {"result": [{"bvid": "BV1xx411c7mD", "title": "示例"}]}}
    fetcher = _StubFetcher(json.dumps(response))
    config = engine.FetchConfig(delay=0.0)
    cards = bilibili._api_search("示例", config, fetcher)
    assert len(cards) == 1
    assert fetcher.calls[0] == bilibili.BILI_HOME
    assert "search_type=video" in fetcher.calls[1]


def test_search_direct_falls_back_to_the_page_when_the_api_refuses(monkeypatch) -> None:
    class _PageFetcher(_StubFetcher):
        def fetch(
            self, url: str, *, check_robots: bool = True, use_cache: bool = True
        ) -> engine.HttpResponse:
            self.calls.append(url)
            if url == bilibili.BILI_HOME:
                return super().fetch(url, check_robots=check_robots, use_cache=use_cache)
            if "api.bilibili.com" in url:
                body = json.dumps({"code": -412, "message": "blocked"})
            else:
                body = fixture("bili_cards.html")
            return engine.HttpResponse(
                url=url,
                final_url=url,
                status=200,
                headers={},
                content=body.encode("utf-8"),
                text=body,
                encoding="utf-8",
                content_type="text/html",
            )

    config = engine.FetchConfig(delay=0.0)
    cards, route = bilibili._search_direct("卡片", config, _PageFetcher(""), check_robots=False)
    assert cards, "the page fallback should still produce cards"
    assert route == "search.bilibili.com"


def test_search_direct_drops_page_cards_that_ignore_the_query() -> None:
    class _PageFetcher(_StubFetcher):
        def fetch(
            self, url: str, *, check_robots: bool = True, use_cache: bool = True
        ) -> engine.HttpResponse:
            if "api.bilibili.com" in url:
                body = json.dumps({"code": -412, "message": "blocked"})
            elif url == bilibili.BILI_HOME:
                body = "<html></html>"
            else:
                body = fixture("bili_cards.html")
            return engine.HttpResponse(
                url=url,
                final_url=url,
                status=200,
                headers={},
                content=body.encode("utf-8"),
                text=body,
                encoding="utf-8",
                content_type="text/html",
            )

    config = engine.FetchConfig(delay=0.0)
    cards, route = bilibili._search_direct(
        "完全不相关的查询词", config, _PageFetcher(""), check_robots=False
    )
    assert cards == []
    assert route == "search.bilibili.com"


def test_search_direct_reports_the_json_api_route() -> None:
    response = {"code": 0, "data": {"result": [{"bvid": "BV1xx411c7mD", "title": "示例视频"}]}}
    fetcher = _StubFetcher(json.dumps(response))
    config = engine.FetchConfig(delay=0.0)
    cards, route = bilibili._search_direct("示例", config, fetcher, check_robots=False)
    assert cards and route == "api.bilibili.com"

