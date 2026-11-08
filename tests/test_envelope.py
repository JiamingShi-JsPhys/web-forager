"""Envelope size and the doctor action (1.0.2).

``results`` used to repeat every page in full, so a search response carried
each Markdown body twice. These tests pin the compact default and the
``--full-results`` / ``fullResults`` escape hatch.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from scripts import engine  # noqa: E402


def page(url: str, body: str = "正文" * 200, **extra) -> dict:
    record = {
        "url": url,
        "final_url": url,
        "status": 200,
        "content_type": "text/html",
        "title": f"title {url}",
        "metadata": {"title": f"title {url}"},
        "markdown": body,
        "tables": [{"name": "t", "columns": ["a"], "rows": [[1]]}],
        "warnings": [],
    }
    record.update(extra)
    return record


def test_single_page_results_are_a_compact_index() -> None:
    envelope = engine.build_envelope("fetch", page("https://example.org/a"))
    summary = envelope["results"][0]
    assert summary["url"] == "https://example.org/a"
    assert summary["markdown_chars"] == len("正文" * 200)
    assert summary["tables"] == 1
    assert "markdown" not in summary
    assert "metadata" not in summary
    # The body is still present exactly once, at the top level.
    assert envelope["markdown"] == "正文" * 200


def test_search_results_carry_snippets_and_no_body() -> None:
    payload = {
        "query": "示例",
        "engine": "auto",
        "search_results": [
            {"title": "A", "url": "https://example.org/a", "snippet": "片段 A", "source": "360"}
        ],
        "pages": [page("https://example.org/a")],
    }
    envelope = engine.build_envelope("fetch", payload)
    assert envelope["results"][0]["snippet"] == "片段 A"
    assert "markdown" not in envelope["results"][0]
    assert envelope["pages"][0]["markdown"]


def test_compact_envelope_is_much_smaller_than_the_full_one() -> None:
    payload = {
        "query": "示例",
        "search_results": [],
        "pages": [page(f"https://example.org/{index}") for index in range(8)],
    }
    compact = engine.build_envelope("fetch", payload)
    full = engine.build_envelope("fetch", payload, full_results=True)
    compact_size = len(json.dumps(compact, ensure_ascii=False))
    full_size = len(json.dumps(full, ensure_ascii=False))
    assert compact_size * 1.5 < full_size
    assert len(full["results"]) == len(compact["results"]) == 8


def test_full_results_keeps_the_old_shape() -> None:
    envelope = engine.build_envelope("fetch", page("https://example.org/a"), full_results=True)
    assert envelope["results"][0]["markdown"] == "正文" * 200
    assert envelope["results"][0]["metadata"]["title"].startswith("title")


def test_surf_payload_gets_a_compact_results_list() -> None:
    payload = {"mode": "surf", "pages": [page("https://example.org/a"), {"url": "https://example.org/b", "error": "FetchError: nope"}]}
    envelope = engine.build_envelope("surf", payload)
    assert envelope["results"][0]["markdown_chars"] > 0
    assert envelope["results"][1]["error"].startswith("FetchError")
    assert "status" not in envelope["results"][1]


def test_payloads_without_pages_keep_their_shape() -> None:
    payload = {"urls": ["https://example.org/a"], "sitemaps": []}
    envelope = engine.build_envelope("map", payload)
    assert envelope["results"] == [payload]


def test_doctor_report_lists_dependencies_and_hints() -> None:
    report = engine.doctor_report()
    names = {item["name"] for item in report["checks"]}
    assert {"requests", "beautifulsoup4", "trafilatura", "playwright", "pypdf"} <= names
    assert report["ok"] is True  # core dependencies are installed in this suite
    playwright = next(item for item in report["checks"] if item["name"] == "playwright")
    if not playwright["ok"]:
        assert "pip install playwright" in playwright["hint"]


def test_cli_doctor_action_reports_json() -> None:
    result = subprocess.run(
        [sys.executable, str(PLUGIN_ROOT / "run.py"), "--action", "doctor"],
        cwd=str(PLUGIN_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["action"] == "doctor"
    assert payload["ok"] is True
    assert isinstance(payload["checks"], list)
