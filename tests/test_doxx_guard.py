"""The doxxing guard: explicit intent is refused, a bare name is only warned."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

import mcp_server
from scripts import bilibili, engine

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "run.py"), *args],
        cwd=str(PLUGIN_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "query",
    [
        "人肉搜索 张三",
        "开盒 某博主",
        "查一下他的手机号",
        "帮我找这个人的住址",
        "王五 身份证 照片",
        "doxxing Jiaming Shi",
        "Jiaming Shi phone number",
    ],
)
def test_explicit_doxxing_is_prohibited(query: str) -> None:
    assert engine.doxxing_reason(query)


@pytest.mark.parametrize(
    "query",
    [
        "反逆向工程 方法",
        "西湖大学 分子张力工程",
        "手机号码归属地",
        "身份证号码校验算法",
        "watermark detection",
        "张三",
        "Jiaming Shi",
    ],
)
def test_topic_and_author_queries_are_allowed(query: str) -> None:
    assert engine.doxxing_reason(query) == ""


def test_bare_person_name_is_flag() -> None:
    assert engine.looks_like_person_name("张三")
    assert engine.looks_like_person_name("Jiaming Shi")
    assert not engine.looks_like_person_name("西湖大学")
    assert not engine.looks_like_person_name("watermark detection")


def test_name_warning_comes_last(monkeypatch) -> None:
    monkeypatch.setattr(engine, "search", lambda *args, **kwargs: [])
    warnings = engine.search_warnings("张三", [])
    assert "no results" in warnings[0]
    assert "bare personal name" in warnings[-1]


# ---------------------------------------------------------------------------
# Runtime refusal
# ---------------------------------------------------------------------------


def test_search_refuses_before_any_request() -> None:
    config = engine.FetchConfig(delay=0.0)
    fetcher = engine.HttpFetcher(config)
    try:
        with pytest.raises(engine.ProhibitedQuery):
            engine.search("人肉搜索 张三", config, fetcher=fetcher)
    finally:
        fetcher.close()


def test_find_refuses_doxxing_query() -> None:
    with pytest.raises(engine.ProhibitedQuery):
        engine.find_within_site("example.org", "查一下他的手机号")


def test_bilibili_search_refuses_doxxing_query() -> None:
    with pytest.raises(engine.ProhibitedQuery):
        bilibili.search("人肉搜索 张三")


def test_cli_returns_exit_code_10() -> None:
    result = run_cli("--action", "fetch", "--query", "人肉搜索 张三", "--agent")
    assert result.returncode == 10
    assert "prohibited_query" in result.stdout


def test_mcp_returns_prohibited_code() -> None:
    with pytest.raises(engine.ProhibitedQuery):
        mcp_server._tool_search({"query": "人肉搜索 张三"})
