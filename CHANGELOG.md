# Changelog

## 1.0.0 — 2026-11-06

First stable release. web-forager is a complete public-web intelligence layer
for agents and analysts, with a CLI, an MCP server and a bilingual skill contract.

### Added

- **Scholarly APIs**: `--action scholar --source arxiv|crossref|pubmed|doi`
  with normalised records (title, authors, venue, year, DOI, abstract, PDF URL).
- **Office documents**: DOCX, XLSX and EPUB extraction with the standard
  library only; CSV becomes structured tables.
- **Feeds**: RSS 2.0, Atom and RSS 1.0 parsing into a Markdown digest.
- **Sitemap discovery**: `--action map` reads `Sitemap:` lines from robots.txt,
  sitemap indexes and `.xml.gz` files.
- **MCP server**: `mcp_server.py` speaks newline-delimited JSON-RPC 2.0 and
  exposes `web_fetch`, `web_search`, `web_surf`, `web_scholar`, `web_map`,
  `web_bilibili` and `web_clean`; `.mcp.json` wires it into Claude Code.
- **Search pagination**: `--search-pages N` reads several result pages per
  engine (360, Bing, Sogou).
- **Context chunks**: `--chunk-size N` adds heading-aware `chunks` to fetch and
  clean output, so an agent can read long pages section by section.
- **HTTP cache**: `--cache --cache-ttl N --cache-dir DIR` reuses polite GET
  responses; `cached: true` is reported in the record.
- **Playwright controls**: `--wait-for SELECTOR` and `--scroll N` for lazy or
  delayed content.
- **Security**: all XML goes through a DOCTYPE/ENTITY guard that uses
  `defusedxml` when available; Office ZIP containers have entry-count and
  expansion limits.
- **Multi-host adaptation**: `AGENTS.md` is the generic agent contract, with
  matching rule files for Cursor, Windsurf, Cline, Continue, Roo Code and
  GitHub Copilot. `install.py` writes project- or user-scoped rules in one run.
- **Packaging**: root `package.json`, `index.js` and `cordis.patch.yml` cover
  npm and dsh; `commands/fetch.md`, `surf.md`, `scholar.md` and `map.md` expose
  the actions as plugin commands.
- **Bilingual documentation**: `README.md` (English) and `README_zh.md`
  (Chinese) mirror each other section for section, with the same three-method
  installation guide, quick start, requirements, repository tree, test summary,
  limitations, issue rules, trademark notice and licence. All documents are
  emoji-free.
- **Tests**: 115 tests, including installer coverage and host-rule and
  disclaimer checks.

### Fixed

- **Trafilatura cross-document deduplication**: extraction previously ran with
  `deduplicate=True`, whose process-global cache silently removed sentences
  seen on an earlier page. Long agent sessions could lose a page's opening
  paragraph. Deduplication is now disabled across calls.
- Sitemap `<loc>` elements were not mapped to the `url` field.
- RSS/XML payloads no longer trigger the HTML dynamic-rendering heuristic or
  BeautifulSoup's XML warning.

### Changed

- Version 1.0.0 across all platform manifests, `SKILL.md` and the CLI
  User-Agent.
- `install.py --global` appends a marked block to `~/.claude/CLAUDE.md` instead
  of replacing the user's global instructions.
- Documentation presents web-forager as an independent plugin; the `--root`
  output is described as a four-zone workspace without third-party branding.

## 0.2.0 — 2026-11-06

- 360/Bing/Sogou search with automatic merge and dedupe.
- Optional PDF extraction through `pypdf` (exit code 7 when absent).
- `--action surf` with ranked link BFS and resumable `--session`.
- `--agent` OpenCLI-style success/error envelope.

## 0.1.0 — 2026-11-06

- Initial clean-room fetcher: robots.txt, polite rate limiting, HTML → Markdown,
  metadata, tables, optional Playwright and a Bilibili adapter.
- Standalone packaging for Claude Code, Codex, CodeBuddy and DSH, plus
  four-zone `--root` workspace integration.
