#!/usr/bin/env python3
"""Minimal MCP (Model Context Protocol) stdio server for web-forager.

No SDK is required: this speaks newline-delimited JSON-RPC 2.0 on stdin/stdout,
implements ``initialize``, ``tools/list`` and ``tools/call``, and exposes the
engine as eight tools.  Diagnostics go to stderr only, never to stdout.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable, Optional

_PLUGIN_ROOT = Path(__file__).resolve().parent
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from scripts import bilibili, documents, engine, pdf, scholar, sitemap  # noqa: E402

SERVER_NAME = "web-forager"
PROTOCOL_VERSION = "2024-11-05"

_TOOLS: list[dict[str, Any]] = [
    {
        "name": "web_fetch",
        "description": "Fetch one URL and return clean Markdown, metadata, tables and optional chunks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 0},
                "chunk_size": {"type": "integer", "minimum": 0},
                "render": {"type": "string", "enum": ["auto", "never", "always"]},
                "include_tables": {"type": "boolean"},
                "cache": {"type": "boolean"},
                "respect_robots": {
                    "type": "boolean",
                    "description": "Check robots.txt before fetching (default true). Set false only for resources you are authorised to read.",
                },
                "input_gate": {
                    "type": "string",
                    "enum": ["off", "mark", "strict"],
                    "description": "Treat fetched text as untrusted: mark instruction-shaped content (default), withhold the body (strict), or skip the scan (off).",
                },
                "fullResults": {
                    "type": "boolean",
                    "description": "Repeat every page record inside results as well as pages (1.0.1 behaviour; doubles the response).",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_search",
        "description": "Search 360/Bing/Sogou/WeChat and optionally fetch the top result pages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "engine": {
                    "type": "string",
                    "enum": ["auto", "all", "360", "bing", "sogou", "weixin", "duckduckgo"],
                },
                "num_results": {"type": "integer", "minimum": 1, "maximum": 50},
                "max_pages": {"type": "integer", "minimum": 0, "maximum": 20},
                "search_pages": {"type": "integer", "minimum": 1, "maximum": 5},
                "respect_robots": {
                    "type": "boolean",
                    "description": "Check robots.txt before fetching a result page (default true). Set false only for resources you are authorised to read.",
                },
                "input_gate": {
                    "type": "string",
                    "enum": ["off", "mark", "strict"],
                    "description": "Treat fetched text as untrusted: mark instruction-shaped content (default), withhold the body (strict), or skip the scan (off).",
                },
                "fullResults": {
                    "type": "boolean",
                    "description": "Repeat every page record inside results as well as pages (1.0.1 behaviour; doubles the response).",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "web_surf",
        "description": "Search or open a page, then follow ranked in-page links like a person browsing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "url": {"type": "string"},
                "depth": {"type": "integer", "minimum": 0, "maximum": 5},
                "max_pages": {"type": "integer", "minimum": 1, "maximum": 50},
                "follow": {"type": "string", "enum": ["same-site", "all", "none"]},
                "session": {"type": "string"},
                "engine": {"type": "string"},
                "respect_robots": {
                    "type": "boolean",
                    "description": "Check robots.txt before fetching a page (default true). Set false only for resources you are authorised to read.",
                },
                "input_gate": {
                    "type": "string",
                    "enum": ["off", "mark", "strict"],
                    "description": "Treat fetched text as untrusted: mark instruction-shaped content (default), withhold the body (strict), or skip the scan (off).",
                },
                "fullResults": {
                    "type": "boolean",
                    "description": "Repeat every page record inside results as well as pages (1.0.1 behaviour; doubles the response).",
                },
            },
        },
    },
    {
        "name": "web_scholar",
        "description": "Query arXiv, Crossref, PubMed or resolve a DOI through public APIs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "source": {"type": "string", "enum": ["arxiv", "crossref", "pubmed", "doi"]},
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 50},
            },
            "required": ["source", "query"],
        },
    },
    {
        "name": "web_map",
        "description": "Discover page URLs from robots.txt Sitemap lines and sitemap XML files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 5000},
            },
            "required": ["url"],
        },
    },
    {
        "name": "web_bilibili",
        "description": "Browse Bilibili public pages: feed, video, related, search or surf.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["feed", "video", "search", "related", "surf"],
                },
                "url": {"type": "string"},
                "query": {"type": "string"},
                "num_results": {"type": "integer", "minimum": 1, "maximum": 50},
                "depth": {"type": "integer", "minimum": 0, "maximum": 5},
            },
        },
    },
    {
        "name": "web_doctor",
        "description": "Report which optional capabilities this installation can serve, with the install command for each missing one.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "probe": {
                    "type": "boolean",
                    "description": "Ask each search engine once and report which ones answer from this network.",
                },
                "proxy": {"type": "string", "description": "Proxy URL to report as configured."},
            },
        },
    },
    {
        "name": "web_find",
        "description": "Search inside one site through the site's own search page, then fetch the best matching pages.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "site": {"type": "string", "description": "Domain or base URL, e.g. the-decoder.com."},
                "query": {"type": "string"},
                "max_pages": {"type": "integer", "minimum": 0, "maximum": 20},
                "respect_robots": {
                    "type": "boolean",
                    "description": "Check robots.txt before fetching (default true).",
                },
                "input_gate": {
                    "type": "string",
                    "enum": ["off", "mark", "strict"],
                    "description": "Treat fetched text as untrusted: mark instruction-shaped content (default), withhold the body (strict), or skip the scan (off).",
                },
                "proxy": {"type": "string"},
                "fullResults": {
                    "type": "boolean",
                    "description": "Repeat every page record inside results as well as pages.",
                },
            },
            "required": ["site", "query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "web_feed",
        "description": "Read a site's RSS/Atom feed, discovering it from the page when given the site URL.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "num_results": {"type": "integer", "minimum": 1, "maximum": 50},
                "respect_robots": {"type": "boolean"},
                "proxy": {"type": "string"},
                "fullResults": {"type": "boolean"},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "web_clean",
        "description": "Clean a local HTML, PDF, DOCX, XLSX, EPUB or CSV file into Markdown.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "base_url": {"type": "string"},
                "include_tables": {"type": "boolean"},
            },
            "required": ["path"],
        },
    },
]

_TOOL_NAMES = {tool["name"] for tool in _TOOLS}


def _full_results(arguments: dict[str, Any]) -> bool:
    """Whether to repeat every page body inside ``results`` as well as ``pages``."""

    return bool(arguments.get("fullResults", False))


def _config(arguments: dict[str, Any]) -> engine.FetchConfig:
    config = engine.FetchConfig(
        max_chars=int(arguments.get("max_chars", 20_000)),
        chunk_size=int(arguments.get("chunk_size", 0)),
        render=str(arguments.get("render", "auto")),
        include_tables=bool(arguments.get("include_tables", True)),
        cache=bool(arguments.get("cache", False)),
        num_results=int(arguments.get("num_results", 8)),
        max_pages=max(1, int(arguments.get("max_pages", 3))),
        search_pages=max(1, int(arguments.get("search_pages", 1))),
        search_engine=str(arguments.get("engine", "auto")),
        follow=str(arguments.get("follow", "same-site")),
        # robots.txt is checked for every fetched page unless the caller turns
        # it off explicitly, which is the same switch the CLI spells
        # --ignore-robots.
        respect_robots=bool(arguments.get("respect_robots", True)),
        proxy=str(arguments.get("proxy", "")),
        input_gate=str(arguments.get("input_gate", "mark")),
        verbose=False,
    )
    config.validate()
    return config


def _tool_fetch(arguments: dict[str, Any]) -> dict[str, Any]:
    config = _config(arguments)
    if not arguments.get("url"):
        raise ValueError("url is required")
    page = engine.fetch_page(str(arguments["url"]), config)
    return engine.build_envelope("fetch", page, full_results=_full_results(arguments))


def _tool_search(arguments: dict[str, Any]) -> dict[str, Any]:
    if not arguments.get("query"):
        raise ValueError("query is required")
    config = _config(arguments)
    query = str(arguments["query"])
    engine_report: list[dict[str, Any]] = []
    results = engine.search(
        query,
        config,
        engine=str(arguments.get("engine", "auto")),
        limit=config.num_results,
        report=engine_report,
    )
    pages: list[dict[str, Any]] = []
    fetch_limit = int(arguments.get("max_pages", 3))
    if fetch_limit > 0:
        fetcher = engine.HttpFetcher(config)
        try:
            for result in results[:fetch_limit]:
                try:
                    pages.append(engine.fetch_page(result["url"], config, fetcher=fetcher))
                except engine.WebForagerError as exc:
                    pages.append({"url": result["url"], "error": f"{exc.__class__.__name__}: {exc}"})
        finally:
            fetcher.close()
    payload: dict[str, Any] = {
        "query": query,
        "engine": str(arguments.get("engine", "auto")),
        "search_results": results,
        "engine_report": engine_report,
        "pages": pages,
    }
    warnings = engine.search_warnings(
        query, results, engine=str(arguments.get("engine", "auto"))
    )
    if warnings:
        payload["warnings"] = warnings
    return engine.build_envelope("fetch", payload, full_results=_full_results(arguments))


def _tool_surf(arguments: dict[str, Any]) -> dict[str, Any]:
    config = _config(arguments)
    seed = arguments.get("url") or arguments.get("query")
    if not seed:
        raise ValueError("url or query is required")
    payload = engine.surf_web(
        str(seed),
        config,
        depth=max(0, int(arguments.get("depth", 1))),
        follow=str(arguments.get("follow", "same-site")),
        max_pages=max(1, int(arguments.get("max_pages", 3))),
        engine_name=str(arguments.get("engine", "auto")),
        session=arguments.get("session") or None,
    )
    if arguments.get("url") and arguments.get("query"):
        payload.setdefault("warnings", []).append(
            "query was ignored because url was given; omit url to surf from a search"
        )
    return engine.build_envelope("surf", payload, full_results=_full_results(arguments))


def _tool_scholar(arguments: dict[str, Any]) -> dict[str, Any]:
    source = str(arguments.get("source", "arxiv"))
    query = str(arguments.get("query", ""))
    config = _config(arguments)
    payload = scholar.search(
        source,
        query,
        config,
        limit=int(arguments.get("limit", config.num_results)),
    )
    return engine.build_envelope("scholar", payload)


def _tool_map(arguments: dict[str, Any]) -> dict[str, Any]:
    config = _config(arguments)
    payload = sitemap.discover(
        str(arguments.get("url", "")),
        config,
        limit=int(arguments.get("limit", 500)),
    )
    return engine.build_envelope("map", payload)


def _tool_bilibili(arguments: dict[str, Any]) -> dict[str, Any]:
    config = _config(arguments)
    mode = str(arguments.get("mode", "auto"))
    url = str(arguments.get("url") or "")
    query = str(arguments.get("query") or "")
    if mode == "auto":
        mode = "search" if query else "video" if url else "feed"
    if mode == "feed":
        payload = bilibili.feed(
            config, limit=config.num_results, enrich=config.max_pages, url=url or bilibili.BILI_HOME
        )
    elif mode == "video":
        payload = {"mode": "video", "videos": [bilibili.fetch_video(url, config)]}
        payload["results"] = payload["videos"]
    elif mode == "search":
        payload = bilibili.search(query, config)
    elif mode == "related":
        payload = bilibili.related(url, config, limit=config.num_results, enrich=config.max_pages)
    elif mode == "surf":
        payload = bilibili.surf(
            url or query,
            config,
            depth=max(0, int(arguments.get("depth", 1))),
            per_level=config.max_pages,
        )
    else:
        raise ValueError(f"unsupported Bilibili mode: {mode}")
    return engine.build_envelope("bili", payload)


def _tool_doctor(arguments: dict[str, Any]) -> dict[str, Any]:
    config = _config(arguments)
    payload = engine.doctor_report(config)
    if arguments.get("probe"):
        payload["search_probe"] = engine.probe_engines(config)
    return engine.build_envelope("doctor", payload)


def _tool_find(arguments: dict[str, Any]) -> dict[str, Any]:
    site = str(arguments.get("site", "")).strip()
    query = str(arguments.get("query", "")).strip()
    if not site:
        raise ValueError("site is required")
    if not query:
        raise ValueError("query is required")
    config = _config(arguments)
    payload = engine.find_within_site(
        site,
        query,
        config,
        max_pages=int(arguments.get("max_pages", config.max_pages)),
    )
    return engine.build_envelope("find", payload, full_results=_full_results(arguments))


def _tool_feed(arguments: dict[str, Any]) -> dict[str, Any]:
    url = str(arguments.get("url", "")).strip()
    if not url:
        raise ValueError("url is required")
    config = _config(arguments)
    payload = engine.discover_feed(url, config)
    payload["results"] = [
        {
            "url": item.get("url", ""),
            "title": item.get("title", ""),
            "published": item.get("published", ""),
        }
        for item in payload.get("items") or []
    ]
    return engine.build_envelope("feed", payload, full_results=_full_results(arguments))


def _tool_clean(arguments: dict[str, Any]) -> dict[str, Any]:
    config = _config(arguments)
    path = Path(str(arguments.get("path", ""))).expanduser()
    if not path.is_file():
        raise ValueError(f"file not found: {path}")
    data = path.read_bytes()
    base_url = str(arguments.get("base_url") or "")
    if pdf.is_pdf(data):
        document = pdf.extract(data)
        markdown = pdf.to_markdown(document, url=base_url)
        metadata = pdf.to_metadata(document, url=base_url)
        tables: list[dict[str, Any]] = []
        kind = "pdf"
    elif (kind := documents.detect(data, url=str(path))) and kind:
        extracted = documents.extract(data, kind, url=str(path))
        markdown = extracted["markdown"]
        metadata = documents.to_metadata(extracted, base_url)
        tables = extracted.get("tables") or []
    else:
        html = engine.decode_bytes(data)
        markdown = engine.html_to_markdown(
            html,
            url=base_url or None,
            include_tables=config.include_tables,
            keep_links=config.keep_links,
        )
        metadata = engine.extract_metadata(html, url=base_url or None)
        tables = engine.extract_tables(html) if config.include_tables else []
        kind = "html"
    if config.max_chars and len(markdown) > config.max_chars:
        markdown = markdown[: config.max_chars].rstrip() + "\n\n<!-- truncated by web-forager -->"
    payload = {
        "source": str(path),
        "content_type": kind,
        "metadata": metadata,
        "tables": tables,
        "markdown": markdown,
        "chunks": engine.chunk_markdown(markdown, config.chunk_size) if config.chunk_size else [],
    }
    return engine.build_envelope("clean", payload)


_DISPATCH: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {
    "web_fetch": _tool_fetch,
    "web_search": _tool_search,
    "web_surf": _tool_surf,
    "web_scholar": _tool_scholar,
    "web_map": _tool_map,
    "web_bilibili": _tool_bilibili,
    "web_doctor": _tool_doctor,
    "web_find": _tool_find,
    "web_feed": _tool_feed,
    "web_clean": _tool_clean,
}


def _result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def handle_request(request: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Handle one JSON-RPC object; return None for notifications."""

    method = request.get("method", "")
    request_id = request.get("id")
    params = request.get("params") or {}

    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": params.get("protocolVersion") or PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": engine.__version__},
            },
        )
    if method in ("notifications/initialized", "initialized", "notifications/cancelled"):
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": _TOOLS})
    if method == "tools/call":
        name = str(params.get("name", ""))
        arguments = params.get("arguments") or {}
        if name not in _TOOL_NAMES:
            return _error(request_id, -32602, f"unknown tool: {name}")
        try:
            payload = _DISPATCH[name](dict(arguments))
            text = json.dumps(payload, ensure_ascii=False, indent=2)
            return _result(
                request_id,
                {"content": [{"type": "text", "text": text}], "isError": False},
            )
        except Exception as exc:  # tool failures are data, not protocol failures
            code = exc.__class__.__name__
            if code == "ProhibitedQuery":
                code = "prohibited_query"
            elif code == "UnsafeAddress":
                code = "unsafe_address"
            text = json.dumps(
                {
                    "ok": False,
                    "error": {"code": code, "message": str(exc)},
                },
                ensure_ascii=False,
            )
            return _result(
                request_id,
                {"content": [{"type": "text", "text": text}], "isError": True},
            )
    return _error(request_id, -32601, f"method not found: {method}")


def _utf8_stream(stream: Any) -> Any:
    """Force UTF-8 on a text stream when the host allows it.

    Windows hosts may launch ``python`` with the ANSI code page (cp1252/cp936)
    as the stdio encoding.  Writing a Chinese title then raises
    ``UnicodeEncodeError`` and kills the server, so the streams are
    reconfigured before the loop starts.  ``serve`` still has an ASCII
    fallback for streams that cannot be reconfigured.
    """

    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return stream
    try:
        reconfigure(encoding="utf-8", errors="strict")
    except (AttributeError, OSError, ValueError):
        return stream
    return stream


def serve(stdin: Any = None, stdout: Any = None) -> int:
    stdin = _utf8_stream(stdin or sys.stdin)
    stdout = _utf8_stream(stdout or sys.stdout)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            response = _error(None, -32700, "parse error")
        else:
            if not isinstance(request, dict):
                response = _error(None, -32600, "invalid request")
            else:
                response = handle_request(request)
        if response is not None:
            try:
                payload = json.dumps(response, ensure_ascii=False)
                stdout.write(payload + "\n")
            except UnicodeEncodeError:
                stdout.write(json.dumps(response, ensure_ascii=True) + "\n")
            stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(serve())
