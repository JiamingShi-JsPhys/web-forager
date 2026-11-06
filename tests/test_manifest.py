"""Repository-level checks: manifest, licence, disclaimer and dependency policy."""

from __future__ import annotations

import json
import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DISCLAIMER = (
    "本插件仅供学习与信息收集使用。使用者需遵守目标网站的 Terms of Service 及相关版权法律。"
    "禁止用于抓取个人隐私数据或进行恶意并发攻击。"
)
DISCLAIMER_EN = (
    "This plugin is for learning and information gathering only. Users must comply with the Terms of Service "
    "of target websites and applicable copyright law. It must not be used to harvest personal "
    "data or to conduct malicious concurrent attacks."
)
ALLOWED_DEPENDENCIES = {"requests", "beautifulsoup4", "trafilatura", "playwright", "pypdf"}


def test_manifest_is_complete() -> None:
    manifest = json.loads((PLUGIN_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "web-forager"
    assert manifest["version"] == "1.0.1"
    assert manifest["license"] == "MIT"
    assert set(manifest["actions"]) == {"fetch", "clean", "bili", "surf", "scholar", "map"}
    assert (PLUGIN_ROOT / manifest["entrypoint"]).is_file()
    assert manifest["disclaimer"] == DISCLAIMER


def test_mit_license_file() -> None:
    text = (PLUGIN_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    assert "THE SOFTWARE IS PROVIDED \"AS IS\"" in text


def test_readme_and_skill_show_the_disclaimer() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (PLUGIN_ROOT / "README_zh.md").read_text(encoding="utf-8")
    skill = (PLUGIN_ROOT / "SKILL.md").read_text(encoding="utf-8")
    # The English README is English-only, so it carries the translated notice.
    assert DISCLAIMER_EN in readme
    assert readme.index(DISCLAIMER_EN) < 1200
    for text in (readme_zh, skill):
        assert DISCLAIMER in text
        assert text.index(DISCLAIMER) < 1200


def test_english_readme_has_no_chinese_text() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    # The language switcher keeps the target language's own name.
    body = readme.replace("[\u7b80\u4f53\u4e2d\u6587](README_zh.md)", "")
    assert not re.search("[\u4e00-\u9fff]", body)


def test_docs_use_no_emoji() -> None:
    emoji = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u2B00-\u2BFF]")
    for relative in (
        "README.md",
        "README_zh.md",
        "SKILL.md",
        "AGENTS.md",
        "CHANGELOG.md",
    ):
        text = (PLUGIN_ROOT / relative).read_text(encoding="utf-8")
        assert not emoji.search(text), relative


def test_agent_contract_and_host_rules_show_the_disclaimer() -> None:
    for relative in (
        "AGENTS.md",
        ".cursor/rules/web-forager.mdc",
        ".windsurf/rules/web-forager.md",
        ".clinerules/web-forager.md",
        ".continue/rules/web-forager.md",
        ".roo/rules/web-forager.md",
        ".github/copilot-instructions.md",
    ):
        text = (PLUGIN_ROOT / relative).read_text(encoding="utf-8")
        assert DISCLAIMER in text, relative
        assert "robots.txt" in text, relative


def test_skill_frontmatter() -> None:
    text = (PLUGIN_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter = text.split("---", 2)[1]
    assert "name: web-forager" in frontmatter
    assert "license: MIT" in frontmatter
    assert "entry_point: python run.py" in frontmatter


def test_only_permitted_dependencies() -> None:
    lines = (PLUGIN_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    declared = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name = re.split(r"[<>=!\[]", line, maxsplit=1)[0].strip().lower()
        declared.append(name)
    assert declared, "requirements.txt must declare the runtime dependencies"
    assert set(declared) <= ALLOWED_DEPENDENCIES
    forbidden = {"scrapy", "crawlee", "selenium", "crawl4ai", "mechanicalsoup", "pyppeteer"}
    assert not (set(declared) & forbidden)


def test_engine_has_no_framework_imports() -> None:
    import ast

    source = (PLUGIN_ROOT / "scripts" / "engine.py").read_text(encoding="utf-8")
    modules: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0].lower() for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0].lower())
    forbidden = {"scrapy", "crawlee", "selenium", "crawl4ai", "mechanize"}
    assert not (modules & forbidden)


def test_required_files_exist() -> None:
    for relative in (
        "manifest.json",
        "run.py",
        "scripts/engine.py",
        "scripts/pdf.py",
        "scripts/documents.py",
        "scripts/feeds.py",
        "scripts/scholar.py",
        "scripts/sitemap.py",
        "scripts/bilibili.py",
        "mcp_server.py",
        ".mcp.json",
        "AGENTS.md",
        "install.py",
        "package.json",
        "index.js",
        "cordis.patch.yml",
        "commands/fetch.md",
        "commands/surf.md",
        "commands/scholar.md",
        "commands/map.md",
        "docs/DEPENDENCIES.md",
        ".cursor/rules/web-forager.mdc",
        ".windsurf/rules/web-forager.md",
        ".clinerules/web-forager.md",
        ".continue/rules/web-forager.md",
        ".roo/rules/web-forager.md",
        ".github/copilot-instructions.md",
        "README.md",
        "README_zh.md",
        "SKILL.md",
        "CHANGELOG.md",
        "LICENSE",
        "THIRD_PARTY_LICENSES.txt",
        "tests/test_engine.py",
        "tests/test_bilibili.py",
        "tests/test_fetch.py",
        "tests/test_search_pdf_surf.py",
        "tests/test_v1_features.py",
        "tests/test_cli.py",
        "tests/test_install.py",
    ):
        assert (PLUGIN_ROOT / relative).is_file(), relative


def test_multi_platform_manifests() -> None:
    for folder in (".claude-plugin", ".codex-plugin", ".codebuddy-plugin", ".dsh-plugin"):
        data = json.loads((PLUGIN_ROOT / folder / "plugin.json").read_text(encoding="utf-8"))
        assert data["name"] == "web-forager"
        assert data["version"] == "1.0.1"

    for folder in (".claude-plugin", ".codex-plugin", ".codebuddy-plugin"):
        market = json.loads((PLUGIN_ROOT / folder / "marketplace.json").read_text(encoding="utf-8"))
        assert market["plugins"][0]["name"] == "web-forager"
        assert market["plugins"][0]["source"] == "./"

    assert "web-forager" in (PLUGIN_ROOT / ".dsh-plugin" / "index.js").read_text(encoding="utf-8")


def test_mcp_registration() -> None:
    manifest = json.loads((PLUGIN_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mcp"]["entrypoint"] == "mcp_server.py"
    config = json.loads((PLUGIN_ROOT / ".mcp.json").read_text(encoding="utf-8"))
    server = config["mcpServers"]["web-forager"]
    assert server["args"][0].endswith("/mcp_server.py")
    assert set(manifest["mcp"]["tools"]) == {
        "web_fetch",
        "web_search",
        "web_surf",
        "web_scholar",
        "web_map",
        "web_bilibili",
        "web_clean",
    }


def test_docs_document_playwright_and_workspace() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    skill = (PLUGIN_ROOT / "SKILL.md").read_text(encoding="utf-8")
    command = "pip install playwright && playwright install chromium"
    assert command in readme
    assert command in skill
    for text in (readme, skill):
        assert "--root" in text
        assert "退出码 6" in text or "exit code 6" in text


def test_readme_covers_installation_and_workspace_output() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    readme_zh = (PLUGIN_ROOT / "README_zh.md").read_text(encoding="utf-8")
    for text in (readme, readme_zh):
        assert "install.py" in text
        assert "AGENTS.md" in text
        assert "process/web-forager" in text
        assert "_broadcast" in text
        assert "workflow" in text or "mermaid" in text
        assert "Chelate" not in text
        assert "https://github.com/JiamingShi-JsPhys/web-forager" in text
    assert "### Method 1: install from the plugin marketplace by URL" in readme
    assert "### 方法一：从插件市场用 URL 安装" in readme_zh
    assert "[English](README.md)" in readme_zh
    assert "[简体中文](README_zh.md)" in readme


def test_package_entry_is_consistent_with_manifest() -> None:
    manifest = json.loads((PLUGIN_ROOT / "manifest.json").read_text(encoding="utf-8"))
    package = json.loads((PLUGIN_ROOT / "package.json").read_text(encoding="utf-8"))
    assert package["name"] == manifest["name"]
    assert package["version"] == manifest["version"]
    assert (PLUGIN_ROOT / package["main"]).is_file()
    assert "cordis.patch.yml" in package.get("dsh", {}).get("bundle", {}).get("patch", "")
