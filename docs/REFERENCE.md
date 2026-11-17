# web-forager reference

> Part of [web-forager](../README.md). This page holds the lookup material: records, actions, exit codes, requirements, repository layout and tests.

**English** · [简体中文](REFERENCE_zh.md)

---

## MCP servers

<details>
<summary>Tool names</summary>

HTTP tools: `web_fetch`, `web_search`, `web_research`, `web_surf`, `web_scholar`, `web_map`, `web_bilibili`, `web_doctor`, `web_find`, `web_feed`. Browser tools: `browser_list`, `browser_run`, `browser_session`, `browser_doctor`.

MCP calls are always read-only and keep the target-page boundary: no tool parameter can change `respect_robots`, `robots_policy`, `input_gate`, the proxy, the browser bridge or a write switch, and the local file `clean` action is not exposed over MCP. Search-engine and scholarly query endpoints have a separate user-level policy (`--query-robots` on the CLI, `WEB_FORAGER_QUERY_ROBOTS` in the server environment), default `warn`: a disallowed query path is read and the engine report names the override; `respect` refuses it. The agent cannot change this through a tool call.

</details>

Test the protocol directly:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | python mcp_server.py
```

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | node browser/mcp_server.js
```

## Browser mode

The browser layer lives in `browser/` and needs Node.js 18 or newer. It is read-only by default: like, coin, favourite, follow, share, comment, danmaku and publish are denied unless `--allow-write` is passed after the user authorises that single action.

```bash
npm install playwright && npx playwright install chromium
node browser/run.js --doctor
node browser/run.js --playbook bili-feed --session bili-01 --max-items 8 --agent
node browser/run.js --playbook zhihu-dig --query "reinforcement learning" --agent
node browser/run.js --playbook wechat-dig --url "https://mp.weixin.qq.com/s/..." --agent
```

| Playbook | Does | Requires |
|---|---|---|
| `bili-feed` | Home feed, scroll and capture unseen cards | none |
| `bili-video` | One video and its visible comments | `--url` or `--bvid` |
| `bili-chain` | Follow the next-episode control and resume from the session | `--url`, `--bvid`, or a chain |
| `bili-danmaku` | Timestamped danmaku, preferring bridge `observe` over DOM text (experimental) | `--url` or `--bvid` |
| `zhihu-dig` | Zhihu search, rank links, capture the best unseen page | `--query` |
| `xhs-dig` | Xiaohongshu public notes, rank `/explore` links, capture one | `--query` |
| `search-dig` | Bilibili search, rank cards, open the best unseen result | `--query` |
| `wechat-dig` | One WeChat article; reports the environment-check wall instead of recycling it | `--url` |

WeChat articles are the one case HTTP mode cannot finish. `mp.weixin.qq.com` disallows `/s` in robots.txt, and even with `--robots-policy warn` the article URL answers with an environment-check page or a captcha redirect instead of the body; the HTTP record reports `verification_required` (exit 9) rather than handing back the error page as content. `wechat-dig` opens the same URL in a real browser profile. If that profile has already passed WeChat's check, the article is captured; if not, the playbook reports `blocked` and does not attempt the challenge.

The bundled bridge is picked up automatically once `playwright` and its Chromium binary are installed; `--bridge` or `WEB_FORAGER_BRIDGE` points at a bridge elsewhere. The command is split on whitespace and started without a shell, so quote a path that contains spaces and pass arguments as usual; pipes, `&&` and redirection are not interpreted. `WEB_FORAGER_BROWSER_HEADFUL=1` shows the window, `WEB_FORAGER_BROWSER_PROFILE=/path` reuses a persistent profile (this is what carries login state for the `extension` backend), and `WEB_FORAGER_BROWSER_CDP=http://127.0.0.1:9222` attaches to a browser you already control (`cdp`). A bridge declares its real capabilities through an optional `describe` call; one that does not implement it is reported as `declared: false` with every capability false.

To sign in once, run `python browser/launch_chrome.py` (it defaults to `~/.web-forager/browser/profile`, and CDP is **off** by default; `--cdp` opts in to a loopback CDP port, random by default or fixed with `--port 9222`). Without `--cdp`, run browser mode with the default backend and it reuses the profile. With `--cdp`, pass `--backend cdp`. CDP itself has no authentication: keep the port local and close the browser when finished. `--storage-state FILE` loads a Playwright state file before the run; `--save-storage-state FILE` writes one after it, with mode `0600` and a refusal if the path is inside `--root`. That file contains cookies and logins: treat it as a credential, keep it out of git, and do not copy it to a shared machine.

`--strict-robots` fetches `robots.txt` before every navigation and stops with `robots_denied` (exit 3) on a disallowed path. Without it the record says so: `compliance.robots_checked` is `false`. A run that reaches the site but finds nothing readable is `degraded` (exit 8) with its records attached; an anti-bot or error interstitial is `blocked` (exit 9); a site that asks for credentials is `login_required` (exit 6).

A browser run is the most expensive thing the plugin does, so its defaults are small: records go to disk with `--out result.json` (or `out:` in MCP), no screenshots are taken unless asked, `--max-screens 5` and `--min-interval 3000` keep a walk polite, and a long walk is better split into runs that resume from `--session`.

---

## When the engines are blocked

Search defaults to `auto`. A mostly-CJK query goes to 360, Sogou and Sogou WeChat — the article index is the one channel that normally carries a Chinese person's or institution's name — and is not handed to Bing, which splits such a phrase into single characters and answers with dictionary pages. Those pages are dropped from any engine's results. An agent that wants Bing for a Chinese query can still ask with `--engine bing`.

Two routes need no search engine at all:

```bash
python run.py --action find --site the-decoder.com --query "OpenAI watermark" --max-pages 3
python run.py --action feed --url https://the-decoder.com/ --num-results 10
```

`find` tries the site's own search URLs (`/?s=`, `/search?q=` and two more), ranks the links by the query and fetches the best ones. `feed` discovers the site's RSS/Atom `<link rel=alternate>` and reads it. `doctor --probe` asks every engine once and reports which ones answer from this network; `doctor` also reports the proxy in use with its credentials removed. Requests honour `HTTPS_PROXY` / `ALL_PROXY`, and `--proxy URL` overrides them for one run.

---

## More CLI examples

Each command has its own block so it can be copied without trimming the others.

**Fetch one Bilibili video.**

```bash
python run.py --action fetch --url "https://www.bilibili.com/video/BV1xx411c7mD"
```

**Fetch a page that needs JavaScript rendering.**

```bash
python run.py --action fetch --url "https://www.zhihu.com/" --render auto
```

**Surf a site and resume the trail later.**

```bash
python run.py --action surf --url "https://www.zhihu.com/" --depth 1 --max-pages 5 --session zhihu-01
```

**Clean a local PDF into Markdown.**

```bash
python run.py --action clean --input notes.pdf --format markdown
```

**List up to 500 page URLs from a site's sitemaps.**

```bash
python run.py --action map --url "https://example.org" --limit 500
```

**Read the Bilibili home feed.**

```bash
python run.py --action bili --mode feed --max-items 10
```

---

## Records and output

### One record per page

| Field | HTTP mode | Browser mode |
|---|---|---|
| `metadata`, `markdown`, `tables`, `warnings` | yes | yes |
| `trust`, `injection_flags`, `injection_findings` | yes | yes |
| `url`, `title` | yes (`url` and `final_url`) | yes |
| `status`, `content_type`, `document_kind`, `cached`, `rendered`, `render_fallback`, `fetched_at`, `chunks`, `links` | yes | no |
| `schema_version`, `captured_at`, `playbook`, `backend`, `compliance`, `viewport_evidence`, `interaction_trace` | no | yes |

`render_fallback` is `true` when the server answered with a minimal script shell and HTTP mode rendered it once with Playwright before extraction. A `fetch --query` allows at most two such renders, and each one adds several seconds.

`injection_findings` is a list of `{code, severity, confidence, span, snippet, context}`. `span` is a character range in the scanned text, `severity` is `hard` or `soft`, and `context` is `direct`, `quote` or `example`. Hard rules describe an action (forged system tag, secret exfiltration, `curl ... | sh`, `rm -rf /`); `--input-gate strict` withholds a body only when one matches. Soft rules describe override or role-swap language and never withhold on their own, because papers and security notes quote them. The scanner walks the whole body in overlapping windows, before `max_chars` truncation, and the first warning repeats up to three matching snippets.

Search results are ordered by query coverage, phrase and title match, a small domain prior, snippet freshness and engine order — including when only one engine answered. Each result carries `coverage`, `matched_terms`, `relevance` and `language_match`. A result is relevant when it contains the exact phrase or at least two meaningful query terms with half the query covered; a wrong-language page that repeats one product name is `language_match: false`. Off-topic rows are ranked last, and are dropped when at least three relevant results exist; otherwise a warning names how many were kept. The final list keeps at most two results per host, so one dominant host cannot crowd out every other source; when too few hosts answered, the overflow fills the remaining slots. A thin first pass is retried once with a simplified query (quotes and common stopwords removed, or a spaced CJK query joined); that retry appears in `engine_report` with `query_variant`. Search titles and snippets pass through the same injection scanner, and a matching result carries its own `injection_flags` and `injection_findings`.

Before ranking, duplicate URLs are canonicalized: `utm_*`, `fbclid`, fragments, `www.`, trailing slashes and `/amp` no longer make one article look like two results. A result found by more than one engine receives a reciprocal-rank-fusion contribution, and an exact title match gets a small bonus over a title that merely contains the phrase. Light English stemming is used for matching only, so `injection` meets `injections` without changing the displayed query or text. The search payload also carries `search_quality: {query, engine, returned, relevant, off_topic, language_mismatch, engines_answered, engine_errors, dropped_off_topic, returned_before_filter}`, a machine-readable summary for agents that do not want to parse the prose warnings.

`--core` returns the shared shape instead:
```json
{
  "schema_version": "core-1",
  "source": "web-forager",
  "mode": "http",
  "url": "https://example.org/article",
  "title": "An article",
  "collected_at": "2026-11-07T10:00:00Z",
  "metadata": {},
  "markdown": "...",
  "tables": [],
  "warnings": [],
  "extra": { "status": 200, "cached": false }
}
```

`mode` is `http` or `browser`, `source` names the producer, and `extra` keeps every field the two modes do not share. The same fold is available as a library call: `engine.normalize_record()` in Python and `normalizeRecord()` in `browser/lib/record.js`.

`results` is an index, not a second copy of every page. For a search it carries `url`, `title`, `snippet`, `status`, `content_type`, `markdown_chars`, `tables` and any `warnings` or `error`; the Markdown body lives once, in `pages`, and a single `fetch` keeps it at the top level. `--full-results` (CLI) or `fullResults: true` (MCP) restores the old shape.

### Workspace output

```bash
python run.py --action fetch --url "https://example.org/article" --root <WS>
```

Writes only:

```text
<WS>/process/web-forager/web-forager_<timestamp>_<slug>.json
<WS>/process/web-forager/web-forager_<timestamp>_<slug>.md
<WS>/_broadcast/web-forager_<timestamp>_<slug>.json
```

`material/` and `results/` belong to the user and the orchestrator; web-forager never writes there. Browser captures follow the same discipline under `<WS>/process/web-forager/browser/` and `<WS>/_broadcast/`.

---

---

## Research output

`research --query` runs two stages: broad recall across the free engines, then
focused reading of a few distinct hosts. The payload adds:

| Field | Meaning |
|---|---|
| `intent` | `{intent, confidence, signals}` from a deterministic keyword classifier |
| `strategy` | `{breadth, search_pages, targeted_site, targeted_sites, targeted_by_site, official_entries, focus_*}` |
| `seeds` | selected results with `authority_tier`, `authority_score`, `reason` |
| `evidence` | `[{url, title, authority_tier, authors, published_at, date_source, passages, partial?}]` |
| `freshness` | `{newest, oldest, dated_sources, undated_sources, newest_age_days, all_stale}` |
| `answerability` | `{level, coverage, authority_level, partial_only, source_count, host_count, view_hosts, multi_view, stale, reason}` |
| `skipped` | pages not used, with `code` (`robots_denied`, `browser_required`, `browser_required_low_value`, `no_matching_passage`, …) |

If the broad pool has no relevant primary/official/academic source, the second
pass prefers a direct official entry page (Python asyncio, Go concurrency, Rust,
MDN, Microsoft Wi-Fi support), then the site's own search page (Microsoft
Support, MDN), and only then a `site:` engine query for a non-CJK question.
Direct entries and host search pages do not depend on an engine honouring
`site:`. A news query with no usable engine rows falls back to a public finance
RSS channel (China News Service); a dated headline and summary are labelled
`feed_headline`, never expanded into a fabricated article. When the article body
has no dateline, the fetched page inherits the feed's publication date. Each
focus fetch is capped at 8 seconds with no retry, and robots.txt at 6 seconds,
so one dead origin cannot consume the whole call. A comparison needs at
least two independent full-source viewpoints;
a WeChat snippet never counts as one. When two full authoritative sources are
already present for a comparison or technical question, a WeChat-only snippet is
skipped rather than mixed in. A WeChat link that HTTP mode cannot read still
yields a `partial` search-snippet record with an explicit warning, never a
fabricated full article. Every passage is quoted, untrusted page text.

## Actions and exit codes

| Action | Purpose |
|---|---|
| `fetch` | one URL or keyword query → pages |
| `research` | broad recall → focused, cited evidence passages |
| `find` | search inside one site through the site's own search page |
| `feed` | read a site's RSS/Atom feed, discovering it from the page |
| `clean` | local or remote HTML/PDF/DOCX/XLSX/EPUB/CSV → Markdown |
| `bili` | Bilibili feed / video / related / search / surf |
| `surf` | search or seed URL, then ranked link BFS |
| `scholar` | arXiv / Crossref / PubMed / DOI records |
| `map` | page URLs from robots.txt and sitemaps |
| `doctor` | dependency report: what is installed, what to install |

| Exit code | Meaning (both modes unless overridden below) |
|---|---|
| 0 | success |
| 2 | argument or URL error |
| 3 | robots.txt denied the request, or no browser bridge configured |
| 4 | network, HTTP or navigation failure |
| 5 | extraction or capture failed |
| 6 | Playwright requested but unavailable |
| 7 | PDF requested but `pypdf` unavailable |
| 9 | verification or anti-bot page instead of content (`verification_required` in HTTP mode, `blocked` in browser mode) |
| 130 | interrupted |

Browser mode reuses that table and changes or adds only these codes:

| Exit code | Browser meaning |
|---|---|
| 2 | also: unknown backend |
| 6 | `login_required`: the site asked for credentials |
| 7 | `confirmation_required`: a write-like action was denied |
| 8 | `degraded`: the page was read, but the playbook found nothing it looks for |
| 9 | `blocked`: an anti-bot or error interstitial replaced the page |

`--agent` keeps these exit codes and prints a `{"ok":false,"error":{"code","message","hint"}}` envelope on stdout. `doctor` reports every dependency with its version or the command that installs it; a missing Playwright returns exit code 6, and a missing `pypdf` returns exit code 7.

---

---

## Requirements

Python 3.10+. Core runtime: `requests`, `beautifulsoup4`, `trafilatura`. Optional: `playwright` (JS rendering), `pypdf` (PDF). `defusedxml` is used when already installed but is never required — XML with an internal DTD subset or any ENTITY declaration is rejected regardless. Browser mode additionally needs Node.js 18+ and a bridge command; `browser/bridges/playwright-bridge.js` needs `playwright` installed with npm. No third-party code is vendored; the full per-capability matrix lives in [DEPENDENCIES.md](DEPENDENCIES.md).

---

---

## Repository layout

<details>
<summary>Full tree</summary>

```text
web-forager/
├── .claude-plugin/               Claude Code manifest + marketplace
├── .codex-plugin/                Codex manifest + marketplace
├── .codebuddy-plugin/            CodeBuddy manifest + marketplace
├── .dsh-plugin/                  DSH manifest + CJS entry
├── .cursor/rules/                Cursor rule file
├── .windsurf/rules/              Windsurf rule file
├── .clinerules/                  Cline rule file
├── .continue/rules/              Continue rule file
├── .roo/rules/                   Roo Code rule file
├── .github/                      Copilot instructions + Actions CI
├── AGENTS.md                     generic agent contract
├── install.py                    one-command rule-file installer
├── manifest.json                 plugin manifest
├── .mcp.json                     MCP stdio registration
├── package.json / index.js       npm + dsh packaging
├── cordis.patch.yml              dsh bundle patch
├── run.py                        CLI: nine actions
├── mcp_server.py                 MCP stdio server (10 HTTP tools)
├── browser/                      browser mode (Node 18+)
│   ├── run.js                    CLI: eight read-only playbooks
│   ├── mcp_server.js             MCP stdio server (4 browser tools)
│   ├── lib/                      bridge backend, session, record, safety, selectors, robots, snapshot
│   ├── playbooks/                bili-* / zhihu-dig / xhs-dig / search-dig / wechat-dig
│   ├── bridges/                  optional Playwright reference bridge
│   └── tests/                    fake backends, real-page snapshots, live smoke
├── SKILL.md                      Claude Code skill contract
├── commands/                     /fetch /research /surf /scholar /map /browse
├── docs/                         install commands, acknowledgements, dependency matrix
├── scripts/
│   ├── engine.py                 robots, fetch, search, cache, chunks, Markdown, surf, find, feed
│   ├── research.py               broad recall, authority selection, cited evidence passages
│   ├── pdf.py                    PDF text (optional pypdf)
│   ├── documents.py              DOCX / XLSX / EPUB / CSV
│   ├── feeds.py                  RSS / Atom / RSS 1.0
│   ├── scholar.py                arXiv / Crossref / PubMed / DOI
│   ├── sitemap.py                sitemap discovery
│   └── bilibili.py               Bilibili adapter
├── tests/                        offline HTTP fixtures
├── requirements.txt
├── THIRD_PARTY_LICENSES.txt
├── CHANGELOG.md
├── README.md · README_zh.md
└── LICENSE                       MIT
```

</details>

---

---

## Tests

```bash
python -m pytest tests -q
npm run test:browser
```

That is **332 Python tests** plus **91 browser tests**, all passing and fully offline.

<details>
<summary>What the suites cover</summary>

`conftest.py` starts a temporary local HTTP server serving robots.txt, articles, PDF/Office files, feeds, sitemaps, search-result pages, a site-search page and multi-hop surf pages. The Python suite covers robots denial, extraction, tables, documents, feeds, cache, search pagination and routing, chunking, MCP, surf sessions, installer behaviour, host-rule and disclaimer checks, the shared `core-1` record, and every exit code. The browser suite uses a fake backend plus fake bridges that speak the wire protocol, so the CLI runs end to end without a browser; it covers capability declaration, robots.txt matching, the `--strict-robots` round trip, the private-address guard, the untrusted-content screen, and the degraded and blocked paths over snapshots recorded from live pages.

</details>

CI runs both suites on every push to `main`, on pull requests and on version tags: Python on Ubuntu 3.10/3.12 and Windows 3.12, browser mode on Node 20/22. A live check is opt-in and never runs in CI:

```bash
WEB_FORAGER_LIVE=1 WEB_FORAGER_BRIDGE="node browser/bridges/playwright-bridge.js" npm run test:live
```

---
