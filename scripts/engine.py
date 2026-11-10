"""web-forager — clean-room web fetching and cleaning engine.

Design notes
------------
This module is an original implementation written from scratch.  It borrows no
source code from Crawlee, Scrapy, or any other crawling framework.  Only general
ideas are reused (politeness delay, a robots-policy cache, an extraction
pipeline); every line below was written for this plugin.

Permitted third-party packages
------------------------------
    requests        Apache-2.0
    beautifulsoup4  MIT
    trafilatura     Apache-2.0   (preferred extractor, optional at runtime)
    playwright      Apache-2.0   (optional, dynamic rendering only)

No GPL / AGPL dependency is used.

Compliance
----------
* robots.txt is always consulted before fetching a target page (RFC 9309
  matching: longest rule wins, ``*`` wildcard, ``$`` end anchor, UA groups).
* Every request carries an explicit information-gathering User-Agent.
* Requests are rate-limited per host; the default delay is one second.
"""

from __future__ import annotations

import base64
import dataclasses
import html as html_lib
import json
import os
import re
import sys
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

__version__ = "1.2.0"

DEFAULT_USER_AGENT = (
    f"WebForager/{__version__} (Information Gathering; "
    "+https://github.com/JiamingShi-JsPhys/web-forager)"
)

DISCLAIMER = (
    "本插件仅供学习与信息收集使用。使用者需遵守目标网站的 Terms of Service 及相关版权法律。"
    "禁止用于恶意并发攻击。严禁收集、聚合或推断特定自然人的个人信息，或将其用于人肉搜索、骚扰、跟踪等侵害他人隐私的活动；此类用法产生的法律责任由使用者自行承担。"
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class WebForagerError(Exception):
    """Base class for all engine errors."""


class InvalidURLError(WebForagerError):
    """The supplied URL is missing, malformed, or uses a forbidden scheme."""


class RobotsDenied(WebForagerError):
    """robots.txt forbids fetching this URL."""


class FetchError(WebForagerError):
    """Network failure, non-success status, or unsupported content type."""


class ExtractionError(WebForagerError):
    """No readable content could be extracted from the document."""


class RenderUnavailable(WebForagerError):
    """Dynamic rendering was requested but Playwright is not usable."""


class PdfUnavailable(WebForagerError):
    """PDF support was requested but pypdf is not usable."""


class PdfExtractionError(WebForagerError):
    """The PDF could not be parsed or contained no text."""


def parse_xml(text: str) -> ET.Element:
    """Parse untrusted XML without XXE or entity-expansion risk.

    ``defusedxml`` is used when it happens to be installed; otherwise the
    input is rejected outright if it declares a DOCTYPE or an ENTITY, which
    blocks both external entities and billion-laughs expansion.
    """

    if "<!ENTITY" in text:
        raise FetchError("refusing XML with ENTITY declarations")
    # An external DTD is harmless here (defusedxml forbids external entities;
    # stdlib ElementTree never fetches the DTD), but an internal subset can
    # declare entities, so only a bare DOCTYPE is stripped.
    doctype = re.search(r"<!DOCTYPE[^>]*>", text, re.I | re.S)
    if doctype:
        if "[" in doctype.group(0):
            raise FetchError("refusing XML with an internal DTD subset")
        text = text.replace(doctype.group(0), "", 1)
    try:
        import defusedxml.ElementTree as DefusedET  # type: ignore
    except ImportError:
        DefusedET = None  # type: ignore[assignment]
    if DefusedET is not None:
        try:
            return DefusedET.fromstring(text)
        except Exception as exc:
            raise FetchError(f"refusing unsafe XML: {exc}") from exc
    try:
        return ET.fromstring(text)
    except ET.ParseError as exc:
        raise FetchError(f"cannot parse XML: {exc}") from exc


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class FetchConfig:
    """Runtime knobs for one CLI invocation."""

    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = 20.0
    retries: int = 2
    delay: float = 1.0
    max_bytes: int = 8 * 1024 * 1024
    max_chars: int = 20_000
    respect_robots: bool = True
    render: str = "auto"          # auto | never | always
    include_tables: bool = True
    keep_links: bool = False
    include_images: bool = False
    max_pages: int = 3
    num_results: int = 8
    verbose: bool = False
    extract_links: bool = False
    max_links: int = 20
    follow: str = "same-site"      # same-site | all | none
    search_engine: str = "auto"
    search_pages: int = 1
    cache: bool = False
    cache_ttl: int = 3600
    cache_dir: str = ""
    chunk_size: int = 0
    wait_for: str = ""
    scroll: int = 0
    proxy: str = ""               # http(s) proxy for every request; "" uses the environment

    def validate(self) -> None:
        if self.render not in ("auto", "never", "always"):
            raise ValueError("render must be auto, never or always")
        if self.follow not in ("same-site", "all", "none"):
            raise ValueError("follow must be same-site, all or none")
        if self.search_engine not in SEARCH_ENGINES:
            raise ValueError(
                "search_engine must be one of: " + ", ".join(SEARCH_ENGINES)
            )
        if self.timeout <= 0:
            raise ValueError("timeout must be positive")
        if self.delay < 0:
            raise ValueError("delay must be >= 0")
        if self.max_chars < 0:
            raise ValueError("max_chars must be >= 0")
        if self.max_pages < 0:
            raise ValueError("max_pages must be >= 0")
        if self.max_links < 1:
            raise ValueError("max_links must be >= 1")
        if self.search_pages < 1:
            raise ValueError("search_pages must be >= 1")
        if self.cache_ttl < 0:
            raise ValueError("cache_ttl must be >= 0")
        if self.chunk_size < 0:
            raise ValueError("chunk_size must be >= 0")
        if self.scroll < 0:
            raise ValueError("scroll must be >= 0")
        if self.proxy and "://" in self.proxy:
            scheme = self.proxy.split("://", 1)[0].lower()
            if scheme not in ("http", "https", "socks5", "socks5h"):
                raise ValueError("proxy must be an http(s) or socks5 URL")
        if not self.user_agent or len(self.user_agent) < 8:
            raise ValueError("user_agent must be a descriptive string")


def log(message: str, config: Optional[FetchConfig] = None) -> None:
    """Write a diagnostic line to stderr (never to stdout)."""

    if config is not None and not config.verbose:
        return
    print(f"[web-forager] {message}", file=sys.stderr, flush=True)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


# ---------------------------------------------------------------------------
# URL helpers
# ---------------------------------------------------------------------------

_ALLOWED_SCHEMES = ("http", "https")
_FORBIDDEN_PREFIXES = ("javascript:", "data:", "file:", "mailto:", "tel:", "ftp:")


def normalize_url(url: str, base: Optional[str] = None) -> str:
    """Return a canonical absolute http(s) URL or raise InvalidURLError.

    Fragments are dropped, whitespace trimmed, and scheme-less input such as
    ``example.com/page`` is promoted to https.  ``base`` resolves relative
    links found while parsing a page.
    """

    if url is None:
        raise InvalidURLError("URL is required")
    raw = str(url).strip().strip("<>").strip()
    if not raw:
        raise InvalidURLError("URL is empty")
    lowered = raw.lower()
    if lowered.startswith(_FORBIDDEN_PREFIXES):
        raise InvalidURLError(f"unsupported URL scheme: {raw.split(':', 1)[0]}")

    if base:
        raw = urllib.parse.urljoin(base, raw)

    parts = urllib.parse.urlsplit(raw)
    if not parts.scheme:
        raw = "https://" + raw.lstrip("/")
        parts = urllib.parse.urlsplit(raw)

    scheme = parts.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise InvalidURLError(f"unsupported URL scheme: {scheme}")
    if not parts.netloc:
        raise InvalidURLError(f"URL has no host: {raw}")

    # Normalise default ports and strip fragments.
    netloc = parts.netloc
    if (scheme == "http" and netloc.endswith(":80")) or (
        scheme == "https" and netloc.endswith(":443")
    ):
        netloc = netloc.rsplit(":", 1)[0]

    path = parts.path or "/"
    rebuilt = urllib.parse.urlunsplit((scheme, netloc, path, parts.query, ""))
    return rebuilt


def origin_of(url: str) -> str:
    """Return ``scheme://host[:port]`` for rate limiting and robots lookup."""

    parts = urllib.parse.urlsplit(url)
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}"


def absolute_url(href: Optional[str], base: Optional[str]) -> str:
    """Best-effort absolute link; returns '' when it cannot be resolved."""

    if not href:
        return ""
    text = str(href).strip()
    if not text:
        return ""
    lowered = text.lower()
    if lowered.startswith(_FORBIDDEN_PREFIXES):
        return ""
    # Without a base there is nothing to resolve a relative link against.
    if base is None and not (text.startswith("//") or re.match(r"^https?://", text, re.I)):
        return ""
    try:
        return normalize_url(text, base=base)
    except InvalidURLError:
        return ""


# ---------------------------------------------------------------------------
# robots.txt (RFC 9309 compatible subset, written from scratch)
# ---------------------------------------------------------------------------

_ROBOTS_CHARSET_RE = re.compile(rb"charset\s*=\s*[\"']?([A-Za-z0-9._:-]+)", re.I)


@dataclass(frozen=True)
class RobotsRule:
    allow: bool
    pattern: str
    regex: re.Pattern
    specificity: int


class RobotsPolicy:
    """An immutable parsed robots.txt policy for one user agent."""

    def __init__(
        self,
        rules: Iterable[RobotsRule] = (),
        crawl_delay: Optional[float] = None,
        *,
        allow_all: bool = False,
        deny_all: bool = False,
        source: str = "",
        note: str = "",
    ) -> None:
        self.rules = tuple(rules)
        self.crawl_delay = crawl_delay
        self.allow_all = allow_all
        self.deny_all = deny_all
        self.source = source
        self.note = note

    @classmethod
    def allowing_all(cls, source: str = "", note: str = "") -> "RobotsPolicy":
        return cls(allow_all=True, source=source, note=note)

    @classmethod
    def denying_all(cls, source: str = "", note: str = "") -> "RobotsPolicy":
        return cls(deny_all=True, source=source, note=note)

    def allowed(self, url: str) -> bool:
        if self.deny_all:
            return False
        if self.allow_all:
            return True
        if not self.rules:
            return True

        path = _robots_path(url)
        winner: Optional[RobotsRule] = None
        for rule in self.rules:
            if not rule.regex.match(path):
                continue
            if winner is None or rule.specificity > winner.specificity:
                winner = rule
            elif rule.specificity == winner.specificity and rule.allow and not winner.allow:
                # RFC 9309: ties are resolved in favour of Allow.
                winner = rule
        return True if winner is None else winner.allow


def _robots_path(url: str) -> str:
    parts = urllib.parse.urlsplit(url)
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    # robots.txt patterns are conventionally unencoded; compare unencoded text.
    try:
        path = urllib.parse.unquote(path)
    except Exception:
        pass
    return path


def _compile_rule(pattern: str) -> re.Pattern:
    """Translate a robots.txt path pattern into a regular expression."""

    anchored = pattern.endswith("$")
    core = pattern[:-1] if anchored else pattern
    if not core.startswith(("/", "*")):
        core = "/" + core
    escaped = re.escape(core).replace(r"\*", ".*")
    return re.compile("^" + escaped + ("$" if anchored else ""), re.S)


def _parse_robots_groups(text: str) -> list[dict[str, Any]]:
    """Split robots.txt into groups of {agents, rules, delay}."""

    groups: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip().lower()
        value = value.strip()

        if key == "user-agent":
            # A user-agent line after rules starts a new group.
            if current is None or current["rules"]:
                current = {"agents": [], "rules": [], "delay": None}
                groups.append(current)
            current["agents"].append(value.lower())
        elif key in ("allow", "disallow"):
            if current is None:
                continue
            if key == "disallow" and value == "":
                # An empty Disallow means "no restriction"; ignore it.
                continue
            current["rules"].append((key == "allow", value))
        elif key == "crawl-delay" and current is not None:
            try:
                delay = float(value)
            except ValueError:
                continue
            if delay >= 0:
                current["delay"] = delay

    return groups


def _agent_match_score(agent_token: str, user_agent: str) -> int:
    """Return a match score for a robots.txt user-agent token.

    ``*`` scores 0; a product token found in the request UA scores its length.
    ``-1`` means no match.
    """

    token = agent_token.strip().lower()
    if not token:
        return -1
    if token == "*":
        return 0
    token = token.split("/", 1)[0].strip()
    if token and token in user_agent.lower():
        return len(token)
    return -1


def parse_robots(text: str, user_agent: str, source: str = "") -> RobotsPolicy:
    """Parse robots.txt text and return the policy for ``user_agent``."""

    groups = _parse_robots_groups(text)
    best_score = -1
    selected: list[dict[str, Any]] = []

    for group in groups:
        score = max((_agent_match_score(a, user_agent) for a in group["agents"]), default=-1)
        if score < 0:
            continue
        if score > best_score:
            best_score = score
            selected = [group]
        elif score == best_score:
            selected.append(group)

    if not selected:
        return RobotsPolicy.allowing_all(source=source, note="no matching user-agent group")

    rules: list[RobotsRule] = []
    delay: Optional[float] = None
    for group in selected:
        if group["delay"] is not None:
            delay = group["delay"] if delay is None else max(delay, group["delay"])
        for allow, pattern in group["rules"]:
            rules.append(
                RobotsRule(
                    allow=allow,
                    pattern=pattern,
                    regex=_compile_rule(pattern),
                    specificity=len(pattern.replace("*", "")),
                )
            )

    return RobotsPolicy(rules=rules, crawl_delay=delay, source=source)


class RobotsCache:
    """Fetch robots.txt once per origin and cache the parsed policy."""

    def __init__(self, config: FetchConfig, ttl: float = 3600.0) -> None:
        self.config = config
        self.ttl = ttl
        self._cache: dict[str, tuple[float, RobotsPolicy]] = {}
        self._lock = threading.Lock()

    def policy_for(self, url: str) -> RobotsPolicy:
        origin = origin_of(url)
        now = time.monotonic()
        with self._lock:
            hit = self._cache.get(origin)
            if hit and hit[0] > now:
                return hit[1]

        policy = self._download(origin)
        with self._lock:
            self._cache[origin] = (now + self.ttl, policy)
        return policy

    def _download(self, origin: str) -> RobotsPolicy:
        robots_url = origin + "/robots.txt"
        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "text/plain,*/*;q=0.5",
        }
        try:
            response = requests.get(
                robots_url,
                headers=headers,
                timeout=min(max(self.config.timeout, 1.0), 10.0),
                allow_redirects=True,
            )
        except requests.RequestException as exc:
            # RFC 9309 §2.3.1: an unreachable robots.txt is treated as a
            # server error, so we take the conservative route and deny.
            return RobotsPolicy.denying_all(
                source=robots_url,
                note=f"robots.txt unreachable ({exc.__class__.__name__}); denied conservatively",
            )

        status = response.status_code
        if status == 200:
            raw = response.content[:512_000]
            text = _decode_robots_bytes(raw, response)
            return parse_robots(text, self.config.user_agent, source=robots_url)
        if status in (401, 403):
            return RobotsPolicy.denying_all(source=robots_url, note=f"HTTP {status} on robots.txt")
        if 500 <= status < 600:
            return RobotsPolicy.denying_all(
                source=robots_url,
                note=(
                    f"HTTP {status} on robots.txt; denied per RFC 9309. The site's "
                    "robots.txt is broken, so no page on it can be read. Contact the "
                    "site owner, or use --ignore-robots only for resources you are "
                    "authorised to access."
                ),
            )
        # 404/410 and other 4xx mean "no restrictions".
        return RobotsPolicy.allowing_all(source=robots_url, note=f"HTTP {status} on robots.txt")


def _decode_robots_bytes(raw: bytes, response: Any) -> str:
    encoding = None
    try:
        match = _ROBOTS_CHARSET_RE.search(raw[:512])
        if match:
            encoding = match.group(1).decode("ascii", "ignore")
    except Exception:
        encoding = None
    if not encoding:
        content_type = ""
        try:
            content_type = response.headers.get("Content-Type", "")
        except Exception:
            content_type = ""
        match = re.search(r"charset=([A-Za-z0-9._:-]+)", content_type, re.I)
        if match:
            encoding = match.group(1)
    if not encoding:
        encoding = getattr(response, "encoding", None) or "utf-8"
    try:
        return raw.decode(encoding, errors="replace")
    except (LookupError, TypeError):
        return raw.decode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Politeness
# ---------------------------------------------------------------------------


class RateLimiter:
    """Per-origin politeness delay, capped so robots.txt cannot stall a run."""

    MAX_EXTRA_DELAY = 30.0

    def __init__(self, delay: float) -> None:
        self.delay = max(0.0, float(delay))
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, url: str, extra_delay: float = 0.0) -> None:
        target = max(self.delay, min(extra_delay, self.MAX_EXTRA_DELAY))
        if target <= 0:
            return
        origin = origin_of(url)
        with self._lock:
            now = time.monotonic()
            last = self._last.get(origin, 0.0)
            pause = max(0.0, last + target - now)
            self._last[origin] = now + pause
        if pause > 0:
            time.sleep(pause)


# ---------------------------------------------------------------------------
# HTTP fetching
# ---------------------------------------------------------------------------

_HTML_CONTENT_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "application/xml",
    "text/xml",
    "application/rss+xml",
    "application/atom+xml",
)
_TEXT_CONTENT_TYPES = ("text/plain", "text/markdown", "text/csv")
_JSON_CONTENT_TYPES = ("application/json", "application/ld+json")
_PDF_CONTENT_TYPES = ("application/pdf",)
_DOCUMENT_CONTENT_TYPES = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/epub+zip",
)
_DOCUMENT_EXTENSIONS = {
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".epub": "application/epub+zip",
    ".csv": "text/csv",
}
_FEED_CONTENT_TYPES = ("application/rss+xml", "application/atom+xml", "application/xml", "text/xml")


@dataclass
class HttpResponse:
    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    content: bytes
    text: str
    encoding: str
    content_type: str
    from_cache: bool = False


def _cache_root(config: FetchConfig) -> Path:
    if config.cache_dir:
        return Path(config.cache_dir).expanduser()
    return Path.home() / ".web-forager" / "cache"


def _cache_key(url: str) -> str:
    import hashlib

    return hashlib.sha256(url.encode("utf-8")).hexdigest()


def decode_js_redirect(text: str) -> str:
    """Read the target URL out of a search engine's ``/link`` interstitial.

    Two shapes exist. One writes the address literally
    (``window.location.replace('https://...')``). The other — used by
    weixin.sogou.com — assembles it from ``url += '...'`` chunks so that the
    address never appears in the HTML as a whole; concatenating the chunks
    recovers it without running any JavaScript.
    """

    if not text:
        return ""
    chunks = re.findall(r"""url\s*\+=\s*['"]([^'"]*)['"]""", text)
    if chunks:
        joined = "".join(chunks)
        if joined.startswith("http"):
            return joined
    match = re.search(r"""window\.location\.replace\(\s*['"]([^'"]+)""", text)
    if not match:
        match = re.search(r"""URL\s*=\s*['"]([^'"]+)""", text)
    return match.group(1) if match else ""


class HttpFetcher:
    """A polite, robots-aware HTTP client built on requests."""

    def __init__(self, config: FetchConfig) -> None:
        self.config = config
        self.session = requests.Session()
        self.session.max_redirects = 5
        self.session.headers.update(
            {
                "User-Agent": config.user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,"
                          "text/plain;q=0.8,application/json;q=0.7,*/*;q=0.5",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "gzip, deflate",
            }
        )
        if config.proxy:
            # An explicit proxy wins over the environment; requests itself still
            # honours HTTPS_PROXY / ALL_PROXY when this is empty.
            self.session.proxies.update({"http": config.proxy, "https": config.proxy})
        self.robots = RobotsCache(config)
        self.limiter = RateLimiter(config.delay)

    def close(self) -> None:
        try:
            self.session.close()
        except Exception:
            pass

    # -- robots ---------------------------------------------------------

    def assert_allowed(self, url: str) -> RobotsPolicy:
        """Raise RobotsDenied when robots.txt forbids ``url``."""

        if not self.config.respect_robots:
            return RobotsPolicy.allowing_all(note="robots checking disabled by --ignore-robots")
        policy = self.robots.policy_for(url)
        if not policy.allowed(url):
            detail = policy.note or policy.source or "robots.txt"
            raise RobotsDenied(f"robots.txt disallows {url} ({detail})")
        return policy

    # -- main entry -----------------------------------------------------

    def fetch(
        self, url: str, *, check_robots: bool = True, use_cache: bool = True
    ) -> HttpResponse:
        """Fetch one URL.

        ``use_cache=False`` skips both lookup and write. A bootstrap request
        whose only job is to set cookies must not be answered from the cache:
        a cached anti-bot page would silently supply no cookie at all.
        """

        url = normalize_url(url)
        policy: Optional[RobotsPolicy] = None
        if check_robots:
            policy = self.assert_allowed(url)

        cached = self._read_cache(url) if use_cache else None
        if cached is not None:
            return cached

        extra = policy.crawl_delay if policy and policy.crawl_delay else 0.0
        self.limiter.wait(url, extra)

        last_error: Optional[Exception] = None
        for attempt in range(self.config.retries + 1):
            try:
                response = self.session.get(
                    url,
                    timeout=self.config.timeout,
                    allow_redirects=True,
                    stream=True,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self.config.retries:
                    break
                time.sleep(min(0.5 * (2**attempt), 4.0))
                continue

            status = response.status_code
            if status in (429, 500, 502, 503, 504) and attempt < self.config.retries:
                retry_after = _retry_after_seconds(response.headers.get("Retry-After"))
                response.close()
                time.sleep(retry_after if retry_after is not None else min(1.0 * (2**attempt), 8.0))
                continue

            if status >= 400:
                response.close()
                raise FetchError(f"HTTP {status} for {url}")

            result = self._read_response(response, url)
            if use_cache:
                self._write_cache(url, result)
            return result

        raise FetchError(f"request failed for {url}: {last_error}") from last_error

    # -- on-disk response cache ----------------------------------------

    def _cache_paths(self, url: str) -> tuple[Path, Path]:
        root = _cache_root(self.config)
        key = _cache_key(url)
        return root / f"{key}.json", root / f"{key}.bin"

    def _read_cache(self, url: str) -> Optional[HttpResponse]:
        if not self.config.cache or self.config.cache_ttl <= 0:
            return None
        meta_path, body_path = self._cache_paths(url)
        try:
            if not meta_path.is_file() or not body_path.is_file():
                return None
            age = time.time() - meta_path.stat().st_mtime
            if age > self.config.cache_ttl:
                return None
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            body = body_path.read_bytes()
        except (OSError, json.JSONDecodeError):
            return None
        content_type = str(meta.get("content_type") or "text/html")
        encoding = str(meta.get("encoding") or "utf-8")
        text = body.decode(encoding, errors="replace")
        log(f"cache hit: {url}", self.config)
        return HttpResponse(
            url=url,
            final_url=str(meta.get("final_url") or url),
            status=int(meta.get("status") or 200),
            headers={str(k): str(v) for k, v in (meta.get("headers") or {}).items()},
            content=body,
            text=text,
            encoding=encoding,
            content_type=content_type,
            from_cache=True,
        )

    def _write_cache(self, url: str, response: HttpResponse) -> None:
        if not self.config.cache or response.status != 200:
            return
        meta_path, body_path = self._cache_paths(url)
        try:
            meta_path.parent.mkdir(parents=True, exist_ok=True)
            body_path.write_bytes(response.content)
            meta_path.write_text(
                json.dumps(
                    {
                        "url": url,
                        "final_url": response.final_url,
                        "status": response.status,
                        "headers": response.headers,
                        "content_type": response.content_type,
                        "encoding": response.encoding,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        except OSError as exc:  # a cache failure must never fail the fetch
            log(f"cache write skipped ({exc})", self.config)

    def _read_response(self, response: requests.Response, requested_url: str) -> HttpResponse:
        content_type = (response.headers.get("Content-Type") or "").split(";", 1)[0].strip().lower()
        path = requested_url.lower().split("?", 1)[0]
        if content_type == "application/octet-stream":
            for extension, mapped in _DOCUMENT_EXTENSIONS.items():
                if path.endswith(extension):
                    content_type = mapped
                    break
            else:
                if path.endswith(".pdf"):
                    content_type = "application/pdf"
        if content_type and not _is_supported_content_type(content_type):
            response.close()
            raise FetchError(
                f"unsupported content type '{content_type}' for {requested_url}; "
                "web-forager handles HTML, XML/feeds, plain text, CSV, JSON, PDF "
                "and DOCX/XLSX/EPUB only"
            )

        chunks: list[bytes] = []
        total = 0
        truncated = False
        try:
            for chunk in response.iter_content(chunk_size=65_536):
                if not chunk:
                    continue
                chunks.append(chunk)
                total += len(chunk)
                if total >= self.config.max_bytes:
                    truncated = True
                    break
        finally:
            response.close()

        raw = b"".join(chunks)[: self.config.max_bytes]
        if raw[:5] == b"%PDF-":
            content_type = "application/pdf"
        if content_type in ("application/octet-stream", "binary/octet-stream"):
            if raw[:4] == b"PK\x03\x04":
                pass  # DOCX/XLSX/EPUB is detected after reading
            elif not _looks_like_text(raw):
                response.close()
                raise FetchError(
                    f"unsupported binary payload for {requested_url}; "
                    "web-forager handles text, HTML, XML/feeds, JSON, PDF and "
                    "DOCX/XLSX/EPUB only"
                )
        encoding = _detect_encoding(raw, content_type, response.encoding)
        text = raw.decode(encoding, errors="replace")
        if truncated:
            text += "\n<!-- web-forager: response truncated at max_bytes -->"

        headers = {k.lower(): v for k, v in response.headers.items()}
        return HttpResponse(
            url=requested_url,
            final_url=response.url,
            status=response.status_code,
            headers=headers,
            content=raw,
            text=text,
            encoding=encoding,
            content_type=content_type or "text/html",
        )

    def resolve(self, url: str) -> str:
        """Follow redirects cheaply and decode Sogou's JS ``/link`` hop.

        Used only for search-result URLs; the returned URL is still passed
        through robots.txt before its content is fetched.
        """

        url = normalize_url(url)
        self.limiter.wait(url)
        response: Optional[requests.Response] = None
        try:
            response = self.session.get(
                url, timeout=self.config.timeout, allow_redirects=True, stream=True
            )
            final = response.url
            text = ""
            if response.status_code == 200:
                try:
                    text = response.content[:4096].decode("utf-8", "ignore")
                except Exception:
                    text = ""
            is_js_redirect = bool(
                text and ("sogou.com/link" in final or "window.location.replace" in text)
            )
            if is_js_redirect:
                final = decode_js_redirect(text) or final
            return final
        except requests.RequestException:
            return url
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass


def _is_supported_content_type(content_type: str) -> bool:
    if (
        content_type in _JSON_CONTENT_TYPES
        or content_type in _PDF_CONTENT_TYPES
        or content_type in _DOCUMENT_CONTENT_TYPES
        or content_type in ("application/octet-stream", "binary/octet-stream")
    ):
        return True
    return any(content_type.startswith(prefix) for prefix in _HTML_CONTENT_TYPES + _TEXT_CONTENT_TYPES)


def _looks_like_text(raw: bytes) -> bool:
    sample = raw[:4096]
    if not sample:
        return True
    if b"\x00" in sample:
        return False
    controls = sum(1 for byte in sample if byte < 9 or 13 < byte < 32)
    return controls / len(sample) < 0.02


def _retry_after_seconds(value: Optional[str]) -> Optional[float]:
    if not value:
        return None
    try:
        return max(0.0, min(float(value), 10.0))
    except (TypeError, ValueError):
        return None


_META_CHARSET_RE = re.compile(
    rb"""<meta[^>]+charset\s*=\s*["']?\s*([A-Za-z0-9._:-]+)""", re.I
)


def _detect_encoding(raw: bytes, content_type: str, header_encoding: Optional[str]) -> str:
    # 1. An explicit charset in Content-Type always wins.
    match = re.search(r"charset=([A-Za-z0-9._:-]+)", content_type or "", re.I)
    if match:
        return match.group(1)
    # 2. A <meta charset> declaration beats requests' RFC 2616 fallback of
    #    ISO-8859-1 for text/* responses without a charset parameter.
    match = _META_CHARSET_RE.search(raw[:4096])
    if match:
        try:
            return match.group(1).decode("ascii", "ignore")
        except Exception:
            pass
    # 3. Validate a UTF-8 sample, then common CJK encodings.
    sample = raw[:4096]
    try:
        sample.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    for candidate in ("gb18030", "big5"):
        try:
            sample.decode(candidate)
            return candidate
        except (UnicodeDecodeError, LookupError):
            continue
    if header_encoding and header_encoding.lower() not in ("iso-8859-1", "latin-1"):
        return header_encoding
    return "utf-8"


def decode_bytes(data: bytes, content_type: str = "") -> str:
    """Decode a local HTML/text file using the same heuristics as the fetcher."""

    return data.decode(_detect_encoding(data, content_type, None), errors="replace")


# ---------------------------------------------------------------------------
# Search back-ends (public result pages; parsed from scratch)
# ---------------------------------------------------------------------------

_BING_RSS = "https://www.bing.com/search?q={query}&format=rss&count={count}&first={first}"
_BING_HTML = (
    "https://www.bing.com/search?q={query}&count={count}&first={first}"
    "&setlang=zh-hans&mkt=zh-CN"
)
_DDG_HTML = "https://html.duckduckgo.com/html/?q={query}"
_SO_360 = "https://www.so.com/s?q={query}&pn={page}"
_SOGOU = "https://www.sogou.com/web?query={query}&page={page}"
_WEIXIN = "https://weixin.sogou.com/weixin?type=2&query={query}&page={page}"

SEARCH_ENGINES = ("auto", "all", "360", "bing", "sogou", "weixin", "duckduckgo")

_360_INTERNAL_HOSTS = (
    "so.com",
    "360kan.com",
    "hao.360.com",
    "e.so.com",
    "image.so.com",
    "tv.360kan.com",
)
_SOGOU_BLOCK_MARKERS = ("antispider", "安全验证", "人机验证", "验证码")


_CJK_RE = re.compile(r"[㐀-䶿一-鿿豈-﫿぀-ヿ가-힯]")
_USEFUL_TITLE_RE = re.compile(r"[\w㐀-䶿一-鿿]")
_MOJIBAKE_RE = re.compile(r"[�\u0000-\u0008\u000b\u000c\u000e-\u001f]")


def looks_garbled(text: str, threshold: float = 0.2) -> bool:
    """True when text is mostly replacement or control characters.

    This catches an engine handing back an anti-bot page instead of results.
    Real mojibake (UTF-8 read as Latin-1) is not caught here: it looks like
    ordinary punctuation to a character-class check.
    """

    value = str(text or "")
    if not value:
        return False
    return len(_MOJIBAKE_RE.findall(value)) / len(value) >= threshold


def prefers_chinese_engines(query: str) -> bool:
    """True when a query is mostly CJK text.

    Such queries rank better on 360 and Sogou; Bing's tokeniser treats quoted
    Chinese phrases as single characters, which buries the precise hits.
    """

    text = str(query or "")
    if not text:
        return False
    cjk = len(_CJK_RE.findall(text))
    if not cjk:
        return False
    return cjk >= len(re.findall(r"[A-Za-z]", text))


def search(
    query: str,
    config: FetchConfig,
    engine: str = "auto",
    limit: Optional[int] = None,
    fetcher: Optional[HttpFetcher] = None,
    report: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, str]]:
    """Return ``[{title, url, snippet, source}]`` for a keyword query.

    ``engine`` is one of ``auto`` (360 + Bing, and 360 + Sogou + the WeChat
    index for a mostly-CJK query), ``all`` (every engine), ``360``, ``bing``,
    ``sogou``, ``weixin`` or ``duckduckgo``. ``auto`` asks one more engine when
    the answer holds fewer than three distinct results.

    Pass ``report`` to collect one entry per engine tried — name, whether it
    answered, how many results and how long it took — so a caller in a hostile
    network can see which backend is actually reachable.

    Search endpoints are query interfaces, not target pages.  robots.txt
    therefore applies to the *result pages* we later fetch, not to the query
    request itself.  Queries are still rate-limited per host.
    """

    query = (query or "").strip()
    if not query:
        raise ValueError("query must not be empty")
    limit = limit or config.num_results or 8
    engine = (engine or "auto").lower()
    if engine not in SEARCH_ENGINES:
        raise ValueError(f"unsupported search engine: {engine}")

    fallback_engines: list[str] = []
    if engine == "auto":
        # Bing tokenises quoted Chinese phrases poorly: it matches single
        # characters and pushes dictionary pages above the precise hits. For a
        # CJK query, ask 360, Sogou and 搜狗微信 first — the article index is the
        # one channel that still carries a Chinese person's or institution's
        # name — and keep Bing only as a fallback.
        if prefers_chinese_engines(query):
            engines = ["360", "sogou", "weixin"]
            fallback_engines = ["bing"]
        else:
            engines = ["360", "bing"]
            # A Latin query answered with a handful of results (or none) is
            # often a narrow topic the first two engines do not index; Sogou
            # widens the net without being asked for every query.
            fallback_engines = ["sogou"]
    elif engine == "all":
        engines = ["360", "bing", "sogou", "weixin"]
    else:
        engines = [engine]

    own_fetcher = fetcher is None
    fetcher = fetcher or HttpFetcher(config)
    groups: list[tuple[str, list[dict[str, str]]]] = []
    errors: list[str] = []

    def collect(names: list[str], fallback: bool = False) -> None:
        for name in names:
            started = time.monotonic()
            entry: dict[str, Any] = {"engine": name}
            if fallback:
                entry["fallback"] = True
            try:
                items = _search_one(
                    name, query, config, limit, fetcher, pages=config.search_pages
                )
                groups.append((name, items))
                entry.update(
                    ok=True,
                    results=len(items),
                    ms=round((time.monotonic() - started) * 1000),
                )
            except Exception as exc:  # one engine failing must not kill the query
                errors.append(f"{name}: {exc}")
                entry.update(
                    ok=False,
                    results=0,
                    error=str(exc),
                    ms=round((time.monotonic() - started) * 1000),
                )
            if report is not None:
                report.append(entry)

    try:
        collect(engines)
        if fallback_engines and (not groups or _thin_results(groups, limit)):
            collect(fallback_engines, fallback=True)
    finally:
        if own_fetcher:
            fetcher.close()

    if not groups:
        raise FetchError("all search engines failed: " + "; ".join(errors) or "no engine available")

    if len(groups) == 1:
        merged = groups[0][1]
    else:
        merged = merge_search_results(groups, query, limit=limit)
    return dedupe_results(merged, limit=limit)


def _thin_results(groups: list[tuple[str, list[dict[str, str]]]], limit: int) -> bool:
    """True when the engines answered with fewer than a useful number of hits.

    Three is the floor: below it a caller almost always has to run a second
    query by hand.  The check counts distinct URLs, not raw rows, because one
    engine repeats the same result across pages.
    """

    items = dedupe_results(
        [item for _, group in groups for item in group], limit=max(limit, 3)
    )
    return len(items) < min(limit, 3)


def _search_one(
    name: str,
    query: str,
    config: FetchConfig,
    limit: int,
    fetcher: HttpFetcher,
    pages: int = 1,
) -> list[dict[str, str]]:
    quoted = urllib.parse.quote_plus(query)
    pages = max(1, pages)
    collected: list[dict[str, str]] = []

    for page in range(1, pages + 1):
        if name == "duckduckgo" and page > 1:
            break
        if name == "360":
            response = fetcher.fetch(
                _SO_360.format(query=quoted, page=page), check_robots=False
            )
            found = parse_360_html(response.text, limit=limit)
        elif name == "sogou":
            response = fetcher.fetch(
                _SOGOU.format(query=quoted, page=page), check_robots=False
            )
            if is_sogou_blocked(response.text):
                raise FetchError("Sogou returned a verification page (antispider)")
            parsed = parse_sogou_html(
                response.text, base="https://www.sogou.com/", limit=limit
            )
            found = resolve_sogou_results(parsed, fetcher, limit=limit)
        elif name == "weixin":
            response = fetcher.fetch(
                _WEIXIN.format(query=quoted, page=page), check_robots=False
            )
            if is_sogou_blocked(response.text):
                raise FetchError("weixin.sogou.com returned a verification page (antispider)")
            parsed = parse_weixin_html(
                response.text, base="https://weixin.sogou.com/", limit=limit
            )
            found = resolve_sogou_results(parsed, fetcher, limit=limit)
        elif name == "duckduckgo":
            response = fetcher.fetch(_DDG_HTML.format(query=quoted), check_robots=False)
            found = parse_ddg_html(response.text, limit=limit)
        else:
            first = 1 + (page - 1) * 10
            # Bing: RSS is cheaper and gives direct URLs; HTML is the fallback.
            try:
                response = fetcher.fetch(
                    _BING_RSS.format(query=quoted, count=limit, first=first),
                    check_robots=False,
                )
                found = parse_bing_rss(response.text, limit=limit)
            except FetchError:
                found = []
            if not found:
                response = fetcher.fetch(
                    _BING_HTML.format(query=quoted, count=limit, first=first),
                    check_robots=False,
                )
                found = parse_bing_html(response.text, limit=limit)

        if not found:
            break
        collected.extend(found)
        collected = dedupe_results(collected, limit=limit * pages)
        if len(collected) >= limit * pages:
            break

    return collected[: limit * pages]


def _query_tokens(query: str) -> list[str]:
    return [token.lower() for token in re.split(r"[\s,，;；|]+", query.strip()) if token]


def result_coverage(result: dict[str, str], tokens: list[str]) -> float:
    """Fraction of query tokens present in title/snippet/url (0..1)."""

    if not tokens:
        return 0.0
    haystack = " ".join(
        (result.get("title", ""), result.get("snippet", ""), result.get("url", ""))
    ).lower()
    return sum(1 for token in tokens if token in haystack) / len(tokens)


def merge_search_results(
    groups: list[tuple[str, list[dict[str, str]]]],
    query: str,
    limit: int = 8,
) -> list[dict[str, str]]:
    """Merge several engines: best query coverage first, engine order breaks ties."""

    tokens = _query_tokens(query)
    scored: list[tuple[float, int, int, dict[str, str]]] = []
    for group_index, (name, items) in enumerate(groups):
        for rank, item in enumerate(items):
            candidate = dict(item)
            candidate.setdefault("source", name)
            scored.append((result_coverage(candidate, tokens), group_index, rank, candidate))
    scored.sort(key=lambda entry: (-entry[0], entry[1], entry[2]))
    return [entry[3] for entry in scored[: max(limit * 3, limit)]]


def parse_360_html(html: str, limit: int = 8) -> list[dict[str, str]]:
    """Parse 360 Search organic results (``li.res-list``)."""

    soup = make_soup(html)
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in soup.select("li.res-list"):
        anchor = item.select_one("h3 a") or item.select_one("a[data-mdurl]")
        if anchor is None:
            continue
        href = _attr_text(anchor, "data-mdurl") or _attr_text(anchor, "href")
        url = absolute_url(href, base="https://www.so.com/")
        if not url:
            continue
        host = urllib.parse.urlsplit(url).netloc.lower()
        if any(host == internal or host.endswith("." + internal) for internal in _360_INTERNAL_HOSTS):
            continue
        heading = item.select_one("h3")
        title = _clean_result_text(heading.get_text(" ", strip=True) if heading else "")
        if not title:
            continue
        snippet = ""
        for selector in (".res-desc", ".res-rich", ".res-comm-con", ".g-ellipsis2", ".mh-title"):
            node = item.select_one(selector)
            if node is not None:
                snippet = _clean_result_text(node.get_text(" ", strip=True))
                if snippet:
                    break
        if url in seen:
            continue
        seen.add(url)
        results.append({"title": title, "url": url, "snippet": snippet, "source": "360"})
        if len(results) >= limit:
            break
    return results


def is_sogou_blocked(html: str) -> bool:
    lowered = (html or "").lower()
    return "antispider" in lowered or (
        any(marker in html for marker in _SOGOU_BLOCK_MARKERS) and "vrwrap" not in lowered
    )


def parse_sogou_html(
    html: str, base: str = "https://www.sogou.com/", limit: int = 8
) -> list[dict[str, str]]:
    """Parse Sogou organic results (``div.vrwrap``)."""

    soup = make_soup(html)
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in soup.select("div.vrwrap"):
        classes = " ".join(str(value) for value in (item.get("class") or []))
        if "hintBox" in classes:
            continue
        anchor = item.select_one("h3 a")
        if anchor is None:
            continue
        href = _attr_text(anchor, "href")
        url = absolute_url(href, base=base)
        if not url:
            continue
        heading = item.select_one("h3")
        title = _clean_result_text(heading.get_text(" ", strip=True) if heading else "")
        if not title:
            continue
        snippet = ""
        for selector in (".str_info", ".space-txt", ".fz-mid", ".text-layout", ".str-text"):
            node = item.select_one(selector)
            if node is not None:
                snippet = _clean_result_text(node.get_text(" ", strip=True))
                if snippet:
                    break
        if url in seen:
            continue
        seen.add(url)
        results.append({"title": title, "url": url, "snippet": snippet, "source": "sogou"})
        if len(results) >= limit:
            break
    return results


def _join_cjk(text: str) -> str:
    """Remove the spaces a highlight tag leaves inside a Chinese sentence.

    ``示例<em>名字</em>解析`` reads as "示例 名字 解析" once tags are replaced with
    spaces; Chinese text has no word spaces, so joining across CJK characters
    restores the original phrase without touching spaces between Latin words.
    """

    return re.sub(r"(?<=[㐀-䶿一-鿿])\s+(?=[㐀-䶿一-鿿])", "", text)


def parse_weixin_html(
    html: str, base: str = "https://weixin.sogou.com/", limit: int = 8
) -> list[dict[str, str]]:
    """Parse 搜狗微信 article results (``ul.news-list > li``).

    Each entry is one WeChat official-account article. The link is a Sogou
    ``/link?url=`` wrapper that resolves to ``mp.weixin.qq.com`` (handled by
    :func:`resolve_sogou_results`); the account name and publish date travel
    with the result so a caller can tell a lab's own post from a re-post.
    """

    soup = make_soup(html)
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in soup.select("ul.news-list li"):
        anchor = item.select_one("h3 a")
        if anchor is None:
            continue
        href = _attr_text(anchor, "href")
        url = absolute_url(href, base=base)
        if not url:
            continue
        heading = item.select_one("h3")
        title = _join_cjk(_clean_result_text(heading.get_text(" ", strip=True) if heading else ""))
        if not title:
            continue
        snippet = ""
        node = item.select_one("p.txt-info")
        if node is not None:
            snippet = _join_cjk(_clean_result_text(node.get_text(" ", strip=True)))
        entry = {
            "title": title,
            "url": url,
            "snippet": snippet,
            "source": "weixin",
        }
        account = item.select_one("div.s-p span.all-time-y2") or item.select_one(
            "div.s-p a.account"
        )
        if account is not None:
            name = _clean_result_text(account.get_text(" ", strip=True))
            if name:
                entry["account"] = name
        stamp = re.search(r"timeConvert\('(\d+)'\)", str(item))
        if stamp:
            try:
                entry["date"] = time.strftime(
                    "%Y-%m-%d", time.localtime(int(stamp.group(1)))
                )
            except (OverflowError, OSError, ValueError):
                pass
        if url in seen:
            continue
        seen.add(url)
        results.append(entry)
        if len(results) >= limit:
            break
    return results


def resolve_sogou_results(
    results: list[dict[str, str]],
    fetcher: HttpFetcher,
    limit: int = 8,
) -> list[dict[str, str]]:
    """Resolve Sogou ``/link?url=`` wrappers to the real target URL."""

    resolved: list[dict[str, str]] = []
    for item in results[:limit]:
        url = item.get("url", "")
        if "sogou.com/link" in url or "/link?url=" in url:
            real = fetcher.resolve(url)
            if real and "sogou.com/link" not in real:
                item = dict(item)
                item["url"] = real
        resolved.append(item)
    return resolved


def dedupe_results(results: Iterable[dict[str, str]], limit: int = 8) -> list[dict[str, str]]:
    """Remove duplicate URLs and unusable titles while preserving rank order."""

    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in results:
        url = item.get("url", "")
        if not url or url in seen:
            continue
        title = str(item.get("title") or "")
        # Engines sometimes answer a query with an anti-bot interstitial and
        # the "title" comes back as replacement characters or bare punctuation.
        # An entry with no title at all is left alone: other callers feed
        # dedupe_results bare URLs.
        if title and (looks_garbled(title) or not _USEFUL_TITLE_RE.search(title)):
            continue
        seen.add(url)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def _clean_result_text(value: Optional[str]) -> str:
    if not value:
        return ""
    text = html_lib.unescape(str(value))
    if "<" in text:
        text = BeautifulSoup(text, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text).strip()


def _attr_text(tag: Tag, name: str, default: str = "") -> str:
    """Read an HTML attribute as a plain string, tolerating list values."""

    value: Any = tag.attrs.get(name, default)
    if isinstance(value, list):
        return " ".join(str(item) for item in value).strip()
    if value is None:
        return default
    return str(value).strip()


def _int_attr(tag: Tag, name: str, default: int) -> int:
    """Read an integer HTML attribute with a safe fallback."""

    raw = _attr_text(tag, name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default


def parse_bing_rss(xml_text: str, limit: int = 8) -> list[dict[str, str]]:
    """Parse a Bing ``format=rss`` response.

    The parser is only ever handed a metered search-engine response, but we
    still refuse documents that declare a DTD or custom entities.  This blocks
    XXE / entity-expansion payloads without pulling in a non-permitted XML
    library.
    """

    results: list[dict[str, str]] = []
    lowered = xml_text[:20_000].lower()
    if "<!doctype" in lowered or "<!entity" in lowered:
        return results
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        return results

    for item in root.iter():
        if not item.tag.lower().endswith("item"):
            continue
        title = _clean_result_text(_xml_text(item, "title"))
        link = (_xml_text(item, "link") or "").strip()
        description = _clean_result_text(_xml_text(item, "description"))
        if not link:
            continue
        url = absolute_url(_decode_bing_redirect(link), base=None)
        if not url:
            continue
        results.append({"title": title, "url": url, "snippet": description, "source": "bing"})
        if len(results) >= limit:
            break
    return results


def _xml_text(node: ET.Element, name: str) -> str:
    for child in node:
        if child.tag.lower().split("}")[-1] == name.lower():
            return child.text or ""
    return ""


def parse_bing_html(html: str, limit: int = 8) -> list[dict[str, str]]:
    """Parse the HTML Bing result list."""

    soup = make_soup(html)
    results: list[dict[str, str]] = []
    for block in soup.select("li.b_algo"):
        anchor = block.select_one("h2 a") or block.select_one("a")
        if not anchor:
            continue
        href = _attr_text(anchor, "href")
        url = absolute_url(_decode_bing_redirect(href), base="https://www.bing.com/")
        if not url:
            continue
        title = _clean_result_text(anchor.get_text(" ", strip=True))
        snippet_tag = block.select_one(".b_caption p") or block.select_one(".b_snippet")
        snippet = _clean_result_text(snippet_tag.get_text(" ", strip=True)) if snippet_tag else ""
        results.append({"title": title, "url": url, "snippet": snippet, "source": "bing"})
        if len(results) >= limit:
            break
    return results


def parse_ddg_html(html: str, limit: int = 8) -> list[dict[str, str]]:
    """Parse the DuckDuckGo HTML result page."""

    soup = make_soup(html)
    results: list[dict[str, str]] = []
    for block in soup.select("div.result"):
        anchor = block.select_one("a.result__a")
        if not anchor:
            continue
        href = _attr_text(anchor, "href")
        url = absolute_url(_decode_ddg_redirect(href), base="https://duckduckgo.com/")
        if not url:
            continue
        title = _clean_result_text(anchor.get_text(" ", strip=True))
        snippet_tag = block.select_one(".result__snippet")
        snippet = _clean_result_text(snippet_tag.get_text(" ", strip=True)) if snippet_tag else ""
        results.append({"title": title, "url": url, "snippet": snippet, "source": "duckduckgo"})
        if len(results) >= limit:
            break
    return results


def _decode_bing_redirect(href: str) -> str:
    """Unwrap Bing's ``/ck/a?...&u=a1<base64url>`` redirect wrapper."""

    if not href:
        return href
    parts = urllib.parse.urlsplit(href)
    if "bing.com" not in parts.netloc.lower() or not parts.path.startswith("/ck/"):
        return href
    query = urllib.parse.parse_qs(parts.query)
    value = (query.get("u") or [""])[0]
    if not value.startswith("a1"):
        return href
    payload = value[2:]
    payload += "=" * (-len(payload) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("ascii")).decode("utf-8", "ignore")
    except Exception:
        return href
    return decoded if decoded.startswith(("http://", "https://")) else href


def _decode_ddg_redirect(href: str) -> str:
    if not href:
        return href
    parts = urllib.parse.urlsplit(href)
    if "duckduckgo.com" not in parts.netloc.lower():
        return href
    query = urllib.parse.parse_qs(parts.query)
    value = (query.get("uddg") or [""])[0]
    return urllib.parse.unquote(value) if value else href


# ---------------------------------------------------------------------------
# HTML inspection
# ---------------------------------------------------------------------------

_SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "template",
    "svg",
    "canvas",
    "iframe",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    "nav",
    "footer",
    "aside",
    "header",
}

_DYNAMIC_MARKERS = (
    "__NEXT_DATA__",
    "__NUXT__",
    'id="root"',
    "id='root'",
    'id="app"',
    "id='app'",
    "window.__INITIAL_STATE__",
    "data-reactroot",
)


def make_soup(html: str) -> BeautifulSoup:
    try:
        return BeautifulSoup(html or "", "lxml")
    except Exception:
        return BeautifulSoup(html or "", "html.parser")


def visible_text(html: str) -> str:
    soup = make_soup(html)
    for tag in soup(list(_SKIP_TAGS)):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()


def looks_dynamic(html: str) -> bool:
    """Heuristic: a short visible body plus SPA markers suggests JS rendering."""

    if not html:
        return False
    head = html.lstrip()[:1000].lower()
    if head.startswith("<?xml") or head.startswith("<rss") or head.startswith("<feed"):
        return False
    script_count = html.lower().count("<script")
    marker_hit = any(marker in html for marker in _DYNAMIC_MARKERS)
    text = visible_text(html)
    if len(text) < 400:
        return marker_hit or script_count >= 3
    return False


# ---------------------------------------------------------------------------
# Markdown conversion
# ---------------------------------------------------------------------------

_INLINE_WS_RE = re.compile(r"[ \t\r\f\v]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def _normalize_markdown(markdown: str) -> str:
    text = (markdown or "").replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


def _hard_split_block(block: str, size: int) -> list[str]:
    pieces: list[str] = []
    remaining = block.strip()
    while len(remaining) > size:
        cut = remaining.rfind("\n", 0, size)
        if cut < size // 2:
            for marker in ("。", "！", "？", ". ", "! ", "? "):
                candidate = remaining.rfind(marker, 0, size)
                if candidate >= size // 2:
                    cut = candidate + len(marker)
                    break
        if cut < size // 2:
            cut = remaining.rfind(" ", 0, size)
        if cut < size // 2:
            cut = size
        pieces.append(remaining[:cut].strip())
        remaining = remaining[cut:].strip()
    if remaining:
        pieces.append(remaining)
    return [piece for piece in pieces if piece]


def chunk_markdown(markdown: str, size: int = 4000, overlap: int = 0) -> list[dict[str, Any]]:
    """Split Markdown into context-sized chunks at paragraph boundaries.

    Each chunk records the nearest preceding heading so an agent can tell
    which section it is reading without re-reading the whole document.
    """

    if size <= 0:
        return []
    text = _normalize_markdown(markdown)
    if not text:
        return []
    blocks = re.split(r"\n{2,}", text)
    chunks: list[dict[str, Any]] = []
    current: list[str] = []
    current_len = 0
    heading = ""
    overlap = max(0, min(overlap, size // 2))

    def flush() -> None:
        nonlocal current, current_len
        body = "\n\n".join(current).strip()
        if body:
            chunks.append(
                {
                    "index": len(chunks) + 1,
                    "heading": heading,
                    "chars": len(body),
                    "text": body,
                }
            )
        current = []
        current_len = 0

    for block in blocks:
        block = block.strip()
        if not block:
            continue
        match = re.match(r"^(#{1,6})\s+(.+)$", block)
        if match and len(block) < 300:
            heading = match.group(2).strip()
        pieces = _hard_split_block(block, size) if len(block) > size else [block]
        for piece in pieces:
            if current and current_len + len(piece) + 2 > size:
                flush()
                if overlap and chunks:
                    tail = chunks[-1]["text"][-overlap:]
                    current = [tail]
                    current_len = len(tail)
            current.append(piece)
            current_len += len(piece) + 2
    flush()
    return chunks


def html_to_markdown(
    html: str,
    url: Optional[str] = None,
    *,
    include_tables: bool = True,
    keep_links: bool = False,
    include_images: bool = False,
) -> str:
    """Convert HTML to clean Markdown, preferring trafilatura when available."""

    markdown = _trafilatura_markdown(
        html,
        url=url,
        include_tables=include_tables,
        keep_links=keep_links,
        include_images=include_images,
    )
    if markdown and markdown.strip():
        return _normalize_markdown(markdown)

    return _bs4_to_markdown(
        html,
        url=url,
        include_tables=include_tables,
        keep_links=keep_links,
        include_images=include_images,
    )


def _trafilatura_markdown(
    html: str,
    *,
    url: Optional[str],
    include_tables: bool,
    keep_links: bool,
    include_images: bool,
) -> str:
    try:
        import trafilatura  # type: ignore
    except ImportError:
        return ""
    try:
        return trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_tables=include_tables,
            include_links=keep_links,
            include_images=include_images,
            include_comments=False,
            include_formatting=True,
            favor_recall=True,
            # A global deduplication cache would silently drop sentences seen in
            # an earlier page during a long agent session. Duplicate removal
            # inside one document is already handled by trafilatura itself.
            deduplicate=False,
        ) or ""
    except Exception:
        return ""


@dataclass
class _RenderContext:
    url: Optional[str]
    include_tables: bool
    keep_links: bool
    include_images: bool


def _bs4_to_markdown(
    html: str,
    url: Optional[str],
    *,
    include_tables: bool,
    keep_links: bool,
    include_images: bool,
) -> str:
    """A dependency-light fallback converter used when trafilatura is absent."""

    soup = make_soup(html)
    for tag in soup(list(_SKIP_TAGS)):
        tag.decompose()
    for tag in soup.find_all(attrs={"role": ["navigation", "banner", "contentinfo", "complementary"]}):
        tag.decompose()

    root: Tag = soup.find("article") or soup.find("main") or soup.body or soup  # type: ignore[assignment]
    ctx = _RenderContext(
        url=url,
        include_tables=include_tables,
        keep_links=keep_links,
        include_images=include_images,
    )
    text = _render_children(root, ctx)
    return _normalize_markdown(text)


def _render_children(node: Tag, ctx: _RenderContext) -> str:
    return "".join(_render_node(child, ctx) for child in node.children)


def _render_node(node: Any, ctx: _RenderContext) -> str:
    if isinstance(node, NavigableString):
        text = str(node)
        if not text.strip():
            return "" if "\n" in text else " "
        return _INLINE_WS_RE.sub(" ", text)

    if not isinstance(node, Tag):
        return ""

    name = (node.name or "").lower()
    if name in _SKIP_TAGS:
        return ""
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        heading = _inline(node, ctx).strip()
        if not heading:
            return ""
        return f"\n\n{'#' * int(name[1])} {heading}\n\n"
    if name == "p":
        paragraph = _inline(node, ctx).strip()
        return f"\n\n{paragraph}\n\n" if paragraph else ""
    if name == "br":
        return "  \n"
    if name == "hr":
        return "\n\n---\n\n"
    if name in ("ul", "ol"):
        listing = _render_list(node, ctx)
        return f"\n\n{listing}\n\n" if listing else ""
    if name == "pre":
        code = node.get_text().strip("\n")
        if not code.strip():
            return ""
        return f"\n\n```\n{code}\n```\n\n"
    if name == "blockquote":
        body = _render_children(node, ctx).strip()
        if not body:
            return ""
        quoted = "\n".join(f"> {line}" if line else ">" for line in body.split("\n"))
        return f"\n\n{quoted}\n\n"
    if name == "table":
        if ctx.include_tables:
            table_md = _table_markdown(node)
            if table_md:
                return f"\n\n{table_md}\n\n"
        return f"\n\n{_render_children(node, ctx).strip()}\n\n"
    if name == "img":
        if not ctx.include_images:
            return ""
        src = absolute_url(_attr_text(node, "src"), ctx.url)
        if not src:
            return ""
        alt = _clean_result_text(_attr_text(node, "alt"))
        return f"![{alt}]({src})"
    if name == "a":
        return _inline(node, ctx)
    if name == "code":
        code = node.get_text().strip("\n")
        return f"`{code}`" if code else ""
    if name in ("strong", "b"):
        inner = _inline(node, ctx).strip()
        return f"**{inner}**" if inner else ""
    if name in ("em", "i"):
        inner = _inline(node, ctx).strip()
        return f"*{inner}*" if inner else ""
    return _render_children(node, ctx)


def _inline(node: Tag, ctx: _RenderContext) -> str:
    parts: list[str] = []
    for child in node.children:
        if isinstance(child, NavigableString):
            parts.append(_INLINE_WS_RE.sub(" ", str(child)))
            continue
        if not isinstance(child, Tag):
            continue
        name = (child.name or "").lower()
        if name in _SKIP_TAGS:
            continue
        if name == "br":
            parts.append(" ")
        elif name == "a":
            label = _clean_result_text(child.get_text(" ", strip=True))
            href = absolute_url(_attr_text(child, "href"), ctx.url)
            if ctx.keep_links and href and label:
                parts.append(f"[{label}]({href})")
            else:
                parts.append(label)
        elif name in ("strong", "b"):
            inner = _inline(child, ctx).strip()
            if inner:
                parts.append(f"**{inner}**")
        elif name in ("em", "i"):
            inner = _inline(child, ctx).strip()
            if inner:
                parts.append(f"*{inner}*")
        elif name == "code":
            code = child.get_text().strip("\n")
            if code:
                parts.append(f"`{code}`")
        elif name == "img":
            if ctx.include_images:
                src = absolute_url(_attr_text(child, "src"), ctx.url)
                if src:
                    parts.append(f"![{_clean_result_text(_attr_text(child, 'alt'))}]({src})")
        else:
            parts.append(_inline(child, ctx))
    text = "".join(parts)
    return re.sub(r"[ \t]{2,}", " ", text)


def _render_list(node: Tag, ctx: _RenderContext) -> str:
    ordered = (node.name or "").lower() == "ol"
    try:
        index = _int_attr(node, "start", 1)
    except (TypeError, ValueError):
        index = 1

    lines: list[str] = []
    for item in node.find_all("li", recursive=False):
        body = _render_children(item, ctx).strip()
        body = re.sub(r"\n{2,}", "\n", body)
        body = body.replace("\n", "\n  ")
        marker = f"{index}." if ordered else "-"
        lines.append(f"{marker} {body}".rstrip())
        index += 1
    return "\n".join(lines)


def _escape_table_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ").strip()


def _table_markdown(table: Tag) -> str:
    rows: list[list[str]] = []
    for tr in table.find_all("tr"):
        # Skip rows that belong to a nested table.
        if tr.find_parent("table") is not table:
            continue
        cells: list[str] = []
        for cell in tr.find_all(["th", "td"]):
            if cell.find_parent("tr") is not tr:
                continue
            cells.append(_clean_result_text(cell.get_text(" ", strip=True)))
        if cells:
            rows.append(cells)

    if len(rows) < 2:
        return ""
    width = max(len(row) for row in rows)
    if width < 2:
        return ""
    rows = [row + [""] * (width - len(row)) for row in rows]

    header = rows[0]
    body = rows[1:]
    lines = [
        "| " + " | ".join(_escape_table_cell(cell) for cell in header) + " |",
        "| " + " | ".join("---" for _ in range(width)) + " |",
    ]
    for row in body:
        lines.append("| " + " | ".join(_escape_table_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def extract_tables(html: str, *, max_tables: int = 20, max_columns: int = 40) -> list[dict[str, Any]]:
    """Extract data tables from HTML as structured rows plus Markdown."""

    soup = make_soup(html)
    tables: list[dict[str, Any]] = []
    for table in soup.find_all("table"):
        caption_tag = table.find("caption")
        caption = _clean_result_text(caption_tag.get_text(" ", strip=True)) if caption_tag else ""
        rows: list[list[str]] = []
        for tr in table.find_all("tr"):
            if tr.find_parent("table") is not table:
                continue
            cells = [
                _clean_result_text(cell.get_text(" ", strip=True))
                for cell in tr.find_all(["th", "td"])
                if cell.find_parent("tr") is tr
            ]
            if cells:
                rows.append(cells[:max_columns])
        if len(rows) < 2:
            continue
        width = max(len(row) for row in rows)
        if width < 2:
            continue
        rows = [row + [""] * (width - len(row)) for row in rows]
        tables.append(
            {
                "caption": caption,
                "headers": rows[0],
                "rows": rows[1:],
                "markdown": _table_markdown(table),
            }
        )
        if len(tables) >= max_tables:
            break
    return tables


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------

_DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.I)
_ARXIV_RE = re.compile(r"arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5}|[a-z\-]+/[0-9]{7})", re.I)

_ARTICLE_TYPES = {
    "article",
    "scholarlyarticle",
    "newsarticle",
    "blogposting",
    "techarticle",
    "report",
    "webpage",
}


def _meta_map(soup: BeautifulSoup) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = {}
    for tag in soup.find_all("meta"):
        key = tag.get("name") or tag.get("property") or tag.get("itemprop")
        value = tag.get("content")
        if key and value:
            mapping.setdefault(str(key).strip().lower(), []).append(str(value).strip())
    return mapping


def _first(mapping: dict[str, list[str]], *keys: str) -> str:
    for key in keys:
        values = mapping.get(key.lower())
        if values:
            for value in values:
                if value:
                    return value
    return ""


def _all(mapping: dict[str, list[str]], *keys: str) -> list[str]:
    values: list[str] = []
    for key in keys:
        values.extend(mapping.get(key.lower(), []))
    return [value for value in values if value]


def _iter_jsonld(soup: BeautifulSoup) -> Iterator[dict[str, Any]]:
    for tag in soup.find_all("script"):
        script_type = (tag.get("type") or "").lower()
        if "ld+json" not in script_type:
            continue
        raw = tag.string or tag.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            continue
        yield from _flatten_jsonld(data)


def _flatten_jsonld(data: Any) -> Iterator[dict[str, Any]]:
    if isinstance(data, list):
        for item in data:
            yield from _flatten_jsonld(item)
    elif isinstance(data, dict):
        if "@graph" in data:
            yield from _flatten_jsonld(data["@graph"])
        yield data


def _jsonld_article(soup: BeautifulSoup) -> dict[str, Any]:
    fallback: dict[str, Any] = {}
    for item in _iter_jsonld(soup):
        raw_type = item.get("@type")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        lowered = {str(value).lower() for value in types if value}
        if lowered & _ARTICLE_TYPES:
            return item
        if not fallback and lowered & {"organization", "website", "product"}:
            fallback = item
    return fallback


def _jsonld_names(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, dict):
        name = value.get("name") or value.get("legalName")
        return [str(name).strip()] if name else []
    if isinstance(value, list):
        names: list[str] = []
        for item in value:
            names.extend(_jsonld_names(item))
        return names
    return []


def _jsonld_publisher(value: Any) -> str:
    if isinstance(value, dict):
        name = value.get("name")
        if name:
            return str(name).strip()
        parent = value.get("parentOrganization")
        return _jsonld_publisher(parent) if parent else ""
    if isinstance(value, list) and value:
        return _jsonld_publisher(value[0])
    if isinstance(value, str):
        return value.strip()
    return ""


def _clean_doi(value: str) -> str:
    return value.rstrip(".,;:)]}。，；").strip()


def extract_metadata(html: str, url: Optional[str] = None) -> dict[str, Any]:
    """Extract bibliographic and social metadata without external services."""

    soup = make_soup(html)
    meta = _meta_map(soup)
    jsonld = _jsonld_article(soup)

    title = _first(meta, "citation_title", "og:title", "twitter:title", "dc.title")
    if not title:
        title_tag = soup.find("title")
        title = _clean_result_text(title_tag.get_text() if title_tag else "")
    if not title:
        title = str(jsonld.get("headline") or jsonld.get("name") or "").strip()

    authors = _all(meta, "citation_author", "dc.creator", "dcterms.creator", "author")
    if not authors:
        authors = _jsonld_names(jsonld.get("author"))

    published = _first(
        meta,
        "citation_publication_date",
        "citation_date",
        "article:published_time",
        "date",
        "dc.date",
        "dcterms.date",
    ) or str(jsonld.get("datePublished") or "").strip()

    modified = _first(meta, "article:modified_time", "og:updated_time") or str(
        jsonld.get("dateModified") or ""
    ).strip()

    journal = _first(meta, "citation_journal_title", "citation_conference_title")
    if not journal:
        journal = _jsonld_publisher(jsonld.get("isPartOf"))

    doi = _first(meta, "citation_doi", "dc.identifier", "dcterms.identifier")
    if not doi:
        candidate = ""
        if url:
            match = _DOI_RE.search(url)
            if match:
                candidate = match.group(0)
        if not candidate:
            match = _DOI_RE.search(html[:500_000])
            if match:
                candidate = match.group(0)
        doi = candidate
    doi = _clean_doi(doi)

    abstract = _first(
        meta, "citation_abstract", "dc.description", "og:description", "description", "twitter:description"
    ) or str(jsonld.get("description") or "").strip()

    keywords_raw = _all(meta, "citation_keywords", "keywords")
    jsonld_keywords = jsonld.get("keywords")
    if isinstance(jsonld_keywords, str):
        keywords_raw.append(jsonld_keywords)
    elif isinstance(jsonld_keywords, list):
        keywords_raw.extend(str(item) for item in jsonld_keywords)
    keywords: list[str] = []
    for chunk in keywords_raw:
        for word in re.split(r"[,;，；]", chunk):
            word = word.strip()
            if word and word not in keywords:
                keywords.append(word)

    canonical = ""
    for link in soup.find_all("link"):
        rel = [str(value).lower() for value in (link.attrs.get("rel") or [])]
        if "canonical" in rel and _attr_text(link, "href"):
            canonical = absolute_url(_attr_text(link, "href"), url)
            if canonical:
                break
    canonical = canonical or _first(meta, "og:url")

    language = ""
    html_tag = soup.find("html")
    if html_tag and _attr_text(html_tag, "lang"):
        language = _attr_text(html_tag, "lang")
    language = language or _first(meta, "content-language", "dc.language") or str(
        jsonld.get("inLanguage") or ""
    ).strip()

    arxiv_id = _first(meta, "citation_arxiv_id")
    if not arxiv_id:
        match = _ARXIV_RE.search(url or "") or _ARXIV_RE.search(html[:200_000])
        if match:
            arxiv_id = match.group(1)

    return {
        "title": title,
        "authors": [author for author in authors if author],
        "published": published,
        "modified": modified,
        "journal": journal,
        "volume": _first(meta, "citation_volume"),
        "issue": _first(meta, "citation_issue"),
        "first_page": _first(meta, "citation_firstpage"),
        "last_page": _first(meta, "citation_lastpage"),
        "doi": doi,
        "arxiv_id": arxiv_id,
        "abstract": abstract,
        "keywords": keywords,
        "language": language,
        "site_name": _first(meta, "og:site_name", "application-name") or str(
            jsonld.get("publisher", {}).get("name")
            if isinstance(jsonld.get("publisher"), dict)
            else ""
        ).strip(),
        "canonical_url": canonical,
        "og_type": _first(meta, "og:type"),
    }


# ---------------------------------------------------------------------------
# Optional dynamic rendering
# ---------------------------------------------------------------------------


def render_html(url: str, config: FetchConfig) -> str:
    """Render a page with Playwright/Chromium (optional dependency)."""

    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:
        raise RenderUnavailable(
            "Playwright is not installed; dynamic rendering is disabled. "
            "Enable it with: pip install playwright && playwright install chromium"
        ) from exc
    except Exception as exc:
        raise RenderUnavailable(
            f"Playwright could not be imported ({exc}). Reinstall it with: "
            "pip install playwright && playwright install chromium"
        ) from exc

    timeout_ms = max(5_000, int(config.timeout * 1000))
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = browser.new_context(user_agent=config.user_agent)
                page = context.new_page()
                page.set_default_timeout(timeout_ms)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=min(5_000, timeout_ms))
                except Exception:
                    pass
                if config.wait_for:
                    try:
                        page.wait_for_selector(config.wait_for, timeout=min(10_000, timeout_ms))
                    except Exception:
                        pass
                for _ in range(config.scroll):
                    try:
                        page.mouse.wheel(0, 1800)
                        page.wait_for_timeout(350)
                    except Exception:
                        break
                page.wait_for_timeout(500)
                html = page.content()
                context.close()
                return html
            finally:
                browser.close()
    except RenderUnavailable:
        raise
    except Exception as exc:
        raise RenderUnavailable(f"Playwright rendering failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Link discovery, sessions and agentic browsing
# ---------------------------------------------------------------------------

_SKIP_LINK_WORDS = (
    "登录",
    "注册",
    "隐私",
    "免责声明",
    "广告",
    "login",
    "sign in",
    "sign up",
    "register",
    "privacy",
    "cookie",
)
_SKIP_LINK_EXTENSIONS = (".zip", ".rar", ".7z", ".exe", ".dmg", ".apk", ".mp4", ".mp3", ".iso")


def _link_in_skipped_region(anchor: Tag) -> bool:
    """True for chrome (nav, forms, page header) but not an article's header.

    A results page commonly wraps each card's title in ``<article><header>``;
    skipping every ``<header>`` silently dropped the very links a caller wants.
    """

    inside_content = anchor.find_parent(["article", "main"]) is not None
    for parent in anchor.parents:
        name = parent.name
        if name not in _SKIP_TAGS:
            continue
        if name == "header" and inside_content:
            continue
        return True
    return False


def extract_links(
    html: str,
    base_url: str,
    query: str = "",
    limit: int = 20,
    same_site: bool = True,
) -> list[dict[str, Any]]:
    """Rank in-page links for a follow-up visit.

    Ordering follows the query: anchor text that covers more query tokens
    ranks first; ties keep document order (how a human scans a page).
    """

    soup = make_soup(html)
    base_host = urllib.parse.urlsplit(base_url).netloc.lower()
    tokens = _query_tokens(query)
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    order = 0

    for anchor in soup.find_all("a", href=True):
        if _link_in_skipped_region(anchor):
            continue
        url = absolute_url(_attr_text(anchor, "href"), base_url)
        if not url or url in seen:
            continue
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in _ALLOWED_SCHEMES:
            continue
        if same_site and parts.netloc.lower() != base_host:
            continue
        text = _clean_result_text(anchor.get_text(" ", strip=True))
        if len(text) < 3:
            continue
        lowered = text.lower()
        if any(word in lowered for word in _SKIP_LINK_WORDS):
            continue
        if any(parts.path.lower().endswith(ext) for ext in _SKIP_LINK_EXTENSIONS):
            continue
        score = result_coverage({"title": text, "snippet": "", "url": url}, tokens)
        candidates.append(
            {"url": url, "text": text, "score": round(score, 3), "order": order}
        )
        seen.add(url)
        order += 1

    candidates.sort(key=lambda item: (-item["score"], item["order"]))
    return candidates[:limit]


def session_path(name: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(name or "")).strip("-._") or "default"
    return Path.home() / ".web-forager" / "sessions" / f"{safe}.json"


def load_session(name: str) -> dict[str, Any]:
    path = session_path(name)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("visited", [])
    data.setdefault("trail", [])
    return data


def save_session(name: str, data: dict[str, Any]) -> Path:
    path = session_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "visited": list(data.get("visited", []))[-1000:],
        "trail": list(data.get("trail", []))[-500:],
        "updated_at": utc_now(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def surf_web(
    seed: str,
    config: Optional[FetchConfig] = None,
    depth: int = 1,
    follow: Optional[str] = None,
    max_pages: Optional[int] = None,
    engine_name: str = "auto",
    session: Optional[str] = None,
    fetcher: Optional[HttpFetcher] = None,
) -> dict[str, Any]:
    """Search or open a page, then follow ranked links like a human browsing.

    ``--session`` makes the walk resumable: visited URLs are skipped on the
    next run and the trail is appended to ``~/.web-forager/sessions/<name>.json``.
    """

    config = config or FetchConfig()
    config.validate()
    follow = follow or config.follow
    if follow not in ("same-site", "all", "none"):
        raise ValueError("follow must be same-site, all or none")
    config.follow = follow
    config.extract_links = True
    max_pages = max_pages or config.max_pages

    own_fetcher = fetcher is None
    fetcher = fetcher or HttpFetcher(config)
    session_data = load_session(session) if session else {"visited": [], "trail": []}
    visited: set[str] = set(session_data.get("visited", []))
    trail: list[dict[str, Any]] = list(session_data.get("trail", []))
    pages: list[dict[str, Any]] = []
    search_results: list[dict[str, str]] = []

    seed_text = str(seed or "").strip()
    if not seed_text:
        raise ValueError("surf needs a URL or a search query")
    is_url = seed_text.lower().startswith(("http://", "https://"))
    query = "" if is_url else seed_text

    try:
        if is_url:
            seeds = [normalize_url(seed_text)]
        else:
            search_results = search(
                query, config, engine=engine_name, limit=config.num_results, fetcher=fetcher
            )
            seeds = [item["url"] for item in search_results[:max_pages]]

        queue: list[tuple[str, str, int]] = [(url, "search" if not is_url else "seed", 0) for url in seeds]

        while queue and len(pages) < max_pages:
            url, origin, level = queue.pop(0)
            if url in visited:
                continue
            visited.add(url)
            try:
                page = fetch_page(url, config, fetcher=fetcher, query=query)
            except (
                RobotsDenied,
                FetchError,
                ExtractionError,
                RenderUnavailable,
                PdfUnavailable,
                PdfExtractionError,
            ) as exc:
                pages.append({"url": url, "error": f"{exc.__class__.__name__}: {exc}"})
                trail.append(
                    {
                        "step": len(trail) + 1,
                        "level": level,
                        "from": origin,
                        "url": url,
                        "error": f"{exc.__class__.__name__}: {exc}",
                    }
                )
                continue

            pages.append(page)
            trail.append(
                {
                    "step": len(trail) + 1,
                    "level": level,
                    "from": origin,
                    "url": url,
                    "title": page.get("title", ""),
                }
            )

            if level < depth and follow != "none":
                for link in page.get("links", [])[: config.max_links]:
                    if link["url"] in visited:
                        continue
                    queue.append((link["url"], url, level + 1))

        return {
            "mode": "surf",
            "seed": seed_text,
            "query": query,
            "engine": engine_name,
            "depth": depth,
            "follow": follow,
            "session": session or "",
            "search_results": search_results,
            "trail": trail,
            "visited": sorted(visited),
            "pages": pages,
        }
    finally:
        if session:
            save_session(session, {"visited": sorted(visited), "trail": trail})
        if own_fetcher:
            fetcher.close()


# ---------------------------------------------------------------------------
# High-level pipeline
# ---------------------------------------------------------------------------


def fetch_page(
    url: str,
    config: Optional[FetchConfig] = None,
    fetcher: Optional[HttpFetcher] = None,
    query: str = "",
) -> dict[str, Any]:
    """Fetch one URL and return a JSON-serialisable record."""

    config = config or FetchConfig()
    config.validate()
    url = normalize_url(url)
    own_fetcher = fetcher is None
    fetcher = fetcher or HttpFetcher(config)
    warnings: list[str] = []

    try:
        policy = fetcher.assert_allowed(url)
        extra_delay = policy.crawl_delay if policy and policy.crawl_delay else 0.0

        response: Optional[HttpResponse] = None
        rendered = False
        html = ""

        if config.render == "always":
            fetcher.limiter.wait(url, extra_delay)
            html = render_html(url, config)
            rendered = True
        else:
            response = fetcher.fetch(url)
            html = response.text
            if config.render == "auto" and looks_dynamic(html):
                try:
                    rendered_html = render_html(url, config)
                    if rendered_html and len(rendered_html) > len(html):
                        html = rendered_html
                        rendered = True
                        log(f"rendered dynamically: {url}", config)
                except RenderUnavailable as exc:
                    warnings.append(f"dynamic rendering skipped: {exc}")
                except Exception as exc:  # pragma: no cover - defensive
                    warnings.append(f"dynamic rendering failed: {exc}")

        content_type = response.content_type if response else "text/html"
        final_url = response.final_url if response else url
        status = response.status if response else 200

        from . import documents, feeds, pdf as pdf_mod

        is_pdf_payload = response is not None and (
            content_type in _PDF_CONTENT_TYPES or pdf_mod.is_pdf(response.content)
        )
        document_kind = ""
        feed_format = ""

        if is_pdf_payload and response is not None:
            try:
                pdf_document = pdf_mod.extract(response.content)
            except pdf_mod.PdfUnavailable as exc:
                raise PdfUnavailable(str(exc)) from exc
            except pdf_mod.PdfError as exc:
                raise PdfExtractionError(str(exc)) from exc
            markdown = pdf_mod.to_markdown(pdf_document, url=final_url)
            metadata = pdf_mod.to_metadata(pdf_document, url=final_url)
            tables = []
            warnings.append(
                f"PDF text extracted: {pdf_document.get('page_count', 0)} page(s), "
                f"{pdf_document.get('empty_pages', 0)} empty"
            )
        elif response is not None and (
            document_kind := documents.detect(response.content, content_type, final_url)
        ):
            document = documents.extract(
                response.content, document_kind, content_type, final_url
            )
            markdown = document["markdown"]
            metadata = documents.to_metadata(document, final_url)
            tables = document.get("tables") or []
            warnings.append(f"{document_kind.upper()} extracted")
        elif response is not None and (
            content_type in _FEED_CONTENT_TYPES
            or (
                ("<rss" in html[:1000].lower() or "<feed" in html[:1000].lower())
                and feeds.is_feed(html)
            )
        ):
            feed = feeds.extract(html, limit=max(1, config.num_results))
            feed_format = feed["format"]
            markdown = feed["markdown"]
            metadata = feeds.to_metadata(feed, final_url)
            tables = []
            warnings.append(f"feed parsed: {feed['format']} with {feed['count']} item(s)")
        elif any(ct in content_type for ct in _JSON_CONTENT_TYPES) and response is not None:
            markdown = "```json\n" + response.text.strip() + "\n```"
            metadata = {
                "title": "",
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
                "abstract": "",
                "keywords": [],
                "language": "",
                "site_name": "",
                "canonical_url": "",
                "og_type": "",
            }
            tables: list[dict[str, Any]] = []
        else:
            markdown = html_to_markdown(
                html,
                url=final_url,
                include_tables=config.include_tables,
                keep_links=config.keep_links,
                include_images=config.include_images,
            )
            metadata = extract_metadata(html, url=final_url)
            tables = extract_tables(html) if config.include_tables else []

        if not markdown.strip():
            raise ExtractionError(
                f"no readable content extracted from {final_url}; "
                "the page may be empty, paywalled, or require JavaScript rendering"
            )

        if config.max_chars and len(markdown) > config.max_chars:
            markdown = markdown[: config.max_chars].rstrip() + "\n\n<!-- truncated by web-forager -->"
            warnings.append(f"markdown truncated to {config.max_chars} characters")

        links = []
        if config.extract_links and not is_pdf_payload and not document_kind and not feed_format:
            links = extract_links(
                html,
                final_url,
                query=query,
                limit=config.max_links,
                same_site=config.follow == "same-site",
            )

        chunks = chunk_markdown(markdown, config.chunk_size) if config.chunk_size else []

        return {
            "url": url,
            "final_url": final_url,
            "status": status,
            "content_type": content_type,
            "document_kind": document_kind,
            "feed_format": feed_format,
            "cached": bool(response.from_cache) if response else False,
            "rendered": rendered,
            "fetched_at": utc_now(),
            "title": metadata.get("title", ""),
            "metadata": metadata,
            "markdown": markdown,
            "chunks": chunks,
            "tables": tables,
            "links": links,
            "warnings": warnings,
        }
    finally:
        if own_fetcher:
            fetcher.close()


def search_warnings(
    query: str, results: list[dict[str, Any]], engine: str = "auto"
) -> list[str]:
    """Warnings for a search that returned nothing or nothing relevant.

    Both the CLI and the MCP server attach these, so an agent that receives a
    list of dictionary pages is told they are unrelated instead of reporting
    them as findings.
    """

    warnings: list[str] = []
    tokens = _query_tokens(query)
    if not results:
        warnings.append(
            f"no results: {engine} returned nothing for {query!r}. Try another "
            "engine (--engine all), a shorter query, or a direct URL."
        )
    elif tokens and max(result_coverage(item, tokens) for item in results) <= 0:
        warnings.append(
            "none of the returned results mention the query text; the engine "
            "most likely split the query into single characters (common with "
            "quoted or CJK names). Treat these results as unrelated and try "
            "another engine or a more specific query."
        )
    return warnings


SITE_SEARCH_TEMPLATES = (
    "/?s={query}",
    "/search?q={query}",
    "/?search={query}",
    "/search?query={query}",
)


def find_within_site(
    site: str,
    query: str,
    config: Optional[FetchConfig] = None,
    fetcher: Optional[HttpFetcher] = None,
    max_pages: Optional[int] = None,
) -> dict[str, Any]:
    """Search inside one site through the site's own search page.

    The general engines are unreliable in some networks while a WordPress-style
    ``/?s=`` page answers directly. This reads that page, ranks its links by
    query coverage, and fetches the best ones — the same route a person takes
    when they already know where the content lives.
    """

    config = config or FetchConfig()
    config.validate()
    site = (site or "").strip()
    query = (query or "").strip()
    if not site:
        raise ValueError("site must not be empty")
    if not query:
        raise ValueError("query must not be empty")
    site_url = normalize_url(site if "://" in site else "https://" + site)
    pages_limit = config.max_pages if max_pages is None else max(0, max_pages)
    own_fetcher = fetcher is None
    fetcher = fetcher or HttpFetcher(config)

    attempts: list[dict[str, Any]] = []
    page: Optional[HttpResponse] = None
    search_url = ""
    try:
        for template in SITE_SEARCH_TEMPLATES:
            candidate = site_url.rstrip("/") + template.format(
                query=urllib.parse.quote_plus(query)
            )
            started = time.monotonic()
            try:
                response = fetcher.fetch(candidate)
            except (FetchError, RobotsDenied) as exc:
                attempts.append(
                    {
                        "url": candidate,
                        "ok": False,
                        "error": f"{exc.__class__.__name__}: {exc}",
                        "ms": round((time.monotonic() - started) * 1000),
                    }
                )
                continue
            attempts.append(
                {
                    "url": candidate,
                    "ok": True,
                    "status": response.status,
                    "ms": round((time.monotonic() - started) * 1000),
                }
            )
            if response.status == 200 and response.text.strip():
                page = response
                search_url = response.final_url or candidate
                break
        if page is None:
            detail = "; ".join(
                f"{item['url']}: {item.get('error', 'empty response')}" for item in attempts
            )
            raise FetchError(f"no readable search page on {site_url} ({detail})")

        warnings: list[str] = []
        candidates = extract_links(
            page.text, search_url, query=query, limit=config.max_links, same_site=True
        )
        # The search page links back to itself ("skip to content", the form's
        # action); those are navigation, not results.
        search_stem = search_url.split("?")[0].rstrip("/")
        candidates = [
            item
            for item in candidates
            if item.get("url", "").split("?")[0].rstrip("/") != search_stem
        ]
        matched = [item for item in candidates if item.get("score", 0) > 0]
        if matched:
            candidates = matched
        elif candidates:
            warnings.append(
                "the site's search page carried no link whose text mentions the "
                "query; its ranked links are returned unfiltered"
            )
        else:
            warnings.append("the site's search page carried no followable links")

        pages: list[dict[str, Any]] = []
        for item in candidates[:pages_limit]:
            try:
                pages.append(fetch_page(item["url"], config, fetcher=fetcher))
            except (RobotsDenied, FetchError, ExtractionError, RenderUnavailable) as exc:
                pages.append(
                    {
                        "url": item["url"],
                        "error": f"{exc.__class__.__name__}: {exc}",
                        "warnings": [],
                    }
                )

        payload: dict[str, Any] = {
            "mode": "site-search",
            "site": site_url,
            "query": query,
            "search_url": search_url,
            "candidates": candidates,
            "pages": pages,
            "attempts": attempts,
        }
        if warnings:
            payload["warnings"] = warnings
        return payload
    finally:
        if own_fetcher:
            fetcher.close()


_FEED_LINK_TYPES = ("rss", "atom", "feed")


def discover_feed(
    url: str,
    config: Optional[FetchConfig] = None,
    fetcher: Optional[HttpFetcher] = None,
) -> dict[str, Any]:
    """Read a feed, discovering it from a page's ``<link rel=alternate>`` first.

    A site's own feed needs no search engine and no rendering: it is the
    cheapest way to follow a publication in a network where the engines fail.
    """

    from . import feeds

    config = config or FetchConfig()
    config.validate()
    url = (url or "").strip()
    if not url:
        raise ValueError("url must not be empty")
    own_fetcher = fetcher is None
    fetcher = fetcher or HttpFetcher(config)

    try:
        response = fetcher.fetch(normalize_url(url))
        if feeds.is_feed(response.text) or response.content_type in _FEED_CONTENT_TYPES:
            feed_url = response.final_url
            feed = feeds.extract(response.text, limit=max(1, config.num_results))
        else:
            soup = make_soup(response.text)
            href = ""
            for link in soup.find_all("link"):
                rel = " ".join(str(value) for value in (link.get("rel") or [])).lower()
                kind = str(link.get("type") or "").lower()
                if "alternate" in rel and any(word in kind for word in _FEED_LINK_TYPES):
                    href = absolute_url(_attr_text(link, "href"), response.final_url)
                    if href:
                        break
            if not href:
                raise ExtractionError(
                    f"no RSS/Atom <link rel=alternate> found at {response.final_url}"
                )
            feed_response = fetcher.fetch(href)
            if not feeds.is_feed(feed_response.text):
                raise ExtractionError(
                    f"{feed_response.final_url} is not an RSS/Atom feed"
                )
            feed = feeds.extract(feed_response.text, limit=max(1, config.num_results))
            feed_url = feed_response.final_url
        return {
            "mode": "feed",
            "feed_url": feed_url,
            "format": feed["format"],
            "count": feed["count"],
            "items": feed.get("items") or [],
            "markdown": feed["markdown"],
            "metadata": feeds.to_metadata(feed, feed_url),
        }
    finally:
        if own_fetcher:
            fetcher.close()


def probe_engines(
    config: Optional[FetchConfig] = None,
    fetcher: Optional[HttpFetcher] = None,
    query: str = "web forager",
) -> list[dict[str, Any]]:
    """Ask every search engine once and report which ones answer right now.

    A network can block one engine and allow another; the report turns "search
    is broken" into "Bing answers, Sogou shows a verification page".
    """

    config = config or FetchConfig()
    config.validate()
    # A probe is a diagnostic, not a retry exercise: one attempt per engine
    # keeps a blocking network from turning the report into a 60-second wait.
    probe_config = dataclasses.replace(config, retries=0)
    own_fetcher = fetcher is None
    fetcher = fetcher or HttpFetcher(probe_config)
    report: list[dict[str, Any]] = []
    try:
        for name in ("360", "bing", "sogou", "weixin", "duckduckgo"):
            started = time.monotonic()
            try:
                items = _search_one(name, query, probe_config, 1, fetcher, pages=1)
                entry: dict[str, Any] = {
                    "engine": name,
                    "ok": bool(items),
                    "results": len(items),
                    "ms": round((time.monotonic() - started) * 1000),
                }
                if not items:
                    entry["error"] = "returned no results (empty page or a challenge page)"
                report.append(entry)
            except Exception as exc:
                report.append(
                    {
                        "engine": name,
                        "ok": False,
                        "results": 0,
                        "error": str(exc),
                        "ms": round((time.monotonic() - started) * 1000),
                    }
                )
    finally:
        if own_fetcher:
            fetcher.close()
    return report


def fetch_by_query(
    query: str,
    config: Optional[FetchConfig] = None,
    engine: str = "auto",
    fetcher: Optional[HttpFetcher] = None,
) -> dict[str, Any]:
    """Search for a keyword query, then fetch and clean the top results."""

    config = config or FetchConfig()
    config.validate()
    own_fetcher = fetcher is None
    fetcher = fetcher or HttpFetcher(config)

    try:
        engine_report: list[dict[str, Any]] = []
        results = search(
            query,
            config,
            engine=engine,
            limit=config.num_results,
            fetcher=fetcher,
            report=engine_report,
        )
        pages: list[dict[str, Any]] = []
        for result in results[: config.max_pages]:
            try:
                pages.append(fetch_page(result["url"], config, fetcher=fetcher))
            except (RobotsDenied, FetchError, ExtractionError, RenderUnavailable) as exc:
                pages.append(
                    {
                        "url": result["url"],
                        "error": f"{exc.__class__.__name__}: {exc}",
                        "warnings": [],
                    }
                )
            except Exception as exc:  # pragma: no cover - defensive
                pages.append(
                    {
                        "url": result["url"],
                        "error": f"unexpected error: {exc}",
                        "warnings": [],
                    }
                )
        payload: dict[str, Any] = {
            "query": query,
            "engine": engine,
            "mode": "search",
            "search_results": results,
            "engine_report": engine_report,
            "pages": pages,
        }
        warnings = search_warnings(query, results, engine=engine)
        if warnings:
            payload["warnings"] = warnings
        return payload
    finally:
        if own_fetcher:
            fetcher.close()


def summarize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Return a compact index entry for one fetched page.

    ``results`` used to repeat every page in full, so a search response carried
    each Markdown body twice and callers with a response cap lost the tail.
    The body lives in ``pages`` once; this is the entry an agent loops over.
    """

    if not isinstance(record, dict):
        return {"value": record}
    summary: dict[str, Any] = {
        "url": record.get("url") or record.get("final_url") or "",
        "title": record.get("title", ""),
        "status": record.get("status"),
        "content_type": record.get("content_type", ""),
        "markdown_chars": len(record.get("markdown") or ""),
        "tables": len(record.get("tables") or []),
    }
    if record.get("error"):
        summary.pop("status", None)
        summary["error"] = record["error"]
    if record.get("warnings"):
        summary["warnings"] = record["warnings"]
    return summary


def redact_url(value: str) -> str:
    """Drop credentials from a URL before it is printed.

    A proxy URL often carries ``user:password@``; a report must show the host
    and port without turning the password into plain text in a log.
    """

    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        text = "http://" + text
    try:
        parts = urllib.parse.urlsplit(text)
    except ValueError:
        return ""
    host = parts.hostname or ""
    port = f":{parts.port}" if parts.port else ""
    scheme = parts.scheme or "http"
    return f"{scheme}://{host}{port}" if host else ""


def doctor_report(config: Optional[FetchConfig] = None) -> dict[str, Any]:
    """Report which capabilities this interpreter can serve, with install hints.

    An agent that gets a rendered-less page can run this and install what is
    missing instead of guessing why the output was thin.
    """

    import importlib.metadata
    import importlib.util
    import platform
    import shutil

    def version_of(distribution: str) -> str:
        try:
            return importlib.metadata.version(distribution)
        except Exception:
            return ""

    def check(name: str, module: str, distribution: str, hint: str, required: bool) -> dict[str, Any]:
        entry: dict[str, Any] = {"name": name, "required": required}
        try:
            available = importlib.util.find_spec(module) is not None
        except (ImportError, ValueError):
            available = False
        entry["ok"] = available
        if available:
            entry["version"] = version_of(distribution)
        elif hint:
            entry["hint"] = hint
        return entry

    checks = [
        check("requests", "requests", "requests", "pip install requests", True),
        check("beautifulsoup4", "bs4", "beautifulsoup4", "pip install beautifulsoup4", True),
        check("trafilatura", "trafilatura", "trafilatura", "pip install trafilatura", True),
        check(
            "playwright",
            "playwright",
            "playwright",
            "pip install playwright && playwright install chromium",
            False,
        ),
        check("pypdf", "pypdf", "pypdf", "pip install pypdf", False),
        check("defusedxml", "defusedxml", "defusedxml", "pip install defusedxml", False),
    ]
    node_path = shutil.which("node")
    if node_path:
        checks.append({"name": "node", "required": False, "ok": True, "path": node_path})
    else:
        checks.append(
            {
                "name": "node",
                "required": False,
                "ok": False,
                "hint": "install Node.js 18+ only if you use browser mode",
            }
        )

    proxy_value = ""
    proxy_source = ""
    if config is not None and config.proxy:
        proxy_value = config.proxy
        proxy_source = "config"
    else:
        for key in (
            "HTTPS_PROXY",
            "https_proxy",
            "ALL_PROXY",
            "all_proxy",
            "HTTP_PROXY",
            "http_proxy",
        ):
            value = os.environ.get(key, "").strip()
            if value:
                proxy_value = value
                proxy_source = f"env:{key}"
                break

    missing_required = [item["name"] for item in checks if item["required"] and not item["ok"]]
    return {
        "ok": not missing_required,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "version": __version__,
        "missing_required": missing_required,
        "checks": checks,
        "proxy": {
            "configured": bool(proxy_value),
            "source": proxy_source,
            "url": redact_url(proxy_value),
        },
    }


def build_envelope(
    action: str, payload: dict[str, Any], full_results: bool = False
) -> dict[str, Any]:
    """Wrap a payload with tool metadata for stable downstream parsing.

    ``results`` is the flat list an agent loops over: fetched pages, videos or
    Bilibili items.  It holds a compact index unless ``full_results`` is set,
    because repeating every page body in both ``pages`` and ``results`` doubled
    the response and pushed the tail past a caller's size cap.  A surf run keeps
    its extra ``trail``/``visited`` fields.
    """

    envelope: dict[str, Any] = {
        "tool": "web-forager",
        "version": __version__,
        "action": action,
        "generated_at": utc_now(),
    }
    envelope.update(payload)
    if "results" not in envelope:
        if "pages" in payload:
            if full_results:
                envelope["results"] = payload["pages"]
            else:
                snippets = {
                    item.get("url", ""): item.get("snippet", "")
                    for item in payload.get("search_results") or []
                }
                entries: list[dict[str, Any]] = []
                for page in payload["pages"]:
                    entry = summarize_record(page)
                    snippet = snippets.get(page.get("url") or page.get("final_url") or "")
                    if snippet:
                        entry["snippet"] = snippet
                    entries.append(entry)
                envelope["results"] = entries
        elif "videos" in payload:
            envelope["results"] = payload["videos"]
        elif "search_results" in payload:
            envelope["results"] = payload["search_results"]
        elif "markdown" in payload or "error" in payload:
            envelope["results"] = [payload] if full_results else [summarize_record(payload)]
        else:
            envelope["results"] = [payload]
    return envelope


CORE_SHARED_KEYS = (
    "metadata",
    "markdown",
    "tables",
    "warnings",
    "url",
    "final_url",
    "title",
    "captured_at",
    "fetched_at",
    "collected_at",
    "source",
    "mode",
    "schema_version",
)


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    """Fold an HTTP record onto the core shape the browser mode also emits.

    The two modes share four fields -- ``metadata``, ``markdown``, ``tables``
    and ``warnings`` -- and differ everywhere else.  ``normalize_record`` maps
    both onto ``core-1`` so a caller can read one list of results without
    branching on the mode; everything mode-specific is kept under ``extra``
    rather than dropped.  The browser side has the same function in
    ``browser/lib/record.js``.
    """

    value = dict(record or {})
    metadata = value.get("metadata") or {}
    if not isinstance(metadata, dict):
        metadata = {}
    raw_source = value.get("source")
    browser = raw_source == "web-forager-browser" or bool(value.get("captured_at"))
    extra = {key: item for key, item in value.items() if key not in CORE_SHARED_KEYS}
    # ``clean`` records use ``source`` for the local file path, which is not the
    # producer name; keep it in extra instead of overwriting the core field.
    if raw_source and raw_source not in ("web-forager", "web-forager-browser"):
        extra["record_source"] = raw_source
    tables = value.get("tables")
    warnings = value.get("warnings")
    return {
        "schema_version": "core-1",
        "source": "web-forager-browser" if browser else "web-forager",
        "mode": "browser" if browser else "http",
        "url": value.get("url") or value.get("final_url") or "",
        "title": value.get("title") or metadata.get("title") or "",
        "collected_at": value.get("collected_at") or value.get("captured_at") or value.get("fetched_at") or "",
        "metadata": metadata,
        "markdown": value.get("markdown") or "",
        "tables": tables if isinstance(tables, list) else [],
        "warnings": warnings if isinstance(warnings, list) else [],
        "extra": extra,
    }


def apply_core(envelope: dict[str, Any]) -> dict[str, Any]:
    """Replace an envelope's ``results`` list with core-1 records."""

    output = dict(envelope)
    results = output.get("results")
    if isinstance(results, list):
        output["results"] = [normalize_record(item) for item in results if isinstance(item, dict)]
    elif isinstance(results, dict):
        output["results"] = normalize_record(results)
    elif "markdown" in output or "metadata" in output:
        # A single-record action (``clean``) keeps its record at the top level.
        record = {
            key: value
            for key, value in output.items()
            if key not in ("tool", "version", "action", "generated_at")
        }
        output["results"] = [normalize_record(record)]
    return output
