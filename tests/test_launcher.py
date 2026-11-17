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
    assert "--remote-debugging-address=127.0.0.1" in result.stdout
    assert "WEB_FORAGER_BROWSER_CDP=http://127.0.0.1:9333" in result.stdout


def test_launcher_cdp_is_off_by_default() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "browser" / "launch_chrome.py"),
            "--dry-run",
            "--chrome",
            "C:/Program Files/Google/Chrome/Application/chrome.exe",
            "--profile",
            "C:/tmp/wf profile",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0
    assert "--remote-debugging-port" not in result.stdout
    assert "--remote-debugging-address" not in result.stdout
    assert "WEB_FORAGER_BROWSER_CDP" not in result.stdout
    assert "CDP is off" in result.stdout


def test_launcher_cdp_uses_a_random_loopback_port_when_asked() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(PLUGIN_ROOT / "browser" / "launch_chrome.py"),
            "--dry-run",
            "--cdp",
            "--chrome",
            "C:/Program Files/Google/Chrome/Application/chrome.exe",
            "--profile",
            "C:/tmp/wf profile",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0
    assert "--remote-debugging-address=127.0.0.1" in result.stdout
    assert "--remote-debugging-port=0" not in result.stdout
    assert "WEB_FORAGER_BROWSER_CDP=http://127.0.0.1:" in result.stdout
    assert "CDP has no authentication" in result.stderr
