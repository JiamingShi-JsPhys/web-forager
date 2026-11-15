# web-forager

**Read the public web politely, and hand an agent one clean record it can trust.**

Search, fetch, extract and browse live in one engine: 360 / Bing / Sogou / Sogou WeChat for discovery; HTML, PDF, Office, EPUB, CSV, feeds and sitemaps for reading; a real browser for pages that only exist after scripts or a login. It refuses what it should not touch, and every record says what was skipped and why.

**English** · [简体中文](README_zh.md)

**Version:** 1.3.0 | **License:** MIT | **Python:** 3.10+ | **Node:** 18+ (browser mode)

> For learning and information gathering only. Read the [full legal notice](#full-legal-notice) before relying on any output.

---

## Contents

**Start**

- [Why web-forager](#why-web-forager)
- [Install and download](#install-and-download)
- [Quick start](#quick-start)
- [Things you can just ask](#things-you-can-just-ask)

**Going deeper**

- [Two modes, one record](#two-modes-one-record)
- [How a run flows](#how-a-run-flows)
- [What a run looks like](#what-a-run-looks-like)
- [Repository layout](#repository-layout)
- [Full reference](#full-reference)
- [Security boundary](#security-boundary)
- [Scope and compliance](#scope-and-compliance)

**Other**

- [Requirements](#requirements)
- [Tests](#tests)
- [Full legal notice](#full-legal-notice)
- [Known limitations](#known-limitations)
- [Issues and feedback](#issues-and-feedback)
- [Acknowledgements](#acknowledgements)
- [Trademarks](#trademarks)
- [License and author](#license-and-author)

---

## Why web-forager

A search API returns links and stops. A scraper reads pages and ignores the rules. An agent needs both halves, plus a contract it can trust. This repository puts all three in one engine, with no API key and no hosted index in the middle.

- **One engine, every content type.** HTML, PDF, DOCX, XLSX, EPUB, CSV, RSS/Atom, sitemaps, Bilibili and rendered pages all come back as the same four fields — `metadata`, `markdown`, `tables`, `warnings` — so the caller never branches on the source.
- **Compliance is inside the fetcher, not in a README promise.** robots.txt, a per-origin delay, response-size caps, redirect limits and a contactable User-Agent apply to every request, including each search, sitemap and surf hop.
- **It degrades instead of crashing.** A missing bridge is exit 3, missing Playwright is exit 6, missing `pypdf` is exit 7, a site without a sitemap is an empty result with a note, and a verification page is reported as `verification_required` rather than recycled as content.
- **It tells the truth about what it read.** `engine_report` names every engine tried with its latency and error, `skipped` names every result that could not be read, `degraded` means the page was read but the playbook found nothing, and fetched text carries `trust: "untrusted"` with `injection_flags` when it looks like a prompt.
- **Results are ordered and diversified.** Coverage, title match, a small domain prior and snippet freshness decide the order; the list keeps at most two results per host and fills from the overflow when too few hosts answered; a thin first pass retries once with a simplified query.
- **A script shell is rendered, within a budget.** When a server returns almost no HTML, `--render auto` renders it once with Playwright before extraction; `fetch --query` and `surf` cap that at two pages per run.

---

## Install and download

Install this repository as **one plugin**. The CLI, both MCP servers and `SKILL.md` share a single engine and a single robots/cache pipeline; splitting the tree breaks that.

**Most people take method one: let an AI install it.** A host with a plugin marketplace takes method two; a terminal install, or several hosts at once, takes method three.

## Method 1: let your AI install it

```bash
Visit the GitHub repository `https://github.com/JiamingShi-JsPhys/web-forager`, clone it, and run `python install.py --project . --global`. If your host has a plugin system, install the whole thing as a single plugin instead; that script covers the hosts that read rule files.
```

## Method 2: install from the plugin marketplace by URL

Every host below has its own plugin marketplace. Register this repository's Git URL, then install the plugin it lists. Registering the same URL twice is harmless — the second call reports that it is already known.

```text
https://github.com/JiamingShi-JsPhys/web-forager
```

Append `#v1.3.0` to pin the install to this release. Drop it to follow the default branch.

## Method 3: install with commands

Claude Code, Codex, dsh and CodeBuddy take a one-line plugin command; Cursor, Windsurf, Cline, Continue, Roo Code, GitHub Copilot and opencode read a rule file, and one script writes all of them. Every command, every flag and the optional dependencies live on one page: **[docs/INSTALL_COMMANDS.md](docs/INSTALL_COMMANDS.md)**.

Each plugin host gets its own MCP launch file: Claude Code reads `.mcp.json`, Codex reads `.codex-plugin/mcp.json`, CodeBuddy reads the `mcpServers` block in `.codebuddy-plugin/plugin.json`, and dsh reads the two `dsh-mcp-client` entries in `cordis.patch.yml`. After installing in CodeBuddy or dsh, start a new session so the servers mount; `codebuddy mcp list` can run before plugins load and is not a health check.

### Keeping an installed copy current

A host copies the plugin into a cache of its own, and that copy is what actually runs. A fixed bug keeps running until the cache is refreshed — and a marketplace backed by a local folder may hold a snapshot rather than the live directory.

For ZCode, refresh the marketplace index first, then the plugin:

```bash
zcode plugins marketplace update web-forager-marketplace
zcode plugins update web-forager@web-forager-marketplace
```

If the version number did not change between two installs, `update` may treat the cache as current; reinstall it instead:

```bash
zcode plugins uninstall web-forager@web-forager-marketplace --force
zcode plugins install web-forager@web-forager-marketplace --yes
```

Claude Code users can run `claude plugin update web-forager`. After any update, `python run.py --action doctor` reports what the running copy can actually see.

---

## Quick start

Three ways in, plus an optional browser mode. Pick the one that matches where you already are.

### From the chat box

The skill is registered under the `web-forager` namespace, so it is one `/` away:

```text
/web-forager:web-forager collect https://www.bilibili.com/video/BV1xx411c7mD as Markdown
```

Say what you need after the name; the skill picks the action and returns Markdown, metadata, tables and warnings. A page that robots.txt disallows is refused, not fetched.

Five commands cover the usual jobs:

| Command | Does |
|---|---|
| `/web-forager:fetch` | Fetch one URL, or search a keyword and read the results |
| `/web-forager:surf` | Search or open a seed URL, then follow ranked in-page links with a resumable session |
| `/web-forager:scholar` | Query arXiv, Crossref or PubMed, or resolve a DOI |
| `/web-forager:map` | Discover page URLs from robots.txt Sitemap lines, sitemap indexes and `.xml.gz` files |
| `/web-forager:browse` | Run a read-only browser playbook through the browser MCP server |

```text
/web-forager:fetch https://example.org/article
/web-forager:scholar 10.1038/nature14539
/web-forager:browse read this WeChat article: https://mp.weixin.qq.com/s/...
```

### From a terminal

Install the Python dependencies once:

```bash
pip install -r requirements.txt
```

Read one page as Markdown, metadata and tables:

```bash
python run.py --action fetch --url "https://example.org/article"
```

Search, then read the most relevant pages:

```bash
python run.py --action fetch --query "city walk guide" --num-results 8 --max-pages 3
```

A paper, without touching a result page:

```bash
python run.py --action scholar --source doi --query "10.1038/nature14539"
```

Search defaults to `auto`: a mostly-CJK query goes to 360, Sogou and Sogou WeChat, a Latin query to 360 and Bing. If the engines are blocked, the [full reference](docs/REFERENCE.md#when-the-engines-are-blocked) shows the site-search and feed routes that need no engine at all.

Not sure which action you need?

| You have | Use |
|---|---|
| one URL or a keyword | `--action fetch` |
| a site you trust, no working search engine | `--action find --site <HOST> --query <TEXT>` |
| a blog or news site | `--action feed --url <SITE>` |
| a PDF, DOCX, XLSX, EPUB or CSV | `--action clean --input <FILE>` |
| a topic to explore link by link | `--action surf --query <TEXT>` |
| a DOI, arXiv id or paper title | `--action scholar` |
| a site whose pages you want to enumerate | `--action map --url <SITE>` |
| Bilibili | `--action bili` |
| "why is this not working" | `--action doctor [--probe]` |

Add `--agent` to any action for a machine-readable `{"ok":true,"data":...}` envelope. Add `--out result.json` to keep the full record on disk, or `--root <WS>` to publish it into a workspace (`<WS>/process/web-forager/` and `<WS>/_broadcast/`); see [records and output](docs/REFERENCE.md#records-and-output).

### From an MCP client

```json
{
  "mcpServers": {
    "web-forager": {
      "command": "python",
      "args": ["/absolute/path/to/web-forager/mcp_server.py"]
    },
    "web-forager-browser": {
      "command": "node",
      "args": ["/absolute/path/to/web-forager/browser/mcp_server.js"]
    }
  }
}
```

The HTTP server exposes ten tools (`web_fetch`, `web_search`, `web_surf`, `web_scholar`, `web_map`, `web_bilibili`, `web_clean`, `web_doctor`, `web_find`, `web_feed`); the browser server exposes four (`browser_list`, `browser_run`, `browser_session`, `browser_doctor`).

Two switches keep a search cheap: `max_pages: 0` returns the result list with no page bodies, and `respect_robots: false` reads a page robots.txt disallows — only for resources you are authorised to read. `web_search` also returns `engine_report` and `warnings` when the results do not mention the query.

### Browser mode (optional)

Needs Node.js 18+ and a bridge command, and is read-only by default. Sign in once with `python browser/launch_chrome.py`, then pass `--backend cdp`; the eight playbooks, their switches, `--strict-robots`, storage-state and the cost controls are in the [full reference](docs/REFERENCE.md#browser-mode). `wechat-dig` is the one to reach for when an HTTP search found a WeChat article but robots.txt and the environment check stopped the read.

---

## Things you can just ask

| Say it your way | Routes to | You get back |
|---|---|---|
| "Read this article and keep the tables" | `fetch --url` | Markdown, metadata, tables and any extraction warnings |
| "Find recent writing on X" | `fetch --query` | Ranked, de-duplicated results, optionally the top pages |
| "What does this site publish?" | `map --url` | Page URLs from robots.txt Sitemap lines and sitemap indexes |
| "Follow this topic from that page" | `surf --query` or `--url` | A resumable link-by-link walk, one state change per cycle |
| "Find papers on X" | `scholar --source arxiv` | arXiv metadata and abstracts, not a scraped result page |
| "What is this DOI?" | `scholar --source doi` | One normalised bibliographic record |
| "Read this PDF / Word file" | `clean --input` | The same Markdown record as an HTML page |
| "Why is this failing?" | `doctor --probe` | Dependency versions and which search engines answer here |
| "Read this WeChat article" | `browse` + `wechat-dig` | The article, or an honest `blocked` when the profile has not passed the check |
| "Open the page behind my login" | `browse` + `--backend cdp` | What the page shows to that profile, with the shared-profile warning |

---

## Two modes, one record

| | HTTP mode | Browser mode |
|---|---|---|
| Reads | what the server returns | what a person sees once scripts run and login state applies |
| Entry points | `run.py`, `mcp_server.py` | `browser/run.js`, `browser/mcp_server.js` |
| Needs | Python 3.10+ | Node.js 18+ and a bridge command |
| Covers | search, HTML/PDF/Office/feeds, sitemaps, surf, Bilibili, scholarly APIs | eight read-only playbooks, rendered pages, danmaku, WeChat articles |

Both modes agree on four core fields — `metadata`, `markdown`, `tables` and `warnings` — and extend them differently. `--core` on either CLI, or `core: true` on `browser_run`, folds a record onto one documented shape ([records and output](docs/REFERENCE.md#records-and-output)).

Only Bilibili has a site-specific HTTP adapter. Zhihu, Xiaohongshu, Weibo and Douban are read as ordinary pages in HTTP mode; Zhihu and Xiaohongshu add browser playbooks, and Weibo and Douban have none. WeChat articles are the one case HTTP mode regularly cannot finish: robots.txt disallows the article path, and the page itself answers with an environment check. `wechat-dig` opens it in a browser profile instead, and reports `blocked` when that profile has not passed the check rather than solving it.

---

## How a run flows

Every request enters through the same `HttpFetcher`: robots policy, cache, retry/backoff, per-origin rate limiter and size cap. The chosen action routes the payload to the matching extractor, and all extractors converge on one Markdown record.

```mermaid
flowchart LR
    IN["URL / keyword / DOI / file"] --> SEL{"choose action"}
    SEL -->|one page| F["fetch"]
    SEL -->|one site| FD["find / feed"]
    SEL -->|local file| C["clean"]
    SEL -->|papers| S["scholar"]
    SEL -->|site inventory| M["map"]
    SEL -->|exploration| W["surf"]
    SEL -->|Bilibili| B["bili"]

    F --> SEARCH["search providers<br/>360 / Bing / Sogou / WeChat"]
    FD --> HTTP
    C --> EXT["HTML / PDF / DOCX / XLSX / EPUB / CSV"]
    S --> API["arXiv / Crossref / PubMed"]
    M --> SM["robots Sitemap / sitemap index / .xml.gz"]
    W --> HTTP
    B --> HTTP
    SEARCH --> RANK["rank + diversify<br/>coverage, title, prior, freshness"]
    RANK --> HTTP["robots.txt check<br/>per-origin rate limit"]
    HTTP --> EXT
    EXT --> MD["Markdown + metadata + tables + chunks"]
    MD --> OUT["JSON / --agent envelope / --root workspace / MCP"]
```

`surf` only follows `<a href>` links that already exist in the page; it never constructs guessed URLs, submits forms or executes page JavaScript. `map` reads only published sitemaps, and `scholar` calls documented APIs instead of scraping result pages.

Browser mode is a second loop beside this one: the bridge supplies a page, `browser/run.js` reads a DOM snapshot, the session decides what is new, the playbook picks the next navigation step and a capture is written. Only one state-changing action runs per observation cycle, and write-like controls are denied by default.

---

## What a run looks like

A search that can read every result:

```text
$ python run.py --action fetch --query "city walk guide" --num-results 8 --max-pages 3
mode: search
pages: 3/3 readable
skipped: none
engine_report: 360 (0), Sogou (7, 0.7 s), WeChat (8, 0.5 s)
```

A search where one source refuses:

```text
skipped: 5
  robots_denied  https://mp.weixin.qq.com/s?...
  robots_denied  https://mp.weixin.qq.com/s?...
warnings:
  robots.txt denied the skipped paths. Use --robots-policy warn only when you are authorised to read them; the record will mark the override.
  WeChat article links cannot be read in HTTP mode ... open one with browser mode: browser_run with playbook "wechat-dig".
```

The first is a success. The second is still a success — it says what it could not do, instead of returning an error page as the article.

---

## Repository layout

```text
web-forager/
├── run.py                 # one CLI entry: fetch, find, feed, clean, surf, scholar, map, bili, doctor
├── mcp_server.py          # stdio JSON-RPC, ten HTTP tools
├── scripts/               # engine, extractors, search parsers, robots, cache, untrusted screen
├── browser/               # Node browser mode: run.js, MCP server, playbooks, bridge, profile launcher
├── commands/              # slash commands: fetch, surf, scholar, map, browse
├── docs/                  # reference, install commands, dependencies, acknowledgements
├── tests/                 # Python suite and offline fixtures
└── browser/tests/         # browser suite: fake backend, fake bridges, recorded snapshots
```

Per-directory detail, every action and flag, record shapes and the full exit-code table: **[docs/REFERENCE.md](docs/REFERENCE.md)**.

---

## Full reference

Records, the full action list, exit codes, requirements, repository layout and test details live in **[docs/REFERENCE.md](docs/REFERENCE.md)**, so this page stays a quick start.

| Exit code | Means |
|---|---|
| `0` | the action finished; unreadable results are listed in `skipped` |
| `2` | argument or URL error |
| `3` | robots.txt denied the request, or no browser bridge configured |
| `4` | network, HTTP or navigation failure |
| `5` | extraction or capture failed |
| `6` | Playwright requested but unavailable, or a login wall in browser mode |
| `7` | PDF requested but `pypdf` unavailable |
| `8` | `degraded`: the page was read but the playbook found nothing |
| `9` | `blocked` or `verification_required`: an anti-bot or verification page replaced the content |
| `10` | the query was refused because it asked to profile a private person |
| `130` | interrupted |

`--agent` keeps these codes and writes `{"ok":false,"error":{"code","message","hint"}}` on stdout.

---

## Security boundary

The tool makes the requests a prompt or an agent asks for, so the boundaries are in the code rather than left to the caller's memory.

- **Private targets are refused.** Loopback, RFC 1918, link-local (including `169.254.169.254`), CGNAT and their IPv6 forms are rejected before a socket opens, and again on every redirect hop, so a public URL cannot bounce the client into the LAN. `--allow-private` exists for local fixtures and trusted intranet tools and is off by default. The browser side installs the same guard as a request filter, so a hostile page cannot probe `http://127.0.0.1:...`.
- **robots.txt is a policy, not a lock.** The default `--robots-policy respect` refuses a disallowed path. `warn` reads it and writes `compliance.robots_overridden: true`; `ignore` records that robots was not consulted. A denial is reported to the caller — it is not a cue to retry the same URL with a tool that ignores robots.
- **The browser keeps its own profile.** The bundled bridge stores state under `~/.web-forager/browser/profile`, not in the browser you use every day. `browser/launch_chrome.py` starts Chrome on that profile, and `--save-storage-state` writes a Playwright state file with mode `0600` (refused inside `--root`). Attaching over CDP to a personal browser still works, but the run is marked `shared_browser: true` with a warning: every cookie and login in that profile is reachable by the pages a playbook opens.
- **Fetched text is data, and says so.** Every record carries `trust: "untrusted"`. When a page contains instruction-shaped text — "ignore previous instructions", fake system tags, `curl ... | sh`, requests to send keys or environment variables — the matching codes appear in `injection_flags` and a warning sits first in the list. `--input-gate strict` withholds the body instead. This is a screen, not a sandbox: the host must still keep untrusted content, private data and outbound requests out of one autonomous loop.

---

## Scope and compliance

The core engine is an original clean-room implementation: no source is copied from Crawlee, Scrapy, Colly, Katana or any other crawling framework, and no GPL/AGPL dependency is used. The tool **never bypasses a login, CAPTCHA, Cloudflare challenge or paywall**, and it does not run concurrent request floods. `robots.txt` (RFC 9309 subset) is checked before every target page according to `--robots-policy`, each request carries a contactable information-gathering User-Agent, and the default rate is one request per second per origin — search, sitemap and surf hops included.

Where a site answers with a verification page, the record says `verification_required` and stops. Where a browser profile has not passed a site's check, the playbook says `blocked` and stops. Neither path tries to satisfy the challenge.

---

## Requirements

Python 3.10+ and the packages in `requirements.txt` (`requests`, `beautifulsoup4`, `trafilatura`). Optional: `playwright` for JavaScript rendering, `pypdf` for PDF text. Browser mode additionally needs Node.js 18+ and a bridge command; the bundled bridge needs `playwright` installed with npm and its Chromium binary.

```bash
pip install playwright && playwright install chromium
```

A missing optional package never crashes a run: Playwright is exit code 6, `pypdf` is exit code 7, and the record carries an install hint. The per-capability matrix is in [DEPENDENCIES.md](DEPENDENCIES.md).

## Tests

```bash
python -m pytest
node --test "browser/tests/*.test.js"
```

258 Python tests and 87 browser tests, all offline. The Python suite starts a temporary local HTTP server for robots.txt, articles, PDF/Office files, feeds, sitemaps, search-result pages and multi-hop surf pages; the browser suite uses a fake backend and fake bridges that speak the same wire protocol, plus snapshots recorded from live pages. CI runs both from a repository clone; release archives exclude the test folders.

## Full legal notice

### What this tool is for

web-forager automates reading publicly reachable pages, for learning, research, monitoring and personal knowledge work only.

### What it must not be used for

- Identifying, locating, profiling or contacting a private individual, or assembling scattered records into a picture of a person.
- Harassment, stalking, intimidation, doxxing, or any invasion of another person's privacy.
- Bypassing logins, CAPTCHAs, paywalls or access controls, or placing load on a site beyond the built-in rate limit.
- Sending malicious concurrent requests, or any denial-of-service-style access, to a target site.
- Any use that breaks the law where you are, or the terms of the site you are reading.

### Your responsibility

It is the end user's responsibility to obey all applicable local, state and federal laws and the Terms of Service and copyright of every site reached. The authors do not grant permission to access anything you are not entitled to read, and do not verify that a given use is lawful. The user bears full legal responsibility for how this software is used.

### No warranty

The software is provided "as is", without warranty of any kind, express or implied, as stated in the [MIT License](LICENSE). It may fail, return incomplete or outdated content, or change behaviour between versions.

### Limitation of liability

To the maximum extent permitted by law, the authors and contributors assume no liability and are not responsible for any misuse of this software or for any damage, loss or legal consequence arising from it. Fetched text comes from third-party sites and is not endorsed or checked by this project.

### If you redistribute it

Keep this disclaimer and the licence notice with any copy you publish or fork.

---

## Known limitations

### Read before use

- **This is a low-frequency tool, not a crawler fleet.** Requests are serial and rate-limited per origin (one per second by default); `surf`, search and sitemap reads do not fan out concurrently. It is unsuitable for large-scale harvesting.
- **PDF extraction reads the text layer only.** Scanned PDFs need OCR, which this plugin does not do.
- **Login walls are not bypassed.** `zhihu-dig` and `xhs-dig` stop with `login_required`; reuse a logged-in profile through your bridge.
- **WeChat articles are not read in HTTP mode.** robots.txt disallows `/s`, and with an override the URL returns an environment check. The record says `verification_required`; `wechat-dig` can read the article only in a profile that has already passed that check.
- **robots.txt unreachable means deny.** That is the conservative RFC behaviour. `--ignore-robots` is only for resources you are explicitly authorised to access. Browser mode consults robots.txt only under `--strict-robots`, and the record always states whether the check was made (`compliance.robots_checked`).

### Edge cases

- **Scholarly APIs return metadata and abstracts.** They do not return full papers; respect each platform's terms.
- **`--render auto` is a heuristic, plus one bounded fallback.** Short visible text plus SPA markers triggers rendering; a minimal script shell triggers one extra render. Complex sites may still need `--render always`, and `--wait-for` / `--scroll` only work when Playwright is installed.
- **Search depends on public result pages.** Availability varies by network, and every parser (`parse_360_html`, `parse_bing_html`, `parse_sogou_html`, `parse_weixin_html`, `parse_ddg_html`) encodes an assumption about the result-page markup. Each has an offline fixture; a redesign breaks the fixture test rather than silently returning nothing. **Baidu is not supported**: its result page is heavily guarded and no parser is shipped. Sogou may show a human-verification page, and `--engine all` can fail partially. A Chinese query never falls back to Bing, and dictionary pages that match one character of a query are dropped.
- **Only Bilibili has a site-specific HTTP adapter.** The other sites named above are read as ordinary pages, which is enough for public article pages and not enough for logged-in feeds.
- **Browser mode needs a working bridge.** `playwright` and its Chromium binary are installed separately, `--doctor` names whichever is missing, and with no bridge at all a live run exits 3.
- **`surf` follows ordinary links only.** It does not click buttons, execute JavaScript or handle login walls.
- **DNS is resolved twice.** The guard checks the addresses DNS returns and the HTTP client then resolves again to connect. A hostile resolver that answers differently between the two calls (rebinding) is outside what this check can stop; pair it with an egress policy if that is your threat model.

### Experimental features and high-risk switches

- **Danmaku is experimental.** Bridge `observe("danmaku", ms)` is preferred; DOM text is a fallback that assumes one visible `mm:ss text` layout, and the record says so in its warnings. Canvas-rendered text still needs OCR.
- **Browser selectors are heuristics.** Every pattern about a third-party page lives in `browser/lib/selectors.js` and is regression-tested against snapshots derived from live pages (`browser/tests/fixtures/snapshots/`, recorded 2026-11-07). That catches drift after the fact, not before it; `npm run test:live` re-checks the live sites when you set `WEB_FORAGER_LIVE=1` and a bridge.
- **The injection screen is a screen, not a sandbox.** It matches known phrasings and will miss paraphrases. `trust: "untrusted"` and the host's own permission model are what contain a hostile page; the flag list only makes the boundary visible.
- **The private-address guard has an off switch.** `--allow-private` (or `WEB_FORAGER_ALLOW_PRIVATE=1`) exists for local fixtures and trusted intranet targets and disables the loopback/LAN/metadata check. Never set it for input you do not control.
- **CDP attach exposes the profile you attach to.** The bundled bridge uses a dedicated profile, but `WEB_FORAGER_BROWSER_CDP` reuses a browser you already run, with every cookie and login in it.

---

## Issues and feedback

**Ordinary bugs and feature requests**: the repository's [Issues](https://github.com/JiamingShi-JsPhys/web-forager/issues) page, with reproduction steps, expected behaviour, actual behaviour and your environment (operating system, Python version).

**Security vulnerabilities (this category only)**: do **not** use the public issue tracker — email `jiamingshi_git@outlook.com` instead.

- **Subject**: must carry the prefix `report_web-forager:` plus a short summary.
  - Example: `report_web-forager: path traversal can read outside the target folder`
- **Body**: must include detailed reproduction steps and the environment.

*Contributors who file clear, reproducible issues or pull requests are credited in the next release's notes and in [Acknowledgements](#acknowledgements).*

## Acknowledgements

**NotFatJustRound** — early testing and feedback.

**DeepSec** — the code-security auditor this repository is scanned with. It found the two command-injection paths closed in 1.2.3 and the supply-chain issue in the same release.

**Claude** (Anthropic) — some assistance on parts of this project: code-snippet suggestions, and suggested changes to the tests, documentation and release notes. Every suggestion was reviewed and adopted only where a test, a check or a direct verification could confirm it; the author made the final call on the wording.

[Full acknowledgements](docs/ACKNOWLEDGEMENTS.md)

## Trademarks

"Bilibili", "Zhihu", "Xiaohongshu", "arXiv", "Crossref", "PubMed", "Claude", "Codex", "CodeBuddy", "ZCode" and "DeepSeek" are trademarks or registered trademarks of their respective owners. web-forager is an independent, third-party tool with no affiliation, endorsement or sponsorship from any of them. All requests go to public pages or documented APIs; users are responsible for complying with each platform's terms.

---

## License and author

MIT. See [LICENSE](LICENSE) and [THIRD_PARTY_LICENSES.txt](THIRD_PARTY_LICENSES.txt).

**Author and maintainer**: Jiaming Shi
