"""Sitemap discovery: robots.txt ``Sitemap:`` lines and sitemap indexes.

Sitemaps are published specifically for crawlers, so they are fetched without
a per-URL robots check.  Every discovered page URL is still checked against
robots.txt by :func:`engine.fetch_page` before its content is read.
"""

from __future__ import annotations

import gzip
import urllib.parse
from typing import Any, Optional

from . import engine


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _decode_sitemap(response: engine.HttpResponse) -> str:
    raw = response.content
    # Some servers answer .xml.gz URLs with plain XML, so trust the magic bytes
    # rather than the URL suffix.
    if raw[:2] == b"\x1f\x8b":
        try:
            raw = gzip.decompress(raw)
        except OSError as exc:
            raise engine.FetchError(f"cannot decompress sitemap: {exc}") from exc
    return raw.decode(response.encoding or "utf-8", errors="replace")


def parse_sitemap(xml_text: str, limit: int = 5_000) -> dict[str, list[dict[str, str]]]:
    """Parse a urlset or sitemapindex into URL/sitemap entries."""

    root = engine.parse_xml(xml_text)
    kind = _local(root.tag)
    urls: list[dict[str, str]] = []
    sitemaps: list[dict[str, str]] = []

    if kind == "sitemapindex":
        for node in root:
            if _local(node.tag) != "sitemap":
                continue
            loc = ""
            lastmod = ""
            for child in node:
                name = _local(child.tag)
                if name == "loc":
                    loc = (child.text or "").strip()
                elif name == "lastmod":
                    lastmod = (child.text or "").strip()
            if loc:
                sitemaps.append({"url": loc, "lastmod": lastmod})
    elif kind == "urlset":
        for node in root:
            if _local(node.tag) != "url":
                continue
            entry = {"url": "", "lastmod": "", "changefreq": "", "priority": ""}
            for child in node:
                name = _local(child.tag)
                if name == "loc":
                    entry["url"] = (child.text or "").strip()
                elif name in entry:
                    entry[name] = (child.text or "").strip()
            if entry["url"]:
                urls.append(entry)
            if len(urls) >= limit:
                break
    else:
        raise engine.FetchError(f"not a sitemap: unexpected root element {root.tag}")

    return {"urls": urls[:limit], "sitemaps": sitemaps}


def discover(
    url: str,
    config: Optional[engine.FetchConfig] = None,
    limit: int = 500,
    max_sitemaps: int = 5,
    fetcher: Optional[engine.HttpFetcher] = None,
) -> dict[str, Any]:
    """Find sitemap URLs for a site and return their page URLs."""

    config = config or engine.FetchConfig()
    seed = engine.normalize_url(url)
    parsed = urllib.parse.urlsplit(seed)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    lowered = seed.lower().split("?", 1)[0]

    own_fetcher = fetcher is None
    fetcher = fetcher or engine.HttpFetcher(config)
    errors: list[str] = []
    candidates: list[str] = []
    sources: list[str] = []

    def add_candidate(value: str, source: str) -> None:
        value = value.strip()
        if not value:
            return
        if not value.lower().startswith(("http://", "https://")):
            value = urllib.parse.urljoin(origin + "/", value)
        if value not in candidates:
            candidates.append(value)
            sources.append(source)

    try:
        if lowered.endswith((".xml", ".xml.gz", ".txt")) or "sitemap" in lowered:
            add_candidate(seed, "seed")
        else:
            robots_url = origin + "/robots.txt"
            try:
                robots = fetcher.fetch(robots_url, check_robots=False).text
                for line in robots.splitlines():
                    if line.lower().startswith("sitemap:"):
                        add_candidate(line.split(":", 1)[1], "robots.txt")
            except engine.FetchError as exc:
                errors.append(f"robots.txt: {exc}")
            add_candidate(origin + "/sitemap.xml", "fallback")
            add_candidate(origin + "/sitemap_index.xml", "fallback")
            add_candidate(origin + "/sitemap.xml.gz", "fallback")

        pages: list[dict[str, str]] = []
        seen_pages: set[str] = set()
        visited_maps: set[str] = set()
        queue = list(candidates[:max_sitemaps])
        while queue and len(pages) < limit and len(visited_maps) < max_sitemaps:
            sitemap_url = queue.pop(0)
            if sitemap_url in visited_maps:
                continue
            visited_maps.add(sitemap_url)
            try:
                response = fetcher.fetch(sitemap_url, check_robots=False)
                parsed_map = parse_sitemap(_decode_sitemap(response), limit=limit)
            except (engine.FetchError, engine.ExtractionError) as exc:
                errors.append(f"{sitemap_url}: {exc}")
                continue
            for entry in parsed_map["urls"]:
                page_url = entry["url"].strip()
                if not page_url or page_url in seen_pages:
                    continue
                seen_pages.add(page_url)
                pages.append(entry)
                if len(pages) >= limit:
                    break
            for entry in parsed_map["sitemaps"]:
                if entry["url"] not in visited_maps and len(queue) < max_sitemaps * 2:
                    queue.append(entry["url"])

        note = "" if pages else "no sitemap was found for this site"
        return {
            "seed": seed,
            "origin": origin,
            "candidates": candidates,
            "sources": sources,
            "sitemaps_read": sorted(visited_maps),
            "count": len(pages),
            "urls": pages,
            "errors": errors,
            "note": note,
        }
    finally:
        if own_fetcher:
            fetcher.close()


def to_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Sitemap: {payload.get('origin', '')}",
        "",
        f"> {payload.get('count', 0)} URL(s) from {len(payload.get('sitemaps_read') or [])} sitemap(s)",
        "",
    ]
    for entry in payload.get("urls") or []:
        suffix = f" — {entry['lastmod']}" if entry.get("lastmod") else ""
        lines.append(f"- {entry['url']}{suffix}")
    if payload.get("errors"):
        lines.extend(["", "## Errors", ""])
        lines.extend(f"- {error}" for error in payload["errors"])
    return "\n".join(lines).strip()
