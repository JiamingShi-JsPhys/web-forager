# web-forager

> ## ⚠️ 免责声明（务必阅读）
>
> **本插件仅供学术研究使用。使用者需遵守目标网站的 Terms of Service 及相关版权法律。禁止用于抓取个人隐私数据或进行恶意并发攻击。**

A clean-room, robots-aware web fetcher for academic research. It turns a URL
or a keyword query into clean Markdown plus structured bibliographic metadata,
extracts text from PDFs, and can let an AI assistant surf the web link by link
like a person reading — including a resumable browse session. It also includes
a Bilibili adapter for reading feeds, video pages and recommendation chains
through pages that robots.txt permits.

- **License:** MIT
- **Entry point:** `python run.py --action fetch|clean|bili|surf`
- **Runtime:** Python ≥ 3.10
- **Allowed dependencies:** `requests` (Apache-2.0), `beautifulsoup4` (MIT),
  `trafilatura` (Apache-2.0), optional `playwright` (Apache-2.0) and optional
  `pypdf` (BSD-3-Clause). **No GPL / AGPL dependency is used.**

---

## 功能

| 能力 | 说明 |
|---|---|
| URL 抓取 | 抓取单页正文、标题、作者、期刊、DOI、摘要、关键词等元数据 |
| 关键词搜索 | `auto` 并行合并 360 + Bing（按查询词覆盖度去重重排）；`all` 再加 Sogou；也可单选 `360` / `bing` / `sogou` / `duckduckgo` |
| HTML → Markdown | 优先用 trafilatura 抽取正文；缺失时使用内置的 BeautifulSoup 转换器 |
| PDF → Markdown | 使用可选依赖 `pypdf` 抽取文本与文档元数据（标题/作者/页数）；缺少依赖时返回退出码 7，不抛 Traceback |
| 表格抽取 | `<table>` → 结构化 rows + Markdown 表格，同时写入 JSON |
| 文献元数据 | Highwire `citation_*`、Dublin Core、OpenGraph、JSON-LD (`ScholarlyArticle`) |
| 自主浏览 | `--action surf`：先搜索或打开种子页，再按查询相关度跟随页内链接（BFS，可设深度/同站策略），像人一样“点进去看” |
| 可续会话 | `--session NAME` 把已访问 URL 与浏览轨迹存到 `~/.web-forager/sessions/`，下次从断点继续，不重复抓取 |
| Agent 协议 | `--agent` 输出 `{"ok":true,"data":…}` / `{"ok":false,"error":{"code","message","hint"}}`，便于 AI 助手稳定解析 |
| 动态渲染 | 可选 Playwright；`--render auto` 只在检测到 JS 空壳时启用；未安装时 `--render always` 返回退出码 6 |
| B 站浏览 | 首页推荐、视频详情、相关推荐、关系链“刷”视频；元数据来自页面内嵌 `__INITIAL_STATE__` |
| 合规 | robots.txt 检查（RFC 9309 子集）、学术 User-Agent、按站点限速、响应体上限 |

## 安装与集成

本目录既是一个可独立运行的 Python 工具，也是一个标准的多平台插件包。

### 方式 A：独立安装（不依赖主库）

```bash
cd plugins/web-forager
pip install -r requirements.txt
python run.py --version
python run.py --action clean --input page.html --format markdown
```

把整个目录复制到任意位置即可使用；`manifest.json`、`SKILL.md`、`run.py`
都是相对路径，不依赖 `chelate-shell`。

### 方式 B：作为 Claude Code / Codex / CodeBuddy / DSH 插件

已按 `chelate-shell` 的规范配齐多平台入口：

| 平台 | 清单位置 |
|---|---|
| Claude Code | `.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json` |
| Codex | `.codex-plugin/plugin.json` + `.codex-plugin/marketplace.json` |
| CodeBuddy | `.codebuddy-plugin/plugin.json` + `.codebuddy-plugin/marketplace.json` |
| DSH | `.dsh-plugin/plugin.json` + `.dsh-plugin/index.js` |

在 Claude Code 中把本目录（或它的父目录）加为 marketplace，然后安装
`web-forager`；`SKILL.md` 会自动作为技能暴露给模型。

### 方式 C：与 `chelate-shell` 主库联动

传入 `--root` 即可把每次运行写进 Chelate 四区工作区：

```bash
python run.py --action fetch --url "https://example.org/article" --root /path/to/workspace
```

写入位置：

```
<WS>/process/web-forager/web-forager_<timestamp>_<slug>.json
<WS>/process/web-forager/web-forager_<timestamp>_<slug>.md
<WS>/_broadcast/web-forager_<timestamp>_<slug>.json   # 索引条目
```

- `process/` 存放中间产物，`_broadcast/` 存放一条可被后续会话读取的索引；
- 不写入 `material/` 或 `results/`，避免把抓取结果误当成用户素材或最终交付；
- `--out FILE` 优先于 `--root`：给了 `--out` 就只写指定文件。

### 可选：JavaScript 动态渲染

```bash
pip install playwright && playwright install chromium
```

**未安装 Playwright 时不会崩溃：**

- `--render auto`：跳过渲染，在 `warnings` 中写一条原因，继续输出静态 HTML 的抽取结果；
- `--render always`：以**退出码 6**结束，并打印
  `error: dynamic rendering unavailable: Playwright is not installed...`，
  不会出现 Python Traceback。安装上面的两条命令后即可开启完整功能。

### 可选：PDF 文本抽取

```bash
pip install pypdf
```

`pypdf` 采用 BSD-3-Clause 许可，是可选依赖。未安装时，PDF 请求会以**退出码 7**
结束并提示 `pip install pypdf`，不会抛出 Traceback；HTML 抓取不受影响。
扫描版 PDF（纯图片、没有文字层）不做 OCR，只会返回空页提示。


## 用法

### 1. 抓取单个 URL

```bash
python run.py --action fetch --url "https://example.org/article" --out article.json
```

输出 JSON 中的 `results[0]` 包含：

```json
{
  "url": "...",
  "final_url": "...",
  "status": 200,
  "title": "...",
  "metadata": {
    "authors": ["..."],
    "published": "2025-03-14",
    "journal": "...",
    "doi": "10.1234/....",
    "abstract": "...",
    "keywords": ["..."],
    "canonical_url": "..."
  },
  "markdown": "# ...",
  "tables": [{"caption": "...", "headers": ["..."], "rows": [["..."]]}],
  "warnings": []
}
```

### 2. 按关键词搜索并抓取

```bash
# 默认 auto：360 + Bing 并行，按查询词覆盖度合并去重
python run.py --action fetch --query "robots.txt 学术爬虫" --num-results 8 --max-pages 3

# 三引擎（Sogou 可能触发人机验证，失败会被记录而不是中断）
python run.py --action fetch --query "Python 教程" --engine all

# 单一引擎
python run.py --action fetch --query "Python 教程" --engine 360
```

`--engine` 可选 `auto`（默认）、`all`、`360`、`bing`、`sogou`、`duckduckgo`。
`auto`/`all` 的每条结果都带 `source` 字段，重复 URL 会被去掉。

### 3. 清洗本地 HTML / PDF

```bash
python run.py --action clean --input page.html --out page.md --format markdown
python run.py --action clean --input paper.pdf --format markdown
cat page.html | python run.py --action clean --format markdown
```

### 4. 刷 B 站（`--action bili`）

```bash
# 首页推荐（服务端渲染，robots.txt 允许 /）
python run.py --action bili --mode feed --num-results 12 --max-pages 1

# 单个视频：标题、UP主、播放/弹幕/点赞、分P、简介、相关推荐
python run.py --action bili --mode video --url BV1xx411c7mD

# 只看相关推荐
python run.py --action bili --mode related --url BV1xx411c7mD --num-results 10

# 沿着“相关推荐”关系链往下刷（depth=2 表示再走两层）
python run.py --action bili --mode surf --url BV1xx411c7mD --depth 2 --max-pages 3

# 关键词搜索（默认走 360+Bing 找视频 URL；B 站自己的搜索页被其 robots.txt 全站禁止）
python run.py --action bili --mode search --query "Python 教程"
```

`--mode auto`（默认）会按输入自动选择：有 `--query` 走 search，有 `--url` 走
video，两者都没有则走 feed。

> **关于 B 站搜索的合规说明**：`search.bilibili.com/robots.txt` 对
> `User-agent: *` 写了 `Disallow: /`，所以 web-forager 默认**不直接请求该搜索页**，
> 而是用 360+Bing 找 `bilibili.com/video/` 链接再抓取（robots 允许的视频页）。
> 搜索引擎对 B 站视频的索引并不稳定；如果你确认自己有权访问该搜索页，可显式加
> `--direct-search`（仅放开这一个搜索请求，视频页仍然检查 robots）。
> 更稳妥的做法是用 `--url` 提供一个种子视频，再沿着相关推荐“刷”。

### 5. 自主浏览网页（`--action surf`）

`surf` 的目标是让 AI 助手像人一样搜索、点开结果、再顺着页内链接继续看：

```bash
# 从一个关键词开始：先搜索，再打开前 N 个结果，并跟随页内链接（同站）
python run.py --action surf --query "Python 教程" --depth 1 --max-pages 5 --session py-tutorial

# 从一个 URL 开始，允许跨站跟随
python run.py --action surf --url "https://example.org/tutorial" --depth 2 --follow all

# 继续上次的浏览：已访问的 URL 会自动跳过
python run.py --action surf --query "Python 教程" --session py-tutorial --max-pages 5
```

输出结构：

```json
{
  "action": "surf",
  "seed": "Python 教程",
  "mode": "surf",
  "depth": 1,
  "follow": "same-site",
  "session": "py-tutorial",
  "search_results": [{"title": "...", "url": "...", "source": "360"}],
  "trail": [{"step": 1, "level": 0, "from": "search", "url": "...", "title": "..."}],
  "visited": ["..."],
  "pages": [{"url": "...", "title": "...", "markdown": "...", "links": [...]}],
  "results": ["..."]
}
```

- `--follow same-site`（默认）只跟同站链接；`all` 允许跨站；`none` 只抓种子页；
- `--depth 0` 只看种子页，`1` 看一层，以此类推；
- `--max-pages` 是本次最多抓取/搜索的页数，配合 `--delay` 保证礼貌；
- robots.txt 拒绝的链接会作为带 `error` 的条目写进 `pages` 和 `trail`，不会中断整次浏览；
- 会话文件位于 `~/.web-forager/sessions/<name>.json`，只保存 URL 列表与轨迹，不保存正文。

### 6. 给 AI 助手用的 `--agent` 协议

所有 action 都支持 `--agent`。成功时 stdout 只有一个 JSON 对象：

```json
{"ok": true, "data": {"tool": "web-forager", "action": "surf", "...": "..."}}
```

失败时退出码保持原语义，stdout 为：

```json
{
  "ok": false,
  "error": {
    "code": "robots_denied",
    "message": "robots.txt denied this request: ...",
    "hint": "use --ignore-robots only for resources you are authorised to access"
  }
}
```

常见 `code`：`invalid_argument`、`invalid_url`、`robots_denied`、`fetch_failed`、
`extraction_failed`、`render_unavailable`、`pdf_unavailable`、`pdf_extraction_failed`、
`interrupted`、`unexpected_error`。

### 7. 常用选项

| 选项 | 默认 | 说明 |
|---|---|---|
| `--engine auto\|all\|360\|bing\|sogou\|duckduckgo` | `auto` | 搜索后端；`auto`=360+Bing，`all`=360+Bing+Sogou |
| `--render auto\|never\|always` | `auto` | 是否用 Playwright 渲染动态页面 |
| `--delay` | `1.0` | 每个站点两次请求之间的最小间隔（秒） |
| `--timeout` | `20` | 单请求超时（秒） |
| `--max-chars` | `20000` | Markdown 截断长度，`0` 表示不限 |
| `--no-tables` | 关 | 不抽取表格 |
| `--keep-links` | 关 | Markdown 中保留超链接 |
| `--images` | 关 | Markdown 中保留图片引用 |
| `--format json\|markdown` | `json` | 标准输出格式 |
| `--agent` | 关 | OpenCLI 风格 `{ok,data}` / `{ok,error}` 信封 |
| `--out FILE` | stdout | 写入指定文件（优先于 `--root`） |
| `--root DIR` | 关 | Chelate 工作区根目录；写入 `process/web-forager/` 与 `_broadcast/` |
| `--mode auto\|feed\|video\|search\|related\|surf` | `auto` | B 站模式 |
| `--depth` | `1` | B 站关系链 / 网页 surf 的层数 |
| `--follow same-site\|all\|none` | `same-site` | surf 的链接跟随策略 |
| `--session NAME` | 关 | surf 的可续会话名（`~/.web-forager/sessions/`） |
| `--direct-search` | 关 | **显式越权**：直接请求 `search.bilibili.com`（该站 robots 禁止通用代理） |
| `--ignore-robots` | 关 | **危险**：跳过 robots.txt 检查，仅用于你有明确授权的资源 |

### 退出码

| 码 | 含义 |
|---|---|
| 0 | 成功 |
| 2 | 参数 / URL 错误 |
| 3 | robots.txt 拒绝 |
| 4 | 网络或 HTTP 失败 |
| 5 | 无法抽取正文 / PDF 解析失败 |
| 6 | 请求了 Playwright 但不可用 |
| 7 | 需要解析 PDF 但 `pypdf` 未安装 |

## 合规设计

1. **robots.txt**：每个 origin 只取一次并缓存 1 小时。匹配规则遵循 RFC 9309
   的核心语义——`*` 通配、`$` 结尾锚定、最长规则优先、同长时 Allow 优先、
   按 User-Agent 分组选择。`401/403/5xx` 或 robots.txt 不可达时按 RFC 保守判定为
   禁止；`404/410` 判定为允许。`Crawl-delay` 会被采用（上限 30 秒）。
2. **学术 User-Agent**：默认
   `WebForager/0.2 (Academic Research; +https://example.org/web-forager; contact: research@example.org)`。
   请通过 `--user-agent` 换成你自己可被联系到的标识。
3. **限速**：同 origin 串行限速，默认 1 秒；不做并发轰炸，surf 也复用同一限速器。
4. **边界**：只允许 http/https；最多 5 次重定向；响应体上限 8 MB；
   只处理 HTML/XML/纯文本/JSON/PDF；PDF 需要可选的 `pypdf`，缺失时明确返回退出码 7。
5. **不绕过**：不处理登录、验证码、Cloudflare 挑战或付费墙；不抓取个人信息。
6. **B 站专门处理**：`api.bilibili.com` 与 `search.bilibili.com` 的 robots.txt
   都禁止通用代理，因此 B 站适配器只读 `www.bilibili.com/`（首页）与
   `/video/BV…`（视频页）这类 robots 允许的页面，并从页面内嵌的
   `window.__INITIAL_STATE__` 提取数据；不请求评论 API、不模拟登录、不绕风控。
   `--direct-search` 只放开搜索页这一次请求，且会在输出中记录 `route` 与 `note`。
7. **自主浏览（surf）**：只跟随页面中本来就存在的 `<a href>`，不构造猜测 URL、
   不提交表单、不执行页面脚本；每一跳仍然经过 robots.txt 与同 origin 限速。
   会话文件只记录 URL 与轨迹，便于续跑，不保存正文。

## 净室开发声明

本插件的全部源码均为本项目从零编写：

- **没有**复制、翻译或改写 Crawlee、Scrapy、Colly、Katana 或其他爬虫框架的代码；
- 仅参考“礼貌延迟、robots 缓存、正文抽取管线”这类通用架构思想；
- 核心逻辑只使用 Python 标准库 + `requests` + `BeautifulSoup` + `trafilatura`；
- 可选依赖为 `playwright` 与 `pypdf`；
- 未引入任何 GPL / AGPL 许可的库（见 `THIRD_PARTY_LICENSES.txt`）。

## 目录结构

```
web-forager/
├── .claude-plugin/               Claude Code 清单 + marketplace
├── .codex-plugin/                Codex 清单 + marketplace
├── .codebuddy-plugin/            CodeBuddy 清单 + marketplace
├── .dsh-plugin/                  DSH 清单 + index.js
├── manifest.json                 插件清单
├── run.py                        CLI：fetch / clean / bili / surf + --root + --agent
├── scripts/
│   ├── __init__.py
│   ├── engine.py                 robots、抓取、360/Bing/Sogou 搜索、Markdown、元数据、渲染、surf
│   ├── pdf.py                    PDF 文本与元数据抽取（可选 pypdf）
│   └── bilibili.py               B 站适配器（首页/视频/相关推荐/关系链）
├── tests/
│   ├── conftest.py               本地 HTTP 站点夹具（无外网依赖）
│   ├── test_engine.py            纯函数与解析器单测
│   ├── test_bilibili.py          B 站解析与本地集成测试
│   ├── test_fetch.py             本地服务器集成测试
│   ├── test_search_pdf_surf.py   360/Sogou、PDF、链接发现、surf 会话与 --agent
│   ├── test_cli.py               CLI、退出码与 --root
│   └── fixtures/                 HTML / RSS / DDG / PDF / B 站样例
├── requirements.txt
├── THIRD_PARTY_LICENSES.txt
├── SKILL.md
├── LICENSE                       MIT
└── README.md
```

## 测试

```bash
python -m pytest tests -q
```

测试不访问公网：`conftest.py` 会启动一个临时本地 HTTP 服务器，并在其中提供
`robots.txt`、文章页、PDF、搜索页样例、多跳 surf 页面与受保护路径，用来验证
robots 拒绝、正文抽取、表格、过滤、PDF、surf 会话与 CLI 退出码。

## 已知限制

- PDF 只抽取文字层；扫描件需要 OCR，本插件不做。
- `--render auto` 只是启发式判断（可见文本过短 + SPA 标记 / 多个 `<script>`），
  复杂站点可能需要 `--render always`。
- 搜索结果来自 360 / Bing / Sogou 的公开结果页，可用性受网络环境影响；
  Sogou 可能触发人机验证，默认 `auto` 不包含它。
- B 站只读公开页面：不登录、不取评论、不取字幕；私人收藏/关注流不在范围内。
- surf 只跟随页面里的普通链接，不点击按钮、不执行 JS、不处理登录墙。
- robots.txt 不可达时保守拒绝是 RFC 建议的行为；如目标站点确实授权，
  可使用 `--ignore-robots`，但请自行确认合规性。

## License

MIT © 2026 Jiaming Shi
