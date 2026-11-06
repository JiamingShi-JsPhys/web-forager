"""Shared fixtures.

The integration tests spin up a temporary local HTTP site so the suite never
touches the public network.
"""

from __future__ import annotations

import functools
import http.server
import sys
import threading
from pathlib import Path
from typing import Iterator

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args: object) -> None:
        pass


@pytest.fixture(scope="session")
def site(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    root = tmp_path_factory.mktemp("site")
    (root / "robots.txt").write_text(
        "User-agent: *\nDisallow: /private/\nAllow: /private/public/\nCrawl-delay: 0\n",
        encoding="utf-8",
    )
    (root / "index.html").write_text(
        (FIXTURES / "article.html").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "table.html").write_text(
        (FIXTURES / "table.html").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "data.bin").write_bytes(bytes([0, 1, 2]))
    (root / "bili_home.html").write_text(
        (FIXTURES / "bili_cards.html").read_text(encoding="utf-8"), encoding="utf-8"
    )
    video_dir = root / "video" / "BV1xx411c7mD"
    video_dir.mkdir(parents=True)
    (video_dir / "index.html").write_text(
        (FIXTURES / "bili_video.html").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "private").mkdir()
    (root / "private" / "secret.html").write_text(
        "<html><body><p>secret</p></body></html>", encoding="utf-8"
    )

    handler = functools.partial(_QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
