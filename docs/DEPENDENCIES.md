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
| MCP stdio server (HTTP) | standard library | — | built in | — |
| Browser mode CLI and MCP | Node.js >= 18, standard library only | — | optional | browser runs exit 3 without a bridge |
| Browser bridge (reference) | `playwright` (npm) | Apache-2.0 | optional | bridge exits 3 with an install hint |

Install the required set:

```bash
pip install -r requirements.txt
```

Enable optional capabilities:

```bash
pip install playwright && playwright install chromium   # JS rendering
pip install pypdf                                       # PDF text
```

Browser mode needs Node.js 18 or newer and a bridge command in
`WEB_FORAGER_BRIDGE`. The reference bridge in `browser/bridges/` additionally
needs `npm install playwright`; the core browser CLI and MCP server use only the
Node standard library.

No GPL or AGPL package is used. See [`THIRD_PARTY_LICENSES.txt`](../THIRD_PARTY_LICENSES.txt).
