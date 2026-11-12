# Install commands

Every per-host command, the `install.py` flags and the optional dependencies. Methods 1 and 2 are short enough to stay in the README: [web-forager](../README.md) · [简体中文](INSTALL_COMMANDS_zh.md)

## Method 3: install with commands

**Claude Code** — from your shell (v2.1.292+), marketplace and install in one step:

```bash
claude plugin install web-forager --marketplace https://github.com/JiamingShi-JsPhys/web-forager.git
```

**Claude Code** — from inside a session (v2.1.275+), add the marketplace from the URL first, pinned to the release tag:

```text
/plugin marketplace add https://github.com/JiamingShi-JsPhys/web-forager.git#v1.2.2
```

Then install the entry it lists:

```text
/plugin install web-forager@web-forager-marketplace
```

**Codex** — register the URL as a Git marketplace; `--ref` pins the release tag, and an SSH URL or a local path works in place of the HTTPS one:

```bash
codex plugin marketplace add https://github.com/JiamingShi-JsPhys/web-forager.git --ref v1.2.2
```

**Codex** — install the plugin from that marketplace:

```bash
codex plugin add web-forager@web-forager-marketplace
```

**dsh (DeepSeek Harness)** — installs from the same repository URL straight into a profile:

```bash
dsh plugin --profile web add github:JiamingShi-JsPhys/web-forager#v1.2.2
```

**CodeBuddy** — add the URL as a Git marketplace:

```text
/plugin marketplace add https://github.com/JiamingShi-JsPhys/web-forager.git#v1.2.2
```

Then install the entry it lists:

```text
/plugin install web-forager@web-forager-marketplace
```

Cursor, Windsurf, Cline's IDE extension, Continue, Roo Code, GitHub Copilot and opencode each read a rule file from their own location, and none of them accepts this repository as a plugin — Cline's `cline plugin install` takes only JS/TS plugin packages, Cursor's plugin format is a different bundle, and `opencode plugin <module>` installs npm modules. **No vendor ships an installer that understands another vendor's rule file**, so this repository ships one:

```bash
git clone https://github.com/JiamingShi-JsPhys/web-forager.git && python web-forager/install.py --project <project> --global
```

That single command writes every rule file at once:

- `--project <project>` covers the project-scoped files — Cursor, Windsurf, Cline, Continue, Roo Code, GitHub Copilot, and the generic `AGENTS.md` that Codex, Cursor, Copilot agents and opencode all read.
- `--global` covers the user-scoped files — `~/.config/opencode/AGENTS.md`, `$CODEX_HOME/AGENTS.md` (default `~/.codex/AGENTS.md`), and, for Claude Code, a marked block appended to `~/.claude/CLAUDE.md` when `~/.claude` already exists — and skips any host this machine does not have.

Re-running it is safe: identical files report `unchanged`, and a rule file that has drifted is left alone unless you pass `--force`.

List every destination without writing anything:

```bash
python web-forager/install.py --list
```

Preview the run:

```bash
python web-forager/install.py --project <project> --global --dry-run
```

Install for one host only:

```bash
python web-forager/install.py --project <project> --only cursor,windsurf
```

Keep the cloned repository somewhere the agent can reach: every rule file names `run.py`, `mcp_server.py` and `SKILL.md`, so the host agent calls the same engine as a plugin host. The rule file describes *how to call* the tool — it does not vendor the code.

**opencode without copying** — opencode can also read the rule file in place through `opencode.json`'s `instructions` array, which needs no copy and can be committed for a whole team:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "instructions": ["../web-forager/AGENTS.md"]
}
```

**Manual alternative** — if you would rather not run the script, copy the file yourself to the destination the script would have used:

```text
<clone>/AGENTS.md  →  <project>/AGENTS.md
```

## Optional capabilities

```bash
pip install -r requirements.txt                        # core: requests, bs4, trafilatura
pip install playwright && playwright install chromium  # JS rendering
pip install pypdf                                      # PDF text
```

DOCX/XLSX/EPUB/CSV, RSS/Atom, sitemap parsing and both MCP servers need **no extra Python package**. Browser mode needs Node.js 18 or newer; a browser bridge is supplied by you, and `browser/bridges/playwright-bridge.js` additionally needs `npm install playwright`. See [docs/DEPENDENCIES.md](DEPENDENCIES.md).
