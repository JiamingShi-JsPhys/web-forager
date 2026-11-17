# web-forager 参考手册

> [web-forager](../README_zh.md) 的一部分。这里放查询类内容：记录结构、动作、退出码、环境要求、目录结构与测试。

[English](REFERENCE.md) · **简体中文**

---

## MCP 服务

<details>
<summary>工具名</summary>

HTTP 工具：`web_fetch`、`web_search`、`web_research`、`web_surf`、`web_scholar`、`web_map`、`web_bilibili`、`web_doctor`、`web_find`、`web_feed`。浏览器工具：`browser_list`、`browser_run`、`browser_session`、`browser_doctor`。

MCP 调用始终只读，并保持目标页边界：没有任何工具参数能改 `respect_robots`、`robots_policy`、`input_gate`、代理、浏览器桥命令或写开关，本地文件 `clean` 动作也不对 MCP 暴露。搜索引擎与学术查询接口有单独的用户级策略（命令行 `--query-robots`，服务进程环境变量 `WEB_FORAGER_QUERY_ROBOTS`），默认 `warn`：会读取被禁止的查询路径，并在引擎报告里写明这次覆盖；`respect` 会拒绝。模型无法通过工具调用改变它。

</details>

直接测试协议：

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | python mcp_server.py
```

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' | node browser/mcp_server.js
```

## 浏览器模式

浏览器层位于 `browser/`，需要 Node.js 18 或更新。它默认只读：点赞、投币、收藏、关注、分享、评论、弹幕与发布一律拒绝，除非用户明确授权某一次动作后传入 `--allow-write`。

```bash
npm install playwright && npx playwright install chromium
node browser/run.js --doctor
node browser/run.js --playbook bili-feed --session bili-01 --max-items 8 --agent
node browser/run.js --playbook zhihu-dig --query "强化学习" --agent
node browser/run.js --playbook wechat-dig --url "https://mp.weixin.qq.com/s/..." --agent
```

| 剧本 | 作用 | 需要 |
|---|---|---|
| `bili-feed` | 首页信息流，逐屏捕捉未见卡片 | 无 |
| `bili-video` | 单个视频与可见评论 | `--url` 或 `--bvid` |
| `bili-chain` | 跟随「下一话」，并从会话续接链路 | `--url`、`--bvid` 或会话链路 |
| `bili-danmaku` | 带时间戳的弹幕，优先用桥的 `observe`，DOM 文本兜底（实验性） | `--url` 或 `--bvid` |
| `zhihu-dig` | 搜知乎、排序链接、捕捉最佳未见页面 | `--query` |
| `xhs-dig` | 搜小红书公开笔记、排序 `/explore` 链接、捕捉一条 | `--query` |
| `search-dig` | 搜 B 站、排序卡片、打开最佳未见结果 | `--query` |
| `wechat-dig` | 单篇公众号文章；遇到环境校验页就如实报告，不把错误页当正文 | `--url` |

公众号是 HTTP 模式唯一走不完的一类：`mp.weixin.qq.com` 在 robots.txt 里禁止 `/s`，即使加 `--robots-policy warn`，文章 URL 也会返回「环境异常」或跳转到验证码页，而不是正文；HTTP 记录会写成 `verification_required`（退出码 9），不会把错误页当成内容交出去。`wechat-dig` 在真实浏览器配置里打开同一个 URL：该配置已通过微信校验时能读到正文，没通过时报告 `blocked`，不会去解验证码。

装好 `playwright` 与它的 Chromium 后，自带的桥会被自动启用；`--bridge` 或 `WEB_FORAGER_BRIDGE` 用于指向别处的桥。命令按空白拆分后直接启动，不经过 shell——路径含空格时加引号，参数照常写；管道、`&&` 与重定向不会被解释。`WEB_FORAGER_BROWSER_HEADFUL=1` 显示窗口；`WEB_FORAGER_BROWSER_PROFILE=/path` 复用持久化配置目录（`extension` 后端的登录态正是靠它保留）；`WEB_FORAGER_BROWSER_CDP=http://127.0.0.1:9222` 接管你已有的浏览器（`cdp`）。桥通过可选的 `describe` 调用声明自己实现了什么；不实现 `describe` 的桥会被标记为 `declared: false`，所有能力一律为 false。

登录一次的做法：运行 `python browser/launch_chrome.py`（默认使用 `~/.web-forager/browser/profile`，**CDP 默认关闭**；加 `--cdp` 才开启一个环回 CDP 端口，默认随机、`--port 9222` 可固定）。不加 `--cdp` 时，用默认后端运行浏览器即可复用该配置；加了 `--cdp` 才需要给剧本加 `--backend cdp`。CDP 本身没有认证：端口只留在本机，用完关闭浏览器。`--storage-state FILE` 在运行前载入 Playwright 状态文件；`--save-storage-state FILE` 在运行后写出，权限为 `0600`，路径落在 `--root` 内会被拒绝。这个文件包含 Cookie 与登录态：按凭据对待，不要提交进 git，也不要复制到共享机器。

`--strict-robots` 在每次导航前读取 `robots.txt`，被禁止的路径以 `robots_denied`（退出码 3）停下。不加这个开关时记录同样说清楚：`compliance.robots_checked` 为 `false`。读到了页面却什么也没找到会报告 `degraded`（退出码 8）并附上记录；反爬或错误页以 `blocked`（退出码 9）停下；站点要求登录是 `login_required`（退出码 6）。

浏览器模式是插件里最贵的一环，默认值因此开得很小：完整记录用 `--out result.json`（MCP 传 `out:`）落盘，默认不截图，`--max-screens 5` 与 `--min-interval 3000` 保持礼貌，长时间刷屏宁可用 `--session` 分几次续跑。

---

## 搜索引擎不可用时

默认搜索走 `auto`。以中日韩文字为主的查询会同时问 360、搜狗与搜狗微信——中文人名或机构名通常只有微信文章索引这条渠道有内容——并且不会交给 Bing：Bing 会把中文短语拆成单字，返回词典页。这类单字词典页无论来自哪个引擎都会被过滤掉；确有需要时可以用 `--engine bing` 明确指定。

另有两条完全不依赖搜索引擎的路：

```bash
python run.py --action find --site the-decoder.com --query "OpenAI watermark" --max-pages 3
python run.py --action feed --url https://the-decoder.com/ --num-results 10
```

`find` 尝试站点自带的搜索地址（`/?s=`、`/search?q=` 等四种），按查询词给页面链接排序并抓取最相关的几篇。`feed` 从页面的 `<link rel=alternate>` 发现 RSS/Atom 并读取。`doctor --probe` 对每个引擎各问一次，报告当前网络下哪些可用；`doctor` 还会显示正在使用的代理（凭据已抹去）。请求会遵循 `HTTPS_PROXY` / `ALL_PROXY`，`--proxy URL` 可为一次运行覆盖它们。

---

## 更多命令行示例

每条命令单独一个代码块，复制时不用删掉相邻的行。

**抓一个 B 站视频。**

```bash
python run.py --action fetch --url "https://www.bilibili.com/video/BV1xx411c7mD"
```

**抓一个需要 JS 渲染的页面。**

```bash
python run.py --action fetch --url "https://www.zhihu.com/" --render auto
```

**冲浪一个站点，之后用会话续游。**

```bash
python run.py --action surf --url "https://www.zhihu.com/" --depth 1 --max-pages 5 --session zhihu-01
```

**把本地 PDF 清成 Markdown。**

```bash
python run.py --action clean --input notes.pdf --format markdown
```

**从站点地图列出最多 500 个页面 URL。**

```bash
python run.py --action map --url "https://example.org" --limit 500
```

**读取 B 站首页信息流。**

```bash
python run.py --action bili --mode feed --max-items 10
```

---

## 记录与输出

### 每页一条记录

| 字段 | HTTP 模式 | 浏览器模式 |
|---|---|---|
| `metadata`、`markdown`、`tables`、`warnings` | 有 | 有 |
| `trust`、`injection_flags`、`injection_findings` | 有 | 有 |
| `url`、`title` | 有（`url` 与 `final_url`） | 有 |
| `status`、`content_type`、`document_kind`、`cached`、`rendered`、`render_fallback`、`fetched_at`、`chunks`、`links` | 有 | 无 |
| `schema_version`、`captured_at`、`playbook`、`backend`、`compliance`、`viewport_evidence`、`interaction_trace` | 无 | 有 |

`render_fallback` 为 `true` 表示服务器只返回了极小的脚本壳，HTTP 模式在抽取前用 Playwright 重渲染了一次。`fetch --query` 每次最多允许两次这样的重渲染，每次会多花数秒。

`injection_findings` 是一个列表，每项包含 `{code, severity, confidence, span, snippet, context}`。`span` 是扫描文本里的字符区间，`severity` 为 `hard` 或 `soft`，`context` 为 `direct`、`quote` 或 `example`。硬规则描述具体动作（伪造 system 标签、外传密钥、`curl ... | sh`、`rm -rf /`），只有命中硬规则时 `--input-gate strict` 才扣留正文；软规则是“忽略之前的指令”和角色切换，只报告、不扣留，因为论文与安全文章会合法引用它们。扫描用重叠窗口覆盖全文，发生在 `max_chars` 截断之前；`warnings` 第一条会重复最多三条命中片段。

搜索结果按查询覆盖度、短语与标题命中、域名先验、摘要时效与引擎顺序排序，**只有一个引擎应答时同样排序**。每条结果带 `coverage`、`matched_terms`、`relevance` 与 `language_match`。结果包含完整短语，或至少两个有意义的查询词且覆盖一半查询时，才算相关；只重复一个产品名的异语言页面会标 `language_match: false`。跑题结果排在最后，真有至少三条相关结果时直接剔除；否则保留并在 `warnings` 里说明数量。最终列表每个域名最多两条，避免单一站点挤掉其他来源；来源不足时再用溢出的结果补满。首轮结果过少时会用简化查询重试一次（去掉引号与常见停用词，或把带空格的中文查询合并），重试会在 `engine_report` 里标 `query_variant`。搜索标题与摘要也走同一套注入扫描，命中的结果会带自己的 `injection_flags` 与 `injection_findings`。

排序前会先规范化 URL：`utm_*`、`fbclid`、片段、`www.`、末尾斜杠与 `/amp` 不再把同一篇文章算成两条结果。被多个引擎同时返回的结果会获得 RRF 加分；标题与查询完全一致时比“标题包含短语”略高。匹配阶段使用轻量英文词形归一，所以 `injection` 能遇到 `injections`，但显示的查询与正文不变。搜索载荷还带 `search_quality: {query, engine, returned, relevant, off_topic, language_mismatch, engines_answered, engine_errors, dropped_off_topic, returned_before_filter}`，供不想解析英文 warnings 的智能体直接读取。

加 `--core` 时返回共享形状：

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

`mode` 为 `http` 或 `browser`，`source` 标明产出方，`extra` 保留两种模式不共享的全部字段。同样的折叠也提供库调用：Python 侧是 `engine.normalize_record()`，浏览器侧是 `browser/lib/record.js` 的 `normalizeRecord()`。

`results` 是给智能体循环用的索引，不是每页正文的第二份拷贝。搜索时它只带 `url`、`title`、`snippet`、`status`、`content_type`、`markdown_chars`、`tables` 以及可能的 `warnings` 或 `error`；Markdown 正文只在 `pages` 里出现一次，单页 `fetch` 则把它放在顶层。要旧行为加 `--full-results`（CLI）或 `fullResults: true`（MCP）。

### 工作区输出

```bash
python run.py --action fetch --url "https://example.org/article" --root <WS>
```

只写这些位置：

```text
<WS>/process/web-forager/web-forager_<timestamp>_<slug>.json
<WS>/process/web-forager/web-forager_<timestamp>_<slug>.md
<WS>/_broadcast/web-forager_<timestamp>_<slug>.json
```

`material/` 与 `results/` 属于用户与编排器，web-forager 从不写入。浏览器捕捉遵循同一套规则，落在 `<WS>/process/web-forager/browser/` 与 `<WS>/_broadcast/`。

---

---

## research 输出

`research --query` 先宽召回，再集中读取少数不同 host。新增字段：

| 字段 | 含义 |
|---|---|
| `intent` | 关键词分类器给出的 `{intent, confidence, signals}` |
| `strategy` | `{breadth, search_pages, targeted_site, targeted_sites, targeted_by_site, official_entries, focus_*}` |
| `seeds` | 入选结果及 `authority_tier`、`authority_score`、`reason` |
| `evidence` | `[{url, title, authority_tier, authors, published_at, date_source, passages, partial?}]` |
| `freshness` | `{newest, oldest, dated_sources, undated_sources, newest_age_days, all_stale}` |
| `answerability` | `{level, coverage, authority_level, partial_only, source_count, host_count, view_hosts, multi_view, stale, reason}` |
| `skipped` | 未使用页面及 `code`（`robots_denied`、`browser_required`、`browser_required_low_value`、`no_matching_passage` 等） |

宽召回里没有相关的高权威来源时，第二遍按顺序尝试：直接读取已知官方入口页
（Python asyncio、Go 并发、Rust、MDN、微软 Wi-Fi 支持），再读站点自己的搜索页
（微软支持、MDN），最后才对非中文问题发一次 `site:` 查询。前两条不依赖搜索引擎
是否支持 `site:`。新闻题没有任何可用引擎结果时，会回退到中新网财经公开 RSS；
带日期的标题与摘要标为 `feed_headline`，绝不扩写成伪造的全文；正文没有日期时，
抓取到的页面继承 feed 的发布日期。每次聚焦抓取最多 8 秒且不重试，robots.txt 最多
6 秒，避免一个不可达的来源拖垮整次调用。对比题至少需要
两个独立全文视角；公众号摘要不算一个视角。
对比题或技术题已经有两个权威全文来源时，纯公众号摘要会被跳过，而不是混进证据。
HTTP 读不了的公众号文章仍只返回 `partial` 搜索摘要并明确警告，不伪造全文。
所有句段都是带 URL 的第三方引用文本。

## 动作与退出码

| 动作 | 用途 |
|---|---|
| `fetch` | 一个 URL 或关键词查询 → 页面 |
| `research` | 宽召回 → 聚焦阅读 → 带引用的证据句段 |
| `find` | 用站点自己的搜索页在站内检索 |
| `feed` | 读取站点的 RSS/Atom，自动从页面里发现订阅地址 |
| `clean` | 本地或远程 HTML/PDF/DOCX/XLSX/EPUB/CSV → Markdown |
| `bili` | B 站首页 / 视频 / 相关 / 搜索 / 冲浪 |
| `surf` | 搜索或种子 URL，再按相关度做链接 BFS |
| `scholar` | arXiv / Crossref / PubMed / DOI 记录 |
| `map` | 从 robots.txt 与 sitemap 发现页面 URL |
| `doctor` | 依赖自检：装了什么，该装什么 |

| 退出码 | 含义（未在下表改写的，两种模式相同） |
|---|---|
| 0 | 成功 |
| 2 | 参数或 URL 错误 |
| 3 | robots.txt 拒绝访问，或没有配置浏览器桥 |
| 4 | 网络 / HTTP / 导航失败 |
| 5 | 抽取或捕捉失败 |
| 6 | 请求了 Playwright 但不可用 |
| 7 | 处理 PDF 但 `pypdf` 不可用 |
| 9 | 返回的是验证页或反爬页而不是内容（HTTP 模式为 `verification_required`，浏览器模式为 `blocked`） |
| 130 | 被中断 |

浏览器模式沿用这张表，只改写或新增以下含义：

| 退出码 | 浏览器模式含义 |
|---|---|
| 2 | 另外表示未知后端 |
| 6 | `login_required`：站点要求登录 |
| 7 | `confirmation_required`：写类操作被拒绝 |
| 8 | `degraded`：页面读到了，但剧本要的东西一个都没找到 |
| 9 | `blocked`：页面被反爬或错误页替换 |

`--agent` 保留这些退出码，并在 stdout 输出 `{"ok":false,"error":{"code","message","hint"}}` 信封。`doctor` 逐项报告依赖的版本或安装命令；缺 Playwright 返回退出码 6，缺 `pypdf` 返回退出码 7。

---

---

## 环境要求

Python 3.10+。核心运行时：`requests`、`beautifulsoup4`、`trafilatura`。可选：`playwright`（JS 渲染）、`pypdf`（PDF）。`defusedxml` 若已安装则使用，但从不强制依赖——含内部 DTD 子集或任何 ENTITY 声明的 XML 一律拒绝。浏览器模式另需 Node.js 18+ 与一个桥命令；`browser/bridges/playwright-bridge.js` 还需要 npm 安装 `playwright`。没有内置任何第三方代码；完整的能力-依赖矩阵见 [DEPENDENCIES.md](DEPENDENCIES.md)。

---

---

## 目录结构

<details>
<summary>完整目录树</summary>

```text
web-forager/
├── .claude-plugin/               Claude Code 清单 + marketplace
├── .codex-plugin/                Codex 清单 + marketplace
├── .codebuddy-plugin/            CodeBuddy 清单 + marketplace
├── .dsh-plugin/                  DSH 清单 + CJS 入口
├── .cursor/rules/                Cursor 规则
├── .windsurf/rules/              Windsurf 规则
├── .clinerules/                  Cline 规则
├── .continue/rules/              Continue 规则
├── .roo/rules/                   Roo Code 规则
├── .github/                      GitHub Copilot 指令 + Actions CI
├── AGENTS.md                     通用智能体契约
├── install.py                    一键安装规则文件
├── manifest.json                 插件清单
├── .mcp.json                     MCP stdio 注册
├── package.json / index.js       npm + dsh 打包
├── cordis.patch.yml              dsh bundle 补丁
├── run.py                        CLI：九个动作
├── mcp_server.py                 MCP stdio 服务（10 个 HTTP 工具）
├── browser/                      浏览器模式（Node 18+）
│   ├── run.js                    CLI：八个只读剧本
│   ├── mcp_server.js             MCP stdio 服务（4 个浏览器工具）
│   ├── lib/                      桥后端、会话、记录、安全门禁、选择器、robots、快照
│   ├── playbooks/                bili-* / zhihu-dig / xhs-dig / search-dig / wechat-dig
│   ├── bridges/                  可选 Playwright 参考桥
│   └── tests/                    假后端、真实页面快照、live 冒烟
├── SKILL.md                      Claude Code 技能契约
├── commands/                     /fetch /surf /scholar /map /browse
├── docs/                         安装命令、致谢、依赖矩阵
├── scripts/
│   ├── engine.py                 robots、抓取、搜索、缓存、分块、Markdown、surf、find、feed
│   ├── pdf.py                    PDF 文本（可选 pypdf）
│   ├── documents.py              DOCX / XLSX / EPUB / CSV
│   ├── feeds.py                  RSS / Atom / RSS 1.0
│   ├── scholar.py                arXiv / Crossref / PubMed / DOI
│   ├── sitemap.py                sitemap 发现
│   └── bilibili.py               B 站适配器
├── tests/                        离线 HTTP 夹具
├── requirements.txt
├── THIRD_PARTY_LICENSES.txt
├── CHANGELOG.md
├── README.md · README_zh.md
└── LICENSE                       MIT
```

</details>

---

---

## 测试

```bash
python -m pytest tests -q
npm run test:browser
```

共 **333 个 Python 测试**加 **91 个浏览器测试**，全部离线通过。

<details>
<summary>测试覆盖了什么</summary>

`conftest.py` 会起一个临时本地 HTTP 站点，提供 robots.txt、文章、PDF/Office 文件、订阅源、站点地图、搜索结果页、站点搜索页与多跳 surf 页面。Python 套件覆盖 robots 拒绝、抽取、表格、文档、订阅源、缓存、搜索分页与路由、分块、MCP、surf 会话、安装器行为、宿主规则与免责声明检查、共享的 `core-1` 记录，以及每一个退出码。浏览器套件用假后端与说同一套线协议的假桥，不打开浏览器也能把 CLI 跑通；它还覆盖能力声明、robots.txt 匹配、`--strict-robots` 往返、私有地址拦截、不可信内容筛查，以及基于真实页面快照的 `degraded` 与 `blocked` 路径。

</details>

CI 在每次推送到 `main`、拉取请求与版本 tag 时运行两套测试：Python 在 Ubuntu 3.10/3.12 与 Windows 3.12，浏览器模式在 Node 20/22。真实站点检查是可选项，CI 从不运行：

```bash
WEB_FORAGER_LIVE=1 WEB_FORAGER_BRIDGE="node browser/bridges/playwright-bridge.js" npm run test:live
```

---
