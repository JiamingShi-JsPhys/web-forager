"""The dedicated-profile launcher prints what it would run, without Chrome."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]


def test_launcher_dry_run_names_the_profile_and_port() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "browser" / "launch_chrome.py"),
            "--dry-run",
            "--chrome",
            "C:/Program Files/Google/Chrome/Application/chrome.exe",
            "--profile",
            "C:/tmp/wf profile",
            "--port",
            "9333",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0
    assert "--user-data-dir=" in result.stdout
    assert "wf profile" in result.stdout
    assert "--remote-debugging-port=9333" in result.stdout
    assert "WEB_FORAGER_BROWSER_CDP=http://127.0.0.1:9333" in result.stdout
