"""Verification interstitials are reported, never recycled as content."""

from __future__ import annotations

from typing import Any

import pytest

from scripts import engine

WECHAT_URL = "https://mp.weixin.qq.com/s/example"
WECHAT_HTML = (
    "<html><head><title>微信公众平台</title></head><body>"
    "<p>环境异常</p><p>当前环境异常，完成验证后即可继续访问。</p>"
    "<p>去验证</p></body></html>"
)


def local_config(**overrides: Any) -> engine.FetchConfig:
    values: dict[str, Any] = dict(delay=0.0, timeout=10.0, render="never", verbose=False)
    values.update(overrides)
    return engine.FetchConfig(**values)  # type: ignore[arg-type]


class _Policy:
    crawl_delay = 0.0
    note = ""
    source = ""

    def allowed(self, url: str) -> bool:
        return True


class _Fetcher:
    def __init__(self, html: str) -> None:
        self.html = html
        self.closed = False

    def assert_allowed(self, url: str) -> _Policy:
        return _Policy()

    def fetch(self, url: str) -> engine.HttpResponse:
        return engine.HttpResponse(
            url=url,
            final_url=url,
            status=200,
            headers={"content-type": "text/html; charset=utf-8"},
            content=self.html.encode("utf-8"),
            text=self.html,
            encoding="utf-8",
            content_type="text/html",
        )

    def close(self) -> None:
        self.closed = True


def test_wechat_environment_check_is_recognised() -> None:
    markdown = "环境异常\n当前环境异常，完成验证后即可继续访问。\n去验证"
    assert engine.looks_like_verification_page(markdown, "", WECHAT_URL) == "环境异常"


def test_a_real_article_that_mentions_the_phrase_is_not_flagged() -> None:
    markdown = "环境异常是微信的提示语。" + "这是正常的文章正文，用来把页面撑长。" * 200
    assert engine.looks_like_verification_page(markdown, "一篇文章", WECHAT_URL) == ""


def test_wechat_markers_do_not_apply_to_other_hosts() -> None:
    assert engine.looks_like_verification_page("环境异常", "", "https://example.org/a") == ""


def test_fetch_page_raises_verification_required() -> None:
    fetcher = _Fetcher(WECHAT_HTML)
    with pytest.raises(engine.VerificationRequired) as caught:
        engine.fetch_page(WECHAT_URL, local_config(), fetcher=fetcher)

    assert "环境异常" in str(caught.value)
    assert "wechat-dig" in str(caught.value)
    assert fetcher.closed is False  # an injected fetcher belongs to the caller


def test_wechat_robots_denial_routes_to_browser_mode(monkeypatch) -> None:
    results = [
        {"title": "一篇文章", "url": WECHAT_URL, "snippet": "", "source": "weixin"}
    ]
    monkeypatch.setattr(engine, "search", lambda *args, **kwargs: results)

    def deny(url, config, fetcher=None, **kwargs):
        raise engine.RobotsDenied("robots.txt disallows /s")

    monkeypatch.setattr(engine, "fetch_page", deny)

    payload = engine.fetch_by_query("城市漫步", local_config(max_pages=1))

    assert payload["skipped"][0]["code"] == "robots_denied"
    assert any("wechat-dig" in warning for warning in payload["warnings"])


def test_search_reports_verification_and_routes_to_browser_mode(monkeypatch) -> None:
    results = [
        {"title": "一篇文章", "url": WECHAT_URL, "snippet": "", "source": "weixin"}
    ]
    monkeypatch.setattr(engine, "search", lambda *args, **kwargs: results)

    def refuse(url, config, fetcher=None, **kwargs):
        raise engine.VerificationRequired("environment check")

    monkeypatch.setattr(engine, "fetch_page", refuse)

    payload = engine.fetch_by_query("城市漫步", local_config(max_pages=1))

    assert payload["pages"] == []
    assert payload["skipped"][0]["code"] == "verification_required"
    assert any("wechat-dig" in warning for warning in payload["warnings"])
