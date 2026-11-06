"""Bilibili site adapter — robots-compliant HTML extraction.

Why HTML instead of the JSON API?
---------------------------------
``https://api.bilibili.com/robots.txt`` disallows every path for generic
agents (``User-agent: * / Disallow: /``).  We therefore read the public pages
that robots.txt *does* allow:

* ``https://www.bilibili.com/``            — home feed, server-rendered cards
* ``https://www.bilibili.com/video/BV…``   — video page, embedded
  ``window.__INITIAL_STATE__`` JSON

Keyword search is resolved through Bing, then filtered to Bilibili video URLs.
The direct search page (``search.bilibili.com``) is disallowed by its own
robots.txt and is only used when the caller explicitly disables robots checks.

No third-party package beyond requests / beautifulsoup4 is used here.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from . import engine

BILI_HOME = "https://www.bilibili.com/"
BILI_VIDEO = "https://www.bilibili.com/video/{bvid}/"
BILI_SEARCH = "https://search.bilibili.com/all?keyword={query}"

_BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
_AV_RE = re.compile(r"\bav(\d+)\b", re.I)
_TITLE_SUFFIX_RE = re.compile(r"[_\-|]\s*哔哩哔哩.*$", re.I)



# ---------------------------------------------------------------------------
# Identifiers and formatting
# ---------------------------------------------------------------------------


def extract_bvid(value: str) -> str:
    """Return a BV id from a URL, a bare BV id, or an av number."""

    text = str(value or "").strip()
    match = _BV_RE.search(text)
    if match:
        return match.group(1)
    match = _AV_RE.search(text)
    if match:
        return f"av{match.group(1)}"
    raise engine.InvalidURLError(f"no Bilibili video id found in: {value!r}")


def video_url(bvid_or_url: str) -> str:
    text = str(bvid_or_url or "").strip()
    if text.lower().startswith(("http://", "https://")):
        return engine.normalize_url(text)
    bvid = extract_bvid(text)
    if bvid.startswith("av"):
        return f"https://www.bilibili.com/video/{bvid}/"
    return BILI_VIDEO.format(bvid=bvid)


def is_video_url(url: str) -> bool:
    try:
        parts = engine.normalize_url(url)
    except engine.InvalidURLError:
        return False
    return "bilibili.com" in parts and "/video/" in parts


def is_b23_url(url: str) -> bool:
    try:
        parts = engine.normalize_url(url)
    except engine.InvalidURLError:
        return False
    return "b23.tv" in parts


def format_duration(seconds: Any) -> str:
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return ""
    if total < 0:
        return ""
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _iso_timestamp(value: Any) -> str:
    try:
        stamp = int(value)
    except (TypeError, ValueError):
        return ""
    if stamp <= 0:
        return ""
    return datetime.fromtimestamp(stamp, tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_title(value: str) -> str:
    text = engine._clean_result_text(value)
    return _TITLE_SUFFIX_RE.sub("", text).strip()


# ---------------------------------------------------------------------------
# Embedded JSON
# ---------------------------------------------------------------------------


def _balanced_json(text: str, start: int) -> str:
    """Return the balanced JSON object beginning at ``start``."""

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return ""


def extract_initial_state(html: str) -> dict[str, Any]:
    """Extract ``window.__INITIAL_STATE__ = {...}`` from a Bilibili page."""

    if not html:
        return {}
    marker = "__INITIAL_STATE__"
    position = html.find(marker)
    while position != -1:
        equals = html.find("=", position)
        brace = html.find("{", equals)
        if equals != -1 and brace != -1 and brace - equals < 40:
            payload = _balanced_json(html, brace)
            if payload:
                try:
                    data = json.loads(payload)
                except json.JSONDecodeError:
                    data = None
                if isinstance(data, dict):
                    return data
        position = html.find(marker, position + len(marker))
    return {}


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------


_DEAD_TITLES = ("视频已失效", "已失效视频", "该视频已失效", "视频失效", "稿件不可见")


def _is_dead_video(item: dict[str, Any]) -> bool:
    title = re.sub(r"\s+", "", str(item.get("title") or ""))
    if any(marker in title for marker in _DEAD_TITLES):
        return True
    # A non-empty redirect field usually means the original video is gone.
    return bool(item.get("redirect_url") or item.get("redirected_url"))


def _related_items(raw: Iterable[Any]) -> list[dict[str, Any]]:
    related: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        bvid = item.get("bvid") or ""
        if not bvid or bvid in seen:
            continue
        if _is_dead_video(item):
            continue
        seen.add(bvid)
        owner = item.get("owner") or {}
        stat = item.get("stat") or {}
        related.append(
            {
                "bvid": bvid,
                "url": BILI_VIDEO.format(bvid=bvid),
                "title": clean_title(item.get("title") or ""),
                "uploader": owner.get("name") or "",
                "duration": format_duration(item.get("duration")),
                "duration_seconds": item.get("duration") or 0,
                "view": stat.get("view") or 0,
                "cover": item.get("pic") or "",
            }
        )
    return related


def parse_video_state(state: dict[str, Any], url: str = "") -> dict[str, Any]:
    """Normalise the embedded video state into a stable record."""

    data = state.get("videoData") or {}
    if not isinstance(data, dict) or not data:
        return {}

    owner = data.get("owner") or {}
    stat = data.get("stat") or {}
    bvid = data.get("bvid") or (extract_bvid(url) if url else "")
    pages = data.get("pages") or []
    parts = [
        {
            "page": page.get("page"),
            "title": page.get("part") or "",
            "duration_seconds": page.get("duration") or 0,
            "duration": format_duration(page.get("duration")),
        }
        for page in pages
        if isinstance(page, dict)
    ]

    tags: list[str] = []
    for tag in state.get("tags") or []:
        if isinstance(tag, dict):
            name = tag.get("tag_name") or tag.get("name")
            if name:
                tags.append(str(name))
        elif isinstance(tag, str):
            tags.append(tag)

    related = _related_items(state.get("related") or data.get("related") or [])

    record: dict[str, Any] = {
        "bvid": bvid,
        "aid": data.get("aid"),
        "url": BILI_VIDEO.format(bvid=bvid) if bvid and not url else (url or ""),
        "title": clean_title(data.get("title") or ""),
        "description": (data.get("desc") or "").strip(),
        "uploader": {
            "name": owner.get("name") or "",
            "mid": owner.get("mid"),
            "url": f"https://space.bilibili.com/{owner.get('mid')}" if owner.get("mid") else "",
        },
        "published": _iso_timestamp(data.get("pubdate")),
        "published_ts": data.get("pubdate") or 0,
        "duration": format_duration(data.get("duration")),
        "duration_seconds": data.get("duration") or 0,
        "category": data.get("tname") or "",
        "cover": data.get("pic") or "",
        "stats": {
            "view": stat.get("view") or 0,
            "danmaku": stat.get("danmaku") or 0,
            "reply": stat.get("reply") or 0,
            "favorite": stat.get("favorite") or 0,
            "coin": stat.get("coin") or 0,
            "share": stat.get("share") or 0,
            "like": stat.get("like") or 0,
        },
        "parts": parts,
        "tags": tags,
        "related": related,
    }
    record["markdown"] = video_markdown(record)
    return record


def video_markdown(record: dict[str, Any]) -> str:
    lines: list[str] = [f"# {record.get('title') or record.get('bvid') or 'Bilibili video'}", ""]
    uploader = (record.get("uploader") or {}).get("name") or ""
    stats = record.get("stats") or {}
    meta = " ｜ ".join(
        part
        for part in (
            f"UP主：{uploader}" if uploader else "",
            f"发布：{record.get('published', '')[:10]}" if record.get("published") else "",
            f"时长：{record.get('duration')}" if record.get("duration") else "",
            f"播放：{stats.get('view')}" if stats.get("view") else "",
            f"弹幕：{stats.get('danmaku')}" if stats.get("danmaku") else "",
        )
        if part
    )
    if meta:
        lines.extend([f"> {meta}", ""])
    if record.get("description"):
        lines.extend([record["description"], ""])
    parts = record.get("parts") or []
    if len(parts) > 1:
        lines.append("## 分P")
        lines.append("")
        for part in parts:
            lines.append(f"- P{part.get('page')} {part.get('title')} ({part.get('duration')})")
        lines.append("")
    related = record.get("related") or []
    if related:
        lines.append("## 相关推荐")
        lines.append("")
        for item in related[:20]:
            suffix = f" · UP主：{item['uploader']}" if item.get("uploader") else ""
            lines.append(f"- [{item['title']}]({item['url']}){suffix}")
        lines.append("")
    return "\n".join(lines).strip()


def parse_video_cards(html: str, base: str = BILI_HOME, limit: int = 20) -> list[dict[str, Any]]:
    """Parse ``.bili-video-card`` blocks from the home page or search page."""

    soup = engine.make_soup(html)
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()

    for card in soup.select(".bili-video-card"):
        anchor = card.select_one("a[href*='/video/']")
        if not anchor:
            continue
        href = engine._attr_text(anchor, "href")
        url = engine.absolute_url(href, base)
        if not url:
            continue
        try:
            bvid = extract_bvid(url)
        except engine.InvalidURLError:
            continue
        if bvid in seen:
            continue
        seen.add(bvid)

        title_tag = card.select_one(".bili-video-card__info--tit")
        title = ""
        if title_tag is not None:
            title = engine._attr_text(title_tag, "title") or title_tag.get_text(" ", strip=True)
        if not title:
            title = engine._attr_text(anchor, "title") or anchor.get_text(" ", strip=True)
        title = clean_title(title)

        author_tag = card.select_one(".bili-video-card__info--author")
        author = author_tag.get_text(" ", strip=True) if author_tag is not None else ""

        duration_tag = card.select_one(".bili-video-card__stats__duration")
        duration = duration_tag.get_text(" ", strip=True) if duration_tag is not None else ""

        stat_items = [
            item.get_text(" ", strip=True) for item in card.select(".bili-video-card__stats--item")
        ]
        date_tag = card.select_one(".bili-video-card__info--date")
        published_text = date_tag.get_text(" ", strip=True) if date_tag is not None else ""
        cover_tag = card.select_one("img")
        cover = engine._attr_text(cover_tag, "src") if cover_tag is not None else ""

        cards.append(
            {
                "bvid": bvid,
                "url": BILI_VIDEO.format(bvid=bvid),
                "title": title,
                "uploader": author,
                "duration": duration,
                "published_text": published_text,
                "stats_text": stat_items,
                "cover": engine.absolute_url(cover, base) if cover else "",
                "markdown": f"- [{title}]({BILI_VIDEO.format(bvid=bvid)})"
                + (f" · UP主：{author}" if author else "")
                + (f" · {duration}" if duration else "")
                + (f" · {published_text}" if published_text else ""),
            }
        )
        if len(cards) >= limit:
            break
    return cards


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def _metadata_from_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": record.get("title", ""),
        "authors": [record.get("uploader", {}).get("name", "")] if record.get("uploader", {}).get("name") else [],
        "published": record.get("published", ""),
        "modified": "",
        "journal": "bilibili",
        "volume": "",
        "issue": "",
        "first_page": "",
        "last_page": "",
        "doi": "",
        "arxiv_id": "",
        "abstract": record.get("description", ""),
        "keywords": record.get("tags", []),
        "language": "zh-CN",
        "site_name": "bilibili",
        "canonical_url": record.get("url", ""),
        "og_type": "video",
    }


def _fetch_raw(url: str, fetcher: engine.HttpFetcher) -> engine.HttpResponse:
    return fetcher.fetch(url)


def fetch_video(
    target: str,
    config: Optional[engine.FetchConfig] = None,
    fetcher: Optional[engine.HttpFetcher] = None,
) -> dict[str, Any]:
    """Fetch one Bilibili video page and return a normalised record."""

    config = config or engine.FetchConfig()
    own_fetcher = fetcher is None
    fetcher = fetcher or engine.HttpFetcher(config)

    try:
        text = str(target or "").strip()
        if text.lower().startswith(("http://", "https://")):
            url = engine.normalize_url(text)
        else:
            url = video_url(text)

        response = _fetch_raw(url, fetcher)
        final_url = response.final_url

        if is_b23_url(final_url):
            # b23.tv redirects to the canonical video page.
            response = _fetch_raw(final_url, fetcher)
            final_url = response.final_url

        record = parse_video_state(extract_initial_state(response.text), final_url)
        if not record:
            metadata = engine.extract_metadata(response.text, url=final_url)
            markdown = engine.html_to_markdown(response.text, url=final_url)
            record = {
                "bvid": extract_bvid(final_url) if _BV_RE.search(final_url) else "",
                "aid": None,
                "url": final_url,
                "title": metadata.get("title", ""),
                "description": metadata.get("abstract", ""),
                "uploader": {"name": "", "mid": None, "url": ""},
                "published": metadata.get("published", ""),
                "published_ts": 0,
                "duration": "",
                "duration_seconds": 0,
                "category": "",
                "cover": "",
                "stats": {},
                "parts": [],
                "tags": metadata.get("keywords", []),
                "related": [],
                "markdown": markdown,
                "fallback": True,
                "warnings": ["embedded __INITIAL_STATE__ not found; used generic extraction"],
            }

        record.setdefault("warnings", [])
        record["metadata"] = _metadata_from_record(record)
        record["final_url"] = final_url
        record["fetched_at"] = engine.utc_now()
        return record
    finally:
        if own_fetcher:
            fetcher.close()


def feed(
    config: Optional[engine.FetchConfig] = None,
    limit: int = 20,
    enrich: int = 0,
    url: str = BILI_HOME,
    fetcher: Optional[engine.HttpFetcher] = None,
) -> dict[str, Any]:
    """Read the server-rendered home feed (robots.txt permits ``/``)."""

    config = config or engine.FetchConfig()
    own_fetcher = fetcher is None
    fetcher = fetcher or engine.HttpFetcher(config)

    try:
        response = fetcher.fetch(url)
        cards = parse_video_cards(response.text, base=response.final_url, limit=limit)
        videos: list[dict[str, Any]] = []
        for card in cards[: max(0, enrich)]:
            try:
                videos.append(fetch_video(card["url"], config, fetcher=fetcher))
            except (engine.RobotsDenied, engine.FetchError, engine.ExtractionError) as exc:
                card["error"] = f"{exc.__class__.__name__}: {exc}"
        return {
            "mode": "feed",
            "source": response.final_url,
            "cards": cards,
            "videos": videos,
            "results": videos or cards,
        }
    finally:
        if own_fetcher:
            fetcher.close()


def _search_via_engines(
    query: str, config: engine.FetchConfig, fetcher: engine.HttpFetcher
) -> list[dict[str, Any]]:
    """Best-effort discovery: ask the web search engines, keep Bilibili video URLs."""

    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for search_query in (f"哔哩哔哩 {query}", f"B站 {query} 视频"):
        try:
            results = engine.search(
                search_query,
                config,
                engine=config.search_engine,
                limit=config.num_results,
                fetcher=fetcher,
            )
        except engine.FetchError:
            continue
        for item in results:
            url = item.get("url", "")
            if "bilibili.com" not in url or "/video/" not in url:
                continue
            try:
                bvid = extract_bvid(url)
            except engine.InvalidURLError:
                continue
            if bvid in seen:
                continue
            seen.add(bvid)
            candidates.append(
                {
                    "bvid": bvid,
                    "url": BILI_VIDEO.format(bvid=bvid),
                    "title": clean_title(item.get("title", "")),
                    "snippet": item.get("snippet", ""),
                    "source": item.get("source", config.search_engine),
                }
            )
        if len(candidates) >= config.num_results:
            break
    return candidates


def _search_direct(
    query: str,
    config: engine.FetchConfig,
    fetcher: engine.HttpFetcher,
    check_robots: bool = True,
) -> list[dict[str, Any]]:
    """Query search.bilibili.com directly.

    ``check_robots=True`` raises RobotsDenied because that host disallows all
    generic agents.  ``--direct-search`` narrows the override to this one
    query; video pages are still fetched with robots checks enabled.
    """

    import urllib.parse

    url = BILI_SEARCH.format(query=urllib.parse.quote_plus(query))
    response = fetcher.fetch(url, check_robots=check_robots)
    return parse_video_cards(response.text, base=response.final_url, limit=config.num_results)


def search(
    query: str,
    config: Optional[engine.FetchConfig] = None,
    fetcher: Optional[engine.HttpFetcher] = None,
    allow_direct: bool = False,
) -> dict[str, Any]:
    """Search Bilibili videos and optionally fetch the top results."""

    config = config or engine.FetchConfig()
    query = (query or "").strip()
    if not query:
        raise ValueError("query must not be empty")

    own_fetcher = fetcher is None
    fetcher = fetcher or engine.HttpFetcher(config)

    try:
        if not config.respect_robots:
            cards = _search_direct(query, config, fetcher, check_robots=False)
            route = "search.bilibili.com"
            note = "direct search page used because robots checks are disabled globally"
        elif allow_direct:
            cards = _search_direct(query, config, fetcher, check_robots=False)
            route = "search.bilibili.com"
            note = (
                "direct search page used because --direct-search was passed; "
                "search.bilibili.com disallows generic agents in robots.txt"
            )
        else:
            cards = _search_via_engines(query, config, fetcher)
            route = f"search:{config.search_engine}"
            note = (
                "search.bilibili.com disallows all agents in robots.txt; "
                f"results were resolved through the {config.search_engine} search backend "
                "and filtered to Bilibili video URLs"
            )
            if not cards:
                note += (
                    "; the search engine returned no video URLs — pass --url with a seed video, "
                    "or --direct-search to query the Bilibili search page explicitly"
                )

        videos: list[dict[str, Any]] = []
        for card in cards[: max(0, config.max_pages)]:
            try:
                videos.append(fetch_video(card["url"], config, fetcher=fetcher))
            except (engine.RobotsDenied, engine.FetchError, engine.ExtractionError) as exc:
                card["error"] = f"{exc.__class__.__name__}: {exc}"

        return {
            "mode": "search",
            "query": query,
            "route": route,
            "note": note,
            "search_results": cards,
            "videos": videos,
            "results": videos or cards,
        }
    finally:
        if own_fetcher:
            fetcher.close()


def related(
    target: str,
    config: Optional[engine.FetchConfig] = None,
    limit: Optional[int] = None,
    enrich: int = 0,
    fetcher: Optional[engine.HttpFetcher] = None,
) -> dict[str, Any]:
    """Return the recommendation list of one video."""

    config = config or engine.FetchConfig()
    own_fetcher = fetcher is None
    fetcher = fetcher or engine.HttpFetcher(config)

    try:
        record = fetch_video(target, config, fetcher=fetcher)
        items = record.get("related", [])[: limit or config.num_results]
        videos: list[dict[str, Any]] = []
        for item in items[: max(0, enrich)]:
            try:
                videos.append(fetch_video(item["url"], config, fetcher=fetcher))
            except (engine.RobotsDenied, engine.FetchError, engine.ExtractionError) as exc:
                item["error"] = f"{exc.__class__.__name__}: {exc}"
        return {
            "mode": "related",
            "seed": record,
            "related": items,
            "videos": videos,
            "results": videos or items,
        }
    finally:
        if own_fetcher:
            fetcher.close()


def surf(
    seed: str,
    config: Optional[engine.FetchConfig] = None,
    depth: int = 1,
    per_level: Optional[int] = None,
    fetcher: Optional[engine.HttpFetcher] = None,
    allow_direct: bool = False,
) -> dict[str, Any]:
    """Walk the recommendation graph from a video or a keyword query."""

    config = config or engine.FetchConfig()
    own_fetcher = fetcher is None
    fetcher = fetcher or engine.HttpFetcher(config)
    per_level = per_level or config.max_pages

    try:
        text = str(seed or "").strip()
        seeds: list[str] = []
        search_payload: dict[str, Any] | None = None
        if text.lower().startswith(("http://", "https://")) or _BV_RE.search(text) or _AV_RE.search(text):
            seeds = [video_url(text)]
        else:
            search_payload = search(text, config, fetcher=fetcher, allow_direct=allow_direct)
            seeds = [card["url"] for card in search_payload.get("search_results", [])[:per_level]]

        visited: set[str] = set()
        videos: list[dict[str, Any]] = []
        edges: list[dict[str, str]] = []
        queue = seeds

        for _ in range(max(0, depth) + 1):
            next_queue: list[str] = []
            for url in queue:
                try:
                    bvid = extract_bvid(url)
                except engine.InvalidURLError:
                    continue
                if bvid in visited:
                    continue
                visited.add(bvid)
                try:
                    record = fetch_video(url, config, fetcher=fetcher)
                except (engine.RobotsDenied, engine.FetchError, engine.ExtractionError) as exc:
                    videos.append({"url": url, "bvid": bvid, "error": f"{exc.__class__.__name__}: {exc}"})
                    continue
                videos.append(record)
                for item in record.get("related", [])[:per_level]:
                    if item["bvid"] in visited:
                        continue
                    edges.append({"from": record.get("bvid", bvid), "to": item["bvid"], "title": item.get("title", "")})
                    next_queue.append(item["url"])
            queue = next_queue[:per_level]
            if not queue:
                break

        return {
            "mode": "surf",
            "seed": text,
            "depth": depth,
            "search": search_payload,
            "edges": edges,
            "visited": sorted(visited),
            "videos": videos,
            "results": videos,
        }
    finally:
        if own_fetcher:
            fetcher.close()
