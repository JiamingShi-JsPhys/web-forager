"""Bilibili adapter tests (parsing plus a local-server integration test)."""

from __future__ import annotations

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


def test_feed_from_local_page(site: str) -> None:
    config = engine.FetchConfig(delay=0.0, timeout=10.0, render="never")
    payload = bilibili.feed(config, limit=10, enrich=1, url=f"{site}/bili_home.html")
    assert len(payload["cards"]) == 2
    assert len(payload["videos"]) == 1
    assert payload["videos"][0]["bvid"] == "BV1xx411c7mD"


def test_related_from_local_video(site: str) -> None:
    config = engine.FetchConfig(delay=0.0, timeout=10.0, render="never")
    payload = bilibili.related(f"{site}/video/BV1xx411c7mD/index.html", config, limit=1)
    assert payload["related"][0]["bvid"] == "BV1zVt3znEc1"
    assert payload["seed"]["bvid"] == "BV1xx411c7mD"
