---
name: web-forager
version: 1.2.0
description: >
  Polite, robots-aware web information gathering with two modes. HTTP mode
  searches 360/Bing/Sogou/WeChat, reads HTML/PDF/DOCX/XLSX/EPUB/CSV and RSS/Atom,
  collects public pages from Bilibili through a dedicated adapter and reads
  other sites as ordinary pages, discovers sitemaps, chunks long Markdown,
  caches responses, and surfs the web link by link with resumable sessions.
  Browser mode drives a real browser through a bridge for login-state pages,
  rendered content, danmaku and seven read-only playbooks covering Bilibili,
  Zhihu and Xiaohongshu. Optional scholarly lookups cover
  arXiv/Crossref/PubMed/DOI. Ships a CLI, an OpenCLI-style --agent envelope and
  two stdio MCP servers.
metadata:
  version: 1.2.0
  author: Jiaming Shi
  license: MIT
  entry_point: python run.py
  python_requires: '>=3.10'
  browser_runtime: node >= 18
---

> ## 免责声明（务必阅读）
>
> **本插件仅供学习与信息收集使用。使用者需遵守目标网站的 Terms of Service 及相关版权法律。禁止用于恶意并发攻击。严禁收集、聚合或推断特定自然人的个人信息，或将其用于人肉搜索、骚扰、跟踪等侵害他人隐私的活动；此类用法产生的法律责任由使用者自行承担。**

# web-forager

Clean-room implementation. Only `requests`, `beautifulsoup4`, `trafilatura`
and (optional) `playwright` / `pypdf` are used. No GPL/AGPL dependency.

- **Stage:** `domain_extensions` · **Sandbox:** no
- **Dependencies:** requests, beautifulsoup4, trafilatura
- **Optional:** playwright (JavaScript rendering), pypdf (PDF text)
- **Standard-library formats:** DOCX, XLSX, EPUB, CSV, RSS, Atom, sitemap
- **MCP:** `python mcp_server.py` (stdio JSON-RPC; tools: web_fetch,
  web_search, web_surf, web_scholar, web_map, web_bilibili, web_clean,
  web_doctor, web_find, web_feed) and
  `node browser/mcp_server.js` (browser_list, browser_run, browser_session,
  browser_doctor)

> **启用 JS 渲染：** 用户需自行运行
> `pip install playwright && playwright install chromium`。
> 未安装时 `--render auto` 会跳过渲染并在 `warnings` 中说明；`--render always`
> 会以**退出码 6**优雅报错，不会抛 Python Traceback。

> **启用 PDF：** 用户需自行运行 `pip install pypdf`。未安装时 PDF 请求以
> **退出码 7** 报错并提示安装命令，不会抛 Python Traceback。

## Quick Execution

Run these exact forms from the plugin root — do not read the source tree:

```bash
# one URL
python run.py --action fetch --url "<URL>" --out result.json

# keyword search, then fetch the top results
# auto = 360 + Bing; a mostly-CJK query also asks Sogou and 搜狗微信
python run.py --action fetch --query "<KEYWORDS>" --num-results 8 --max-pages 3
python run.py --action fetch --query "<KEYWORDS>" --engine all
# a Chinese person or institution name: the general engines answer with
# dictionary and directory pages, so ask the article index directly
python run.py --action fetch --query "<中文人名>" --engine weixin --max-pages 3
# when the engines return nothing useful, search the site you already trust
python run.py --action find --site the-decoder.com --query "OpenAI watermark" --max-pages 3
# or read that site's feed directly
python run.py --action feed --url https://the-decoder.com/ --num-results 10

# local HTML / Office / EPUB / CSV -> Markdown
python run.py --action clean --input page.html --out page.md --format markdown
python run.py --action clean --input paper.pdf --format markdown   # needs pypdf
python run.py --action clean --input report.docx --format markdown
python run.py --action clean --input data.xlsx --format markdown

# HTML on stdin
cat page.html | python run.py --action clean --format markdown

# scholarly APIs (normalised bibliographic records)
python run.py --action scholar --source arxiv --query "<TOPIC>" --num-results 10
python run.py --action scholar --source crossref --query "<TOPIC>"
python run.py --action scholar --source pubmed --query "<TOPIC>" --num-results 5
python run.py --action scholar --source doi --query "10.1038/nature14539"

# sitemap discovery
python run.py --action map --url "https://example.org" --limit 500

# long-page chunks and polite cache
python run.py --action fetch --url "<URL>" --chunk-size 4000 --cache

# surf: search or open a page, then follow ranked links like a human
python run.py --action surf --query "<KEYWORDS>" --depth 1 --max-pages 5 --session info-01
python run.py --action surf --url "<URL>" --depth 2 --follow all --max-pages 10

# agent envelope: {"ok":true,"data":...} or {"ok":false,"error":{code,message,hint}}
python run.py --action surf --query "<KEYWORDS>" --agent

# write into a four-zone workspace
python run.py --action fetch --url "<URL>" --root <WS>
# -> <WS>/process/web-forager/*.json|*.md + <WS>/_broadcast/web-forager_*.json
```

### Bilibili (刷 B 站)

```bash
# home feed
python run.py --action bili --mode feed --num-results 12 --max-pages 1

# one video (title, UP, stats, parts, description, recommendations)
python run.py --action bili --mode video --url BV1xx411c7mD

# recommendation list / relationship-chain browsing
python run.py --action bili --mode related --url BV1xx411c7mD --num-results 10
python run.py --action bili --mode surf --url BV1xx411c7mD --depth 2 --max-pages 3

# keyword search (360+Bing route by default; Bilibili's own search page blocks agents)
python run.py --action bili --mode search --query "Python 教程"
python run.py --action bili --mode search --query "Python 教程" --direct-search
```

## When to use

- A paper, report or documentation page must be read as clean Markdown.
- A keyword query must be resolved to sources and the top pages harvested.
- A PDF must be turned into text and document metadata (needs `pypdf`).
- A DOCX/XLSX/EPUB/CSV file or an RSS/Atom feed must become Markdown.
- A paper must be found through arXiv/Crossref/PubMed or resolved from a DOI.
- A site's page inventory must come from robots.txt/sitemap discovery.
- A long page must be split into heading-aware chunks for a context window.
- Repeated fetches should reuse a polite on-disk cache.
- Bibliographic metadata (authors, journal, DOI, abstract) must be captured.
- Tables on a page must be turned into structured rows or Markdown tables.
- A JavaScript-rendered page needs a real browser (requires Playwright).
- An assistant should browse autonomously: open search results, follow links,
  and continue a previous walk without re-fetching (`--action surf --session`).
- A tool or agent needs a machine-readable success/failure envelope (`--agent`).
- The user asks to browse Bilibili: home feed, a specific video, its UP主 and
  statistics, its recommendation list, or a chain of related videos.
- A Bilibili seed video is supplied and the user wants “相关视频”“刷下去”.
- The page needs the browser's own session: Zhihu or Xiaohongshu behind a login
  wall, lazy-loaded comments, or Bilibili danmaku (browser mode, needs a bridge).
- The user asks to “像人一样点开/滚动/看完” rather than parse a response.

Do **not** use for: login-protected content without an authorised browser
session, paywalled material, personal data, CAPTCHA/Cloudflare bypass, or
high-concurrency crawling.

## Browser mode (Node 18+)

The browser layer lives in `browser/`. It drives a real browser through a
bridge process and records what it sees with the same four core fields the HTTP
mode uses (`metadata`, `markdown`, `tables`, `warnings`) plus browser-specific
ones. It is read-only by default: like, coin, favourite, follow, share, comment,
danmaku and publish are denied unless `--allow-write` is passed after the user
authorises that single action.

```bash
# list playbooks and backends
node browser/run.js --list

# Bilibili feed, one video, episode chain, danmaku
node browser/run.js --playbook bili-feed --session bili-01 --max-items 8 --agent
node browser/run.js --playbook bili-video --url "https://www.bilibili.com/video/BV1xx411c7mD"
node browser/run.js --playbook bili-chain --url "https://www.bilibili.com/video/BV1xx411c7mD"
node browser/run.js --playbook bili-danmaku --url "https://www.bilibili.com/video/BV1xx411c7mD"

# Zhihu and Xiaohongshu search
node browser/run.js --playbook zhihu-dig --query "<KEYWORDS>" --agent
node browser/run.js --playbook xhs-dig --query "<KEYWORDS>" --agent

# plan without a browser
node browser/run.js --playbook bili-feed --dry-run

# connect a bridge (Playwright reference bridge is optional)
npm install playwright && npx playwright install chromium
WEB_FORAGER_BRIDGE="node browser/bridges/playwright-bridge.js" node browser/run.js --playbook bili-feed
```

Backends are labels only (`--backend iab|extension|cdp`); the bridge declares
its real capabilities. Without a bridge, a live run exits 3. `zhihu-dig` and
`xhs-dig` return `login_required` (exit 6) when a platform shows a login wall.
An empty feed or search reports `degraded` (exit 8) with the records attached;
an anti-bot page reports `blocked` (exit 9). `--strict-robots` checks
`robots.txt` before every navigation, and every record states whether that
check was made (`compliance.robots_checked`).

Browser sessions live in `~/.web-forager/browser/sessions/` (override with
`WEB_FORAGER_BROWSER_HOME`). With `--root <WS>`, records land in
`<WS>/process/web-forager/browser/` and `<WS>/_broadcast/`.

## Inputs and outputs

| Action | Input | Output |
|---|---|---|
| `fetch --url` | one http(s) URL | JSON with `metadata`, `markdown`, `tables`, `warnings` |
| `fetch --query` | keywords + engine | JSON with `search_results` and one record per fetched page |
| `clean --input` | local HTML/PDF/DOCX/XLSX/EPUB/CSV file | JSON or Markdown |
| `clean --url` | http(s) URL (any supported type) | JSON or Markdown |
| `clean` (stdin) | HTML/PDF/Office bytes | JSON or Markdown |
| `surf --query` | keywords | search results + BFS page trail + visited URLs |
| `surf --url` | one seed URL | BFS page trail + visited URLs |
| `scholar --source` | arxiv/crossref/pubmed/doi + query | normalised record list |
| `map --url` | site, sitemap or robots.txt URL | URL inventory + sitemap sources |
| `bili --mode feed` | home page | feed cards + optionally fetched videos |
| `bili --mode video` | BV id or video URL | one normalised video record |
| `find --site` | domain + query | that site's search page, ranked links, fetched pages |
| `feed --url` | site URL or feed URL | feed items + Markdown digest |
| `doctor` | nothing | dependency report with install hints |
| `bili --mode related` | BV id or video URL | recommendation list |
| `bili --mode surf` | BV id or keyword | relationship-chain traversal |
| `bili --mode search` | keyword | search results + fetched videos |

## Key options

| Option | Default | Meaning |
|---|---|---|
| `--engine auto\|all\|360\|bing\|sogou\|weixin\|duckduckgo` | `auto` | search backend; auto=360+Bing (mostly-CJK queries: 360+Sogou+搜狗微信, Bing fallback), all adds Sogou and 搜狗微信 |
| `--max-pages N` | `3` | result pages to fetch; `0` returns the search results only |
| `--site HOST` | off | `find`: the site whose own search page is read |
| `--probe` | off | `doctor`: ask every search engine once and report which answer |
| `--proxy URL` | env | route every request through this proxy (`HTTPS_PROXY` / `ALL_PROXY` otherwise) |
| `--search-pages N` | `1` | result pages read per engine |
| `--source arxiv\|crossref\|pubmed\|doi` | `arxiv` | scholarly source |
| `--sort relevance\|submittedDate\|lastUpdatedDate` | `relevance` | arXiv sort |
| `--limit N` | `500` | map: maximum URLs |
| `--max-sitemaps N` | `5` | map: sitemap files to read |
| `--render auto\|never\|always` | `auto` | Playwright rendering policy |
| `--wait-for SELECTOR` | off | Playwright: wait for a CSS selector |
| `--scroll N` | `0` | Playwright: wheel-scroll N times |
| `--delay` | `1.0` | per-origin politeness delay (seconds) |
| `--timeout` | `20` | request timeout (seconds) |
| `--max-chars` | `20000` | Markdown truncation (`0` = unlimited) |
| `--chunk-size N` | `0` | emit heading-aware `chunks` of about N chars |
| `--cache` | off | reuse `~/.web-forager/cache` |
| `--cache-ttl N` | `3600` | cache lifetime (seconds) |
| `--cache-dir DIR` | user dir | custom cache directory |
| `--no-tables` | off | skip table extraction |
| `--keep-links` | off | keep hyperlinks in Markdown |
| `--images` | off | keep image references |
| `--format json\|markdown` | `json` | stdout format |
| `--agent` | off | OpenCLI-style `{ok,data}` / `{ok,error}` envelope |
| `--out FILE` | stdout | write result to a file (wins over `--root`) |
| `--root DIR` | off | four-zone workspace root; writes `process/web-forager/` and `_broadcast/` |
| `--mode auto\|feed\|video\|search\|related\|surf` | `auto` | Bilibili mode |
| `--depth` | `1` | Bilibili chain / web surf depth |
| `--follow same-site\|all\|none` | `same-site` | surf link policy |
| `--session NAME` | off | resumable surf session (`~/.web-forager/sessions/`) |
| `--direct-search` | off | explicit override for `search.bilibili.com` only |
| `--ignore-robots` | off | **dangerous**; only for authorised resources |

## Compliance guardrails

- robots.txt is fetched once per origin and cached for one hour; matching uses
  longest-rule-wins with `*` and `$` support (RFC 9309 subset).
- `401/403/5xx` or an unreachable robots.txt → conservative deny.
- Every request carries an explicit information-gathering User-Agent; override it with
  `--user-agent` so you are contactable.
- Per-origin rate limiting; no concurrency fan-out.
- Max 5 redirects, 8 MB response cap, http/https only.
- Exit code `3` means robots.txt denied the request — respect it.
- PDF text extraction requires `pypdf`; without it, exit code `7` is returned.
- DOCX/XLSX/EPUB archives are capped by entry count and uncompressed size;
  XML is parsed with defusedxml when available, and DOCTYPE internal subsets /
  ENTITY declarations are always rejected.
- Scholarly APIs (arXiv/Crossref/PubMed) are official query endpoints and are
  rate-limited; sitemap/robots discovery files are read without a per-URL robots
  check, but every page later opened is still checked.
- `surf` follows only links already present in the page, never constructs URLs,
  never submits forms and never runs page JavaScript; every hop is re-checked
  against robots.txt and the per-origin rate limiter.
- Bilibili: `api.bilibili.com` and `search.bilibili.com` disallow all generic
  agents, so only `www.bilibili.com/` and `/video/BV…` are read by default.
  Search resolves through the 360+Bing discovery route; `--direct-search` is an
  explicit, logged override that asks the JSON search endpoint first (one
  home-page visit supplies the `buvid3` cookie) and falls back to the search
  page. No login, comments or private data.

## MCP servers

```bash
python mcp_server.py          # HTTP mode
node browser/mcp_server.js    # browser mode
```

Both speak newline-delimited JSON-RPC 2.0 on stdin/stdout; `.mcp.json`
registers them as `web-forager` and `web-forager-browser`. HTTP tools:
`web_fetch`, `web_search`, `web_surf`, `web_scholar`, `web_map`,
`web_bilibili`, `web_clean`, `web_doctor`, `web_find`, `web_feed`. Browser tools:
`browser_list`, `browser_run`, `browser_session`, `browser_doctor`. Tool failures return `isError: true` with
`{"ok":false,"error":{...}}` as text; protocol errors use JSON-RPC codes.

Two switches keep a search cheap: `max_pages: 0` returns the result list with
no page bodies (fetch one with `web_fetch` and a small `max_chars`), and
`respect_robots: false` reads a page robots.txt disallows — only for resources
you are authorised to read. A search whose results do not mention the query
comes back with a `warnings` entry saying so.

Browser runs cost far more than HTTP reads; keep them small:

- pass `out` to `browser_run` so the full record goes to disk and only a
  summary comes back;
- take no screenshots unless the layout is the question — one image costs
  about as much context as a page of prose;
- keep `maxScreens` at or below 5 and `minInterval` at or above 3000 ms, and
  split long walks into runs resumed from `--session`;
- treat `bili-danmaku` as experimental: it prefers the bridge's `observe`
  call and marks DOM fallback text `partial`;
- login state comes from a browser you already run (`WEB_FORAGER_BROWSER_CDP`
  with `--backend cdp`, or `WEB_FORAGER_BROWSER_PROFILE`), never from the
  plugin signing in.

HTTP mode is not a general search client: `web_scholar` (arXiv / Crossref /
PubMed / DOI) and `web_map` (robots.txt and sitemap discovery) are the parts a
search CLI does not cover, and they are the reason to reach for it.

## Tests

```bash
python -m pytest tests -q
npm run test:browser
```

The Python suite uses a temporary local HTTP server; no public network access
needed. The browser suite uses a fake backend and a fake bridge that speaks the
wire protocol, so the CLI runs end to end without a browser.
