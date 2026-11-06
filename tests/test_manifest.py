"""Repository-level checks: manifest, licence, disclaimer and dependency policy."""

from __future__ import annotations

import json
import re
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DISCLAIMER = (
    "本插件仅供学术研究使用。使用者需遵守目标网站的 Terms of Service 及相关版权法律。"
    "禁止用于抓取个人隐私数据或进行恶意并发攻击。"
)
ALLOWED_DEPENDENCIES = {"requests", "beautifulsoup4", "trafilatura", "playwright", "pypdf"}


def test_manifest_is_complete() -> None:
    manifest = json.loads((PLUGIN_ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "web-forager"
    assert manifest["version"] == "0.2.0"
    assert manifest["license"] == "MIT"
    assert set(manifest["actions"]) == {"fetch", "clean", "bili", "surf"}
    assert (PLUGIN_ROOT / manifest["entrypoint"]).is_file()
    assert manifest["disclaimer"] == DISCLAIMER


def test_mit_license_file() -> None:
    text = (PLUGIN_ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License")
    assert "THE SOFTWARE IS PROVIDED \"AS IS\"" in text


def test_readme_and_skill_show_the_disclaimer() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    skill = (PLUGIN_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert DISCLAIMER in readme
    assert DISCLAIMER in skill
    # It must be near the top, not buried at the end.
    assert readme.index(DISCLAIMER) < 1200
    assert skill.index(DISCLAIMER) < 1200


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
        "scripts/bilibili.py",
        "README.md",
        "SKILL.md",
        "LICENSE",
        "THIRD_PARTY_LICENSES.txt",
        "tests/test_engine.py",
        "tests/test_bilibili.py",
        "tests/test_fetch.py",
        "tests/test_search_pdf_surf.py",
        "tests/test_cli.py",
    ):
        assert (PLUGIN_ROOT / relative).is_file(), relative


def test_multi_platform_manifests() -> None:
    for folder in (".claude-plugin", ".codex-plugin", ".codebuddy-plugin", ".dsh-plugin"):
        data = json.loads((PLUGIN_ROOT / folder / "plugin.json").read_text(encoding="utf-8"))
        assert data["name"] == "web-forager"
        assert data["version"] == "0.2.0"

    for folder in (".claude-plugin", ".codex-plugin", ".codebuddy-plugin"):
        market = json.loads((PLUGIN_ROOT / folder / "marketplace.json").read_text(encoding="utf-8"))
        assert market["plugins"][0]["name"] == "web-forager"
        assert market["plugins"][0]["source"] == "./"

    assert "web-forager" in (PLUGIN_ROOT / ".dsh-plugin" / "index.js").read_text(encoding="utf-8")


def test_docs_document_playwright_and_workspace() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    skill = (PLUGIN_ROOT / "SKILL.md").read_text(encoding="utf-8")
    command = "pip install playwright && playwright install chromium"
    assert command in readme
    assert command in skill
    for text in (readme, skill):
        assert "--root" in text
        assert "退出码 6" in text or "exit code 6" in text


def test_readme_covers_standalone_and_chelate_integration() -> None:
    readme = (PLUGIN_ROOT / "README.md").read_text(encoding="utf-8")
    assert "独立安装" in readme
    assert "chelate-shell" in readme
    assert "process/web-forager" in readme
    assert "_broadcast" in readme
