#!/usr/bin/env python3
"""Start a Chrome/Chromium with a dedicated profile for browser mode.

The profile is the login state: sign in once in the window this opens, and
later runs reuse it. Nothing here touches the browser you use every day.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def default_profile() -> Path:
    return Path.home() / ".web-forager" / "browser" / "profile"


def candidates() -> list[str]:
    found: list[str] = []
    if sys.platform == "win32":
        roots = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ]
        relative = [
            r"Google\Chrome\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
            r"Chromium\Application\chrome.exe",
        ]
        for root in roots:
            if not root:
                continue
            for tail in relative:
                found.append(str(Path(root) / tail))
    elif sys.platform == "darwin":
        found.extend(
            [
                "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
            ]
        )
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"):
            path = shutil.which(name)
            if path:
                found.append(path)
    return found


def find_chrome(explicit: str = "") -> str:
    if explicit:
        return explicit
    for path in candidates():
        if Path(path).is_file():
            return path
    for name in ("chrome", "google-chrome", "chromium", "msedge"):
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit(
        "Chrome/Chromium not found. Pass --chrome <path>, or install Chrome, "
        "Chromium or Edge first."
    )


def launch_command(chrome: str, profile: Path, port: int | None) -> list[str]:
    command = [
        chrome,
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]
    if port is not None:
        command[2:2] = [
            f"--remote-debugging-port={port}",
            # CDP has no authentication. Keep it on loopback even if Chrome's
            # default changes in a future build.
            "--remote-debugging-address=127.0.0.1",
        ]
    return command


def free_port() -> int:
    """Pick a free loopback port so the debug endpoint is not predictable."""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_for_devtools(port: int, timeout: float = 15.0) -> bool:
    endpoint = f"http://127.0.0.1:{port}/json/version"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(endpoint, timeout=1.0) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if payload.get("webSocketDebuggerUrl"):
                return True
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            pass
        time.sleep(0.25)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--chrome", default="", help="path to chrome.exe / Chrome binary")
    parser.add_argument("--profile", default=str(default_profile()), help="profile directory")
    parser.add_argument(
        "--cdp",
        action="store_true",
        help="opt in to a DevTools port; off by default because CDP has no authentication",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="DevTools port when --cdp is used; 0 picks a free loopback port",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the command and exit")
    parser.add_argument("--timeout", type=float, default=15.0, help="seconds to wait for DevTools")
    args = parser.parse_args(argv)

    chrome = find_chrome(args.chrome)
    profile = Path(args.profile).expanduser().resolve()
    use_cdp = bool(args.cdp or args.port)
    port = (args.port or free_port()) if use_cdp else None
    command = launch_command(chrome, profile, port)

    if args.dry_run:
        print(" ".join(f'"{part}"' if " " in part else part for part in command))
        if port is not None:
            print(f"WEB_FORAGER_BROWSER_CDP=http://127.0.0.1:{port}")
            print(
                "CDP has no authentication; keep this loopback port private and "
                "close the browser when finished.",
                file=sys.stderr,
            )
        else:
            print("CDP is off; pass --cdp to enable it.")
        return 0

    profile.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            profile.chmod(0o700)
        except OSError:
            pass

    child = subprocess.Popen(command, close_fds=True)
    if port is None:
        print(f"Chrome is running with the dedicated profile: {profile}")
        print("CDP is off. Sign in once and close the browser when finished;")
        print("later browser runs reuse the profile. Pass --cdp only if you need")
        print("to attach over DevTools.")
        return 0

    assert port is not None
    if wait_for_devtools(port, timeout=args.timeout):
        print(f"Chrome is ready with the dedicated profile: {profile}")
        print(f"WEB_FORAGER_BROWSER_CDP=http://127.0.0.1:{port}")
        print(
            "CDP has no authentication; keep this loopback port private and "
            "close the browser when finished.",
            file=sys.stderr,
        )
        print("Sign in once in that window; later runs reuse the profile.")
        print("Ctrl+C here stops this launcher; the browser keeps running.")
        return 0

    print(
        f"Chrome started (pid {child.pid}) but DevTools did not answer on port {port}.\n"
        "Close other Chrome windows using the same profile, or choose another --port.",
        file=sys.stderr,
    )
    return 3


if __name__ == "__main__":
    raise SystemExit(main())
