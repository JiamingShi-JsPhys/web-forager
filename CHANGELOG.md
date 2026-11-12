# Changelog

## 1.2.2 — 2026-11-15

A hardening release that replaces the 1.2.2 build published on 2026-11-12: a request can no longer be aimed at the machine or the LAN, browser state stays in a profile of its own, and fetched text is labelled as third-party data. The legal-notice rewrite and packaging rules from that earlier build are included.

### Security

- **Private-address guard (SSRF).** Loopback, RFC 1918, link-local (including `169.254.169.254`), CGNAT, multicast, reserved and their IPv6 forms are refused before a socket opens. The host is resolved and checked as written, so decimal IPv4 spellings and IPv6-mapped IPv4 are caught too. The check runs before the request, on every redirect hop (redirects are followed one hop at a time instead of by `requests`), on the robots.txt download, on search-result resolution, and on the URL a rendered page actually lands on. `--allow-private` / `WEB_FORAGER_ALLOW_PRIVATE=1` is the documented opt-out for local fixtures and trusted intranet targets.
- **Browser navigation is guarded too.** `guardedGoto` checks the requested and the final URL, and the bundled Playwright bridge installs a request filter: every document and subresource the page asks for is resolved, and private targets are aborted. A hostile page can no longer use the open browser to probe `http://127.0.0.1:…` or a cloud metadata endpoint.
- **Browser state stays in its own profile.** The bundled bridge already kept `~/.web-forager/browser/profile`; the report now states `dedicated_profile` and `shared_browser`, and a CDP attach to a browser you use for everything else adds a warning that every cookie and login in that profile is reachable by the pages a playbook opens.
- **Fetched text is marked as data.** Every record carries `trust: "untrusted"`. A small scanner (same rules in `scripts/untrusted.py` and `browser/lib/untrusted.js`) names instruction-shaped passages — overrides, fake system tags, `curl … | sh`, secret-exfiltration requests, role swaps — in `injection_flags`, and puts one warning first in the list. `--input-gate strict` withholds the body instead of handing it on; `--input-gate off` skips the scan.
- **Cookies never enter a record.** The Bilibili cookie is held in memory for the API request and is not written to the record, the session file or an error message; the browser profile directory is reported as a flag, not a path.

### Documentation

- **Both READMEs were reorganised around a first visit.** The page now opens with what the tool is, what you get and what it refuses, followed by a table of contents, the why section, the three install methods and a quick start split by entry point — chat, terminal, MCP and the optional browser mode — with a "which action do I need" table and copy-paste commands. The first screen carries a one-line notice that links to the full legal terms; the terms themselves moved below the quick start, section by section.
- **Quick start now holds only the three entry points**: chat, terminal and MCP. The browser playbook table, switches and `--strict-robots` details, and "when the engines are blocked" routes moved to the reference; each is a one-sentence pointer on the landing page. Installation opens with "let your AI install it" as the recommended path for most readers, followed by the plugin-marketplace URL and the per-host commands. The contents is grouped, with acknowledgements, trademarks and licence added.
- **Reference material moved to `docs/REFERENCE.md` and `docs/REFERENCE_zh.md`**: the full action list and exit-code tables, record fields and `core-1`, workspace output, MCP tool names and protocol checks, requirements, repository layout, test details and extra CLI examples. Every example is its own one-line block, so it can be copied or run without trimming its neighbours. README keeps a three-table quick start, a short exit-code summary and a link.
- **Long sections fold.** The repository tree, test coverage notes and MCP tool names sit in `<details>` blocks; known limitations are grouped into read-first, edge cases and experimental/high-risk switches.
- Both READMEs gain a **Security boundaries** section and three limitation bullets (the guard's off switch, the screen's limits, the CDP profile exposure).
- `AGENTS.md`, `SKILL.md` and the six host rule files state that fetched text is data and must not be executed as instructions.
- **The README pair carries a six-part legal notice** — purpose, prohibited use, responsibility, no warranty, limitation of liability, redistribution. `SKILL.md`, `AGENTS.md` and the six host rule files carry the short version.
- **Test fixtures are no longer part of a published archive.** `.gitattributes` marks `tests/` and `browser/tests/` as `export-ignore`, and both npm manifests drop tests from `files`; CI still runs them from the repository clone.

### Tests

- **228 Python tests** and **75 browser tests**, all offline. New coverage: every private range, a redirect into a metadata endpoint, a two-hop redirect chain, the robots download, the CLI exit code and `--allow-private`, marker detection, strict withholding, and the browser-side guard and scanner.

## 1.2.1 — 2026-11-11

A search hygiene release: a Chinese query no longer collects dictionary pages for one of its characters, and the README pair was rewritten around what the tool does now.

### Fixed

- **A mostly-CJK query is no longer handed to Bing as a fallback.** Bing splits a Chinese phrase into single characters, so a search about 反逆向工程 came back with the dictionary page of 反 once the Chinese engines answered thinly. `auto` now stops after 360, Sogou and 搜狗微信; `--engine bing` still asks Bing explicitly.
- **Dictionary pages that match one character of the query are dropped**, whatever engine returned them. `looks_like_character_page()` recognises a title that shares exactly one character with a longer query and carries a dictionary marker (百科, 拼音, 笔顺, 部首, 组词…), so a result list is not padded with them and `engine_report` counts only usable hits.

### Documentation

- **Both READMEs were rewritten.** The duplicated mode paragraphs and the second disclaimer block are gone; scope and compliance sit in one section, the two modes face each other in one table, and the CJK search routing, `find`/`feed`, CI and current tool/test counts are stated once. README text now matches the 10 HTTP tools, 4 browser tools and 9 CLI actions that actually ship.

### Tests

- **174 Python tests** and **60 browser tests**, all offline. New coverage: a CJK query never calls Bing, a character page is dropped from an engine's results, and `looks_like_character_page()` leaves a single-character query and a full-phrase hit alone.

## 1.2.0 — 2026-11-09

Search is no longer the only way in. A site's own search page and its feed are
first-class routes now, every engine attempt is reported, and one run can be
sent through a proxy.

### Added

- **`--action find` (`web_find`)**: search inside one site through the site's
  own search page. It tries `/?s=`, `/search?q=`, `/?search=` and
  `/search?query=`, ranks the page's links by query coverage, and fetches the
  best ones. This is the route that keeps working when the general engines
  answer with dictionary pages or a verification wall.
- **`--action feed` (`web_feed`)**: read a site's RSS/Atom feed, discovering it
  from `<link rel=alternate>` when given the site URL instead of the feed URL.
- **`engine_report`**: every search response now carries one entry per engine
  tried — `ok`, `results`, `ms`, and `error` when it failed, plus `fallback`
  when the engine was asked only because the first answer was thin. "Search is
  broken" becomes "Bing answered, Sogou showed a verification page".
- **`doctor --probe` (`web_doctor {probe: true}`)**: asks 360, Bing, Sogou, the
  WeChat index and DuckDuckGo once each and reports which ones answer from this
  network, with latency.
- **`--proxy URL`** and `proxy` on the MCP tools. Requests already honoured
  `HTTPS_PROXY` / `ALL_PROXY`; an explicit proxy now overrides them for one run,
  and `doctor` reports the proxy in use with credentials redacted.

### Changed

- The MCP server exposes ten HTTP tools instead of eight; the README and
  `SKILL.md` document the two routes that do not depend on a search engine.
- `doctor` reports the proxy source (`config` or `env:NAME`) without printing a
  password.

### Documentation

- **The disclaimer forbids building a profile of an identifiable person.**
  Collecting, aggregating or inferring personal information, or using it for
  doxxing, harassment or stalking, is prohibited and is the user's own legal
  responsibility. It appears in `--help`, `manifest.json`, the README pair,
  `SKILL.md` and every host rule file.
- **The per-host install commands moved to `docs/INSTALL_COMMANDS.md` and
  `docs/INSTALL_COMMANDS_zh.md`.** Methods 1 and 3 stay in the README because
  they are three lines each; Method 2, which is a page of commands, is one link.
- **The READMEs gained an Acknowledgements section** listing the reporter of
  issue #1 by name, with a link to `docs/ACKNOWLEDGEMENTS.md` /
  `docs/ACKNOWLEDGEMENTS_zh.md` for the details.

### Acknowledgements

- **NotFatJustRound** ([issue #1](https://github.com/JiamingShi-JsPhys/web-forager/issues/1))
  reported that `web_search` returned every page body twice — once in `pages`,
  once in `results` — which doubled the response and pushed the tail past an
  agent's size limit; the compact `results` index in 1.0.2 came from that report.

### Fixed

- **Links inside `<article><header>` are no longer skipped.** A results page
  commonly wraps each card's title in an article header; the universal
  "skip `<header>`" rule silently dropped exactly the links a search page
  offers. Page-level headers and navigations are still skipped.
- `doctor --probe` makes one attempt per engine instead of retrying, so a
  blocking engine costs one timeout rather than three.
- `.cursor/rules/web-forager.mdc` carried `v1.0.0` in its front matter, so
  `install.py --only cursor` wrote a stale label; it now follows the release
  version.

### Tests

- **172 Python tests** and **60 browser tests**, all offline. The new suite
  covers site search against a local WordPress-style page, feed discovery from a
  page link and from a direct feed, the per-engine report, the probe, proxy
  wiring and the redaction of proxy credentials.

## 1.1.0 — 2026-11-08

Browser mode joins web-forager, and an audit pass follows it. The HTTP toolkit
and the browser layer ship as **one plugin, one name and one version**; the
former standalone `web-actor` product no longer exists. The empty-result path,
the bridge's capability claims, the robots.txt audit trail and the shared record
shape are now honest, and neither README claims coverage the code does not have.

### Added

- **Browser mode** under `browser/`: a CLI, seven read-only playbooks and an MCP
  server that drive a real browser through a pluggable bridge.
- **Playbooks**: `bili-feed`, `bili-video`, `bili-chain`, `bili-danmaku`,
  `zhihu-dig`, `xhs-dig` and `search-dig`.
- **Second MCP server**: `browser/mcp_server.js` exposes `browser_list`,
  `browser_run`, `browser_session` and `browser_doctor`; `.mcp.json`
  registers both servers.
- **A reference bridge that is found automatically**:
  `browser/bridges/playwright-bridge.js` supports a fresh browser, a persistent
  profile, a headful window and attaching over CDP. `browser/lib/bridge.js`
  looks for `--bridge`, then `WEB_FORAGER_BRIDGE`, then that file, so a first
  run no longer fails with `backend_unavailable` only because nobody exported a
  variable.
- **A browser profile that persists by default**:
  `~/.web-forager/browser/profile` keeps cookies and logins between runs;
  `WEB_FORAGER_BROWSER_PROFILE=off` restores the throwaway browser. The
  reference bridge also drops the automation banner flag.
- **Browser records**: the same `metadata / markdown / tables / warnings` shape,
  written to `<WS>/process/web-forager/browser/` and `_broadcast/`.
- **`/browse` command** for the browser playbooks.
- **Shared record core (`core-1`)**: `--core` on both CLIs and `core: true` on
  `browser_run` return `schema_version / source / mode / url / title /
  collected_at / metadata / markdown / tables / warnings / extra`, so a mixed
  list of HTTP and browser records can be read uniformly. The same fold is
  available as `engine.normalize_record()` and `normalizeRecord()`.
- **Browser robots auditing**: `--strict-robots` reads `robots.txt` before every
  navigation and stops with `robots_denied` (exit 3) on a disallowed path.
  Without it the record still states `compliance.robots_checked: false`, so the
  compliance status is auditable either way. `browser/lib/robots.js` implements
  the same RFC 9309 subset as the Python engine.
- **`degraded` (exit 8) and `blocked` (exit 9)**: a browser run that reads a
  page but finds nothing the playbook looks for now reports `degraded` with its
  records attached, instead of `ok: true` with `captured: 0`. An anti-bot or
  error interstitial reports `blocked`. Both are distinct from `login_required`.
- **`describe` handshake**: a bridge can declare its capabilities; a bridge that
  does not gets `declared: false` with every capability false. The reference
  Playwright bridge and the test fixtures implement it.
- **`browser/lib/selectors.js`**: every structural assumption about a
  third-party page lives in one file.
- **Real-page fixtures**: `browser/tests/fixtures/snapshots/` holds snapshots
  built from live Bilibili pages on 2026-11-07 by
  `browser/tests/tools/html-to-snapshot.py`, with `tests/real-pages.test.js`
  as the offline regression and `npm run test:live` as the opt-in live check.
- **`--action doctor`** and the **`web_doctor` MCP tool** report every
  dependency with its version or its install command, so an agent that receives
  a thin page can install what is missing instead of guessing.
- **`node browser/run.js --doctor`** and the **`browser_doctor` MCP tool** do the
  same for the browser stack: Node version, the bridge command in use, whether
  the `playwright` package resolves (searched from the bridge's own directory
  first), whether its Chromium binary is downloaded, and where the profile is.
- **The Bilibili search API is asked before the result page is read.**
  `lib/bili-api.js` calls Bilibili's public JSON search endpoint (the `buvid3`
  cookie comes from one home-page request) and falls back to scraping the page
  only when the endpoint refuses. `source` in the record says which path ran.
  `WEB_FORAGER_BILI_API=off` keeps the playbook on the page.
- **`respect_robots` on the MCP tools.** `web_fetch`, `web_search` and
  `web_surf` accept the same switch the CLI spells `--ignore-robots`, so a page
  that robots.txt disallows can be read when the caller is authorised to read
  it. The default is still to check.
- **Bilibili's JSON search on the direct path.** When robots checks are off
  (`--direct-search` or a global override), `scripts/bilibili.py` asks
  `api.bilibili.com` first — the `buvid3` cookie comes from one home-page
  request, and that request is never answered from the cache because a cached
  anti-bot page supplies no cookie — and scrapes the search page only if the
  API answers `-412` or malformed JSON. Cards read from the page are kept only
  when their text mentions the query, so a recommendation rail can no longer
  pass as search results. `route` in the payload names the host that answered.
- **The WeChat article index as a search engine (`--engine weixin`).**
  `weixin.sogou.com` indexes article text, which is the one channel that
  normally carries a Chinese person's or institution's name; each result keeps
  its account name and publish date. It joins `auto` for mostly-CJK queries and
  `--engine all`.

### Changed

- Version 1.1.0 across manifests, `SKILL.md`, CLI and README install tags.
- The browser layer uses the web-forager name throughout: environment variables
  are `WEB_FORAGER_BRIDGE`, `WEB_FORAGER_BROWSER_HOME`,
  `WEB_FORAGER_BROWSER_HEADFUL`, `WEB_FORAGER_BROWSER_PROFILE` and
  `WEB_FORAGER_BROWSER_CDP`; sessions live in `~/.web-forager/browser/`; record
  `source` is `web-forager-browser`.
- The plugin manifest gained a `browser` block listing playbooks, backends and
  the browser MCP tools.
- The User-Agent now carries the real version and the repository URL instead of
  a stale `WebForager/1.0` and a placeholder domain.
- `bili-danmaku` asks the bridge to observe first and falls back to DOM text
  second; a DOM-derived list is recorded with a warning that it is partial.
- Duplicate card links now merge, so a captured card keeps its readable title
  instead of the "views danmaku duration" overlay text.
- The MCP server exposes eight HTTP tools instead of seven.
- **`auto` widens a thin answer once.** A Latin query that returns fewer than
  three distinct results from 360 and Bing now asks Sogou as well; a CJK query
  whose engines all fail keeps its Bing fallback. A full answer is not widened,
  so the common case costs nothing extra.
- **`--max-pages 0` returns a search answer without page bodies.** The CLI used
  to floor the value at 1; both the CLI and `web_search` now let a caller ask
  for the result list alone and fetch only what it needs with `--max-chars`.
- **The MCP search tool carries the same warnings as the CLI.** A response whose
  results do not mention the query text — or that is empty — now says so in
  `warnings` instead of leaving the agent to present dictionary pages as
  findings.

### Fixed

- A browser run that found nothing no longer reports success.
- A bridge without `observe` is no longer reported as observing.
- The Bilibili feed enrichment test no longer reaches the network, so the suite
  is genuinely offline.
- **`results` no longer repeats every page body.** A search response carried
  each Markdown page twice — once in `pages`, once in `results` — so a caller
  with an output cap received a truncated tail. `results` is now a compact
  index (`url`, `title`, `status`, `content_type`, `markdown_chars`, `tables`,
  `snippet`, `warnings`, `error`); the body stays in `pages` and, for a single
  fetch, at the top level. The old shape is one flag away: `--full-results` on
  the CLI, `fullResults` on the MCP tools.
- **`auto` no longer mixes Bing into Chinese queries.** Bing treats a quoted
  Chinese phrase as single characters, so dictionary and encyclopaedia pages
  outranked the precise hits. A mostly-CJK query now asks 360, Sogou and the
  WeChat index, and falls back to Bing only if all three are unreachable. Latin
  queries are unchanged.
- **Navigation waits for the page it lands on.** `goto` now waits for the load
  state and a short settle before returning, so an `evaluate` issued right after
  a redirect no longer races it; `snapshot` retries once on the "execution
  context was destroyed" error that a redirect leaves behind.
- **The bridge's stderr is kept.** A dead bridge now reports its last few
  stderr lines in the error instead of a bare timeout.
- **Login walls and anti-bot pages are classified.** A playbook that lands on a
  sign-in or verification URL reports `login_required` or `blocked` with the
  page's real URL, instead of `degraded` with zero captures.
- **Garbled result titles are dropped.** A title made mostly of replacement or
  control characters — the shape an anti-bot page leaves behind — no longer
  reaches the caller.

### Documentation

- Browser mode now documents what it costs: `--out` / `out:` to keep records on
  disk, no screenshots by default, `maxScreens` at or below 5 and
  `minInterval` at or above 3000 ms, `bili-danmaku` as experimental, and login
  state through `WEB_FORAGER_BROWSER_CDP` or a persistent profile.
- HTTP mode is positioned where a search CLI is not: `web_scholar` and
  `web_map`.
- Weibo and Douban are no longer listed as covered sites: they have no
  site-specific code and are read as ordinary pages.
- The two modes are described as sharing four core fields, not as writing the
  same record; a field-by-field table replaces the old claim.
- Baidu's absence, the parser assumptions behind each search engine and the
  absence of site adapters for Zhihu and Xiaohongshu in HTTP mode are documented.
- Browser exit codes 8 and 9, `--strict-robots`, `--doctor` and automatic
  bridge discovery are documented.

### Tests

- **157 Python tests** and **60 browser tests**, all offline. The browser suite
  grows from 35 to 60: capabilities, robots parsing and matching, the
  strict-robots round trip, degraded and blocked paths, the core schema, the
  real-page fixtures, the Bilibili JSON client and its page-card filter, the MCP
search switches and warnings, the thin-result fallback, and the doctor report. The suite
  clears `WEB_FORAGER_BRIDGE`, so a machine that exports the variable still runs
  the no-bridge paths green, and the Bilibili feed test no longer reaches the
  network.

### Notes

- Browser mode is read-only by default. Like, coin, favourite, follow, share,
  comment, danmaku and publish are denied unless `--allow-write` is passed after
  explicit authorisation.
- The bundled Playwright bridge still needs `playwright` and its Chromium
  binary installed separately; `--doctor` names whichever is missing. With no
  bridge at all a live browser run exits 3.
- Danmaku and `observe("danmaku", ms)` are experimental; canvas-rendered text
  still needs OCR.

## 1.0.1 — 2026-11-06

Patch release for the MCP server on Windows hosts.

### Fixed

- **MCP stdio encoding**: some hosts (ZCode among them) launch `python` with the
  ANSI code page as the stdio encoding. A response containing a Chinese title
  then raised `UnicodeEncodeError`, closed the server and surfaced as
  "Connection closed" on the tool call. The server now reconfigures stdin and
  stdout to UTF-8 at startup and falls back to `ensure_ascii` escapes when a
  stream cannot be reconfigured.

### Tests

- Added `tests/test_mcp_stdio.py`, which reproduces the cp1252 sink and checks
  both the reconfigure path and the ASCII fallback. Total: 117 tests.

### Verified

- Bilibili `feed`, `search`, `video` and `related` were exercised against the
  live site from the CLI, and `web_bilibili` through the MCP server inside
  ZCode. Comments and danmaku text remain out of scope for web-forager.

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
