"""CLI tests: exit codes, formats, and stdin handling."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"


def run_cli(*args: str, stdin_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "run.py"), *args],
        cwd=str(PLUGIN_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        input=stdin_text,
        timeout=90,
    )


def test_clean_local_file_to_markdown() -> None:
    result = run_cli(
        "--action", "clean",
        "--input", str(FIXTURES / "article.html"),
        "--format", "markdown",
        "--max-chars", "0",
    )
    assert result.returncode == 0, result.stderr
    assert "Polite Crawling for Research" in result.stdout
    assert "Observed request rates" in result.stdout


def test_clean_local_file_to_json_keeps_metadata() -> None:
    result = run_cli(
        "--action", "clean",
        "--input", str(FIXTURES / "article.html"),
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["action"] == "clean"
    assert payload["metadata"]["doi"] == "10.1234/jewr.2025.0042"
    assert payload["tables"]


def test_clean_reads_stdin() -> None:
    html = (FIXTURES / "table.html").read_text(encoding="utf-8")
    result = run_cli("--action", "clean", stdin_text=html)
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["tables"][0]["rows"][0] == ["A", "298", "101.3"]


def test_clean_writes_output_file(tmp_path: Path) -> None:
    target = tmp_path / "out.md"
    result = run_cli(
        "--action", "clean",
        "--input", str(FIXTURES / "article.html"),
        "--format", "markdown",
        "--out", str(target),
    )
    assert result.returncode == 0, result.stderr
    assert "Polite Crawling" in target.read_text(encoding="utf-8")


def test_fetch_single_url_against_local_site(site: str) -> None:
    result = run_cli(
        "--action", "fetch",
        "--url", f"{site}/index.html",
        "--delay", "0",
        "--format", "json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["tool"] == "web-forager"
    assert payload["action"] == "fetch"
    record = payload["results"][0]
    assert record["metadata"]["doi"] == "10.1234/jewr.2025.0042"
    assert record["markdown"]


def test_robots_denied_exit_code_is_three(site: str) -> None:
    result = run_cli(
        "--action", "fetch",
        "--url", f"{site}/private/secret.html",
        "--delay", "0",
    )
    assert result.returncode == 3
    assert "robots" in result.stderr.lower()


def test_fetch_requires_exactly_one_source() -> None:
    result = run_cli("--action", "fetch")
    assert result.returncode == 2
    assert "exactly one" in result.stderr


def test_help_contains_disclaimer() -> None:
    result = run_cli("--help")
    assert result.returncode == 0
    assert "本插件仅供学术研究使用" in result.stdout


def test_version_flag() -> None:
    result = run_cli("--version")
    assert result.returncode == 0
    assert "web-forager 0.1.0" in result.stdout


def test_bili_video_mode(site: str) -> None:
    result = run_cli(
        "--action", "bili",
        "--mode", "video",
        "--url", f"{site}/video/BV1xx411c7mD/index.html",
        "--delay", "0",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["action"] == "bili"
    record = payload["results"][0]
    assert record["bvid"] == "BV1xx411c7mD"
    assert record["uploader"]["name"] == "测试UP主"


def test_bili_feed_mode(site: str) -> None:
    result = run_cli(
        "--action", "bili",
        "--mode", "feed",
        "--url", f"{site}/bili_home.html",
        "--num-results", "10",
        "--max-pages", "1",
        "--delay", "0",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert len(payload["cards"]) == 2
    assert payload["videos"][0]["bvid"] == "BV1xx411c7mD"


def test_root_writes_chelate_four_zone_artifacts(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    result = run_cli(
        "--action", "clean",
        "--input", str(FIXTURES / "article.html"),
        "--root", str(workspace),
    )
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr

    json_files = list((workspace / "process" / "web-forager").glob("*.json"))
    md_files = list((workspace / "process" / "web-forager").glob("*.md"))
    index_files = list((workspace / "_broadcast").glob("web-forager_*.json"))
    assert len(json_files) == 1
    assert len(md_files) == 1
    assert len(index_files) == 1

    index = json.loads(index_files[0].read_text(encoding="utf-8"))
    assert index["tool"] == "web-forager"
    assert index["action"] == "clean"
    assert index["files"]["json"].startswith("process/web-forager/")
    assert index["files"]["markdown"].startswith("process/web-forager/")


def test_out_takes_precedence_over_root(tmp_path: Path) -> None:
    workspace = tmp_path / "ws"
    target = tmp_path / "result.json"
    result = run_cli(
        "--action", "clean",
        "--input", str(FIXTURES / "article.html"),
        "--root", str(workspace),
        "--out", str(target),
    )
    assert result.returncode == 0, result.stderr
    assert target.is_file()
    assert not workspace.exists()


def test_render_always_without_playwright_fails_gracefully(site: str) -> None:
    if importlib.util.find_spec("playwright") is not None:
        pytest.skip("Playwright is installed on this machine")
    result = run_cli(
        "--action", "fetch",
        "--url", f"{site}/index.html",
        "--render", "always",
        "--delay", "0",
    )
    assert result.returncode == 6
    assert "Playwright is not installed" in result.stderr
    assert "pip install playwright && playwright install chromium" in result.stderr
    assert "Traceback" not in result.stderr
