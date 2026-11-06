"""Integration tests against a temporary local HTTP server."""

from __future__ import annotations

from typing import Any

import pytest

from scripts import engine


def local_config(**overrides: Any) -> engine.FetchConfig:
    values: dict[str, Any] = dict(delay=0.0, timeout=10.0, max_chars=0, render="never", verbose=False)
    values.update(overrides)
    return engine.FetchConfig(**values)  # type: ignore[arg-type]


def test_fetch_page_extracts_markdown_metadata_and_tables(site: str) -> None:
    page = engine.fetch_page(f"{site}/index.html", local_config())

    assert page["status"] == 200
    assert page["rendered"] is False
    assert page["metadata"]["doi"] == "10.1234/jewr.2025.0042"
    assert page["metadata"]["authors"] == ["Ada Lovelace", "Alan Turing"]
    assert page["tables"][0]["caption"] == "Observed request rates"
    assert "robots.txt" in page["markdown"].lower()
    assert page["warnings"] == []


def test_robots_txt_blocks_private_path(site: str) -> None:
    with pytest.raises(engine.RobotsDenied):
        engine.fetch_page(f"{site}/private/secret.html", local_config())


def test_ignore_robots_flag_allows_private_path(site: str) -> None:
    page = engine.fetch_page(
        f"{site}/private/secret.html", local_config(respect_robots=False)
    )
    assert "secret" in page["markdown"].lower()


def test_clean_table_page(site: str) -> None:
    page = engine.fetch_page(f"{site}/table.html", local_config())
    assert page["tables"][0]["headers"] == ["样本", "温度 / K", "压力 / kPa"]
    assert "样本测量结果" in page["markdown"]


def test_unknown_content_type_is_reported(tmp_path: object, site: str) -> None:
    # The local server serves unknown extensions as application/octet-stream.
    path = str(tmp_path) + "/data.bin"  # type: ignore[operator]
    with open(path, "wb") as handle:
        handle.write(b"\x00\x01\x02")
    with pytest.raises(engine.FetchError):
        engine.HttpFetcher(local_config()).fetch(f"{site}/data.bin")
