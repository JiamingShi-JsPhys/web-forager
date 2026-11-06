"""RSS 2.0 / Atom / RSS 1.0 feed parsing.

Feeds are structured XML, so they are far cheaper to read than the rendered
HTML of a blog index.  Parsing goes through :func:`engine.parse_xml`, which
rejects DOCTYPE/ENTITY and uses defusedxml when available.
"""

from __future__ import annotations

import html as html_lib
import re
from typing import Any

from . import engine

_ATOM = "{http://www.w3.org/2005/Atom}"
_RSS1 = "{http://purl.org/rss/1.0/}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}"


def _clean(value: Any, limit: int = 1200) -> str:
    text = html_lib.unescape(str(value or ""))
    if "<" in text:
        text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _text(node: Any, path: str = "") -> str:
    target = node.find(path) if path else node
    return (target.text or "").strip() if target is not None else ""


def _atom_link(entry: Any) -> str:
    fallback = ""
    for link in entry.findall(f"{_ATOM}link"):
        href = link.get("href", "")
        if link.get("rel", "alternate") == "alternate":
            return href
        fallback = fallback or href
    return fallback


def _atom_entry(entry: Any) -> dict[str, Any]:
    return {
        "title": _clean(_text(entry, f"{_ATOM}title"), 300),
        "url": _atom_link(entry),
        "published": _text(entry, f"{_ATOM}published") or _text(entry, f"{_ATOM}updated"),
        "summary": _clean(
            _text(entry, f"{_ATOM}summary") or _text(entry, f"{_ATOM}content")
        ),
        "authors": [
            _clean(_text(author, f"{_ATOM}name"), 120)
            for author in entry.findall(f"{_ATOM}author")
            if _text(author, f"{_ATOM}name")
        ],
        "categories": [
            category.get("term", "")
            for category in entry.findall(f"{_ATOM}category")
            if category.get("term")
        ],
    }


def _rss_item(item: Any, rss1: bool = False) -> dict[str, Any]:
    ns = _RSS1 if rss1 else ""
    summary = _text(item, f"{ns}description")
    if not summary:
        summary = _text(item, f"{_CONTENT}encoded")
    author = _text(item, f"{_DC}creator") or _text(item, f"{ns}author")
    return {
        "title": _clean(_text(item, f"{ns}title"), 300),
        "url": _text(item, f"{ns}link") or _text(item, f"{ns}guid"),
        "published": _text(item, f"{ns}pubDate") or _text(item, f"{_DC}date"),
        "summary": _clean(summary),
        "authors": [_clean(author, 120)] if author else [],
        "categories": [
            _clean(category.text, 80)
            for category in item.findall(f"{ns}category")
            if _clean(category.text)
        ],
    }


def is_feed(xml_text: str) -> bool:
    """Cheaply decide whether an XML payload is an RSS/Atom feed."""

    head = xml_text.lstrip()[:2000].lower()
    if not head.startswith("<?xml") and not head.startswith("<rss") and not head.startswith("<feed"):
        return False
    try:
        root = engine.parse_xml(xml_text)
    except engine.FetchError:
        return False
    tag = root.tag.lower()
    return tag == "rss" or tag.endswith("}feed") or tag.endswith("}rdf")


def extract(xml_text: str, limit: int = 50) -> dict[str, Any]:
    """Parse a feed and return a Markdown digest plus structured items."""

    root = engine.parse_xml(xml_text)
    tag = root.tag.lower()
    if tag.endswith("}feed") or tag == "feed":
        feed_format = "atom"
        channel = root
        entries = root.findall(f"{_ATOM}entry")[:limit]
        items = [_atom_entry(entry) for entry in entries]
        title = _clean(_text(channel, f"{_ATOM}title"), 300)
        site_url = _atom_link(channel)
        description = _clean(_text(channel, f"{_ATOM}subtitle"))
    elif tag == "rss":
        feed_format = "rss"
        channel = root.find("channel")
        if channel is None:
            raise engine.ExtractionError("RSS feed has no channel element")
        items = [_rss_item(item) for item in channel.findall("item")[:limit]]
        title = _clean(_text(channel, "title"), 300)
        site_url = _text(channel, "link")
        description = _clean(_text(channel, "description"))
    elif tag.endswith("}rdf"):
        feed_format = "rss1"
        channel = root.find(f"{_RSS1}channel")
        items = [_rss_item(item, rss1=True) for item in root.findall(f"{_RSS1}item")[:limit]]
        title = _clean(_text(channel, f"{_RSS1}title") if channel is not None else "", 300)
        site_url = _text(channel, f"{_RSS1}link") if channel is not None else ""
        description = _clean(_text(channel, f"{_RSS1}description") if channel is not None else "")
    else:
        raise engine.ExtractionError(f"not a feed: unexpected root element {root.tag}")

    lines = [f"# {title or 'Feed'}", ""]
    if description:
        lines.extend([description, ""])
    if site_url:
        lines.extend([f"> {site_url}", ""])
    for index, item in enumerate(items, start=1):
        lines.append(f"## {index}. {item['title'] or item['url'] or 'Untitled'}")
        if item["published"]:
            lines.append(f"**Published:** {item['published']}")
        if item["authors"]:
            lines.append(f"**Authors:** {', '.join(item['authors'])}")
        if item["url"]:
            lines.append(f"**URL:** {item['url']}")
        if item["summary"]:
            lines.extend(["", item["summary"]])
        lines.append("")

    return {
        "kind": "feed",
        "format": feed_format,
        "title": title,
        "site_url": site_url,
        "description": description,
        "count": len(items),
        "items": items,
        "markdown": "\n".join(lines).strip(),
    }


def to_metadata(document: dict[str, Any], url: str = "") -> dict[str, Any]:
    return {
        "title": document.get("title", ""),
        "authors": [],
        "published": "",
        "modified": "",
        "journal": "",
        "volume": "",
        "issue": "",
        "first_page": "",
        "last_page": "",
        "doi": "",
        "arxiv_id": "",
        "abstract": document.get("description", ""),
        "keywords": [],
        "language": "",
        "site_name": document.get("format", "feed"),
        "canonical_url": url or document.get("site_url", ""),
        "og_type": "feed",
    }
