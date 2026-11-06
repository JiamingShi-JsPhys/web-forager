# Dependency matrix

`web-forager` starts with the standard library plus three runtime packages.
Everything else is optional and degrades with a clear exit code and hint.

| Capability | Package | Licence | Required? | Missing behaviour |
|---|---|---|---|---|
| HTTP, robots, search, surf, cache | `requests` | Apache-2.0 | yes | exit 1 with import error |
| HTML parsing and fallback Markdown | `beautifulsoup4` | MIT | yes | exit 1 with import error |
| Preferred article extraction | `trafilatura` | Apache-2.0 | yes | falls back to BeautifulSoup |
| JavaScript rendering | `playwright` | Apache-2.0 | optional | `--render always` exits 6; `auto` skips with a warning |
| PDF text and metadata | `pypdf` | BSD-3-Clause | optional | PDF input exits 7 with `pip install pypdf` |
| Hardened XML parsing | `defusedxml` | PSF-2.0 | optional | DOCTYPE internal subsets and all ENTITY declarations are rejected anyway |
| DOCX / XLSX / EPUB / CSV | standard library | — | built in | — |
| RSS / Atom / RSS 1.0 | standard library | — | built in | — |
| Sitemap parsing (`.xml`, `.xml.gz`) | standard library | — | built in | — |
| arXiv / Crossref / PubMed / DOI | `requests` only | — | built in | — |
| MCP stdio server | standard library | — | built in | — |

Install the required set:

```bash
pip install -r requirements.txt
```

Enable optional capabilities:

```bash
pip install playwright && playwright install chromium   # JS rendering
pip install pypdf                                       # PDF text
```

No GPL or AGPL package is used. See [`THIRD_PARTY_LICENSES.txt`](../THIRD_PARTY_LICENSES.txt).
