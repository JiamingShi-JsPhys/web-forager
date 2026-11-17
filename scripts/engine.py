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
import ipaddress
import json
import os
import re
import socket
import sys
import threading
import time
import urllib.parse
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Optional

import requests
from bs4 import BeautifulSoup
from bs4.element import NavigableString, Tag

from . import untrusted

__version__ = "1.3.1"

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


class VerificationRequired(WebForagerError):
    """The site answered with a verification or anti-bot page, not content.

    HTTP mode cannot pass these interstitials: doing so would mean solving a
    challenge, which this tool does not do.  Browser mode may succeed when the
    page is readable in a real profile that has already passed verification.
    """


class RenderUnavailable(WebForagerError):
    """Dynamic rendering was requested but Playwright is not usable."""


class PdfUnavailable(WebForagerError):
    """PDF support was requested but pypdf is not usable."""


class PdfExtractionError(WebForagerError):
    """The PDF could not be parsed or contained no text."""


class ProhibitedQuery(WebForagerError):
    """The query asks to identify a private person and is refused."""


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


def _allow_private_from_env() -> bool:
    """Local fixtures and trusted intranet tools set WEB_FORAGER_ALLOW_PRIVATE=1."""

    return os.environ.get("WEB_FORAGER_ALLOW_PRIVATE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _query_robots_from_env() -> str:
    """User-level policy for query endpoints (search, scholarly APIs).

    This is deliberately an environment/CLI decision, not an MCP parameter:
    a fetched page must never be able to turn robots off for the agent.
    """

    value = os.environ.get("WEB_FORAGER_QUERY_ROBOTS", "warn").strip().lower()
    return value if value in ("respect", "warn", "ignore") else "warn"


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
    # respect: refuse a disallowed path; warn: read it and mark the record;
    # ignore: do not consult robots.txt (same as respect_robots=False).
    robots_policy: str = "respect"
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
    # Query interfaces (search engines, scholarly APIs) have their own policy.
    # warn reads a disallowed endpoint and records the override; respect
    # refuses it; ignore skips the check. MCP never lets the model choose.
    query_robots: str = field(default_factory=_query_robots_from_env)
    search_pages: int = 1
    # Engines are different hosts, so they may run at once without breaking the
    # per-origin delay. Set False for a strictly serial diagnostic run.
    parallel_engines: bool = True
    cache: bool = False
    cache_ttl: int = 3600
    cache_dir: str = ""
    chunk_size: int = 0
    wait_for: str = ""
    scroll: int = 0
    proxy: str = ""               # http(s) proxy for every request; "" uses the environment
    # Refuse private/loopback/link-local targets unless the caller opts in.
    allow_private: bool = field(default_factory=_allow_private_from_env)
    # off | mark | strict: what to do with instruction-shaped page text.
    input_gate: str = "mark"

    def validate(self) -> None:
        if self.render not in ("auto", "never", "always"):
            raise ValueError("render must be auto, never or always")
        if self.robots_policy not in ("respect", "warn", "ignore"):
            raise ValueError("robots_policy must be respect, warn or ignore")
        if self.query_robots not in ("respect", "warn", "ignore"):
            raise ValueError("query_robots must be respect, warn or ignore")
        if self.input_gate not in ("off", "mark", "strict"):
            raise ValueError("input_gate must be off, mark or strict")
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
# Private-address guard (SSRF)
# ---------------------------------------------------------------------------

# Loopback, RFC 1918, link-local, CGNAT, documentation, multicast and reserved
# ranges.  ``ipaddress`` flags cover most of them; the explicit list keeps the
# same answer on every supported Python version.
_BLOCKED_NETWORKS = tuple(
    ipaddress.ip_network(cidr)
    for cidr in (
        "0.0.0.0/8",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "127.0.0.0/8",
        "169.254.0.0/16",
        "172.16.0.0/12",
        "192.0.0.0/24",
        "192.0.2.0/24",
        "192.168.0.0/16",
        "198.18.0.0/15",
        "198.51.100.0/24",
        "203.0.113.0/24",
        "240.0.0.0/4",
        "255.255.255.255/32",
        "::1/128",
        "64:ff9b::/96",
        "100::/64",
        "2001:db8::/32",
        "fc00::/7",
        "fe80::/10",
        "ff00::/8",
    )
)


class UnsafeAddress(InvalidURLError):
    """The URL points at a loopback, private or link-local address."""


def _blocked_ip(ip: Any) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    if any(ip in network for network in _BLOCKED_NETWORKS if network.version == ip.version):
        return True
    return bool(
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _host_is_local_name(host: str) -> bool:
    host = host.rstrip(".").lower()
    return (
        host == "localhost"
        or host.endswith(".localhost")
        or host.endswith(".local")
        or host.endswith(".internal")
        or host == "metadata.google.internal"
    )


def assert_public_url(url: str, *, allow_private: bool = False) -> None:
    """Refuse URLs that resolve to this machine, the LAN or a metadata service.

    The host as written and every address DNS returns are checked, so decimal
    IPv4 spellings and IPv6-mapped IPv4 are caught as well.  The guard runs
    before each request and on every redirect hop.  A host that does not resolve
    is left to the HTTP client, which fails on its own.

    ``allow_private`` exists for local fixtures and trusted intranet tools; it
    is off by default and the CLI exposes it as ``--allow-private``.
    """

    if allow_private:
        return
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if not host:
        raise UnsafeAddress(f"URL has no host: {url}")
    if _host_is_local_name(host):
        raise UnsafeAddress(f"refusing a local host: {host}")
    try:
        port = parts.port or (443 if parts.scheme.lower() == "https" else 80)
    except ValueError as exc:
        raise UnsafeAddress(f"invalid port in {url}") from exc

    try:
        literal = ipaddress.ip_address(host.strip("[]").split("%", 1)[0])
    except ValueError:
        literal = None
    if literal is not None:
        if _blocked_ip(literal):
            raise UnsafeAddress(f"refusing a private address: {host}")
        return

    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return  # unresolvable: the HTTP client reports the failure
    for info in infos:
        address = str(info[4][0])
        try:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
        except ValueError:
            continue
        if _blocked_ip(ip):
            raise UnsafeAddress(f"refusing {host}: it resolves to {address}")


def _guarded_request(
    getter: Any,
    url: str,
    *,
    allow_private: bool = False,
    max_redirects: int = 5,
    before_request: Any = None,
    **kwargs: Any,
) -> Any:
    """GET ``url`` and follow redirects one hop at a time, checking each target.

    ``requests`` follows redirects internally, which would let a public URL
    bounce the client to ``127.0.0.1`` or a metadata endpoint without the guard
    ever seeing it.  Every hop is therefore resolved and checked here.
    """

    current = url
    for _ in range(max_redirects + 1):
        assert_public_url(current, allow_private=allow_private)
        if before_request is not None:
            before_request(current)
        response = getter(current, allow_redirects=False, **kwargs)
        location = response.headers.get("Location") if response.headers else None
        if response.status_code in (301, 302, 303, 307, 308) and location:
            current = normalize_url(urllib.parse.urljoin(current, location))
            response.close()
            continue
        return response
    raise FetchError(f"too many redirects for {url}")


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
            response = _guarded_request(
                requests.get,
                robots_url,
                allow_private=self.config.allow_private,
                headers=headers,
                timeout=(
                    min(max(self.config.timeout, 1.0), 3.0),
                    min(max(self.config.timeout, 1.0), 6.0),
                ),
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
    robots_overridden: bool = False


def _cache_root(config: FetchConfig) -> Path:
    if config.cache_dir:
        return Path(config.cache_dir).expanduser()
    return Path.home() / ".web-forager" / "cache"


def _private_path(path: Path, mode: int) -> None:
    """Best-effort owner-only permissions for local state on POSIX."""

    if os.name == "nt":
        return
    try:
        path.chmod(mode)
    except OSError:
        pass


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

    def clone(self) -> "HttpFetcher":
        """A per-thread fetcher sharing robots and rate limits but not a session.

        ``requests.Session`` is not thread-safe, so parallel focus reads use one
        clone per worker.  The robots cache and rate limiter are shared, which
        keeps politeness global; cookies already collected are copied once.
        """

        other = HttpFetcher(self.config)
        other.robots = self.robots
        other.limiter = self.limiter
        try:
            other.session.cookies.update(self.session.cookies)
        except Exception:
            pass
        return other

    # -- robots ---------------------------------------------------------

    def assert_allowed(
        self, url: str, robots_policy: Optional[str] = None
    ) -> RobotsPolicy:
        """Raise RobotsDenied when the effective policy is ``respect``.

        ``warn`` returns the denying policy instead of raising, so the caller
        can still read the page and must record ``robots_overridden: true``.
        ``robots_policy`` lets a query interface use its own policy without
        changing the policy for target pages.
        """

        effective = (robots_policy or self.config.robots_policy).strip().lower()
        if not self.config.respect_robots or effective == "ignore":
            return RobotsPolicy.allowing_all(note="robots checking disabled by policy")
        policy = self.robots.policy_for(url)
        if not policy.allowed(url):
            if effective == "warn":
                return policy
            detail = policy.note or policy.source or "robots.txt"
            raise RobotsDenied(f"robots.txt disallows {url} ({detail})")
        return policy

    # -- main entry -----------------------------------------------------

    def fetch(
        self,
        url: str,
        *,
        check_robots: bool = True,
        use_cache: bool = True,
        robots_policy: Optional[str] = None,
    ) -> HttpResponse:
        """Fetch one URL.

        ``use_cache=False`` skips both lookup and write. A bootstrap request
        whose only job is to set cookies must not be answered from the cache:
        a cached anti-bot page would silently supply no cookie at all.
        """

        url = normalize_url(url)
        assert_public_url(url, allow_private=self.config.allow_private)
        policy: Optional[RobotsPolicy] = None
        overridden = {"value": False}
        if check_robots:
            policy = self.assert_allowed(url, robots_policy)
            if policy is not None and not policy.allowed(url):
                overridden["value"] = True

        def robots_guard(target: str) -> None:
            checked = self.assert_allowed(target, robots_policy)
            if checked is not None and not checked.allowed(target):
                overridden["value"] = True

        cached = self._read_cache(url) if use_cache else None
        if cached is not None:
            return cached

        extra = policy.crawl_delay if policy and policy.crawl_delay else 0.0
        self.limiter.wait(url, extra)

        last_error: Optional[Exception] = None
        for attempt in range(self.config.retries + 1):
            try:
                response = _guarded_request(
                    self.session.get,
                    url,
                    allow_private=self.config.allow_private,
                    max_redirects=self.session.max_redirects,
                    before_request=robots_guard if check_robots else None,
                    # A connect timeout per resolved address: a blocked
                    # address must not consume the full read budget.
                    timeout=(min(self.config.timeout, 3.0), self.config.timeout),
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
            result.robots_overridden = overridden["value"]
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
        log(f"cache hit: {redact_url_for_log(url)}", self.config)
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
            robots_overridden=bool(meta.get("robots_overridden", False)),
        )

    def _write_cache(self, url: str, response: HttpResponse) -> None:
        if not self.config.cache or response.status != 200:
            return
        lowered = {str(key).lower() for key in response.headers}
        if lowered & {"set-cookie", "set-cookie2"}:
            # A response that plants a session cookie is not a neutral copy of a
            # public page; keep it (and the credential) out of the on-disk cache.
            log("cache skipped: response sets cookies", self.config)
            return
        safe_headers = {
            key: value
            for key, value in response.headers.items()
            if str(key).lower() not in ("authorization", "proxy-authorization")
        }
        meta_path, body_path = self._cache_paths(url)
        try:
            meta_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            _private_path(meta_path.parent, 0o700)
            body_path.write_bytes(response.content)
            _private_path(body_path, 0o600)
            meta_path.write_text(
                json.dumps(
                    {
                        "url": url,
                        "final_url": response.final_url,
                        "status": response.status,
                        "headers": safe_headers,
                        "content_type": response.content_type,
                        "encoding": response.encoding,
                        "robots_overridden": bool(response.robots_overridden),
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            _private_path(meta_path, 0o600)
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
            def resolve_robots_guard(target: str) -> None:
                if self.config.query_robots != "ignore":
                    self.assert_allowed(target, self.config.query_robots)

            response = _guarded_request(
                self.session.get,
                url,
                allow_private=self.config.allow_private,
                max_redirects=self.session.max_redirects,
                before_request=(
                    resolve_robots_guard
                    if self.config.query_robots != "ignore"
                    else None
                ),
                timeout=self.config.timeout,
                stream=True,
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
        except (requests.RequestException, InvalidURLError):
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


_CJK_CHAR_RE = re.compile(r"[㐀-䶿一-鿿]")

_CHARACTER_PAGE_MARKERS = (
    "百科",
    "字典",
    "词典",
    "拼音",
    "笔顺",
    "笔画",
    "部首",
    "读音",
    "组词",
    "汉字",
    "汉语",
    "释义",
    "字义",
    "意思",
    "解释",
)


def looks_like_character_page(title: str, query: str) -> bool:
    """True for a dictionary entry that shares only one character with the query.

    Engines that split a Chinese phrase into characters rank the dictionary
    page of its first character — ``反（汉语汉字）_百度百科`` for a query about
    反逆向工程. That page shares a single character with the query and is never
    the one the caller asked for, so it is dropped instead of padding the list.
    """

    query_chars = set(_CJK_CHAR_RE.findall(query or ""))
    if len(query_chars) < 2:
        return False
    title_text = title or ""
    title_chars = set(_CJK_CHAR_RE.findall(title_text))
    if len(title_chars & query_chars) != 1:
        return False
    return any(marker in title_text for marker in _CHARACTER_PAGE_MARKERS)


_DICTIONARY_MARKERS = (
    "词典",
    "翻译",
    "音标",
    "是什么意思",
    "英语单词",
    "汉语词典",
    "dictionary",
    "translation",
)


def looks_like_dictionary_page(result: dict[str, str], query: str) -> bool:
    """True for a word page that matches only one token of a longer query.

    Bing occasionally answers a Latin phrase with the dictionary entry of its
    first word (``reinforcement`` for ``reinforcement learning survey``). The
    page is not wrong, but it is not an answer to the query; dropping it lets
    the next result through instead of filling the list with word pages.
    """

    tokens = _query_tokens(query)
    if len(tokens) < 2:
        return False
    title = (result.get("title") or "").lower()
    if not any(marker in title for marker in _DICTIONARY_MARKERS):
        return False
    return result_coverage(result, tokens) <= 1 / len(tokens)


_DOXXING_PHRASES = (
    "人肉搜索",
    "人肉",
    "开盒",
    "社工库",
    "查户籍",
    "户籍信息",
    "开房记录",
    "查开房",
    "家庭住址",
    "具体住址",
    "亲属关系",
    "查身份证",
    "查手机号",
    "查住址",
    "查家人",
    "查个人资料",
    "定位某人",
)
_DOXXING_LATIN = ("doxxing", "doxx", "doxed", "doxing", "dox ")
_SENSITIVE_ATTRIBUTES = (
    "手机号",
    "手机号码",
    "电话号码",
    "住址",
    "身份证",
    "照片",
    "微信号",
    "学号",
    "工号",
    "行踪",
    "轨迹",
)
_PERSON_REFERENCES = (
    "这个人",
    "此人",
    "该人",
    "某人",
    "对方",
    "本人",
    "他的",
    "她的",
    "家人",
    "家属",
)
_LATIN_PERSON_RE = re.compile(r"\b[A-Z][a-z]+(?: [A-Z][a-z]+){1,2}\b")
_LATIN_SENSITIVE = ("phone number", "home address", "email address", "social security", "id number")
_PERSON_NAME_RE = re.compile(r"^[一-鿿]{2,3}$")
_LATIN_NAME_RE = re.compile(r"^[A-Z][a-z]+(?: [A-Z][a-z]+){1,2}$")


def doxxing_reason(query: str) -> str:
    """Return a reason when a query asks to identify a private person, else "".

    The check refuses *intent*, not names: an explicit doxxing phrase, a
    sensitive attribute asked about a specific person, or a Latin personal name
    combined with a contact field. A plain name on its own is not refused,
    because it cannot be told apart from a paper author or a public figure; it
    draws a warning instead.
    """

    text = (query or "").lower()
    for phrase in _DOXXING_PHRASES:
        if phrase in text:
            return (
                "the query asks for information about a person in a way that "
                "amounts to doxxing or profiling"
            )
    for word in _DOXXING_LATIN:
        if word in text:
            return "the query names doxxing as its purpose"
    if any(word in text for word in _LATIN_SENSITIVE) and _LATIN_PERSON_RE.search(query or ""):
        return "the query asks for contact details about a named individual"
    if any(word in text for word in _SENSITIVE_ATTRIBUTES):
        if any(ref in text for ref in _PERSON_REFERENCES):
            return "the query asks for a sensitive attribute of a specific person"
        # A short Chinese token beside an attribute word is a name: 王五 身份证.
        for token in re.split(r"[\s,，;；|/]+", query or ""):
            if not _PERSON_NAME_RE.match(token):
                continue
            if any(token in word or word in token for word in _SENSITIVE_ATTRIBUTES):
                continue
            return "the query pairs a person's name with a sensitive attribute"
    return ""


def looks_like_person_name(query: str) -> bool:
    """True for a bare personal name, which draws a warning but is not refused."""

    text = (query or "").strip()
    if not text:
        return False
    return bool(_PERSON_NAME_RE.match(text) or _LATIN_NAME_RE.match(text))


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
    quality: Optional[dict[str, Any]] = None,
) -> list[dict[str, str]]:
    """Return ``[{title, url, snippet, source}]`` for a keyword query.

    ``engine`` is one of ``auto`` (360 + Bing, and 360 + Sogou + the WeChat
    index for a mostly-CJK query), ``all`` (every engine), ``360``, ``bing``,
    ``sogou``, ``weixin`` or ``duckduckgo``. ``auto`` asks one more engine when
    the answer holds fewer than three distinct results.

    Pass ``report`` to collect one entry per engine tried — name, whether it
    answered, how many results and how long it took — so a caller in a hostile
    network can see which backend is actually reachable.  Pass ``quality`` to
    receive counts for the rows removed by the relevance filter.

    Search endpoints are query interfaces, not target pages.  Their robots
    policy is ``config.query_robots`` (default ``warn``): a disallowed query
    endpoint is read and the override is recorded; ``respect`` refuses it and
    ``ignore`` skips the check.  Result pages we later fetch still go through
    the normal target-page robots policy.  Queries are rate-limited per host.
    """

    query = (query or "").strip()
    if not query:
        raise ValueError("query must not be empty")
    reason = doxxing_reason(query)
    if reason:
        raise ProhibitedQuery(
            f"refused: {reason}. web-forager does not collect or assemble "
            "profiles of identifiable people; search for a topic, a paper "
            "title or an organisation instead."
        )
    limit = limit or config.num_results or 8
    engine = (engine or "auto").lower()
    if engine not in SEARCH_ENGINES:
        raise ValueError(f"unsupported search engine: {engine}")

    fallback_engines: list[str] = []
    if engine == "auto":
        # Bing tokenises Chinese phrases into single characters: a query about
        # 反逆向工程 comes back as the dictionary page of 反. For a CJK query,
        # ask 360, Sogou and 搜狗微信 and stop there — the article index is the
        # one channel that still carries a Chinese person's or institution's
        # name. Bing stays available through --engine bing.
        if prefers_chinese_engines(query):
            engines = ["360", "sogou", "weixin"]
            fallback_engines = []
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
    parallel = own_fetcher and config.parallel_engines
    groups: list[tuple[str, list[dict[str, str]]]] = []
    errors: list[str] = []

    def run_engine(
        name: str, fallback: bool, qtext: str = query
    ) -> tuple[dict[str, Any], Optional[list[dict[str, str]]]]:
        started = time.monotonic()
        entry: dict[str, Any] = {"engine": name}
        if config.query_robots != "respect":
            entry["query_robots"] = config.query_robots
        if fallback:
            entry["fallback"] = True
        if qtext != query:
            entry["query_variant"] = qtext
        # A requests.Session is not safe to share across engine threads. Each
        # engine gets its own fetcher; the disk cache and per-host limiters are
        # still shared through the filesystem and the host split.
        local = HttpFetcher(config) if parallel else fetcher
        try:
            items = _search_one(
                name, qtext, config, limit, local, pages=config.search_pages
            )
            # An engine that split a Chinese phrase into characters returns
            # the dictionary page of the first one; drop it before it can
            # pad the list or inflate the per-engine count.
            items = [
                item
                for item in items
                if not looks_like_character_page(item.get("title", ""), query)
                and not looks_like_dictionary_page(item, query)
            ]
            entry.update(
                ok=True,
                status="ok" if items else "empty",
                results=len(items),
                ms=round((time.monotonic() - started) * 1000),
            )
            return entry, items
        except Exception as exc:  # one engine failing must not kill the query
            errors.append(f"{name}: {exc}")
            entry.update(
                ok=False,
                status=_engine_failure_status(exc),
                results=0,
                error=str(exc),
                ms=round((time.monotonic() - started) * 1000),
            )
            return entry, None
        finally:
            if parallel:
                local.close()

    def collect(names: list[str], fallback: bool = False, qtext: str = query) -> None:
        if parallel and len(names) > 1:
            with ThreadPoolExecutor(max_workers=len(names)) as pool:
                outcomes = list(pool.map(lambda n: run_engine(n, fallback, qtext), names))
        else:
            outcomes = [run_engine(name, fallback, qtext) for name in names]
        for entry, items in outcomes:
            if items is not None:
                groups.append((entry["engine"], items))
            if report is not None:
                report.append(entry)

    try:
        collect(engines)
        if fallback_engines and (not groups or _thin_results(groups, limit)):
            collect(fallback_engines, fallback=True)
        # A thin first pass is often a formatting mismatch rather than a
        # missing topic. One simplified variant costs two or three more
        # requests and is skipped entirely when the first pass was healthy, or
        # when the caller pinned a single engine on purpose.
        if groups and engine in ("auto", "all") and _thin_results(groups, limit):
            for variant in query_variants(query)[1:]:
                collect(engines, fallback=True, qtext=variant)
    finally:
        if own_fetcher:
            fetcher.close()

    if not groups:
        raise FetchError("all search engines failed: " + "; ".join(errors) or "no engine available")

    # Rank even when only one engine answered.  The old single-group path
    # returned engine order untouched, which is how an Excel INDIRECT tutorial
    # could sit third for an "indirect prompt injection" query.
    merged = merge_search_results(groups, query, limit=limit)
    final = diversify_results(
        dedupe_results(merged, limit=max(limit * 3, limit)), limit=limit
    )
    annotate_results(final, query)
    before_filter = len(final)
    # When enough real answers exist, do not pad the list with results that
    # matched one word or the wrong language.  With only one or two relevant
    # hits the unrelated rows stay at the bottom and a warning names them.
    relevant = [item for item in final if item.get("relevance")]
    if len(relevant) >= min(3, limit):
        final = relevant
    if quality is not None:
        quality["returned_before_filter"] = before_filter
        quality["dropped_off_topic"] = max(0, before_filter - len(final))
    return final


def _engine_failure_status(exc: BaseException) -> str:
    """Classify one engine failure for the machine-readable report.

    A caller in a hostile network needs to tell an empty result from a block,
    a timeout and a parser change.  The old ``ok: false`` plus free text hid
    that distinction, which made a blocked engine look like a thin topic.
    """

    text = f"{type(exc).__name__}: {exc}".lower()
    if any(word in text for word in ("timeout", "timed out", "time out")):
        return "timeout"
    if "robots" in text:
        return "robots_denied"
    if any(
        word in text
        for word in ("verification", "antispider", "captcha", "blocked", "forbidden")
    ):
        return "blocked"
    if any(word in text for word in ("parse", "decode", "json", "xml", "unexpected")):
        return "parse_error"
    return "error"


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


def is_360_blocked(html: str) -> bool:
    """True when so.com answered with a verification page instead of results.

    The page is small and has no result list; a real result page always carries
    ``res-list``. Only used to report the engine honestly, never to retry past
    the check.
    """

    lowered = (html or "").lower()
    if not lowered or "res-list" in lowered or len(html) > 60000:
        return False
    if any(marker in html for marker in ("安全验证", "人机验证", "请输入验证码", "访问异常", "滑动验证")):
        return True
    return "验证" in html and len(html) < 12000


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
    # Search endpoints are query interfaces, not target pages. They still get
    # a policy: respect (default) refuses a disallowed endpoint, warn reads it
    # and marks the override, ignore skips the check. MCP force-sets respect.
    query_fetch = {
        "check_robots": config.query_robots != "ignore",
        "robots_policy": config.query_robots,
    }
    collected: list[dict[str, str]] = []

    for page in range(1, pages + 1):
        if name == "duckduckgo" and page > 1:
            break
        if name == "360":
            response = fetcher.fetch(
                _SO_360.format(query=quoted, page=page), **query_fetch
            )
            if is_360_blocked(response.text):
                raise FetchError("360 returned a verification page; wait and retry later")
            found = parse_360_html(response.text, limit=limit)
        elif name == "sogou":
            response = fetcher.fetch(
                _SOGOU.format(query=quoted, page=page), **query_fetch
            )
            if is_sogou_blocked(response.text):
                raise FetchError("Sogou returned a verification page (antispider)")
            parsed = parse_sogou_html(
                response.text, base="https://www.sogou.com/", limit=limit
            )
            found = resolve_sogou_results(parsed, fetcher, limit=limit)
        elif name == "weixin":
            response = fetcher.fetch(
                _WEIXIN.format(query=quoted, page=page), **query_fetch
            )
            if is_sogou_blocked(response.text):
                raise FetchError("weixin.sogou.com returned a verification page (antispider)")
            parsed = parse_weixin_html(
                response.text, base="https://weixin.sogou.com/", limit=limit
            )
            found = resolve_sogou_results(parsed, fetcher, limit=limit)
        elif name == "duckduckgo":
            response = fetcher.fetch(_DDG_HTML.format(query=quoted), **query_fetch)
            found = parse_ddg_html(response.text, limit=limit)
        else:
            first = 1 + (page - 1) * 10
            # Bing: RSS is cheaper and gives direct URLs; HTML is the fallback.
            try:
                response = fetcher.fetch(
                    _BING_RSS.format(query=quoted, count=limit, first=first),
                    **query_fetch,
                )
                found = parse_bing_rss(response.text, limit=limit)
            except FetchError:
                found = []
            if not found:
                response = fetcher.fetch(
                    _BING_HTML.format(query=quoted, count=limit, first=first),
                    **query_fetch,
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


def _content_tokens(query: str) -> list[str]:
    """Query terms that carry meaning; stopwords and one-letter words are noise.

    Chinese is not whitespace-separated.  A long CJK run is expanded into
    character bigrams for matching; a mixed token carrying digits (``2026年11月``)
    stays whole because the date is itself the searchable unit.  This is not a
    word segmenter, but it stops a whole sentence from becoming one token that
    no result can ever match.
    """

    tokens = _query_tokens(query)
    content: list[str] = []
    for token in tokens:
        if token in _QUERY_STOPWORDS or len(token) < 2:
            continue
        if re.search(r"\d", token):
            content.append(token)
            continue
        if not _CJK_RE.search(token):
            content.append(token)
            continue
        for run in re.findall(
            r"[㐀-䶿一-鿿豈-﫿぀-ヿ가-힯]+"
            r"|[A-Za-z0-9]+",
            token,
        ):
            if _CJK_RE.search(run):
                if len(run) <= 3:
                    content.append(run)
                else:
                    content.extend(run[index : index + 2] for index in range(len(run) - 1))
            elif len(run) >= 2:
                content.append(run.lower())
    return list(dict.fromkeys(content)) or tokens


_LATIN_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9+#.-]*")


def _stem_token(token: str) -> str:
    """A deliberately small English stemmer for matching, not display.

    ``injections`` and ``injection`` should meet; a full Porter stemmer would
    also merge unrelated words and make the relevance check harder to explain.
    Tokens containing CJK or punctuation are returned unchanged.
    """

    value = token.lower()
    if not re.fullmatch(r"[a-z][a-z0-9+-]*", value) or len(value) <= 4:
        return value
    if value.endswith("ies"):
        return value[:-3] + "y"
    if value.endswith("ing") and len(value) > 5:
        return value[:-3]
    if value.endswith("ed") and len(value) > 4:
        return value[:-2]
    if value.endswith("sses"):
        return value[:-2]
    if value.endswith(("ches", "shes", "xes", "zes", "oes")):
        return value[:-2]
    if value.endswith("s") and not value.endswith("ss"):
        return value[:-1]
    return value


def _stems(text: str) -> set[str]:
    return {_stem_token(word) for word in _LATIN_WORD_RE.findall(text.lower())}


def _token_in_text(token: str, text: str, stems: set[str]) -> bool:
    token = (token or "").lower()
    if token and token in text:
        return True
    return bool(re.fullmatch(r"[a-z][a-z0-9+-]*", token)) and _stem_token(token) in stems


def _script_stats(text: str) -> tuple[int, int]:
    """Return ``(CJK characters, Latin words)`` for a language sanity check."""

    value = str(text or "")
    return (
        len(_CJK_RE.findall(value)),
        len(re.findall(r"[A-Za-z]{2,}", value)),
    )


_INTENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "news": re.compile(
        r"新闻|资讯|最新|今日|今天|本周|本月|今年|刚刚|发布会|财报|营收|股价|"
        r"202[4-9]年|\bnews\b|\bupdate\b",
        re.I,
    ),
    "comparison": re.compile(
        r"对比|比较|区别|差异|怎么选|如何选|哪个好|哪个更|优缺点|取舍|"
        r"\bvs\.?\b|\bversus\b|\bcomparison\b|\bcompare\b|\bbetter\b|\bchoose\b",
        re.I,
    ),
    "technical": re.compile(
        r"python|javascript|typescript|java|golang|rust|asyncio|api|sdk|cli|"
        r"http|json|sql|docker|kubernetes|git|linux|regex|报错|异常|安装|配置|"
        r"函数|接口|依赖|编译|代码|文档|版本|任务组|协程",
        re.I,
    ),
    "policy": re.compile(
        r"法规|法律|政策|合规|监管|标准|条例|法案|司法|欧盟|ai act|gdpr|"
        r"regulation|compliance|\blaw\b|\bact\b",
        re.I,
    ),
    "howto": re.compile(
        r"怎么办|咋办|怎么解决|如何解决|修复|连不上|打不开|用不了|设置|教程|"
        r"步骤|方法|技巧|how to|fix|troubleshoot|setup|repair",
        re.I,
    ),
    "research": re.compile(
        r"arxiv|论文|文献|综述|survey|paper|study|research|academic|acl|ieee|acm",
        re.I,
    ),
    "factual": re.compile(
        r"是谁|多少|哪年|何时|什么时候|定义|作者|创始人|营收|人口|面积|"
        r"what is|who is|when|how many|definition",
        re.I,
    ),
}
_INTENT_ORDER = (
    "news",
    "policy",
    "comparison",
    "technical",
    "howto",
    "research",
    "factual",
    "general",
)
_INTENT_STRONG_SIGNALS = {
    "comparison": ("怎么选", "如何选", "哪个好", "对比", "vs"),
    "howto": ("怎么办", "咋办", "连不上", "打不开", "怎么解决"),
    "factual": ("是谁", "的作者", "多少", "定义"),
    "policy": ("法规", "合规", "监管", "ai act"),
    "news": ("新闻", "最新", "今天", "本月"),
    "technical": ("报错", "异常", "api", "sdk", "asyncio"),
}


def classify_intent(query: str) -> dict[str, Any]:
    """Classify what kind of source will actually answer ``query``.

    Free and deterministic: a small keyword vote, with a few strong phrases
    counted twice.  It is deliberately conservative — ``general`` is a valid
    answer, and authority weighting keeps working without it.
    """

    text = (query or "").lower()
    scores: dict[str, int] = {}
    signals: dict[str, list[str]] = {}
    for name, pattern in _INTENT_PATTERNS.items():
        matches = pattern.findall(text)
        if matches:
            scores[name] = len(matches)
            signals[name] = list(dict.fromkeys(item.lower() for item in matches))[:5]
    for name, phrases in _INTENT_STRONG_SIGNALS.items():
        for phrase in phrases:
            if phrase in text:
                scores[name] = scores.get(name, 0) + 1
                signals.setdefault(name, []).append(phrase)
    if not scores:
        return {"intent": "general", "confidence": 0.3, "signals": []}
    best = max(
        scores,
        key=lambda name: (scores[name], -_INTENT_ORDER.index(name)),
    )
    confidence = min(0.95, round(0.45 + 0.1 * scores[best], 2))
    return {
        "intent": best,
        "confidence": confidence,
        "signals": list(dict.fromkeys(signals.get(best, [])))[:5],
    }


_AUTHORITY_TIERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "primary",
        (
            "docs.python.org",
            "developer.mozilla.org",
            "go.dev",
            "rust-lang.org",
            "nodejs.org",
            "developer.apple.com",
            "learn.microsoft.com",
            "support.microsoft.com",
            "kubernetes.io",
            "docs.docker.com",
            "postgresql.org",
            "nginx.org",
            "apache.org",
            "w3.org",
            "ietf.org",
            "unicode.org",
            "docs.github.com",
        ),
    ),
    (
        "official",
        (
            "gov.cn",
            "gov",
            "europa.eu",
            "sec.gov",
            "nist.gov",
            "who.int",
            "worldbank.org",
            "un.org",
            "nvidia.com",
            "openai.com",
            "anthropic.com",
        ),
    ),
    (
        "academic",
        (
            "arxiv.org",
            "aclanthology.org",
            "openreview.net",
            "semanticscholar.org",
            "pubmed.ncbi.nlm.nih.gov",
            "nature.com",
            "science.org",
            "springer.com",
            "sciencedirect.com",
            "ieee.org",
            "acm.org",
            "plos.org",
            "biorxiv.org",
        ),
    ),
    (
        "media",
        (
            "reuters.com",
            "bloomberg.com",
            "ft.com",
            "wsj.com",
            "nytimes.com",
            "bbc.com",
            "bbc.co.uk",
            "caixin.com",
            "yicai.com",
            "cls.cn",
            "nbd.com.cn",
            "stcn.com",
            "thepaper.cn",
            "jiemian.com",
            "chinanews.com.cn",
            "finance.sina.com.cn",
        ),
    ),
    (
        "reference",
        (
            "wikipedia.org",
            "britannica.com",
            "imdb.com",
            "themoviedb.org",
        ),
    ),
    (
        "community",
        (
            "stackoverflow.com",
            "stackexchange.com",
            "github.com",
            "reddit.com",
            "news.ycombinator.com",
            "zhihu.com",
            "cnblogs.com",
            "medium.com",
            "dev.to",
            "quora.com",
        ),
    ),
    (
        "low",
        (
            "csdn.net",
            "php.cn",
            "doc88.com",
            "docin.com",
            "wenku.baidu.com",
            "360doc.com",
            "book118.com",
            "jianshu.com",
            "toutiao.com",
        ),
    ),
)
_AUTHORITY_BASE = {
    "primary": 0.18,
    "official": 0.18,
    "academic": 0.16,
    "media": 0.10,
    "reference": 0.06,
    "community": 0.05,
    "low": -0.16,
    "unknown": 0.0,
}
_AUTHORITY_MULTIPLIER = {
    "technical": {
        "primary": 1.3,
        "official": 0.8,
        "academic": 0.9,
        "media": 0.4,
        "reference": 0.6,
        "community": 0.9,
        "low": 1.2,
        "unknown": 1.0,
    },
    "news": {
        "primary": 0.4,
        "official": 0.9,
        "academic": 0.4,
        "media": 1.4,
        "reference": 0.4,
        "community": 0.3,
        "low": 1.0,
        "unknown": 1.0,
    },
    "comparison": {
        "primary": 0.8,
        "official": 0.6,
        "academic": 0.8,
        "media": 0.5,
        "reference": 0.6,
        "community": 1.0,
        "low": 1.2,
        "unknown": 1.0,
    },
    "policy": {
        "primary": 0.6,
        "official": 1.3,
        "academic": 1.0,
        "media": 0.8,
        "reference": 0.7,
        "community": 0.4,
        "low": 1.2,
        "unknown": 1.0,
    },
    "howto": {
        "primary": 1.3,
        "official": 1.0,
        "academic": 0.5,
        "media": 0.4,
        "reference": 0.6,
        "community": 1.0,
        "low": 0.8,
        "unknown": 1.0,
    },
    "factual": {
        "primary": 1.0,
        "official": 1.2,
        "academic": 1.1,
        "media": 0.9,
        "reference": 1.1,
        "community": 0.6,
        "low": 1.0,
        "unknown": 1.0,
    },
    "research": {
        "primary": 0.9,
        "official": 0.7,
        "academic": 1.4,
        "media": 0.4,
        "reference": 0.6,
        "community": 0.6,
        "low": 1.2,
        "unknown": 1.0,
    },
    "general": {tier: 1.0 for tier in _AUTHORITY_BASE},
}


def authority_for(host: str, intent: str = "general") -> dict[str, Any]:
    """Return an explicit source-authority tier and a small ranking bonus."""

    host = (host or "").lower().lstrip(".")
    tier = "unknown"
    for name, suffixes in _AUTHORITY_TIERS:
        if any(host == suffix or host.endswith("." + suffix) for suffix in suffixes):
            tier = name
            break
    multiplier = _AUTHORITY_MULTIPLIER.get(
        intent, _AUTHORITY_MULTIPLIER["general"]
    ).get(tier, 1.0)
    score = _AUTHORITY_BASE[tier] * multiplier
    return {
        "tier": tier,
        "score": round(score, 3),
        "intent": intent,
    }


def result_match(
    result: dict[str, str], query: str, tokens: Optional[list[str]] = None
) -> dict[str, Any]:
    """Grade how well one search result answers ``query``.

    A title is not a match just because the URL contains one query word.  The
    result must either contain the full phrase or at least two meaningful query
    terms with half the query covered.  A Chinese page that merely repeats one
    English product name does not pass an English four-word query; it is marked
    with ``language_match: false`` and ranked below real answers.
    """

    tokens = tokens if tokens is not None else _content_tokens(query)
    haystack = " ".join(
        (result.get("title", ""), result.get("snippet", ""))
    ).lower()
    title = (result.get("title") or "").lower()
    stems = _stems(haystack)
    title_stems = _stems(title)
    matched = [token for token in tokens if _token_in_text(token, haystack, stems)]
    coverage = len(matched) / len(tokens) if tokens else 0.0
    title_hits = (
        sum(1 for token in tokens if _token_in_text(token, title, title_stems)) / len(tokens)
        if tokens
        else 0.0
    )
    phrase = " ".join((query or "").lower().split())
    exact = bool(phrase and phrase in haystack)
    title_exact = bool(phrase and title.strip() == phrase)
    cjk_query = any(_CJK_RE.search(token) for token in tokens)
    # A CJK query has no word boundaries, so its tokens are character bigrams
    # and full coverage is the wrong bar: an eight-character question has seven
    # bigrams, and a correct title often carries only a few of them.  Requiring
    # several *overlapping* pieces is the useful signal there; Latin queries
    # keep the stricter coverage rule.
    required = 1 if len(tokens) <= 1 else (3 if cjk_query and len(tokens) >= 8 else 2)
    if cjk_query:
        relevant = exact or len(matched) >= required
    else:
        relevant = exact or (len(matched) >= required and coverage >= 0.5)

    query_cjk, query_latin = _script_stats(query)
    result_cjk, result_latin = _script_stats(haystack)
    language_match = True
    # Latin query, overwhelmingly Chinese result that does not carry the query
    # terms.  This is the Excel INDIRECT failure mode: one English product name
    # in a Chinese tutorial is not an answer to an English concept query.
    if query_latin >= 2 and query_cjk == 0:
        if (
            result_cjk >= 8
            and result_latin < max(2, len(tokens))
            and coverage < 0.5
        ):
            language_match = False
    # A Chinese query answered by an unrelated English page.
    elif query_cjk >= 2 and query_latin == 0:
        if result_latin >= 8 and result_cjk < 4 and coverage < 0.5:
            language_match = False

    return {
        "coverage": round(coverage, 3),
        "title_coverage": round(title_hits, 3),
        "matched_terms": matched,
        "exact": exact,
        "title_exact": title_exact,
        "relevant": relevant,
        "language_match": language_match,
    }


def annotate_results(results: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    """Attach relevance and authority fields in place and return the same list."""

    tokens = _content_tokens(query)
    intent = classify_intent(query)
    for item in results:
        details = result_match(item, query, tokens)
        host = urllib.parse.urlsplit(item.get("url", "")).netloc
        authority = authority_for(host, intent["intent"])
        item.update(
            coverage=details["coverage"],
            matched_terms=details["matched_terms"],
            relevance=details["relevant"],
            language_match=details["language_match"],
            authority_tier=authority["tier"],
            authority_score=authority["score"],
            intent=intent["intent"],
        )
    return results


def _freshness_bonus(text: str) -> float:
    """Prefer results whose snippet carries a recent year."""

    years = [int(match) for match in re.findall(r"\b(20\d{2})\b", text or "")]
    if not years:
        return 0.0
    newest = max(years)
    current = datetime.now(timezone.utc).year
    if newest >= current:
        return 0.06
    if newest == current - 1:
        return 0.03
    return 0.0


def query_variants(query: str) -> list[str]:
    """Return the original query and at most one simplified variant.

    Only used when the first pass came back thin. It strips quotes and common
    English stopwords, and joins a spaced CJK query, because result pages treat
    those two forms differently.
    """

    base = (query or "").strip()
    if not base:
        return []
    variants = [base]
    simplified = re.sub(r"[\"'“”‘’]", " ", base)
    simplified = re.sub(r"[\s,，;；|、]+", " ", simplified).strip()
    tokens = [
        token
        for token in simplified.split()
        if token.lower() not in _QUERY_STOPWORDS
    ]
    candidate = " ".join(tokens).strip()
    if candidate and candidate.lower() != base.lower():
        variants.append(candidate)
    if re.search(r"[㐀-鿿]", base) and " " in base:
        joined = re.sub(r"\s+", "", base)
        if joined and joined not in variants:
            variants.append(joined)
    return variants[:2]


_QUERY_STOPWORDS = {
    "a",
    "an",
    "the",
    "of",
    "for",
    "to",
    "in",
    "on",
    "and",
    "or",
    "with",
    "about",
    "please",
    "如何",
    "怎么",
    "什么",
    "怎样",
}


def diversify_results(
    results: list[dict[str, str]], limit: int, per_host: int = 2
) -> list[dict[str, str]]:
    """Keep at most ``per_host`` results per host, then fill from the overflow.

    A single host that dominates the list (WeChat, one content farm) no longer
    crowds out every other source; if too few hosts answered, the overflow is
    appended so the caller still receives ``limit`` results.
    """

    chosen: list[dict[str, str]] = []
    overflow: list[dict[str, str]] = []
    counts: dict[str, int] = {}
    for item in results:
        host = (urllib.parse.urlsplit(item.get("url", "")).netloc or "").lower()
        if counts.get(host, 0) < per_host:
            counts[host] = counts.get(host, 0) + 1
            chosen.append(item)
        else:
            overflow.append(item)
    return (chosen + overflow)[:limit]


_SEARCH_ENGINE_HOSTS = {
    "sogou.com",
    "www.sogou.com",
    "m.sogou.com",
    "weixin.sogou.com",
    "m.weixin.sogou.com",
    "so.com",
    "www.so.com",
    "m.so.com",
    "bing.com",
    "www.bing.com",
    "cn.bing.com",
    "baidu.com",
    "www.baidu.com",
    "m.baidu.com",
    "google.com",
    "www.google.com",
    "duckduckgo.com",
    "html.duckduckgo.com",
    "yandex.com",
    "yandex.ru",
}


def _is_search_engine_page(url: str) -> bool:
    """True for a search engine's own result page, which is not an answer.

    One backend occasionally echoes a Sogou/360 results URL into its own list.
    Ranking it first would cite the search box instead of the source, so these
    intermediate pages are dropped before scoring.  Article hosts that merely
    live under a portal (``baijiahao.baidu.com``) are not in this set.
    """

    try:
        parts = urllib.parse.urlsplit(str(url or "").strip())
    except ValueError:
        return False
    host = (parts.hostname or "").lower().rstrip(".")
    if host not in _SEARCH_ENGINE_HOSTS:
        return False
    path = (parts.path or "").lower()
    query = (parts.query or "").lower()
    if any(
        marker in query
        for marker in ("query=", "q=", "wd=", "keyword=", "word=")
    ):
        return True
    return path.startswith(("/sogou", "/search", "/web", "/s", "/antispider"))


def merge_search_results(
    groups: list[tuple[str, list[dict[str, Any]]]],
    query: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Merge several engines by coverage, title match, authority and freshness.

    Engine order only breaks exact ties, so two engines that return the same
    page still produce one stable ordering.
    """

    tokens = _content_tokens(query)
    intent = classify_intent(query)
    rrf_by_url: dict[str, float] = {}
    for _, items in groups:
        for rank, item in enumerate(items):
            key = _canonical_url(item.get("url", ""))
            if key:
                rrf_by_url[key] = rrf_by_url.get(key, 0.0) + 1.0 / (60 + rank + 1)

    scored: list[tuple[float, int, int, dict[str, Any]]] = []
    for group_index, (name, items) in enumerate(groups):
        for rank, item in enumerate(items):
            if _is_search_engine_page(item.get("url", "")):
                continue
            candidate: dict[str, Any] = dict(item)
            candidate.setdefault("source", name)
            details = result_match(candidate, query, tokens)
            key = _canonical_url(candidate.get("url", ""))
            rrf = rrf_by_url.get(key, 0.0)
            host = urllib.parse.urlsplit(candidate.get("url", "")).netloc
            authority = authority_for(host, intent["intent"])
            freshness = _freshness_bonus(
                f"{candidate.get('title', '')} {candidate.get('snippet', '')}"
            )
            components = {
                "coverage": round(details["coverage"], 3),
                "title": round(details["title_coverage"], 3),
                "exact": bool(details["exact"]),
                "title_exact": bool(details["title_exact"]),
                "relevant": bool(details["relevant"]),
                "rrf": round(rrf, 4),
                "authority": round(float(authority["score"]), 3),
                "freshness": round(freshness, 3),
                "language_penalty": 0.0 if details["language_match"] else -0.35,
            }
            candidate.update(
                coverage=details["coverage"],
                matched_terms=details["matched_terms"],
                relevance=details["relevant"],
                language_match=details["language_match"],
                rrf=round(rrf, 4),
                authority_tier=authority["tier"],
                authority_score=authority["score"],
                intent=intent["intent"],
                rank_components=components,
                rank_reason=[
                    name
                    for name in (
                        "coverage",
                        "title",
                        "rrf",
                        "exact",
                        "title_exact",
                        "relevant",
                        "authority",
                        "freshness",
                        "language_penalty",
                    )
                    if components[name]
                ],
            )
            score = (
                components["coverage"] * 0.5
                + components["title"] * 0.15
                + (0.15 if components["exact"] else 0.0)
                + (0.05 if components["title_exact"] else 0.0)
                + (0.2 if components["relevant"] else 0.0)
                + min(0.12, components["rrf"] * 3.0)
                + components["authority"]
                + components["freshness"]
                + components["language_penalty"]
            )
            if not components["relevant"]:
                score -= 0.15
            scored.append((score, group_index, rank, candidate))
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


_TRACKING_QUERY = re.compile(
    r"^(?:utm_|gclid$|fbclid$|yclid$|spm$|ref$|source$|share_token$|"
    r"from$|mc_cid$|mc_eid$|igshid$)",
    re.I,
)


def _canonical_url(url: str) -> str:
    """A dedupe key for one URL, without tracking noise.

    Search engines return the same article as ``/a``, ``/a/``, ``/a#top`` and
    ``/a?utm_source=...``.  Keeping the display URL untouched is important;
    this key only decides whether two rows are the same result.
    """

    raw = str(url or "").strip()
    if not raw:
        return ""
    try:
        parts = urllib.parse.urlsplit(raw)
        port = parts.port
    except ValueError:
        return raw
    if not parts.netloc:
        return raw
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        return raw
    if host.startswith("www."):
        host = host[4:]
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if port and not (
        (parts.scheme.lower() == "http" and port == 80)
        or (parts.scheme.lower() == "https" and port == 443)
    ):
        host = f"{host}:{port}"
    path = re.sub(r"/+", "/", parts.path or "/")
    if len(path) > 1:
        path = path.rstrip("/")
    if path.endswith("/amp"):
        path = path[:-4] or "/"
    query = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query = sorted(
        (key, value) for key, value in query if not _TRACKING_QUERY.match(key)
    )
    return urllib.parse.urlunsplit(
        (
            (parts.scheme or "https").lower(),
            host,
            path,
            urllib.parse.urlencode(query, doseq=True),
            "",
        )
    )


def dedupe_results(results: Iterable[dict[str, str]], limit: int = 8) -> list[dict[str, str]]:
    """Remove duplicate URLs and unusable titles while preserving rank order."""

    seen: set[str] = set()
    unique: list[dict[str, str]] = []
    for item in results:
        url = item.get("url", "")
        key = _canonical_url(url)
        if not url or key in seen:
            continue
        title = str(item.get("title") or "")
        # Engines sometimes answer a query with an anti-bot interstitial and
        # the "title" comes back as replacement characters or bare punctuation.
        # An entry with no title at all is left alone: other callers feed
        # dedupe_results bare URLs.
        if title and (looks_garbled(title) or not _USEFUL_TITLE_RE.search(title)):
            continue
        seen.add(key)
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


def looks_like_html_shell(html: str) -> bool:
    """A tiny HTML document whose body is a script, cookie check or redirect.

    php.cn and similar sites answer a plain HTTP request with a few dozen bytes
    that only a browser can resolve; without this, extraction reports an empty
    page even though the rendered page is readable.
    """

    if not html or len(html) > 4000:
        return False
    if len(visible_text(html)) >= 120:
        return False
    lowered = html.lower()
    return "<script" in lowered or "location" in lowered or "window." in lowered


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

    assert_public_url(url, allow_private=config.allow_private)
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

                def guard_request(route: Any) -> None:
                    """Block private/file subresources, not just the document.

                    ``page.goto`` checks the requested and final document URL,
                    but a hostile page can still ask Chromium to load an image,
                    script or fetch() from 127.0.0.1, the LAN or a metadata
                    endpoint. The browser-mode bridge already installs this
                    filter; the Python render path needs the same boundary.
                    """

                    request_url = route.request.url
                    if request_url.startswith(("file:", "filesystem:")):
                        route.abort()
                        return
                    if request_url.startswith(("http://", "https://")):
                        try:
                            assert_public_url(
                                request_url, allow_private=config.allow_private
                            )
                        except UnsafeAddress:
                            route.abort()
                            return
                    route.continue_()

                context.route("**/*", guard_request)
                page = context.new_page()
                page.set_default_timeout(timeout_ms)
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                # A JS or meta redirect can land on a private address; check
                # where the document actually ended up before reading it.
                assert_public_url(page.url, allow_private=config.allow_private)
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
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _private_path(path.parent, 0o700)
    payload = {
        "visited": list(data.get("visited", []))[-1000:],
        "trail": list(data.get("trail", []))[-500:],
        "updated_at": utc_now(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _private_path(path, 0o600)
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
    render_fallbacks = 0

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
                page = fetch_page(
                    url,
                    config,
                    fetcher=fetcher,
                    query=query,
                    allow_render_fallback=(
                        config.render == "auto" and render_fallbacks < 2
                    ),
                )
                if page.get("render_fallback"):
                    render_fallbacks += 1
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


# Interstitials served instead of content. They are checked only when the
# extracted body is short, so an article *about* verification is not flagged.
_VERIFICATION_PATTERNS = (
    "verify you are human",
    "unusual traffic",
    "enable javascript and cookies to continue",
    "complete the security check",
)
_WECHAT_VERIFICATION_PATTERNS = (
    "环境异常",
    "完成验证后即可继续访问",
    "请在微信客户端打开链接",
    "访问过于频繁",
)
_VERIFICATION_MAX_CHARS = 1500


def looks_like_verification_page(markdown: str, title: str, url: str) -> str:
    """Return the marker that identifies a verification page, or ``""``.

    WeChat is checked by host because its interstitial is served on the article
    URL itself; the generic English markers are safe anywhere as long as the
    page carries almost no content.  The caller turns a match into
    ``VerificationRequired`` so a record says what happened instead of handing
    back 65 characters of an error page as if it were the article.
    """

    text = f"{title}\n{markdown}".strip()
    if not text or len(text) > _VERIFICATION_MAX_CHARS:
        return ""
    lowered = text.lower()
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if host == "mp.weixin.qq.com" or host.endswith(".weixin.qq.com"):
        for marker in _WECHAT_VERIFICATION_PATTERNS:
            if marker.lower() in lowered:
                return marker
    for marker in _VERIFICATION_PATTERNS:
        if marker in lowered:
            return marker
    return ""


def fetch_page(
    url: str,
    config: Optional[FetchConfig] = None,
    fetcher: Optional[HttpFetcher] = None,
    query: str = "",
    allow_render_fallback: bool = True,
) -> dict[str, Any]:
    """Fetch one URL and return a JSON-serialisable record."""

    config = config or FetchConfig()
    config.validate()
    url = normalize_url(url)
    own_fetcher = fetcher is None
    fetcher = fetcher or HttpFetcher(config)
    warnings: list[str] = []

    try:
        response: Optional[HttpResponse] = None
        policy = fetcher.assert_allowed(url)
        robots_checked = bool(config.respect_robots and config.robots_policy != "ignore")
        robots_overridden = bool(robots_checked and not policy.allowed(url))
        if robots_overridden:
            warnings.append(
                "robots.txt disallows this path; read because robots policy is "
                "'warn'. This override is recorded as compliance.robots_overridden."
            )
        extra_delay = policy.crawl_delay if policy and policy.crawl_delay else 0.0

        rendered = False
        render_fallback = False
        html = ""

        if config.render == "always":
            fetcher.limiter.wait(url, extra_delay)
            html = render_html(url, config)
            rendered = True
        else:
            response = fetcher.fetch(url)
            if getattr(response, "robots_overridden", False) and not robots_overridden:
                robots_overridden = True
                warnings.append(
                    "a redirect target was read because robots policy is 'warn'; "
                    "this override is recorded as compliance.robots_overridden."
                )
            html = response.text
            if config.render == "auto" and looks_dynamic(html):
                try:
                    rendered_html = render_html(url, config)
                    if rendered_html and len(rendered_html) > len(html):
                        html = rendered_html
                        rendered = True
                        log(f"rendered dynamically: {redact_url_for_log(url)}", config)
                except RenderUnavailable as exc:
                    warnings.append(f"dynamic rendering skipped: {exc}")
                except Exception as exc:  # pragma: no cover - defensive
                    warnings.append(f"dynamic rendering failed: {exc}")

            # Some sites answer a plain request with a 100-byte script shell
            # that only a browser resolves. It carries no SPA markers, so the
            # heuristic above misses it and extraction would report an empty
            # page. Render it once, within the caller's budget.
            if (
                allow_render_fallback
                and config.render == "auto"
                and not rendered
                and response is not None
                and "html" in response.content_type.lower()
                and looks_like_html_shell(html)
            ):
                try:
                    rendered_html = render_html(url, config)
                    if rendered_html and len(rendered_html) > len(html):
                        html = rendered_html
                        rendered = True
                        render_fallback = True
                        warnings.append(
                            "the server returned a minimal HTML shell; rendered it "
                            "once with Playwright before extraction"
                        )
                except RenderUnavailable as exc:
                    warnings.append(f"shell rendering skipped: {exc}")
                except Exception as exc:  # pragma: no cover - defensive
                    warnings.append(f"shell rendering failed: {exc}")

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

        marker = looks_like_verification_page(
            markdown, str(metadata.get("title", "")), final_url
        )
        if marker:
            hint = ""
            host = (urllib.parse.urlparse(final_url).hostname or "").lower()
            if host == "mp.weixin.qq.com" or host.endswith(".weixin.qq.com"):
                hint = (
                    " WeChat serves its article body only to a browser session that "
                    "has already passed verification: try the wechat-dig browser "
                    "playbook with --backend cdp and a profile you have opened once."
                )
            raise VerificationRequired(
                f"{final_url} returned a verification/anti-bot page ({marker}); "
                f"HTTP mode does not solve challenges.{hint}"
            )

        if not markdown.strip():
            raise ExtractionError(
                f"no readable content extracted from {final_url}; "
                "the page may be empty, paywalled, or require JavaScript rendering"
            )

        # Everything below came from a third party. Say so in the record, and
        # name instruction-shaped passages instead of letting them read as
        # part of the surrounding conversation.  Scan before max_chars
        # truncation: a hostile instruction near the tail of a long page must
        # not disappear just because the caller asked for a shorter body.
        injection_flags: list[str] = []
        injection_findings: list[dict[str, Any]] = []
        trust = "untrusted"
        if config.input_gate != "off":
            injection_findings = untrusted.scan_findings(
                markdown + "\n" + str(metadata.get("title", ""))
            )
            injection_flags = untrusted.codes(injection_findings)
            hard = untrusted.hard_codes(injection_findings)
            if hard and config.input_gate == "strict":
                markdown = ""
                trust = "rejected"
                warnings.insert(0, untrusted.withheld(hard, injection_findings))
            elif injection_findings:
                warnings.insert(0, untrusted.warning(injection_flags, injection_findings))

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
            "render_fallback": render_fallback,
            "fetched_at": utc_now(),
            "title": metadata.get("title", ""),
            "metadata": metadata,
            "markdown": markdown,
            "chunks": chunks,
            "tables": tables,
            "links": links,
            "warnings": warnings,
            "trust": trust,
            "injection_flags": injection_flags,
            "injection_findings": injection_findings,
            "compliance": {
                "robots_checked": robots_checked,
                "robots_policy": (
                    config.robots_policy if config.respect_robots else "ignore"
                ),
                "robots_overridden": robots_overridden,
            },
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
    tokens = _content_tokens(query)
    if results:
        annotate_results(results, query)
    if not results:
        warnings.append(
            f"no results: {engine} returned nothing for {query!r}. Try another "
            "engine (--engine all), a shorter query, or a direct URL."
        )
    elif tokens and not any(item.get("relevance") for item in results):
        if max(result_coverage(item, tokens) for item in results) <= 0:
            warnings.append(
                "none of the returned results mention the query text; the engine "
                "most likely split the query into single characters (common with "
                "quoted or CJK names). Treat these results as unrelated and try "
                "another engine or a more specific query."
            )
        else:
            warnings.append(
                "none of the returned results pass the relevance check: each needs "
                "at least two meaningful query terms, the exact phrase, or an "
                "equivalent match. Treat these results as unrelated and try another "
                "engine or a shorter, more specific query."
            )
    else:
        off_topic = [item for item in results if item.get("relevance") is False]
        if off_topic:
            warnings.append(
                f"{len(off_topic)} of {len(results)} results look off-topic: they "
                "match only one query term or come from the wrong language. They "
                "are kept at the bottom of the list; check relevance before using "
                "them as findings."
            )
    if results:
        probe_findings: list[dict[str, Any]] = []
        for item in results:
            findings = untrusted.scan_findings(
                f"{item.get('title', '')} {item.get('snippet', '')}"
            )
            if findings:
                item["injection_flags"] = untrusted.codes(findings)
                item["injection_findings"] = findings
                probe_findings.extend(findings)
        if probe_findings:
            warnings.append(
                untrusted.warning(untrusted.codes(probe_findings), probe_findings)
            )
    if looks_like_person_name(query):
        warnings.append(
            "the query is a bare personal name. Searching a paper author or a "
            "public figure is fine; do not build or publish a profile of a "
            "private individual — that is out of scope for this tool."
        )
    return warnings


def search_quality(
    query: str,
    results: list[dict[str, Any]],
    engine: str = "auto",
    engine_report: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    """A small, machine-readable summary of how good a result list is.

    The prose warnings remain for humans; this block lets an agent decide
    whether to trust the list without parsing English.  Counts describe what
    was returned, not what the engine could have returned.
    """

    annotate_results(results, query)
    intent = classify_intent(query)
    relevant = sum(1 for item in results if item.get("relevance"))
    off_topic = sum(1 for item in results if item.get("relevance") is False)
    language_mismatch = sum(
        1 for item in results if item.get("language_match") is False
    )
    tiers: dict[str, int] = {}
    for item in results:
        tier = str(item.get("authority_tier") or "unknown")
        tiers[tier] = tiers.get(tier, 0) + 1
    answered = [
        str(entry.get("engine", ""))
        for entry in (engine_report or [])
        if entry.get("ok") and entry.get("engine")
    ]
    errors = [
        {"engine": entry.get("engine", ""), "error": entry.get("error", "")}
        for entry in (engine_report or [])
        if not entry.get("ok")
    ]
    engine_status = {
        str(entry.get("engine", "")): str(
            entry.get("status") or ("ok" if entry.get("ok") else "error")
        )
        for entry in (engine_report or [])
        if entry.get("engine")
    }
    engine_states: dict[str, int] = {}
    for state in engine_status.values():
        engine_states[state] = engine_states.get(state, 0) + 1
    return {
        "query": query,
        "engine": engine,
        "intent": intent["intent"],
        "intent_confidence": intent["confidence"],
        "returned": len(results),
        "relevant": relevant,
        "off_topic": off_topic,
        "language_mismatch": language_mismatch,
        "authority_tiers": tiers,
        "high_authority": sum(
            tiers.get(tier, 0)
            for tier in ("primary", "official", "academic")
        ),
        "engines_answered": answered,
        "engine_errors": errors,
        "engine_status": engine_status,
        "engine_states": engine_states,
    }


SITE_SEARCH_TEMPLATES = (
    "/?s={query}",
    "/search?q={query}",
    "/?search={query}",
    "/search?query={query}",
)
# Hosts whose own search page is not one of the generic WordPress/Sphinx
# shapes above.  These are public search interfaces, not scraped result pages;
# the links they return are still fetched through the normal robots-aware path.
_SITE_SEARCH_URLS = {
    "support.microsoft.com": (
        "https://support.microsoft.com/en-us/search/results?query={query}"
    ),
    "developer.mozilla.org": "https://developer.mozilla.org/en-US/search?q={query}",
}


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
    reason = doxxing_reason(query)
    if reason:
        raise ProhibitedQuery(
            f"refused: {reason}. web-forager does not collect or assemble "
            "profiles of identifiable people; search for a topic, a paper "
            "title or an organisation instead."
        )
    site_url = normalize_url(site if "://" in site else "https://" + site)
    pages_limit = config.max_pages if max_pages is None else max(0, max_pages)
    own_fetcher = fetcher is None
    fetcher = fetcher or HttpFetcher(config)

    attempts: list[dict[str, Any]] = []
    page: Optional[HttpResponse] = None
    search_url = ""
    host = (urllib.parse.urlsplit(site_url).hostname or "").lower()
    preferred = _SITE_SEARCH_URLS.get(host) or _SITE_SEARCH_URLS.get(
        host.removeprefix("www.")
    )
    templates = ((preferred,) if preferred else ()) + SITE_SEARCH_TEMPLATES
    try:
        for template in templates:
            if template.startswith(("http://", "https://")):
                candidate = template.format(query=urllib.parse.quote_plus(query))
            else:
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
        quality_data: dict[str, Any] = {}
        results = search(
            query,
            config,
            engine=engine,
            limit=config.num_results,
            report=engine_report,
            quality=quality_data,
        )
        pages: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        attempts = 0
        render_fallbacks = 0
        # ``max_pages`` means readable pages, not attempts. Keep scanning past
        # robots-denied or unreadable results, with a cap so one query cannot
        # turn into an unbounded site walk.
        max_attempts = min(len(results), max(config.max_pages * 3, config.max_pages + 5))
        for result in results:
            if len(pages) >= config.max_pages or attempts >= max_attempts:
                break
            attempts += 1
            try:
                page = fetch_page(
                    result["url"],
                    config,
                    fetcher=fetcher,
                    allow_render_fallback=(
                        config.render == "auto" and render_fallbacks < 2
                    ),
                )
                if page.get("render_fallback"):
                    render_fallbacks += 1
                pages.append(page)
            except RobotsDenied as exc:
                skipped.append(
                    {"url": result["url"], "code": "robots_denied", "reason": str(exc)}
                )
            except VerificationRequired as exc:
                skipped.append(
                    {
                        "url": result["url"],
                        "code": "verification_required",
                        "reason": str(exc),
                    }
                )
            except FetchError as exc:
                skipped.append(
                    {"url": result["url"], "code": "fetch_error", "reason": str(exc)}
                )
            except ExtractionError as exc:
                skipped.append(
                    {"url": result["url"], "code": "extraction_error", "reason": str(exc)}
                )
            except RenderUnavailable as exc:
                skipped.append(
                    {"url": result["url"], "code": "render_unavailable", "reason": str(exc)}
                )
            except Exception as exc:  # pragma: no cover - defensive
                skipped.append(
                    {"url": result["url"], "code": "unexpected", "reason": str(exc)}
                )
        quality = search_quality(query, results, engine, engine_report)
        quality.update(quality_data)
        payload: dict[str, Any] = {
            "query": query,
            "engine": engine,
            "mode": "search",
            "search_results": results,
            "search_quality": quality,
            "engine_report": engine_report,
            "pages": pages,
            "skipped": skipped,
            "pages_attempted": attempts,
        }
        warnings = search_warnings(query, results, engine=engine)
        if skipped:
            counts: dict[str, int] = {}
            for item in skipped:
                counts[item["code"]] = counts.get(item["code"], 0) + 1
            summary = ", ".join(f"{code} ({count})" for code, count in sorted(counts.items()))
            warnings.append(
                f"{len(skipped)} result(s) skipped while filling {config.max_pages} "
                f"readable page(s): {summary}"
            )
            if counts.get("robots_denied"):
                warnings.append(
                    "robots.txt denied the skipped paths. Use --robots-policy warn only "
                    "when you are authorised to read them; the record will mark the "
                    "override. Do not silently switch to a tool that ignores robots."
                )
            if counts.get("verification_required"):
                warnings.append(
                    "verification_required means the site answered with an anti-bot or "
                    "verification page instead of the article. For a WeChat link, read it "
                    "in browser mode: browser_run with playbook \"wechat-dig\" and that URL "
                    "(CLI: node browser/run.js --playbook wechat-dig --url <URL> --backend cdp) "
                    "after signing in once with browser/launch_chrome.py. Do not try to solve "
                    "the challenge."
                )
            wechat_denied = [
                item
                for item in skipped
                if item["code"] == "robots_denied"
                and (
                    urllib.parse.urlparse(item["url"]).hostname or ""
                ).lower()
                == "mp.weixin.qq.com"
            ]
            if wechat_denied:
                warnings.append(
                    "WeChat article links cannot be read in HTTP mode: robots.txt disallows "
                    "/s, and the page itself returns an environment check. Open one with "
                    "browser mode instead: browser_run with playbook \"wechat-dig\" and that "
                    "URL (CLI: node browser/run.js --playbook wechat-dig --url <URL> --backend cdp). "
                    "Do not try to solve the challenge."
                )
            if not pages:
                warnings.append(
                    "No readable page was left. Try --engine bing for a Latin query, "
                    "--action find --site <host> for a site's own search, or "
                    "--action feed --url <site> for its RSS/Atom feed."
                )
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


def redact_url_for_log(value: str) -> str:
    """A URL safe to put in a diagnostic line.

    Query strings carry search terms, signed tokens and session identifiers,
    and fragments can carry the same.  Verbose logging therefore keeps the
    scheme, host and path only; the caller already has the full URL in the
    result when it needs it.
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
    if not parts.scheme or not parts.netloc:
        return ""
    return urllib.parse.urlunsplit(
        (parts.scheme, parts.netloc, parts.path or "/", "", "")
    )


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
