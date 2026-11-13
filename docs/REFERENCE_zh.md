# web-forager 参考手册

> [web-forager](../README_zh.md) 的一部分。这里放查询类内容：记录结构、动作、退出码、环境要求、目录结构与测试。

[English](REFERENCE.md) · **简体中文**

---

## MCP 服务

<details>
<summary>工具名</summary>

HTTP 工具：`web_fetch`、`web_search`、`web_surf`、`web_scholar`、`web_map`、`web_bilibili`、`web_clean`、`web_doctor`、`web_find`、`web_feed`。浏览器工具：`browser_list`、`browser_run`、`browser_session`、`browser_doctor`。

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

装好 `playwright` 与它的 Chromium 后，自带的桥会被自动启用；`--bridge` 或 `WEB_FORAGER_BRIDGE` 用于指向别处的桥。命令按空白拆分后直接启动，不经过 shell——路径含空格时加引号，参数照常写；管道、`&&` 与重定向不会被解释。`WEB_FORAGER_BROWSER_HEADFUL=1` 显示窗口；`WEB_FORAGER_BROWSER_PROFILE=/path` 复用持久化配置目录（`extension` 后端的登录态正是靠它保留）；`WEB_FORAGER_BROWSER_CDP=http://127.0.0.1:9222` 接管你已有的浏览器（`cdp`）。桥通过可选的 `describe` 调用声明自己实现了什么；不实现 `describe` 的桥会被标记为 `declared: false`，所有能力一律为 false。

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
| `trust`、`injection_flags` | 有 | 有 |
| `url`、`title` | 有（`url` 与 `final_url`） | 有 |
| `status`、`content_type`、`document_kind`、`cached`、`rendered`、`fetched_at`、`chunks`、`links` | 有 | 无 |
| `schema_version`、`captured_at`、`playbook`、`backend`、`compliance`、`viewport_evidence`、`interaction_trace` | 无 | 有 |

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

## 动作与退出码

| 动作 | 用途 |
|---|---|
| `fetch` | 一个 URL 或关键词查询 → 页面 |
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
│   ├── run.js                    CLI：七个只读剧本
│   ├── mcp_server.js             MCP stdio 服务（4 个浏览器工具）
│   ├── lib/                      桥后端、会话、记录、安全门禁、选择器、robots、快照
│   ├── playbooks/                bili-* / zhihu-dig / xhs-dig / search-dig
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

共 **228 个 Python 测试**加 **75 个浏览器测试**，全部离线通过。

<details>
<summary>测试覆盖了什么</summary>

`conftest.py` 会起一个临时本地 HTTP 站点，提供 robots.txt、文章、PDF/Office 文件、订阅源、站点地图、搜索结果页、站点搜索页与多跳 surf 页面。Python 套件覆盖 robots 拒绝、抽取、表格、文档、订阅源、缓存、搜索分页与路由、分块、MCP、surf 会话、安装器行为、宿主规则与免责声明检查、共享的 `core-1` 记录，以及每一个退出码。浏览器套件用假后端与说同一套线协议的假桥，不打开浏览器也能把 CLI 跑通；它还覆盖能力声明、robots.txt 匹配、`--strict-robots` 往返、私有地址拦截、不可信内容筛查，以及基于真实页面快照的 `degraded` 与 `blocked` 路径。

</details>

CI 在每次推送到 `main`、拉取请求与版本 tag 时运行两套测试：Python 在 Ubuntu 3.10/3.12 与 Windows 3.12，浏览器模式在 Node 20/22。真实站点检查是可选项，CI 从不运行：

```bash
WEB_FORAGER_LIVE=1 WEB_FORAGER_BRIDGE="node browser/bridges/playwright-bridge.js" npm run test:live
```

---
