"""Office-document and ebook extraction without extra dependencies.

DOCX, XLSX and EPUB are ZIP containers with XML inside, so the standard
library is enough.  XML is parsed through :func:`engine.parse_xml` (defused
when available, DOCTYPE/ENTITY rejected otherwise), and archive expansion is
capped to avoid zip bombs.
"""

from __future__ import annotations

import csv
import io
import re
import zipfile
from typing import Any

from . import engine

ZIP_MAGIC = b"PK\x03\x04"
_MAX_ENTRIES = 5_000
_MAX_UNCOMPRESSED = 64 * 1024 * 1024
_MAX_ENTRY = 24 * 1024 * 1024

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_S = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_DC = "{http://purl.org/dc/elements/1.1/}"
_CONTAINER = "{urn:oasis:names:tc:opendocument:xmlns:container}"
_OPF = "{http://www.idpf.org/2007/opf}"

CONTENT_TYPES = {
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/epub+zip": "epub",
    "text/csv": "csv",
    "application/csv": "csv",
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _open_zip(data: bytes) -> zipfile.ZipFile:
    archive = zipfile.ZipFile(io.BytesIO(data))
    infos = archive.infolist()
    if len(infos) > _MAX_ENTRIES:
        raise engine.ExtractionError("archive contains too many entries")
    if sum(info.file_size for info in infos) > _MAX_UNCOMPRESSED:
        raise engine.ExtractionError("archive expands beyond the safety limit")
    return archive


def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    info = archive.getinfo(name)
    if info.file_size > _MAX_ENTRY:
        raise engine.ExtractionError(f"archive member too large: {name}")
    return archive.read(name)


def detect(data: bytes, content_type: str = "", url: str = "") -> str:
    """Return docx/xlsx/epub/csv, or '' when the payload is not one of them."""

    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if ctype in CONTENT_TYPES:
        return CONTENT_TYPES[ctype]
    lowered = (url or "").lower().split("?", 1)[0]
    if lowered.endswith(".csv"):
        return "csv"
    if data[:4] != ZIP_MAGIC:
        return ""
    try:
        with _open_zip(data) as archive:
            names = set(archive.namelist())
            if "word/document.xml" in names:
                return "docx"
            if "xl/workbook.xml" in names:
                return "xlsx"
            if "META-INF/container.xml" in names:
                return "epub"
    except (zipfile.BadZipFile, engine.ExtractionError, KeyError):
        return ""
    return ""


# ---------------------------------------------------------------------------
# DOCX
# ---------------------------------------------------------------------------


def _docx_paragraph(node: Any) -> str:
    pieces: list[str] = []
    for text in node.iter(f"{_W}t"):
        pieces.append(text.text or "")
    for tab in node.iter(f"{_W}tab"):
        pieces.append("\t")
    for br in node.iter(f"{_W}br"):
        pieces.append("\n")
    return "".join(pieces).strip()


def _docx_style(node: Any) -> str:
    style = node.find(f"{_W}pPr/{_W}pStyle")
    if style is not None:
        return style.get(f"{_W}val", "") or ""
    return ""


def _docx_table(node: Any) -> dict[str, Any]:
    rows: list[list[str]] = []
    for row in node.findall(f"{_W}tr"):
        cells = []
        for cell in row.findall(f"{_W}tc"):
            text = " ".join(
                _docx_paragraph(paragraph)
                for paragraph in cell.findall(f"{_W}p")
                if _docx_paragraph(paragraph)
            )
            cells.append(text)
        if cells:
            rows.append(cells)
    return {"caption": "", "headers": rows[0] if rows else [], "rows": rows[1:] if rows else []}


def _table_markdown(table: dict[str, Any]) -> str:
    headers = [str(value) for value in table.get("headers") or []]
    rows = [[str(value) for value in row] for row in table.get("rows") or []]
    width = max([len(headers)] + [len(row) for row in rows]) if headers or rows else 0
    if not width:
        return ""
    headers += [""] * (width - len(headers))
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * width) + " |"]
    for row in rows:
        row += [""] * (width - len(row))
        lines.append("| " + " | ".join(cell.replace("|", "\\|") for cell in row) + " |")
    return "\n".join(lines)


def extract_docx(data: bytes) -> dict[str, Any]:
    with _open_zip(data) as archive:
        document = engine.parse_xml(_read_member(archive, "word/document.xml").decode("utf-8", "replace"))
        metadata: dict[str, str] = {}
        if "docProps/core.xml" in archive.namelist():
            core = engine.parse_xml(_read_member(archive, "docProps/core.xml").decode("utf-8", "replace"))
            metadata = {
                "title": _clean((core.findtext(f"{_DC}title") or "")),
                "creator": _clean((core.findtext(f"{_DC}creator") or "")),
                "subject": _clean((core.findtext(f"{_DC}subject") or "")),
                "created": _clean((core.findtext(f"{_DC}created") or "")),
            }

    body = document.find(f"{_W}body")
    blocks: list[str] = []
    tables: list[dict[str, Any]] = []
    if body is not None:
        for child in body:
            if child.tag == f"{_W}p":
                text = _docx_paragraph(child)
                if not text:
                    continue
                style = _docx_style(child)
                match = re.search(r"Heading\s*(\d)", style, re.I)
                if match:
                    blocks.append("#" * min(int(match.group(1)), 6) + " " + text)
                elif style.lower() in ("title",):
                    blocks.append("# " + text)
                elif style.lower() in ("subtitle",):
                    blocks.append("## " + text)
                elif child.find(f".//{_W}numPr") is not None:
                    blocks.append("- " + text)
                else:
                    blocks.append(text)
            elif child.tag == f"{_W}tbl":
                table = _docx_table(child)
                if table["headers"] or table["rows"]:
                    tables.append(table)
                    blocks.append(_table_markdown(table))

    markdown = "\n\n".join(blocks).strip()
    if not markdown:
        raise engine.ExtractionError("DOCX contains no readable text")
    title = metadata.get("title") or (blocks[0].lstrip("# ").strip() if blocks else "")
    return {
        "kind": "docx",
        "title": title,
        "markdown": markdown,
        "tables": tables,
        "metadata": {
            "title": title,
            "authors": [metadata["creator"]] if metadata.get("creator") else [],
            "published": metadata.get("created", ""),
            "abstract": metadata.get("subject", ""),
            "site_name": "DOCX",
        },
    }


# ---------------------------------------------------------------------------
# XLSX
# ---------------------------------------------------------------------------


def _column_index(reference: str) -> int:
    letters = re.match(r"([A-Z]+)", reference.upper())
    if not letters:
        return 0
    index = 0
    for letter in letters.group(1):
        index = index * 26 + (ord(letter) - 64)
    return max(0, index - 1)


def extract_xlsx(data: bytes, max_rows: int = 500, max_columns: int = 40) -> dict[str, Any]:
    with _open_zip(data) as archive:
        names = set(archive.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = engine.parse_xml(_read_member(archive, "xl/sharedStrings.xml").decode("utf-8", "replace"))
            for item in root.findall(f"{_S}si"):
                shared.append("".join(node.text or "" for node in item.iter(f"{_S}t")))

        workbook = engine.parse_xml(_read_member(archive, "xl/workbook.xml").decode("utf-8", "replace"))
        rels: dict[str, str] = {}
        if "xl/_rels/workbook.xml.rels" in names:
            rel_root = engine.parse_xml(
                _read_member(archive, "xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
            )
            for rel in rel_root.findall(f"{_PKG_REL}Relationship"):
                rels[rel.get("Id", "")] = rel.get("Target", "")

        sheets: list[dict[str, Any]] = []
        for sheet in workbook.findall(f"{_S}sheets/{_S}sheet"):
            name = sheet.get("name", "Sheet")
            target = rels.get(sheet.get(f"{_R}id", ""), "")
            target = target.lstrip("/")
            if not target.startswith("xl/"):
                target = "xl/" + target
            if target not in names:
                continue
            root = engine.parse_xml(_read_member(archive, target).decode("utf-8", "replace"))

            grid: list[list[str]] = []
            for row_index, row in enumerate(root.findall(f".//{_S}sheetData/{_S}row")):
                if row_index >= max_rows:
                    break
                cells: dict[int, str] = {}
                for cell in row.findall(f"{_S}c"):
                    reference = cell.get("r", "")
                    col = _column_index(reference)
                    if col >= max_columns:
                        continue
                    kind = cell.get("t", "")
                    if kind == "inlineStr":
                        value = "".join(node.text or "" for node in cell.iter(f"{_S}t"))
                    else:
                        raw = cell.findtext(f"{_S}v") or ""
                        if kind == "s":
                            try:
                                value = shared[int(raw)]
                            except (ValueError, IndexError):
                                value = ""
                        elif kind == "b":
                            value = "TRUE" if raw == "1" else "FALSE"
                        else:
                            value = raw
                    cells[col] = _clean(value)
                if cells:
                    width = max(cells) + 1
                    grid.append([cells.get(index, "") for index in range(width)])

            if not grid:
                continue
            width = max(len(row) for row in grid)
            grid = [row + [""] * (width - len(row)) for row in grid]
            table = {"caption": name, "headers": grid[0], "rows": grid[1:]}
            sheets.append({"name": name, "table": table})

    if not sheets:
        raise engine.ExtractionError("XLSX contains no readable cells")

    blocks: list[str] = []
    tables: list[dict[str, Any]] = []
    for sheet in sheets:
        table = sheet["table"]
        tables.append(table)
        blocks.append(f"## {sheet['name']}\n\n{_table_markdown(table)}")
    return {
        "kind": "xlsx",
        "title": sheets[0]["name"],
        "markdown": "\n\n".join(blocks).strip(),
        "tables": tables,
        "metadata": {"title": sheets[0]["name"], "site_name": "XLSX"},
    }


# ---------------------------------------------------------------------------
# EPUB
# ---------------------------------------------------------------------------


def extract_epub(data: bytes) -> dict[str, Any]:
    with _open_zip(data) as archive:
        names = set(archive.namelist())
        container = engine.parse_xml(
            _read_member(archive, "META-INF/container.xml").decode("utf-8", "replace")
        )
        rootfile = container.find(f".//{_CONTAINER}rootfile")
        opf_path = rootfile.get("full-path", "") if rootfile is not None else ""
        if not opf_path or opf_path not in names:
            raise engine.ExtractionError("EPUB container does not point to a readable OPF file")
        opf = engine.parse_xml(_read_member(archive, opf_path).decode("utf-8", "replace"))
        base = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""

        metadata_node = opf.find(f"{_OPF}metadata")
        title = ""
        creators: list[str] = []
        if metadata_node is not None:
            title = _clean(metadata_node.findtext(f"{_DC}title") or "")
            creators = [
                _clean(node.text)
                for node in metadata_node.findall(f"{_DC}creator")
                if _clean(node.text)
            ]

        manifest: dict[str, str] = {}
        for item in opf.findall(f"{_OPF}manifest/{_OPF}item"):
            manifest[item.get("id", "")] = item.get("href", "")
        spine = [
            manifest.get(item.get("idref", ""), "")
            for item in opf.findall(f"{_OPF}spine/{_OPF}itemref")
        ]

        from . import engine as engine_mod  # lazy: avoids an import cycle at load time

        chapters: list[str] = []
        for href in spine:
            if not href:
                continue
            member = base + href
            if member not in names:
                continue
            raw = _read_member(archive, member)
            html = engine_mod.decode_bytes(raw, "application/xhtml+xml")
            soup = engine_mod.make_soup(html)
            heading_node = soup.find(["h1", "h2"])
            heading = _clean(heading_node.get_text(" ", strip=True)) if heading_node else ""
            if heading_node is not None:
                heading_node.decompose()
            chapter = engine_mod.html_to_markdown(
                str(soup), url=member, include_tables=True, keep_links=False, include_images=False
            ).strip()
            if heading:
                chapter = f"# {heading}\n\n{chapter}" if chapter else f"# {heading}"
            if chapter:
                chapters.append(chapter)

    if not chapters:
        raise engine.ExtractionError("EPUB contains no readable chapters")
    markdown = "\n\n---\n\n".join(chapters)
    return {
        "kind": "epub",
        "title": title or (chapters[0].splitlines()[0].lstrip("# ").strip() if chapters else ""),
        "markdown": markdown,
        "tables": [],
        "metadata": {
            "title": title,
            "authors": creators,
            "site_name": "EPUB",
        },
    }


# ---------------------------------------------------------------------------
# CSV
# ---------------------------------------------------------------------------


def extract_csv(data: bytes, content_type: str = "", max_rows: int = 1000) -> dict[str, Any]:
    text = engine.decode_bytes(data, content_type or "text/csv")
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    rows = [row for row in csv.reader(io.StringIO(text), dialect)]
    rows = [[_clean(cell) for cell in row] for row in rows[: max_rows + 1] if row]
    if not rows:
        raise engine.ExtractionError("CSV contains no rows")
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    table = {"caption": "", "headers": rows[0], "rows": rows[1:]}
    return {
        "kind": "csv",
        "title": "CSV table",
        "markdown": _table_markdown(table),
        "tables": [table],
        "metadata": {"title": "CSV table", "site_name": "CSV", "rows": len(rows) - 1},
    }


def extract(data: bytes, kind: str = "", content_type: str = "", url: str = "") -> dict[str, Any]:
    kind = kind or detect(data, content_type, url)
    if kind == "docx":
        return extract_docx(data)
    if kind == "xlsx":
        return extract_xlsx(data)
    if kind == "epub":
        return extract_epub(data)
    if kind == "csv":
        return extract_csv(data, content_type)
    raise engine.ExtractionError(f"unsupported document kind: {kind or 'unknown'}")


def to_metadata(document: dict[str, Any], url: str = "") -> dict[str, Any]:
    """Return document metadata in the same shape as article metadata."""

    source: dict[str, Any] = document.get("metadata") or {}
    return {
        "title": source.get("title", ""),
        "authors": source.get("authors") or [],
        "published": source.get("published", ""),
        "modified": "",
        "journal": "",
        "volume": "",
        "issue": "",
        "first_page": "",
        "last_page": "",
        "doi": "",
        "arxiv_id": "",
        "abstract": source.get("abstract", ""),
        "keywords": [],
        "language": "",
        "site_name": source.get("site_name", document.get("kind", "")),
        "canonical_url": url,
        "og_type": document.get("kind", ""),
    }
