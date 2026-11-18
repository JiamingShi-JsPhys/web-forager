"""Ranking signals, evidence checks, syndication and host diversity."""

from __future__ import annotations

from typing import Any

from scripts import engine


def _result(url: str, title: str, snippet: str = "", source: str = "360") -> dict[str, Any]:
    return {"url": url, "title": title, "snippet": snippet, "source": source}


def test_quiz_pages_are_recognized_as_answer_key_dumps() -> None:
    assert engine.looks_like_qa_dump(
        _result("https://m.shenzhen.huatu.com/tiku/2976538.html", "梵高是哪个国家的画家？")
    )
    assert engine.looks_like_qa_dump(
        _result(
            "https://www.pipixue.com/ti/efd0.html",
            "联合国教科文组织总部设在哪里？()【单选题】",
        )
    )
    assert not engine.looks_like_qa_dump(
        _result("https://www.who.int/about", "WHO headquarters")
    )


def test_a_quiz_dump_ranks_below_an_article_that_covers_the_same_terms() -> None:
    query = "联合国教科文组织总部在哪个城市"
    quiz = _result(
        "https://www.pipixue.com/ti/efd0.html",
        "联合国教科文组织总部设在哪里？()A.巴黎B.纽约C.北京D.莫斯科【单选题】",
    )
    article = _result(
        "https://news.example.org/unesco",
        "联合国教科文组织总部的所在地",
        "总部位于法国巴黎。",
    )
    ranked = engine.merge_search_results([("360", [quiz, article])], query, limit=8)
    assert ranked[0]["url"] == article["url"]
    assert ranked[0]["rank_components"]["qa_dump"] is False
    assert ranked[1]["rank_components"]["qa_dump"] is True


def test_evidence_is_unsupported_when_no_result_states_the_claim() -> None:
    query = "2026年诺贝尔数学奖获奖者是谁"
    results = [
        _result("https://finance.sina.com.cn/a", "2026年度菲尔兹奖揭晓"),
        _result("https://www.stdaily.com/b", "他获得2026年阿贝尔奖"),
    ]
    evidence = engine.search_evidence(query, results)
    assert evidence["checked"] is True
    assert evidence["status"] == "unsupported"


def test_evidence_is_supported_when_a_result_states_the_fact() -> None:
    query = "NVIDIA 2024 财年营收是多少"
    results = [
        _result("https://nvidia.com/ir", "NVIDIA 2024 财年营收 609 亿美元"),
    ]
    evidence = engine.search_evidence(query, results)
    assert evidence["status"] == "supported"


def test_evidence_leaves_a_broad_topic_query_alone() -> None:
    query = "本周国内发布了哪些重要经济政策"
    results = [_result("https://www.gov.cn/a", "国务院常务会议部署经济政策")]
    evidence = engine.search_evidence(query, results)
    assert evidence["checked"] is False
    assert evidence["status"] == "not_checked"


def test_quiz_pages_do_not_count_as_evidence() -> None:
    query = "联合国教科文组织总部在纽约吗"
    results = [
        _result(
            "https://www.shuashuati.com/ti/x.html",
            "联合国教科文组织总部设在? A.美国纽约 B.瑞士日内瓦 C.法国巴黎",
        )
    ]
    evidence = engine.search_evidence(query, results)
    assert evidence["status"] == "unsupported"


def test_syndicated_copies_of_one_article_are_dropped() -> None:
    results = [
        _result("https://cloud.tencent.com/a", "深入剖析 Kubernetes 原生 Sidecar 容器"),
        _result("https://blog.csdn.net/x/1", "深入剖析 Kubernetes 原生 Sidecar 容器_CSDN博客"),
        _result("https://example.org/other", "Kubernetes 1.31 发布说明"),
    ]
    kept = engine.dedupe_syndicated(results)
    assert [item["url"] for item in kept] == [results[0]["url"], results[2]["url"]]


def test_diversify_gives_each_host_one_slot_before_a_second() -> None:
    results = [
        _result("https://a.example/1", "one"),
        _result("https://a.example/2", "two"),
        _result("https://b.example/1", "three"),
        _result("https://c.example/1", "four"),
    ]
    engine.annotate_results(results, "one two three four")
    for item in results:
        item["relevance"] = True
    chosen = engine.diversify_results(results, limit=3)
    hosts = [item["url"].split("/")[2] for item in chosen]
    assert hosts == ["a.example", "b.example", "c.example"]


def test_official_candidates_name_the_docs_page_for_a_python_question() -> None:
    rows = engine._official_candidates("Python 3.12 asyncio.TaskGroup 默认异常处理")
    urls = [row["url"] for row in rows]
    assert any(url.startswith("https://docs.python.org/") for url in urls)
    assert all(row["source"] == "official-entry" for row in rows)
    assert all(row["targeted"] is True for row in rows)


def test_official_candidates_name_the_entity_site() -> None:
    rows = engine._official_candidates("世界卫生组织总部在哪个城市")
    assert any("who.int" in row["url"] for row in rows)


def test_search_adds_an_official_row_when_the_engines_return_only_farms(
    monkeypatch: Any,
) -> None:
    farm_rows = [
        {
            "title": "Python asyncio TaskGroup 异常处理 - CSDN博客",
            "url": "https://blog.csdn.net/a/1",
            "snippet": "TaskGroup 默认异常处理",
            "source": "360",
        },
        {
            "title": "asyncio.TaskGroup 教程 - PHP中文网",
            "url": "https://www.php.cn/faq/1.html",
            "snippet": "默认异常处理",
            "source": "360",
        },
        {
            "title": "Python 并发编程 - CSDN博客",
            "url": "https://blog.csdn.net/b/2",
            "snippet": "TaskGroup",
            "source": "360",
        },
    ]

    def fake_search_one(
        name: str, query: str, config: Any, limit: int, fetcher: Any, pages: int = 1
    ) -> list[dict[str, str]]:
        return list(farm_rows)

    monkeypatch.setattr(engine, "_search_one", fake_search_one)
    config = engine.FetchConfig(
        delay=0.0, timeout=5.0, max_chars=0, render="never",
        cache=False, num_results=8, max_pages=0, search_pages=1,
    )
    results = engine.search("Python 3.12 asyncio.TaskGroup 默认异常处理", config, limit=8)
    urls = [item["url"] for item in results]
    assert any(url.startswith("https://docs.python.org/") for url in urls)
    assert any(item.get("source") == "official-entry" for item in results)


def test_official_candidates_need_the_page_itself_to_match_the_topic() -> None:
    rows = engine._official_candidates("Python 和 Go 做高并发服务怎么选")
    urls = [row["url"] for row in rows]
    assert not any("asyncio-task" in url for url in urls), (
        "a language comparison should not receive an unrelated asyncio chapter"
    )


def test_an_off_topic_official_page_does_not_count_as_authority() -> None:
    assert engine._lacks_authority(
        [{"authority_tier": "primary", "relevance": False, "targeted": False}]
    )
    assert not engine._lacks_authority(
        [{"authority_tier": "primary", "relevance": True, "targeted": False}]
    )


def test_an_authoritative_result_survives_the_relevance_filter(
    monkeypatch: Any,
) -> None:
    rows = [
        {
            "title": "Python asyncio TaskGroup 异常处理 - CSDN博客",
            "url": "https://blog.csdn.net/a/1",
            "snippet": "TaskGroup 默认异常处理",
            "source": "360",
        },
        {
            "title": "asyncio.TaskGroup 教程 - PHP中文网",
            "url": "https://www.php.cn/faq/1.html",
            "snippet": "默认异常处理",
            "source": "360",
        },
        {
            "title": "Python 并发编程 - CSDN博客",
            "url": "https://blog.csdn.net/b/2",
            "snippet": "TaskGroup",
            "source": "360",
        },
        {
            "title": "Python 3 documentation",
            "url": "https://docs.python.org/3/",
            "snippet": "Python documentation",
            "source": "bing",
        },
    ]

    def fake_search_one(
        name: str, query: str, config: Any, limit: int, fetcher: Any, pages: int = 1
    ) -> list[dict[str, str]]:
        return list(rows)

    monkeypatch.setattr(engine, "_search_one", fake_search_one)
    config = engine.FetchConfig(
        delay=0.0, timeout=5.0, max_chars=0, render="never",
        cache=False, num_results=8, max_pages=0, search_pages=1,
    )
    results = engine.search("Python 3.12 asyncio.TaskGroup 默认异常处理", config, limit=8)
    urls = [item["url"] for item in results]
    assert any(url.startswith("https://docs.python.org/") for url in urls)


def test_a_doi_query_resolves_through_doi_org() -> None:
    rows = engine._official_candidates("DOI 10.1145/3290605.3300233 是什么论文")
    assert [row["url"] for row in rows] == ["https://doi.org/10.1145/3290605.3300233"]


def test_a_gdpr_article_question_gets_the_article_page() -> None:
    rows = engine._official_candidates("GDPR 第 17 条 被遗忘权 英文原文")
    assert any("gdpr-info.eu" in row["url"] for row in rows)


def test_an_engine_ad_is_demoted_below_the_same_organic_title() -> None:
    query = "Transformer 论文作者后来创办了哪家公司"
    title = "Transformer 论文作者后来创办了哪家公司"
    ad = _result("https://ads.example/?utm_source=360zrkp&utm_query=x", title)
    organic = _result("https://news.example/a", title)
    ranked = engine.merge_search_results([("360", [ad, organic])], query, limit=8)
    assert ranked[0]["url"] == organic["url"]
    assert ranked[1]["rank_components"]["ad"] is True
