"""Cross-host rule-file installer tests.

Nothing here touches the real user home: the global scope is exercised with
HOME / USERPROFILE / CODEX_HOME redirected into a temporary directory.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import install

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DISCLAIMER = (
    "本插件仅供学习与信息收集使用。使用者需遵守目标网站的 Terms of Service 及相关版权法律。"
    "禁止用于抓取个人隐私数据或进行恶意并发攻击。"
)


def test_list_names_every_host(capsys: pytest.CaptureFixture[str]) -> None:
    assert install.main(["--list"]) == 0
    out = capsys.readouterr().out
    for host in ("cursor", "windsurf", "cline", "continue", "roo", "copilot", "agents"):
        assert host in out
    for host in ("opencode", "codex", "claude"):
        assert host in out


def test_project_scope_writes_only_the_selected_host(tmp_path: Path) -> None:
    assert install.main(["--project", str(tmp_path), "--only", "cursor"]) == 0
    written = tmp_path / ".cursor" / "rules" / "web-forager.mdc"
    assert written.is_file()
    assert DISCLAIMER in written.read_text(encoding="utf-8")
    assert not (tmp_path / "AGENTS.md").exists()
    assert not (tmp_path / ".clinerules").exists()


def test_project_scope_writes_all_hosts_by_default(tmp_path: Path) -> None:
    assert install.main(["--project", str(tmp_path)]) == 0
    for relative in (
        ".cursor/rules/web-forager.mdc",
        ".windsurf/rules/web-forager.md",
        ".clinerules/web-forager.md",
        ".continue/rules/web-forager.md",
        ".roo/rules/web-forager.md",
        ".github/copilot-instructions.md",
        "AGENTS.md",
    ):
        assert (tmp_path / relative).is_file(), relative


def test_rerun_reports_unchanged(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert install.main(["--project", str(tmp_path), "--only", "windsurf"]) == 0
    capsys.readouterr()
    assert install.main(["--project", str(tmp_path), "--only", "windsurf"]) == 0
    out = capsys.readouterr().out
    assert "unchanged" in out
    assert "0 file(s) written" in out


def test_drifted_file_is_skipped_until_forced(tmp_path: Path) -> None:
    dest = tmp_path / ".cursor" / "rules" / "web-forager.mdc"
    dest.parent.mkdir(parents=True)
    dest.write_text("local customisation\n", encoding="utf-8")

    assert install.main(["--project", str(tmp_path), "--only", "cursor"]) == 0
    assert dest.read_text(encoding="utf-8") == "local customisation\n"

    assert install.main(["--project", str(tmp_path), "--only", "cursor", "--force"]) == 0
    assert DISCLAIMER in dest.read_text(encoding="utf-8")


def test_dry_run_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert install.main(["--project", str(tmp_path), "--only", "roo", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "wrote" in out
    assert "dry run" in out
    assert not (tmp_path / ".roo" / "rules" / "web-forager.md").exists()


def test_unknown_host_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as excinfo:
        install.main(["--project", str(tmp_path), "--only", "not-a-host"])
    assert "unknown host" in str(excinfo.value)


def test_global_scope_skips_absent_hosts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("CODEX_HOME", str(home / ".codex"))

    assert install.main(["--global"]) == 0
    out = capsys.readouterr().out
    assert "absent" in out
    assert not (home / ".config" / "opencode" / "AGENTS.md").exists()
    assert not (home / ".codex" / "AGENTS.md").exists()
    assert not (home / ".claude" / "CLAUDE.md").exists()


def test_global_scope_writes_into_an_existing_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".config" / "opencode").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    assert install.main(["--global", "--only", "opencode"]) == 0
    written = home / ".config" / "opencode" / "AGENTS.md"
    assert written.is_file()
    assert DISCLAIMER in written.read_text(encoding="utf-8")


def test_global_claude_appends_without_touching_existing_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    claude_md = home / ".claude" / "CLAUDE.md"
    original = "# My private rules\n\n- keep this line\n"
    claude_md.write_text(original, encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    assert install.main(["--global", "--only", "claude"]) == 0
    text = claude_md.read_text(encoding="utf-8")
    assert text.startswith(original.rstrip("\n"))
    assert install.BEGIN_MARKER in text
    assert install.END_MARKER in text
    assert DISCLAIMER in text

    capsys.readouterr()
    assert install.main(["--global", "--only", "claude"]) == 0
    assert "unchanged" in capsys.readouterr().out
    assert claude_md.read_text(encoding="utf-8").count(install.BEGIN_MARKER) == 1


def test_global_claude_block_is_replaced_only_with_force(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    claude_md = home / ".claude" / "CLAUDE.md"
    claude_md.write_text(
        "keep me\n\n"
        f"{install.BEGIN_MARKER}\nstale block\n{install.END_MARKER}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    assert install.main(["--global", "--only", "claude"]) == 0
    text = claude_md.read_text(encoding="utf-8")
    assert "stale block" in text
    assert DISCLAIMER not in text

    assert install.main(["--global", "--only", "claude", "--force"]) == 0
    text = claude_md.read_text(encoding="utf-8")
    assert text.startswith("keep me")
    assert "stale block" not in text
    assert DISCLAIMER in text
    assert text.count(install.BEGIN_MARKER) == 1
