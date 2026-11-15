"""Free ranking, query variants and host diversity."""

from __future__ import annotations

from scripts import engine


def result(title: str, url: str, snippet: str = "") -> dict[str, str]:
    return {"title": title, "url": url, "snippet": snippet}


def test_domain_prior_breaks_a_coverage_tie() -> None:
    groups = [
        (
            "360",
            [
                result("reinforcement learning survey", "https://www.doc88.com/p-1.html"),
                result("reinforcement learning survey", "https://arxiv.org/abs/1"),
            ],
        )
    ]
    merged = engine.merge_search_results(groups, "reinforcement learning survey")
    assert merged[0]["url"].startswith("https://arxiv.org/")


def test_recent_snippet_breaks_a_coverage_tie() -> None:
    groups = [
        (
            "bing",
            [
                result("城市漫步 攻略", "https://a.example/", "2019 年的旧文章"),
                result("城市漫步 攻略", "https://b.example/", "2026 年 11 月更新"),
            ],
        )
    ]
    merged = engine.merge_search_results(groups, "城市漫步 攻略")
    assert merged[0]["url"] == "https://b.example/"


def test_diversify_caps_one_host_and_fills_from_overflow() -> None:
    items = [
        result(f"微信 {index}", f"https://mp.weixin.qq.com/s/{index}")
        for index in range(2)
    ] + [result("other", "https://example.org/a")]
    picked = engine.diversify_results(items, limit=3, per_host=2)
    assert len(picked) == 3
    hosts = [item["url"].split("/")[2] for item in picked]
    assert hosts.count("mp.weixin.qq.com") == 2


def test_diversify_prefers_other_hosts_before_overflow() -> None:
    items = [
        result("微信 1", "https://mp.weixin.qq.com/s/1"),
        result("微信 2", "https://mp.weixin.qq.com/s/2"),
        result("微信 3", "https://mp.weixin.qq.com/s/3"),
        result("blog", "https://example.org/a"),
    ]
    picked = engine.diversify_results(items, limit=3, per_host=2)
    assert [item["url"] for item in picked][2] == "https://example.org/a"


def test_query_variants_strip_quotes_and_stopwords() -> None:
    variants = engine.query_variants('"the reinforcement learning" survey for me')
    assert variants[0] == '"the reinforcement learning" survey for me'
    assert variants[1] == "reinforcement learning survey me"


def test_query_variants_join_a_spaced_cjk_query() -> None:
    variants = engine.query_variants("城市 漫步 攻略")
    assert variants == ["城市 漫步 攻略", "城市漫步攻略"]


def test_query_allows_at_most_two_render_fallbacks(monkeypatch) -> None:
    results = [
        {"title": f"r{index}", "url": f"https://example.org/{index}", "snippet": "", "source": "bing"}
        for index in range(5)
    ]
    monkeypatch.setattr(engine, "search", lambda *args, **kwargs: results)
    calls = []

    def fake_fetch(url, config, fetcher=None, allow_render_fallback=True):
        calls.append(allow_render_fallback)
        return {
            "url": url,
            "markdown": "body",
            "warnings": [],
            "render_fallback": True,
        }

    monkeypatch.setattr(engine, "fetch_page", fake_fetch)
    config = engine.FetchConfig(delay=0.0, max_pages=5, render="auto")
    payload = engine.fetch_by_query("example", config)

    assert len(payload["pages"]) == 5
    assert calls == [True, True, False, False, False]
