"""Integration tests against a temporary local HTTP server."""

from __future__ import annotations

import os
import stat
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


def test_robotstxt_blocks_private_path(site: str) -> None:
    with pytest.raises(engine.RobotsDenied):
        engine.fetch_page(f"{site}/private/secret.html", local_config())


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are not portable to Windows")
def test_cache_and_session_state_are_owner_only(
    tmp_path: object, site: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = str(tmp_path) + "/cache"  # type: ignore[operator]
    config = local_config(cache=True, cache_dir=cache_dir)
    engine.fetch_page(f"{site}/index.html", config)
    cache_root = engine.Path(cache_dir)
    assert stat.S_IMODE(cache_root.stat().st_mode) == 0o700
    written = [path for path in cache_root.iterdir() if path.is_file()]
    assert written
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in written)

    session_file = engine.Path(str(tmp_path)) / "sessions" / "one.json"  # type: ignore[operator]
    monkeypatch.setattr(engine, "session_path", lambda name: session_file)
    saved = engine.save_session("one", {"visited": ["https://example.org/"]})
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600


def test_redirect_into_a_disallowed_path_is_refused(site: str) -> None:
    """Every redirect hop is checked, not only the caller-supplied URL."""

    with pytest.raises(engine.RobotsDenied):
        engine.fetch_page(f"{site}/redirect-private", local_config())


def test_ignore_robots_flag_allows_private_path(site: str) -> None:
    page = engine.fetch_page(
        f"{site}/private/secret.html", local_config(respect_robots=False)
    )
    assert "secret" in page["markdown"].lower()


def test_robots_warn_reads_the_path_and_records_the_override(site: str) -> None:
    page = engine.fetch_page(
        f"{site}/private/secret.html", local_config(robots_policy="warn")
    )
    assert "secret" in page["markdown"].lower()
    assert page["compliance"] == {
        "robots_checked": True,
        "robots_policy": "warn",
        "robots_overridden": True,
    }
    assert any("robots.txt disallows" in warning for warning in page["warnings"])


def test_allowed_page_records_a_clean_compliance_block(site: str) -> None:
    page = engine.fetch_page(f"{site}/index.html", local_config())
    assert page["compliance"] == {
        "robots_checked": True,
        "robots_policy": "respect",
        "robots_overridden": False,
    }


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


class _ShellFetcher:
    """Serve one tiny HTML shell without touching the network."""

    def __init__(self, html: str) -> None:
        self.html = html
        self.closed = False

    def assert_allowed(self, url: str) -> object:
        class Policy:
            crawl_delay = 0.0
            note = ""
            source = ""

            def allowed(self, target: str) -> bool:
                return True

        return Policy()

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


def test_minimal_html_shell_is_recognised() -> None:
    assert engine.looks_like_html_shell(
        '<html><body><script>location.href="/x"</script></body></html>'
    )
    assert not engine.looks_like_html_shell(
        "<html><body><p>" + "ordinary text " * 40 + "</p></body></html>"
    )


def test_fetch_page_renders_a_minimal_html_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    shell = '<html><body><script>location.href="/x"</script></body></html>'
    rendered = (
        "<html><head><title>Article</title></head><body><p>"
        + "Rendered body. " * 60
        + "</p></body></html>"
    )
    monkeypatch.setattr(engine, "render_html", lambda url, config: rendered)

    page = engine.fetch_page(
        "https://example.org/shell", local_config(render="auto"), fetcher=_ShellFetcher(shell)
    )

    assert page["rendered"] is True
    assert page["render_fallback"] is True
    assert "Rendered body" in page["markdown"]
    assert any("minimal HTML shell" in warning for warning in page["warnings"])


def test_render_fallback_can_be_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    shell = '<html><body><script>location.href="/x"</script></body></html>'
    called = {"count": 0}

    def fake_render(url: str, config: engine.FetchConfig) -> str:
        called["count"] += 1
        return ""

    monkeypatch.setattr(engine, "render_html", fake_render)
    fetcher = _ShellFetcher(shell)

    with pytest.raises(engine.ExtractionError):
        engine.fetch_page(
            "https://example.org/shell",
            local_config(render="auto"),
            fetcher=fetcher,
            allow_render_fallback=False,
        )
    assert called["count"] == 0
