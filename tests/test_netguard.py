"""SSRF guard: private, loopback and metadata addresses are refused."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import engine

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:8080/admin",
        "http://10.0.0.5/",
        "http://172.16.3.4/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://100.64.0.1/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://localhost/",
        "http://metadata.google.internal/computeMetadata/v1/",
    ],
)
def test_private_targets_are_refused(url: str) -> None:
    with pytest.raises(engine.UnsafeAddress):
        engine.assert_public_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "http://8.8.8.8/",
        "https://93.184.216.34/",
        "http://[2001:4860:4860::8888]/",
    ],
)
def test_public_literal_addresses_pass(url: str) -> None:
    engine.assert_public_url(url)


def test_opt_out_allows_loopback() -> None:
    engine.assert_public_url("http://127.0.0.1:9/", allow_private=True)


def test_fetch_refuses_before_opening_a_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    config = engine.FetchConfig(delay=0.0, respect_robots=False, allow_private=False)
    fetcher = engine.HttpFetcher(config)

    def explode(*args: object, **kwargs: object) -> None:
        raise AssertionError("the request must not be attempted")

    monkeypatch.setattr(fetcher.session, "get", explode)
    with pytest.raises(engine.UnsafeAddress):
        fetcher.fetch("http://127.0.0.1:9/private")
    fetcher.close()


class _FakeResponse:
    def __init__(self, status: int, headers: dict[str, str], url: str) -> None:
        self.status_code = status
        self.headers = headers
        self.url = url

    def close(self) -> None:
        pass


def test_redirect_to_metadata_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    config = engine.FetchConfig(delay=0.0, respect_robots=False, allow_private=False)
    fetcher = engine.HttpFetcher(config)
    seen: list[str] = []

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        seen.append(url)
        return _FakeResponse(
            302, {"Location": "http://169.254.169.254/latest/meta-data/"}, url
        )

    monkeypatch.setattr(fetcher.session, "get", fake_get)
    with pytest.raises(engine.UnsafeAddress):
        fetcher.fetch("http://93.184.216.34/")
    assert seen == ["http://93.184.216.34/"]
    fetcher.close()


def test_redirect_chain_stops_at_the_private_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    config = engine.FetchConfig(delay=0.0, respect_robots=False, allow_private=False)
    fetcher = engine.HttpFetcher(config)

    def fake_get(url: str, **kwargs: object) -> _FakeResponse:
        if url == "http://93.184.216.34/":
            return _FakeResponse(301, {"Location": "/start"}, url)
        return _FakeResponse(302, {"Location": "http://127.0.0.1/"}, url)

    monkeypatch.setattr(fetcher.session, "get", fake_get)
    with pytest.raises(engine.UnsafeAddress):
        fetcher.fetch("http://93.184.216.34/")
    fetcher.close()


def test_robots_download_is_guarded() -> None:
    config = engine.FetchConfig(delay=0.0, allow_private=False)
    cache = engine.RobotsCache(config)
    with pytest.raises(engine.UnsafeAddress):
        cache.policy_for("http://127.0.0.1:9/")


def test_cache_never_writes_a_session_cookie(tmp_path: Path) -> None:
    config = engine.FetchConfig(
        delay=0.0, cache=True, cache_dir=str(tmp_path), allow_private=True
    )
    fetcher = engine.HttpFetcher(config)
    response = engine.HttpResponse(
        url="https://example.org/page",
        final_url="https://example.org/page",
        status=200,
        headers={"Set-Cookie": "buvid3=secret", "Content-Type": "text/html"},
        content=b"<html>ok</html>",
        text="<html>ok</html>",
        encoding="utf-8",
        content_type="text/html",
    )
    fetcher._write_cache("https://example.org/page", response)
    assert list(tmp_path.rglob("*.json")) == []
    assert list(tmp_path.rglob("*.bin")) == []
    fetcher.close()


def _cli_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "WEB_FORAGER_ALLOW_PRIVATE"}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def test_cli_reports_unsafe_address_with_exit_2() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "run.py"),
            "--action",
            "fetch",
            "--url",
            "http://169.254.169.254/latest/meta-data/",
            "--agent",
        ],
        capture_output=True,
        text=True,
        env=_cli_env(),
        timeout=60,
    )
    assert result.returncode == 2, result.stderr
    assert "unsafe_address" in result.stdout


def test_cli_allow_private_opens_the_local_fixture(site: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "run.py"),
            "--action",
            "fetch",
            "--url",
            site + "/index.html",
            "--allow-private",
            "--agent",
        ],
        capture_output=True,
        text=True,
        env=_cli_env(),
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert '"ok": true' in result.stdout
