"""PDF text extraction for web-forager.

The only third-party dependency here is ``pypdf`` (BSD-3-Clause).  It is an
optional dependency: when it is absent, callers receive a clear
``PdfUnavailable`` error instead of a traceback.
"""

from __future__ import annotations

import io
from typing import Any

PDF_MAGIC = b"%PDF-"


class PdfError(Exception):
    """Base class for PDF failures."""


class PdfUnavailable(PdfError):
    """pypdf is not installed or could not be imported."""


class PdfExtractionError(PdfError):
    """The file is not a readable PDF."""


def is_pdf(data: bytes) -> bool:
    return bool(data) and data[:5] == PDF_MAGIC


def _meta_value(metadata: Any, key: str) -> str:
    try:
        value = metadata.get(key) if metadata else None
    except Exception:
        return ""
    return str(value).strip() if value else ""


def extract(data: bytes) -> dict[str, Any]:
    """Extract text and document metadata from PDF bytes."""

    if not is_pdf(data):
        raise PdfExtractionError("the supplied data is not a PDF (missing %PDF- header)")
    try:
        from pypdf import PdfReader  # type: ignore
    except ImportError as exc:
        raise PdfUnavailable(
            "pypdf is not installed; enable PDF support with: pip install pypdf"
        ) from exc
    except Exception as exc:  # pragma: no cover - broken installation
        raise PdfUnavailable(f"pypdf could not be imported ({exc}); reinstall it with: pip install pypdf") from exc

    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise PdfExtractionError(f"cannot open PDF: {exc}") from exc

    pages: list[str] = []
    empty_pages = 0
    for index, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # a single damaged page should not kill the run
            text = f"[page {index}: extraction failed: {exc}]"
        text = text.strip()
        if not text:
            empty_pages += 1
        pages.append(text)

    metadata = reader.metadata
    return {
        "pages": pages,
        "page_count": len(pages),
        "empty_pages": empty_pages,
        "text": "\n\n".join(pages).strip(),
        "metadata": {
            "title": _meta_value(metadata, "/Title"),
            "author": _meta_value(metadata, "/Author"),
            "subject": _meta_value(metadata, "/Subject"),
            "creator": _meta_value(metadata, "/Creator"),
            "producer": _meta_value(metadata, "/Producer"),
            "creation_date": _meta_value(metadata, "/CreationDate"),
        },
    }


def to_markdown(document: dict[str, Any], url: str = "") -> str:
    metadata = document.get("metadata") or {}
    title = metadata.get("title") or (url.rsplit("/", 1)[-1] if url else "PDF document")
    lines = [f"# {title}", ""]
    info = " ｜ ".join(
        part
        for part in (
            f"作者：{metadata.get('author')}" if metadata.get("author") else "",
            f"页数：{document.get('page_count')}" if document.get("page_count") else "",
            f"来源：{url}" if url else "",
        )
        if part
    )
    if info:
        lines.extend([f"> {info}", ""])
    pages = document.get("pages") or []
    for index, text in enumerate(pages, start=1):
        if not text:
            continue
        if len(pages) > 1:
            lines.extend([f"## 第 {index} 页", ""])
        lines.extend([text, ""])
    return "\n".join(lines).strip()


def to_metadata(document: dict[str, Any], url: str = "") -> dict[str, Any]:
    """Return PDF metadata in the same shape as article metadata."""

    source = document.get("metadata") or {}
    return {
        "title": source.get("title", ""),
        "authors": [source["author"]] if source.get("author") else [],
        "published": source.get("creation_date", ""),
        "modified": "",
        "journal": "",
        "volume": "",
        "issue": "",
        "first_page": "",
        "last_page": "",
        "doi": "",
        "arxiv_id": "",
        "abstract": source.get("subject", ""),
        "keywords": [],
        "language": "",
        "site_name": "PDF",
        "canonical_url": url,
        "og_type": "pdf",
    }
