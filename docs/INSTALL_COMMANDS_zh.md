# 安装命令

各宿主的完整命令、`install.py` 的全部参数与可选依赖。方法一与方法三较短，留在 README：[web-forager](../README_zh.md) · [English](INSTALL_COMMANDS.md)

## 方法二：用命令安装

**Claude Code** —— 在终端执行（v2.1.292+），一步完成注册与安装：

```bash
claude plugin install web-forager --marketplace https://github.com/JiamingShi-JsPhys/web-forager.git
```

**Claude Code** —— 在会话内执行（v2.1.275+），先用 URL 添加市场，并锁定发布 tag：

```text
/plugin marketplace add https://github.com/JiamingShi-JsPhys/web-forager.git#v1.2.0
```

再安装它列出的条目：

```text
/plugin install web-forager@web-forager-marketplace
```

**Codex** —— 把 URL 注册为 Git 市场；`--ref` 锁定发布 tag，HTTPS 换成 SSH 或本地路径同样可用：

```bash
codex plugin marketplace add https://github.com/JiamingShi-JsPhys/web-forager.git --ref v1.2.0
```

**Codex** —— 从该市场安装插件：

```bash
codex plugin add web-forager@web-forager-marketplace
```

**dsh（DeepSeek Harness）** —— 直接从同一个仓库 URL 安装进指定 profile：

```bash
dsh plugin --profile web add github:JiamingShi-JsPhys/web-forager#v1.2.0
```

**CodeBuddy** —— 先把 URL 加为 Git 市场：

```text
/plugin marketplace add https://github.com/JiamingShi-JsPhys/web-forager.git#v1.2.0
```

再安装它列出的条目：

```text
/plugin install web-forager@web-forager-marketplace
```

Cursor、Windsurf、Cline 的 IDE 扩展、Continue、Roo Code、GitHub Copilot 与 opencode 各自从自己的位置读取规则文件，而且它们都不接受本仓库作为插件——Cline 的 `cline plugin install` 只接受 JS/TS 插件包，Cursor 的插件格式是另一套打包，`opencode plugin <module>` 装的是 npm 模块。**没有任何厂商提供能识别别家规则文件的安装器**，所以本仓库自带一个：

```bash
git clone https://github.com/JiamingShi-JsPhys/web-forager.git && python web-forager/install.py --project <项目> --global
```

这一条命令会一次性写好全部规则文件：

- `--project <项目>` 负责项目级文件——Cursor、Windsurf、Cline、Continue、Roo Code、GitHub Copilot，以及 Codex、Cursor、Copilot Agent 与 opencode 都会读的通用 `AGENTS.md`。
- `--global` 负责用户级文件——`~/.config/opencode/AGENTS.md`、`$CODEX_HOME/AGENTS.md`（默认 `~/.codex/AGENTS.md`），以及对 Claude Code 在 `~/.claude` 已存在时向 `~/.claude/CLAUDE.md` 追加的带标记块——并自动跳过本机没有安装的宿主。

重复运行是安全的：内容相同的文件报告 `unchanged`，已经改动过的规则文件在你不加 `--force` 时保持原样。

先看清单，不写任何文件：

```bash
python web-forager/install.py --list
```

预演一次：

```bash
python web-forager/install.py --project <项目> --global --dry-run
```

只装某一个宿主：

```bash
python web-forager/install.py --project <项目> --only cursor,windsurf
```

克隆下来的仓库要放在 Agent 能访问到的位置：每个规则文件都点名了 `run.py`、`mcp_server.py` 与 `SKILL.md`，宿主 Agent 因此可以像插件宿主一样调用同一个引擎。规则文件只描述“怎么调用”，并不内置代码。

**opencode 也可以完全不复制** —— 用 `opencode.json` 的 `instructions` 数组原地指向规则文件，无需复制，还能随项目提交给整个团队：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "instructions": ["../web-forager/AGENTS.md"]
}
```

**不想跑脚本时的手动方式** —— 自己复制，目标路径就是脚本会写入的那一处：

```text
<克隆目录>/AGENTS.md  →  <项目>/AGENTS.md
```

## 可选能力

```bash
pip install -r requirements.txt                        # 核心：requests、bs4、trafilatura
pip install playwright && playwright install chromium  # JS 渲染
pip install pypdf                                      # PDF 文本
```

DOCX/XLSX/EPUB/CSV、RSS/Atom、sitemap 解析与两个 MCP 服务**无需额外 Python 依赖**。浏览器模式需要 Node.js 18 或更新；浏览器桥由你提供，`browser/bridges/playwright-bridge.js` 另需 `npm install playwright`。详见 [docs/DEPENDENCIES.md](DEPENDENCIES.md)。
