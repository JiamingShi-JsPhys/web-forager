"""Scholarly metadata through public APIs (arXiv, Crossref, PubMed).

These are documented query APIs, not scraped result pages, so they are both
more stable and more polite than reading a search engine's HTML.  Only the
standard library and ``requests`` (through :mod:`scripts.engine`) are used.
"""

from __future__ import annotations

import html as html_lib
import json
import re
import urllib.parse
import xml.etree.ElementTree as ET
from typing import Any, Optional

from . import engine

SCHOLAR_SOURCES = ("arxiv", "crossref", "pubmed", "doi")

_ARXIV_API = (
    "https://export.arxiv.org/api/query?search_query={search_query}"
    "&start={start}&max_results={limit}&sortBy={sort}&sortOrder=descending"
)
_CROSSREF_API = (
    "https://api.crossref.org/works?query.bibliographic={query}&rows={limit}"
    "&select=DOI,title,author,container-title,issued,published-print,published-online,"
    "abstract,URL,type,subject,ISSN,volume,issue,page"
)
_CROSSREF_DOI = "https://api.crossref.org/works/{doi}"
_PUBMED_SEARCH = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
    "?db=pubmed&term={query}&retmode=json&retmax={limit}&sort=relevance"
)
_PUBMED_SUMMARY = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
    "?db=pubmed&id={ids}&retmode=json"
)
_PUBMED_FETCH = (
    "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
    "?db=pubmed&id={ids}&retmode=xml"
)

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


def _text(node: Optional[ET.Element], path: str = "") -> str:
    target = node.find(path) if node is not None and path else node
    if target is None or target.text is None:
        return ""
    return re.sub(r"\s+", " ", target.text).strip()


def _clean(value: Any) -> str:
    if value is None:
        return ""
    text = html_lib.unescape(str(value))
    if "<" in text:
        text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _date_parts(value: Any) -> str:
    """Return a Crossref ``date-parts`` value as ``YYYY[-MM[-DD]]``.

    Crossref sometimes sends ``[[null]]`` for a record with no date, and may
    send partial arrays.  A missing or non-numeric component ends the chain:
    a month cannot be trusted when the year is absent, and a day cannot be
    trusted when the month is absent.
    """

    if not isinstance(value, dict):
        return ""
    parts = value.get("date-parts")
    if not isinstance(parts, list) or not parts:
        return ""
    first = parts[0]
    if not isinstance(first, list) or not first:
        return ""

    numbers: list[int] = []
    for part in first[:3]:
        try:
            number = int(part)
        except (TypeError, ValueError):
            break
        numbers.append(number)
    if not numbers or numbers[0] <= 0:
        return ""

    text = f"{numbers[0]:04d}"
    if len(numbers) > 1 and 1 <= numbers[1] <= 12:
        text += f"-{numbers[1]:02d}"
        if len(numbers) > 2 and 1 <= numbers[2] <= 31:
            text += f"-{numbers[2]:02d}"
    return text


_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}


def _iso_date(value: Any) -> str:
    """Normalise an ISO-like date to ``YYYY[-MM[-DD]]``."""

    match = re.match(r"^(\d{4})-(\d{1,2})(?:-(\d{1,2}))?", str(value or "").strip())
    if not match:
        return ""
    year = int(match.group(1))
    month = int(match.group(2))
    if not 1 <= month <= 12:
        return f"{year:04d}"
    if match.group(3) is None:
        return f"{year:04d}-{month:02d}"
    day = int(match.group(3))
    if not 1 <= day <= 31:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def _pubmed_date(item: dict[str, Any]) -> str:
    """Normalise a PubMed esummary record's ``pubdate``.

    ``pubdate`` carries the precision the record actually has: ``2024``,
    ``2024 Jan`` or ``2024 Jan 15``.  ``sortpubdate`` is only a fallback and
    its month/day are often placeholders, so the fallback keeps the year only.
    """

    raw = str(item.get("pubdate") or "").strip()
    match = re.match(r"^(\d{4})(?:\s+([A-Za-z]{3,9}))?(?:\s+(\d{1,2}))?", raw)
    if match:
        year = int(match.group(1))
        month = _MONTHS.get((match.group(2) or "").lower())
        if month is None:
            return f"{year:04d}"
        if match.group(3) is None:
            return f"{year:04d}-{month:02d}"
        day = int(match.group(3))
        if 1 <= day <= 31:
            return f"{year:04d}-{month:02d}-{day:02d}"
        return f"{year:04d}-{month:02d}"

    fallback = re.match(r"^(\d{4})/", str(item.get("sortpubdate") or "").strip())
    return f"{int(fallback.group(1)):04d}" if fallback else ""


def _arxiv_search_query(query: str, field: str) -> str:
    """Build an arXiv ``search_query`` value.

    ``all:`` keeps the caller's terms as terms; the field-specific forms quote
    the query so ``ti:Deep Residual Learning`` does not become four independent
    terms.  A caller that already quoted the phrase (the research action does)
    gets exactly one pair of quotes rather than two.
    """

    text = re.sub(r"\s+", " ", query.strip()).strip()
    if field == "all":
        return f"all:{text}"
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    text = re.sub(r"\s+", " ", text.replace('"', " ")).strip()
    if not text:
        raise ValueError("query must contain a search term")
    return f'{field}:"{text}"'


def parse_arxiv(xml_text: str, limit: int = 10) -> list[dict[str, Any]]:
    """Parse an arXiv Atom feed into normalised records."""

    root = engine.parse_xml(xml_text)

    records: list[dict[str, Any]] = []
    for entry in root.findall(f"{_ATOM}entry")[:limit]:
        identifier = _text(entry, f"{_ATOM}id")
        abs_url = identifier
        if abs_url.startswith("http://arxiv.org/"):
            abs_url = "https://" + abs_url[len("http://") :]
        pdf_url = ""
        for link in entry.findall(f"{_ATOM}link"):
            if link.get("title") == "pdf" or link.get("type") == "application/pdf":
                pdf_url = link.get("href", "")
        authors = [
            _text(author, f"{_ATOM}name")
            for author in entry.findall(f"{_ATOM}author")
            if _text(author, f"{_ATOM}name")
        ]
        categories = [
            category.get("term", "")
            for category in entry.findall(f"{_ATOM}category")
            if category.get("term")
        ]
        journal = _text(entry, f"{_ARXIV}journal_ref")
        doi = _text(entry, f"{_ARXIV}doi")
        records.append(
            {
                "source": "arxiv",
                "id": identifier.rsplit("/", 1)[-1],
                "title": _text(entry, f"{_ATOM}title"),
                "authors": authors,
                "published": _iso_date(_text(entry, f"{_ATOM}published")),
                "updated": _iso_date(_text(entry, f"{_ATOM}updated")),
                "journal": journal,
                "volume": "",
                "issue": "",
                "pages": "",
                "doi": doi,
                "url": abs_url,
                "pdf_url": pdf_url,
                "abstract": _text(entry, f"{_ATOM}summary"),
                "type": "preprint",
                "keywords": categories,
            }
        )
    return records


def parse_crossref(payload: Any, limit: int = 10) -> list[dict[str, Any]]:
    """Parse a Crossref ``works`` response (already decoded JSON)."""

    if isinstance(payload, str):
        payload = json.loads(payload)
    message = payload.get("message", payload) if isinstance(payload, dict) else {}
    if not isinstance(message, dict):
        message = {}
    items = message.get("items")
    single_work = False
    if items is None and message.get("DOI"):
        items = [message]
        single_work = True
    if not isinstance(items, list):
        items = []
    if not single_work:
        # A bibliographic search returns figures, tables and supplementary
        # files as type "component".  They are not papers and can fill the
        # whole page budget before the first real article.  A direct DOI
        # lookup keeps its single record even when it is a component.
        items = [
            item
            for item in items
            if isinstance(item, dict) and item.get("type") != "component"
        ]
    records: list[dict[str, Any]] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        authors: list[str] = []
        for author in item.get("author") or []:
            name = author.get("name") or " ".join(
                part for part in (author.get("given"), author.get("family")) if part
            )
            if name:
                authors.append(name)
        titles = item.get("title") or []
        title = titles[0] if isinstance(titles, list) and titles else str(titles or "")
        containers = item.get("container-title") or []
        journal = containers[0] if isinstance(containers, list) and containers else str(containers or "")
        published = (
            _date_parts(item.get("published-print"))
            or _date_parts(item.get("published-online"))
            or _date_parts(item.get("issued"))
        )
        records.append(
            {
                "source": "crossref",
                "id": item.get("DOI", ""),
                "title": _clean(title),
                "authors": authors,
                "published": published,
                "updated": "",
                "journal": _clean(journal),
                "volume": str(item.get("volume", "") or ""),
                "issue": str(item.get("issue", "") or ""),
                "pages": str(item.get("page", "") or ""),
                "doi": item.get("DOI", ""),
                "url": item.get("URL", "") or (
                    f"https://doi.org/{item.get('DOI')}" if item.get("DOI") else ""
                ),
                "pdf_url": "",
                "abstract": _clean(item.get("abstract", "")),
                "type": item.get("type", ""),
                "keywords": [str(value) for value in item.get("subject") or []],
            }
        )
    return records


def parse_pubmed(
    search_payload: Any,
    summary_payload: Any,
    abstracts: Optional[dict[str, str]] = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Merge PubMed esearch + esummary (+ optional efetch abstracts)."""

    if isinstance(search_payload, str):
        search_payload = json.loads(search_payload)
    if isinstance(summary_payload, str):
        summary_payload = json.loads(summary_payload)
    abstracts = abstracts or {}

    ids = (search_payload.get("esearchresult", {}) or {}).get("idlist", [])[:limit]
    result = summary_payload.get("result", {}) or {}
    records: list[dict[str, Any]] = []
    for uid in ids:
        item = result.get(uid) or {}
        doi = ""
        for article_id in item.get("articleids") or []:
            if article_id.get("idtype") == "doi":
                doi = article_id.get("value", "")
                break
        records.append(
            {
                "source": "pubmed",
                "id": uid,
                "title": _clean(item.get("title", "")),
                "authors": [
                    author.get("name", "")
                    for author in item.get("authors") or []
                    if author.get("name")
                ],
                "published": _pubmed_date(item),
                "updated": "",
                "journal": str(item.get("fulljournalname") or item.get("source") or ""),
                "volume": str(item.get("volume", "") or ""),
                "issue": str(item.get("issue", "") or ""),
                "pages": str(item.get("pages", "") or ""),
                "doi": doi,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{uid}/",
                "pdf_url": "",
                "abstract": abstracts.get(uid, ""),
                "type": "journal-article",
                "keywords": [],
            }
        )
    return records


def _pubmed_abstracts(xml_text: str) -> dict[str, str]:
    """Map PMID → abstract from an efetch XML response."""

    try:
        root = engine.parse_xml(xml_text)
    except engine.FetchError:
        return {}
    abstracts: dict[str, str] = {}
    for article in root.findall(".//PubmedArticle"):
        pmid = _text(article, ".//PMID")
        parts = [
            _clean(node.text)
            for node in article.findall(".//Abstract/AbstractText")
            if node.text
        ]
        if pmid and parts:
            abstracts[pmid] = " ".join(part for part in parts if part)
    return abstracts


def _query_fetch(fetcher: engine.HttpFetcher, url: str) -> engine.HttpResponse:
    """Fetch a scholarly query endpoint under the user-level query policy."""

    config = fetcher.config
    return fetcher.fetch(
        url,
        check_robots=config.query_robots != "ignore",
        robots_policy=config.query_robots,
    )


def _fetch_json(fetcher: engine.HttpFetcher, url: str) -> Any:
    response = _query_fetch(fetcher, url)
    try:
        return json.loads(response.text)
    except json.JSONDecodeError as exc:
        raise engine.FetchError(f"invalid JSON from {url}: {exc}") from exc


def search(
    source: str,
    query: str,
    config: Optional[engine.FetchConfig] = None,
    limit: Optional[int] = None,
    fetcher: Optional[engine.HttpFetcher] = None,
    sort: str = "relevance",
    field: str = "all",
) -> dict[str, Any]:
    """Query one scholarly source and return normalised records.

    ``field`` is the arXiv query field (``all``, ``ti``, ``au`` or ``abs``) and
    is ignored by the other sources.  ``ti`` is useful when the caller already
    has a paper title: it avoids the broad ``all`` search returning a different
    paper that merely shares a phrase.
    """

    source = (source or "arxiv").lower()
    if source not in SCHOLAR_SOURCES:
        raise ValueError(f"unsupported scholarly source: {source}")
    query = (query or "").strip()
    if not query:
        raise ValueError("query must not be empty")

    config = config or engine.FetchConfig()
    limit = max(1, min(limit or config.num_results or 10, 50))
    own_fetcher = fetcher is None
    fetcher = fetcher or engine.HttpFetcher(config)

    try:
        if source == "arxiv":
            if sort not in ("relevance", "submittedDate", "lastUpdatedDate"):
                raise ValueError("arXiv sort must be relevance, submittedDate or lastUpdatedDate")
            if field not in ("all", "ti", "au", "abs"):
                raise ValueError("arXiv field must be all, ti, au or abs")
            search_query = _arxiv_search_query(query, field)
            url = _ARXIV_API.format(
                search_query=urllib.parse.quote_plus(search_query),
                start=0,
                limit=limit,
                sort=sort,
            )
            response = _query_fetch(fetcher, url)
            records = parse_arxiv(response.text, limit=limit)
        elif source == "crossref":
            url = _CROSSREF_API.format(query=urllib.parse.quote_plus(query), limit=limit)
            records = parse_crossref(_fetch_json(fetcher, url), limit=limit)
        elif source == "doi":
            doi = query
            if doi.lower().startswith("https://doi.org/"):
                doi = doi[len("https://doi.org/"):]
            elif doi.lower().startswith("doi:"):
                doi = doi[4:]
            url = _CROSSREF_DOI.format(doi=urllib.parse.quote(doi, safe="/"))
            try:
                payload = _fetch_json(fetcher, url)
            except engine.FetchError as exc:
                if exc.status == 404:
                    raise engine.NotFoundError(
                        f"DOI not found: {doi} is not registered with Crossref"
                    ) from exc
                raise
            records = parse_crossref(payload, limit=1)
        else:  # pubmed
            search_url = _PUBMED_SEARCH.format(
                query=urllib.parse.quote_plus(query), limit=limit
            )
            search_payload = _fetch_json(fetcher, search_url)
            ids = (search_payload.get("esearchresult", {}) or {}).get("idlist", [])[:limit]
            if not ids:
                records = []
            else:
                summary_url = _PUBMED_SUMMARY.format(ids=",".join(ids))
                summary_payload = _fetch_json(fetcher, summary_url)
                abstracts: dict[str, str] = {}
                try:
                    fetch_url = _PUBMED_FETCH.format(ids=",".join(ids))
                    abstracts = _pubmed_abstracts(_query_fetch(fetcher, fetch_url).text)
                except engine.FetchError:
                    abstracts = {}
                records = parse_pubmed(search_payload, summary_payload, abstracts, limit=limit)

        return {
            "source": source,
            "query": query,
            "query_robots": config.query_robots,
            "count": len(records),
            "results": records,
        }
    finally:
        if own_fetcher:
            fetcher.close()


def to_markdown(payload: dict[str, Any]) -> str:
    """Render scholarly records as a compact Markdown bibliography."""

    lines = [
        f"# {payload.get('source', 'scholar')}: {payload.get('query', '')}",
        "",
        f"> {payload.get('count', 0)} record(s)",
        "",
    ]
    for index, record in enumerate(payload.get("results") or [], start=1):
        title = record.get("title") or record.get("id") or "Untitled"
        lines.append(f"## {index}. {title}")
        if record.get("authors"):
            lines.append(f"**Authors:** {', '.join(record['authors'])}")
        if record.get("published"):
            lines.append(f"**Published:** {record['published']}")
        if record.get("journal"):
            volume_issue = " ".join(
                part for part in (record.get("volume"), record.get("issue")) if part
            )
            lines.append(f"**Journal:** {record['journal']}" + (f" {volume_issue}" if volume_issue else ""))
        if record.get("doi"):
            lines.append(f"**DOI:** {record['doi']}")
        if record.get("url"):
            lines.append(f"**URL:** {record['url']}")
        if record.get("pdf_url"):
            lines.append(f"**PDF:** {record['pdf_url']}")
        if record.get("abstract"):
            lines.extend(["", record["abstract"]])
        lines.append("")
    return "\n".join(lines).strip()
