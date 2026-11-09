"""The shared core schema (``core-1``) and the ``--core`` flag.

The two modes write different records: HTTP mode returns
``url / final_url / status / fetched_at / ...`` and browser mode returns
``playbook / backend / captured_at / compliance / ...``.  They agree only on
``metadata``, ``markdown``, ``tables`` and ``warnings``.  ``normalize_record``
folds both onto one shape so a caller can read a single list.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from scripts import engine  # noqa: E402

CORE_KEYS = {
    "schema_version",
    "source",
    "mode",
    "url",
    "title",
    "collected_at",
    "metadata",
    "markdown",
    "tables",
    "warnings",
    "extra",
}


def test_normalize_record_folds_both_modes_onto_one_shape() -> None:
    http = engine.normalize_record(
        {
            "url": "https://example.org/a",
            "final_url": "https://example.org/a",
            "status": 200,
            "fetched_at": "2026-11-07T10:00:00Z",
            "title": "A",
            "metadata": {"title": "A"},
            "markdown": "body",
            "tables": [],
            "warnings": ["w"],
            "cached": False,
        }
    )
    browser = engine.normalize_record(
        {
            "source": "web-forager-browser",
            "captured_at": "2026-11-07T11:00:00Z",
            "url": "https://www.bilibili.com/video/BV1aa411c7mD",
            "metadata": {"title": "B"},
            "markdown": "body",
            "tables": [],
            "warnings": [],
            "playbook": "bili-video",
        }
    )

    assert set(http) == CORE_KEYS
    assert set(browser) == CORE_KEYS
    assert http["schema_version"] == "core-1"
    assert http["mode"] == "http"
    assert http["source"] == "web-forager"
    assert http["title"] == "A"
    assert http["extra"]["status"] == 200
    assert browser["mode"] == "browser"
    assert browser["title"] == "B"
    assert browser["extra"]["playbook"] == "bili-video"
    assert browser["collected_at"].startswith("2026-11-07")


def test_normalize_record_tolerates_missing_fields() -> None:
    record = engine.normalize_record({})
    assert set(record) == CORE_KEYS
    assert record["markdown"] == ""
    assert record["tables"] == []
    assert record["warnings"] == []
    assert record["metadata"] == {}


def test_apply_core_replaces_the_results_list_only() -> None:
    envelope = {
        "tool": "web-forager",
        "action": "fetch",
        "query": "x",
        "results": [{"url": "https://example.org/a", "markdown": "m", "metadata": {}}],
    }
    core = engine.apply_core(envelope)
    assert core["tool"] == "web-forager"
    assert core["query"] == "x"
    assert core["results"][0]["schema_version"] == "core-1"


def test_cli_core_flag_emits_core_records() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "run.py"),
            "--action",
            "clean",
            "--input",
            str(FIXTURES / "article.html"),
            "--core",
            "--max-chars",
            "0",
        ],
        cwd=str(PLUGIN_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    document = json.loads(result.stdout)
    record = document["results"][0]
    assert record["schema_version"] == "core-1"
    assert record["mode"] == "http"
    assert "Polite Crawling" in record["markdown"]
    assert record["source"] == "web-forager"
