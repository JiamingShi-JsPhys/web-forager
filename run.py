#!/usr/bin/env python3
"""web-forager command-line entry point.

Actions
-------
fetch
    ``--url URL``   fetch one page and return metadata, Markdown and tables
    ``--query TEXT`` search (360+Bing by default), then fetch the top results

clean
    ``--input file``       clean a local HTML/PDF/DOCX/XLSX/EPUB/CSV file
    ``--url URL``          fetch a page/document and clean it
    (no input)             read HTML/PDF/document bytes from stdin

bili
    ``--url BV...`` / ``--query TEXT`` / neither  Bilibili video, search or feed

surf
    ``--url URL`` or ``--query TEXT``  open/search, then follow ranked links
    ``--depth N --follow same-site|all|none --session NAME``

scholar
    ``--source arxiv|crossref|pubmed|doi --query TEXT``  bibliographic records

map
    ``--url SITE``         discover page URLs from robots.txt / sitemaps

Global
    ``--engine auto|all|360|bing|sogou|weixin|duckduckgo``
    ``--cache --chunk-size N --search-pages N``
    ``--agent``  OpenCLI-style ``{ok,data}`` / ``{ok,error}`` envelope for agents

MCP
    ``python mcp_server.py``  stdio JSON-RPC server exposing the same engine.

本插件仅供学习与信息收集使用。使用者需遵守目标网站的 Terms of Service 及相关版权法律。
禁止用于恶意并发攻击。严禁收集、聚合或推断特定自然人的个人信息，或将其用于人肉搜索、骚扰、跟踪等侵害他人隐私的活动；此类用法产生的法律责任由使用者自行承担。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

_PLUGIN_ROOT = Path(__file__).resolve().parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from scripts import bilibili, documents, engine, pdf as pdf_mod, scholar, sitemap  # noqa: E402


def _reconfigure_stdio() -> None:
    """Force UTF-8 so Chinese metadata survives Windows code pages."""

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except Exception:
            pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="web-forager",
        description=(
            "Polite, robots-aware web information gathering and "
            "HTML-to-Markdown cleaning for public pages."

        ),
        epilog=engine.DISCLAIMER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--action",
        required=True,
        choices=["fetch", "find", "feed", "clean", "bili", "surf", "scholar", "map", "doctor"],
        help="operation to run",
    )
    parser.add_argument("--url", help="target URL, or a Bilibili BV/av id (fetch/clean/bili/surf/map)")
    parser.add_argument("--query", help="keyword query (fetch/bili/surf/scholar)")
    parser.add_argument("--site", help="domain or base URL to search inside (find)")
    parser.add_argument("--input", dest="input_path", help="local HTML/PDF/DOCX/XLSX/EPUB/CSV file (clean)")
    parser.add_argument(
        "--source",
        choices=list(scholar.SCHOLAR_SOURCES),
        default="arxiv",
        help="scholarly source for --action scholar (default: arxiv)",
    )
    parser.add_argument(
        "--sort",
        choices=["relevance", "submittedDate", "lastUpdatedDate"],
        default="relevance",
        help="arXiv sort order (default: relevance)",
    )
    parser.add_argument("--limit", type=int, default=500, help="map: maximum URLs to return (default: 500)")
    parser.add_argument("--max-sitemaps", type=int, default=5, help="map: sitemap files to read (default: 5)")
    parser.add_argument(
        "--engine",
        choices=list(engine.SEARCH_ENGINES),
        default="auto",
        help="search backend: auto=360+Bing (mostly-CJK queries: 360+Sogou+WeChat); all=every engine (default: auto)",
    )
    parser.add_argument("--num-results", type=int, default=8, help="search results to request (default: 8)")
    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="result pages to fetch (default: 3; 0 = search results only)",
    )
    parser.add_argument("--search-pages", type=int, default=1, help="search result pages to read per engine (default: 1)")
    parser.add_argument(
        "--mode",
        choices=["auto", "feed", "video", "search", "related", "surf"],
        default="auto",
        help="Bilibili mode (default auto: query->search, url->video, neither->feed)",
    )
    parser.add_argument("--depth", type=int, default=1, help="Bilibili/surf depth (default: 1)")
    parser.add_argument(
        "--follow",
        choices=["same-site", "all", "none"],
        default="same-site",
        help="surf link policy: same-site (default), all, none",
    )
    parser.add_argument(
        "--session",
        help="surf session name; visited URLs and the trail are saved under ~/.web-forager/sessions/",
    )
    parser.add_argument(
        "--direct-search",
        action="store_true",
        help=(
            "Bilibili only: query search.bilibili.com directly. That host disallows "
            "generic agents in robots.txt, so this is an explicit opt-in override; "
            "video pages are still fetched with robots checks enabled."
        ),
    )
    parser.add_argument(
        "--render",
        choices=["auto", "never", "always"],
        default="auto",
        help="dynamic rendering with Playwright: auto detects JS shells (default), never, always",
    )
    parser.add_argument("--no-tables", action="store_true", help="do not extract tables")
    parser.add_argument("--keep-links", action="store_true", help="preserve hyperlinks in Markdown")
    parser.add_argument("--images", action="store_true", help="preserve image references in Markdown")
    parser.add_argument("--max-chars", type=int, default=20_000, help="truncate Markdown to N characters (0 = no limit)")
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=0,
        help="also emit Markdown chunks of about N characters (0 = off)",
    )
    parser.add_argument("--cache", action="store_true", help="reuse responses cached under ~/.web-forager/cache")
    parser.add_argument("--cache-ttl", type=int, default=3600, help="cache lifetime in seconds (default: 3600)")
    parser.add_argument("--cache-dir", default="", help="override the cache directory")
    parser.add_argument("--wait-for", default="", help="Playwright: wait for this CSS selector before reading the page")
    parser.add_argument("--scroll", type=int, default=0, help="Playwright: wheel-scroll N times to load lazy content")
    parser.add_argument("--timeout", type=float, default=20.0, help="per-request timeout in seconds")
    parser.add_argument("--delay", type=float, default=1.0, help="politeness delay per host in seconds")
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="DANGEROUS: skip robots.txt checks (only for resources you are authorised to access)",
    )
    parser.add_argument(
        "--allow-private",
        action="store_true",
        help=(
            "DANGEROUS: allow loopback, private and link-local targets. "
            "For local fixtures and trusted intranet tools only"
        ),
    )
    parser.add_argument(
        "--input-gate",
        choices=["off", "mark", "strict"],
        default="mark",
        help=(
            "treat fetched text as untrusted: mark instruction-shaped content "
            "(default), withhold the body on a hard hit (strict), or skip the scan"
        ),
    )
    parser.add_argument("--user-agent", default=engine.DEFAULT_USER_AGENT, help="explicit User-Agent string")
    parser.add_argument(
        "--probe",
        action="store_true",
        help="doctor: ask each search engine once and report which ones answer",
    )
    parser.add_argument(
        "--proxy",
        default="",
        help="route every request through this proxy (default: HTTPS_PROXY / ALL_PROXY from the environment)",
    )
    parser.add_argument("--format", choices=["json", "markdown"], default="json", help="stdout format")
    parser.add_argument(
        "--full-results",
        action="store_true",
        help=(
            "repeat every page record inside results as well as pages "
            "(1.0.1 behaviour; off by default because it doubles the response)"
        ),
    )
    parser.add_argument(
        "--core",
        action="store_true",
        help="report results in the shared core-1 schema that browser mode also emits",
    )
    parser.add_argument(
        "--agent",
        action="store_true",
        help="OpenCLI-style envelope: {ok:true,data:...} or {ok:false,error:{code,message,hint}}",
    )
    parser.add_argument("--out", help="write the result to this file instead of stdout")
    parser.add_argument(
        "--root",
        help=(
            "Chelate workspace root; writes <root>/process/web-forager/ and a "
            "<root>/_broadcast/ index entry. Ignored when --out is given."
        ),
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="diagnostics on stderr")
    parser.add_argument("--version", action="version", version=f"web-forager {engine.__version__}")
    return parser


def build_config(args: argparse.Namespace) -> engine.FetchConfig:
    config = engine.FetchConfig(
        user_agent=args.user_agent,
        timeout=args.timeout,
        delay=args.delay,
        max_chars=args.max_chars,
        respect_robots=not args.ignore_robots,
        render=args.render,
        include_tables=not args.no_tables,
        keep_links=args.keep_links,
        include_images=args.images,
        max_pages=max(0, args.max_pages),
        num_results=max(1, args.num_results),
        verbose=args.verbose,
        extract_links=args.action == "surf",
        follow=args.follow,
        search_engine=args.engine,
        proxy=args.proxy,
        search_pages=max(1, args.search_pages),
        cache=args.cache,
        cache_ttl=max(0, args.cache_ttl),
        cache_dir=args.cache_dir,
        chunk_size=max(0, args.chunk_size),
        wait_for=args.wait_for,
        scroll=max(0, args.scroll),
        allow_private=bool(args.allow_private) or engine._allow_private_from_env(),
        input_gate=args.input_gate,
    )
    config.validate()
    return config


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------


def document_to_markdown(document: dict) -> str:
    """Render a result envelope as a human-readable Markdown document."""

    if document.get("action") == "clean":
        return document.get("markdown", "")
    if document.get("action") == "scholar":
        return scholar.to_markdown(document)
    if document.get("action") == "map":
        return sitemap.to_markdown(document)

    blocks: list[str] = []
    for record in document.get("results", []):
        if record.get("error"):
            blocks.append(f"## {record.get('url', 'unknown')}\n\n**Error:** {record['error']}")
            continue
        title = record.get("title") or record.get("final_url") or record.get("url", "")
        if not record.get("markdown"):
            blocks.append(f"- [{title}]({record.get('url', '')})")
            continue
        lines = [f"# {title}", "", f"> Source: {record.get('final_url') or record.get('url', '')}", ""]
        metadata = record.get("metadata") or {}
        if metadata.get("authors"):
            lines.append(f"**Authors:** {', '.join(metadata['authors'])}")
        if metadata.get("published"):
            lines.append(f"**Published:** {metadata['published']}")
        if metadata.get("doi"):
            lines.append(f"**DOI:** {metadata['doi']}")
        if metadata.get("journal"):
            lines.append(f"**Journal:** {metadata['journal']}")
        if metadata.get("authors") or metadata.get("published") or metadata.get("doi") or metadata.get("journal"):
            lines.append("")
        lines.append(record.get("markdown", "").strip())
        blocks.append("\n".join(lines).strip())
    return "\n\n---\n\n".join(blocks)


def emit(text: str, output_path: str | None) -> None:
    if output_path:
        target = Path(output_path)
        if target.parent and not target.parent.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        print(f"[web-forager] wrote {target}", file=sys.stderr)
    else:
        sys.stdout.write(text)
        if not text.endswith("\n"):
            sys.stdout.write("\n")
        sys.stdout.flush()


# ---------------------------------------------------------------------------
# Chelate workspace integration
# ---------------------------------------------------------------------------


def _workspace_slug(args: argparse.Namespace) -> str:
    raw = args.query or args.url or (Path(args.input_path).stem if args.input_path else "stdin")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(raw)).strip("-._")
    if not slug:
        slug = "result-" + hashlib.sha1(str(raw).encode("utf-8")).hexdigest()[:8]
    return slug[:48]


def _workspace_timestamp(document: dict) -> str:
    stamp = str(document.get("generated_at") or engine.utc_now())
    return re.sub(r"[^0-9TZ]", "", stamp) or "00000000T000000Z"


def _document_summary(document: dict) -> str:
    action = document.get("action")
    if action == "clean":
        return f"cleaned {document.get('source', 'input')}"
    if action == "scholar":
        return f"{document.get('count', 0)} record(s) from {document.get('source', 'scholar')}"
    if action == "map":
        return f"{document.get('count', 0)} URL(s) from {document.get('origin', 'sitemap')}"
    results = document.get("results") or []
    if action == "bili":
        first = results[0] if results else {}
        title = first.get("title") or document.get("query") or document.get("seed") or ""
        mode = document.get("mode", "bili")
        return f"bilibili {mode} · {len(results)} item(s)" + (f" · {title}" if title else "")
    first = results[0] if results else {}
    title = first.get("title") or first.get("url") or ""
    return f"{len(results)} page(s)" + (f" · {title}" if title else "")


def write_workspace(
    args: argparse.Namespace,
    document: dict,
    json_text: str,
    markdown_text: str,
) -> list[Path]:
    """Write the run into a Chelate four-zone workspace.

    Layout follows the main library:

    * ``<root>/process/web-forager/`` - intermediate JSON + Markdown artefacts
    * ``<root>/_broadcast/``          - one read-only index entry per run
    """

    root = Path(args.root).expanduser().resolve()
    if root.exists() and not root.is_dir():
        raise ValueError(f"--root is not a directory: {root}")

    process_dir = root / "process" / "web-forager"
    broadcast_dir = root / "_broadcast"
    process_dir.mkdir(parents=True, exist_ok=True)
    broadcast_dir.mkdir(parents=True, exist_ok=True)

    base = f"web-forager_{_workspace_timestamp(document)}_{_workspace_slug(args)}"
    json_path = process_dir / f"{base}.json"
    markdown_path = process_dir / f"{base}.md"
    index_path = broadcast_dir / f"{base}.json"

    json_path.write_text(json_text + "\n", encoding="utf-8", newline="\n")
    markdown_path.write_text(markdown_text + "\n", encoding="utf-8", newline="\n")

    index = {
        "tool": "web-forager",
        "version": engine.__version__,
        "action": document.get("action", ""),
        "generated_at": document.get("generated_at", ""),
        "summary": _document_summary(document),
        "source": document.get("source") or document.get("query") or document.get("seed") or "",
        "files": {
            "json": json_path.relative_to(root).as_posix(),
            "markdown": markdown_path.relative_to(root).as_posix(),
        },
    }
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")

    for path in (json_path, markdown_path, index_path):
        print(f"[web-forager] workspace: {path}", file=sys.stderr)
    return [json_path, markdown_path, index_path]


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------


def _envelope(action: str, payload: dict, args: argparse.Namespace) -> dict:
    """Build the response envelope, honouring --full-results."""

    return engine.build_envelope(action, payload, full_results=bool(getattr(args, "full_results", False)))


def cmd_find(args: argparse.Namespace, config: engine.FetchConfig) -> dict:
    if not args.site:
        raise ValueError("--action find needs --site")
    if not args.query:
        raise ValueError("--action find needs --query")
    payload = engine.find_within_site(
        args.site, args.query, config, max_pages=args.max_pages
    )
    return _envelope("find", payload, args)


def cmd_feed(args: argparse.Namespace, config: engine.FetchConfig) -> dict:
    if not args.url:
        raise ValueError("--action feed needs --url")
    payload = engine.discover_feed(args.url, config)
    payload["results"] = [
        {
            "url": item.get("url", ""),
            "title": item.get("title", ""),
            "published": item.get("published", ""),
        }
        for item in payload.get("items") or []
    ]
    return _envelope("feed", payload, args)


def cmd_fetch(args: argparse.Namespace, config: engine.FetchConfig) -> dict:
    if bool(args.url) == bool(args.query):
        raise ValueError("--action fetch needs exactly one of --url or --query")

    if args.url:
        page = engine.fetch_page(args.url, config)
        return _envelope("fetch", page, args)

    payload = engine.fetch_by_query(args.query, config, engine=args.engine)
    return _envelope("fetch", payload, args)


def _clean_chunks(payload: dict, config: engine.FetchConfig) -> dict:
    if config.chunk_size:
        payload["chunks"] = engine.chunk_markdown(payload.get("markdown", ""), config.chunk_size)
    return payload


def _pdf_document(
    data: bytes,
    source: str,
    url: str,
    config: engine.FetchConfig,
) -> dict:
    """Build a clean-style document from PDF bytes.

    ``pdf_mod`` raises ``PdfUnavailable`` when pypdf is missing and
    ``PdfExtractionError`` when the file cannot be parsed; ``main`` maps both
    to stable exit codes instead of letting a traceback escape.
    """

    extracted = pdf_mod.extract(data)
    markdown = pdf_mod.to_markdown(extracted, url=url or "")
    if config.max_chars and len(markdown) > config.max_chars:
        markdown = markdown[: config.max_chars].rstrip() + "\n\n<!-- truncated by web-forager -->"

    return {
        "tool": "web-forager",
        "version": engine.__version__,
        "action": "clean",
        "generated_at": engine.utc_now(),
        "source": source,
        "content_type": "application/pdf",
        "page_count": extracted.get("page_count", 0),
        "empty_pages": extracted.get("empty_pages", 0),
        "metadata": pdf_mod.to_metadata(extracted, url=url or ""),
        "tables": [],
        "markdown": markdown,
        "chunks": engine.chunk_markdown(markdown, config.chunk_size) if config.chunk_size else [],
    }


def _document_document(
    data: bytes,
    kind: str,
    source: str,
    url: str,
    config: engine.FetchConfig,
) -> dict:
    extracted = documents.extract(data, kind, url=url or source)
    markdown = extracted["markdown"]
    if config.max_chars and len(markdown) > config.max_chars:
        markdown = markdown[: config.max_chars].rstrip() + "\n\n<!-- truncated by web-forager -->"
    payload = {
        "tool": "web-forager",
        "version": engine.__version__,
        "action": "clean",
        "generated_at": engine.utc_now(),
        "source": source,
        "content_type": kind,
        "metadata": documents.to_metadata(extracted, url=url or ""),
        "tables": extracted.get("tables") or [],
        "markdown": markdown,
    }
    return _clean_chunks(payload, config)


def cmd_clean(args: argparse.Namespace, config: engine.FetchConfig) -> dict:
    source = ""
    base_url: str | None = None
    fetcher: engine.HttpFetcher | None = None

    try:
        if args.input_path and args.url:
            raise ValueError("--action clean accepts --input or --url, not both")

        if args.input_path:
            path = Path(args.input_path)
            if not path.is_file():
                raise ValueError(f"input file not found: {path}")
            data = path.read_bytes()
            source = str(path)
            if pdf_mod.is_pdf(data):
                return _pdf_document(data, source, "", config)
            kind = documents.detect(data, url=source)
            if kind:
                return _document_document(data, kind, source, "", config)
            html = engine.decode_bytes(data)
            base_url = args.url if args.url else None
        elif args.url:
            fetcher = engine.HttpFetcher(config)
            response = fetcher.fetch(args.url)
            source = response.final_url
            base_url = response.final_url
            if "application/pdf" in response.content_type or pdf_mod.is_pdf(response.content):
                return _pdf_document(response.content, source, response.final_url, config)
            kind = documents.detect(response.content, response.content_type, response.final_url)
            if kind:
                return _document_document(
                    response.content, kind, source, response.final_url, config
                )
            html = response.text
        else:
            if sys.stdin.isatty():
                raise ValueError("--action clean needs --input, --url, or HTML on stdin")
            data = sys.stdin.buffer.read()
            source = "stdin"
            if pdf_mod.is_pdf(data):
                return _pdf_document(data, source, "", config)
            kind = documents.detect(data)
            if kind:
                return _document_document(data, kind, source, "", config)
            html = engine.decode_bytes(data)

        markdown = engine.html_to_markdown(
            html,
            url=base_url,
            include_tables=config.include_tables,
            keep_links=config.keep_links,
            include_images=config.include_images,
        )
        if not markdown.strip():
            raise engine.ExtractionError("no readable content found in the supplied HTML")
        if config.max_chars and len(markdown) > config.max_chars:
            markdown = markdown[: config.max_chars].rstrip() + "\n\n<!-- truncated by web-forager -->"

        payload = {
            "tool": "web-forager",
            "version": engine.__version__,
            "action": "clean",
            "generated_at": engine.utc_now(),
            "source": source,
            "metadata": engine.extract_metadata(html, url=base_url),
            "tables": engine.extract_tables(html) if config.include_tables else [],
            "markdown": markdown,
        }
        return _clean_chunks(payload, config)
    finally:
        if fetcher is not None:
            fetcher.close()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def cmd_surf(args: argparse.Namespace, config: engine.FetchConfig) -> dict:
    """Search (or open) a page, then follow ranked links like a human browsing."""

    if bool(args.url) == bool(args.query):
        raise ValueError("--action surf needs exactly one of --url or --query")

    seed = args.url or args.query
    payload = engine.surf_web(
        seed,
        config,
        depth=max(0, args.depth),
        follow=args.follow,
        max_pages=max(1, args.max_pages),
        engine_name=args.engine,
        session=args.session or None,
    )
    return _envelope("surf", payload, args)


def cmd_scholar(args: argparse.Namespace, config: engine.FetchConfig) -> dict:
    if not args.query:
        raise ValueError("--action scholar needs --query (or a DOI with --source doi)")
    payload = scholar.search(
        args.source,
        args.query,
        config,
        limit=max(1, args.num_results),
        sort=args.sort,
    )
    return _envelope("scholar", payload, args)


def cmd_map(args: argparse.Namespace, config: engine.FetchConfig) -> dict:
    if not args.url:
        raise ValueError("--action map needs --url (a site, sitemap or robots.txt URL)")
    payload = sitemap.discover(
        args.url,
        config,
        limit=max(1, args.limit),
        max_sitemaps=max(1, args.max_sitemaps),
    )
    return _envelope("map", payload, args)


def cmd_bili(args: argparse.Namespace, config: engine.FetchConfig) -> dict:
    mode = args.mode
    if mode == "auto":
        mode = "search" if args.query else "video" if args.url else "feed"

    if mode == "feed":
        payload = bilibili.feed(
            config,
            limit=args.num_results,
            enrich=max(0, args.max_pages),
            url=args.url or bilibili.BILI_HOME,
        )
    elif mode == "video":
        if not args.url:
            raise ValueError("--mode video needs --url with a BV id or a video URL")
        record = bilibili.fetch_video(args.url, config)
        payload = {"mode": "video", "videos": [record], "results": [record]}
    elif mode == "search":
        if not args.query:
            raise ValueError("--mode search needs --query")
        payload = bilibili.search(args.query, config, allow_direct=args.direct_search)
    elif mode == "related":
        if not args.url:
            raise ValueError("--mode related needs --url with a BV id or a video URL")
        payload = bilibili.related(
            args.url, config, limit=args.num_results, enrich=max(0, args.max_pages)
        )
    elif mode == "surf":
        seed = args.url or args.query
        if not seed:
            raise ValueError("--mode surf needs --url (a video) or --query (a keyword)")
        payload = bilibili.surf(
            seed,
            config,
            depth=max(0, args.depth),
            per_level=max(1, args.max_pages),
            allow_direct=args.direct_search,
        )
    else:  # pragma: no cover - argparse prevents this
        raise ValueError(f"unsupported Bilibili mode: {mode}")

    return _envelope("bili", payload, args)


def cmd_doctor(args: argparse.Namespace, config: engine.FetchConfig) -> dict:
    """Report optional dependencies so an agent can install what is missing."""

    payload = engine.doctor_report(config)
    if getattr(args, "probe", False):
        payload["search_probe"] = engine.probe_engines(config)
    return _envelope("doctor", payload, args)


def _fail(
    args: argparse.Namespace,
    code: str,
    message: str,
    hint: str,
    exit_code: int,
) -> int:
    """Report a failure either as an OpenCLI-style envelope or on stderr."""

    if getattr(args, "agent", False):
        payload = {
            "ok": False,
            "error": {"code": code, "message": message, "hint": hint},
        }
        print(json.dumps(payload, ensure_ascii=False))
    else:
        suffix = f" ({hint})" if hint else ""
        print(f"error: {message}{suffix}", file=sys.stderr)
    return exit_code


def main(argv: list[str] | None = None) -> int:
    _reconfigure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        config = build_config(args)
        if args.action == "fetch":
            document = cmd_fetch(args, config)
        elif args.action == "find":
            document = cmd_find(args, config)
        elif args.action == "feed":
            document = cmd_feed(args, config)
        elif args.action == "clean":
            document = cmd_clean(args, config)
        elif args.action == "surf":
            document = cmd_surf(args, config)
        elif args.action == "scholar":
            document = cmd_scholar(args, config)
        elif args.action == "map":
            document = cmd_map(args, config)
        elif args.action == "bili":
            document = cmd_bili(args, config)
        else:
            document = cmd_doctor(args, config)
    except engine.ProhibitedQuery as exc:
        return _fail(
            args,
            "prohibited_query",
            str(exc),
            "search a topic, a paper title or an organisation; person profiling is out of scope",
            10,
        )
    except engine.RobotsDenied as exc:
        return _fail(
            args,
            "robots_denied",
            f"robots.txt denied this request: {exc}",
            "use --ignore-robots only for resources you are authorised to access",
            3,
        )
    except engine.UnsafeAddress as exc:
        return _fail(
            args,
            "unsafe_address",
            str(exc),
            "loopback, private, link-local and cloud-metadata addresses are refused",
            2,
        )
    except engine.InvalidURLError as exc:
        return _fail(args, "invalid_url", f"invalid URL: {exc}", "pass an absolute http(s) URL", 2)
    except engine.PdfUnavailable as exc:
        return _fail(args, "pdf_unavailable", str(exc), "pip install pypdf", 7)
    except engine.PdfExtractionError as exc:
        return _fail(args, "pdf_extraction_failed", str(exc), "check that the file is a valid PDF", 5)
    except engine.FetchError as exc:
        return _fail(args, "fetch_failed", f"fetch failed: {exc}", "check the URL and network", 4)
    except engine.ExtractionError as exc:
        return _fail(
            args,
            "extraction_failed",
            f"extraction failed: {exc}",
            "try --render always (needs Playwright) for JavaScript-heavy pages",
            5,
        )
    except engine.RenderUnavailable as exc:
        return _fail(
            args,
            "render_unavailable",
            f"dynamic rendering unavailable: {exc}",
            "pip install playwright && playwright install chromium",
            6,
        )
    except ValueError as exc:
        return _fail(args, "invalid_argument", str(exc), "", 2)
    except KeyboardInterrupt:
        return _fail(args, "interrupted", "interrupted", "", 130)
    except Exception as exc:  # never surface a raw traceback to the user
        if getattr(args, "verbose", False):
            import traceback

            traceback.print_exc()
        return _fail(args, "unexpected_error", f"unexpected failure: {exc}", "run with --verbose for the traceback", 1)

    if getattr(args, "core", False):
        document = engine.apply_core(document)

    json_text = json.dumps(document, ensure_ascii=False, indent=2)
    markdown_text = document_to_markdown(document)
    if args.agent:
        output = json.dumps({"ok": True, "data": document}, ensure_ascii=False, indent=2)
    elif args.format == "markdown":
        output = markdown_text
    else:
        output = json_text

    if args.root and not args.out:
        try:
            write_workspace(args, document, json_text, markdown_text)
        except (OSError, ValueError) as exc:
            print(f"error: cannot write Chelate workspace: {exc}", file=sys.stderr)
            return 2

    emit(output, args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
