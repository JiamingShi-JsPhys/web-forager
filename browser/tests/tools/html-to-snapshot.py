#!/usr/bin/env python3
"""Turn a saved HTML page into the DOM snapshot shape the browser bridge emits.

The browser tests must not need a browser, so the fixtures under
``tests/fixtures/snapshots/`` are built from pages captured on the dates named
in each file. This script reproduces the same node selection the reference
Playwright bridge performs: headings, links and short leaf text nodes.

Usage:
    python tests/tools/html-to-snapshot.py <page.html> <out.json> --url URL

The fixtures are committed. Re-run this only when refreshing them against a
live page, and update the capture date in the recording block by hand.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup


def text_of(element) -> str:
    return " ".join(element.get_text(" ", strip=True).split())


def build(html: str, url: str, limit: int = 800) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    nodes: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def push(role: str, name: str, href: str | None = None) -> None:
        if not name or len(nodes) >= limit:
            return
        key = (role, name)
        if key in seen:
            return
        seen.add(key)
        node = {"role": role, "name": name[:300], "locator": f"[data-web-forager-browser-id=\"{len(nodes) + 1}\"]"}
        if href:
            node["href"] = href
        nodes.append(node)

    for element in soup.select("h1, h2, h3, h4"):
        push("heading", text_of(element))

    for element in soup.select("a[href]"):
        href = str(element.get("href") or "")
        if href.startswith(("javascript:", "#")):
            continue
        if href.startswith("/"):
            href = url.rstrip("/") + href
        push("link", text_of(element), href)

    for element in soup.select("p, li, span, div"):
        if element.find(True) is not None:
            continue
        name = text_of(element)
        if len(name) > 4:
            push("text", name)

    return {"url": url, "title": soup.title.get_text(strip=True) if soup.title else "", "nodes": nodes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("html", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--url", required=True)
    parser.add_argument("--limit", type=int, default=800)
    args = parser.parse_args(argv)

    snapshot = build(args.html.read_text(encoding="utf-8", errors="replace"), args.url, args.limit)
    args.out.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"{args.out}: {len(snapshot['nodes'])} nodes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
