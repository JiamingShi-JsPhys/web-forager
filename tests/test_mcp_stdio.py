"""stdio encoding tests for the MCP server.

Windows hosts sometimes launch ``python`` with an ANSI code page as the stdio
encoding.  A Chinese payload then raised ``UnicodeEncodeError`` and killed the
server mid-call, which is exactly what happened under ZCode on 2026-11-06.
"""

from __future__ import annotations

import io

import mcp_server


class Cp1252Sink:
    """Mimics a stdout that can only encode cp1252."""

    encoding = "cp1252"

    def __init__(self) -> None:
        self.data = ""

    def write(self, text: str) -> int:
        text.encode("cp1252")  # raises UnicodeEncodeError for CJK
        self.data += text
        return len(text)

    def flush(self) -> None:
        return None


def test_utf8_stream_reconfigures_a_cp1252_stream() -> None:
    stream = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    assert stream.encoding == "cp1252"
    mcp_server._utf8_stream(stream)
    assert stream.encoding == "utf-8"


def test_serve_falls_back_to_ascii_escapes(monkeypatch) -> None:
    monkeypatch.setattr(
        mcp_server,
        "handle_request",
        lambda request: {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {"content": [{"type": "text", "text": "西湖大学"}]},
        },
    )
    sink = Cp1252Sink()
    code = mcp_server.serve(stdin=['{"jsonrpc":"2.0","id":1,"method":"probe"}'], stdout=sink)

    assert code == 0
    assert "\\u897f\\u6e56\\u5927\\u5b66" in sink.data
    assert "\n" in sink.data
