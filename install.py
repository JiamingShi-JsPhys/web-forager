"""Cross-host rule-file installer for web-forager.

No agent host ships an installer that understands another host's rules, so
"install everywhere" cannot be delegated to a single vendor command. This
script copies the agent contract into every supported host's rule location in
one run.

Two scopes:

    python install.py --project <dir>   project-scoped rules inside <dir>
    python install.py --global          user-scoped rules for detected hosts

`--project` writes Cursor, Windsurf, Cline, Continue, Roo Code and GitHub
Copilot rule files plus the generic `AGENTS.md` that Codex, Cursor, Copilot
agents and opencode read. `--global` writes user-level rules for opencode and
Codex, and appends a marked block to `~/.claude/CLAUDE.md` instead of replacing
the user's own instructions. A host whose directory is absent is skipped.

Plugin hosts (Claude Code, CodeBuddy, Codex, dsh) should install the real
plugin from its marketplace instead; this script covers hosts that read rule
files. Re-running is safe: identical files report `unchanged`, and a drifted
file is left alone unless `--force` is passed.

Usage:
    python install.py --list
    python install.py --project . --dry-run
    python install.py --project .
    python install.py --global --only opencode,codex
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.abspath(__file__))

PROJECT_RULES = {
    "cursor": (
        os.path.join(".cursor", "rules", "web-forager.mdc"),
        os.path.join(".cursor", "rules", "web-forager.mdc"),
    ),
    "windsurf": (
        os.path.join(".windsurf", "rules", "web-forager.md"),
        os.path.join(".windsurf", "rules", "web-forager.md"),
    ),
    "cline": (
        os.path.join(".clinerules", "web-forager.md"),
        os.path.join(".clinerules", "web-forager.md"),
    ),
    "continue": (
        os.path.join(".continue", "rules", "web-forager.md"),
        os.path.join(".continue", "rules", "web-forager.md"),
    ),
    "roo": (
        os.path.join(".roo", "rules", "web-forager.md"),
        os.path.join(".roo", "rules", "web-forager.md"),
    ),
    "copilot": (
        os.path.join(".github", "copilot-instructions.md"),
        os.path.join(".github", "copilot-instructions.md"),
    ),
    "agents": ("AGENTS.md", "AGENTS.md"),
}


def global_rules() -> dict[str, tuple[str, str]]:
    """Return user-scoped rule targets for this machine."""

    home = os.path.expanduser("~")
    return {
        "opencode": (
            os.path.join(home, ".config", "opencode", "AGENTS.md"),
            "AGENTS.md",
        ),
        "codex": (
            os.path.join(os.environ.get("CODEX_HOME") or os.path.join(home, ".codex"), "AGENTS.md"),
            "AGENTS.md",
        ),
        "claude": (os.path.join(home, ".claude", "CLAUDE.md"), "AGENTS.md"),
    }


def _same(left_path: str, right_path: str) -> bool:
    try:
        with open(left_path, "rb") as left, open(right_path, "rb") as right:
            return left.read() == right.read()
    except OSError:
        return False


def _install(src_rel: str, dest: str, force: bool, dry_run: bool) -> str:
    """Copy one rule file; return 'wrote', 'unchanged' or 'skipped'."""

    src = os.path.join(REPO_ROOT, src_rel)
    if not os.path.isfile(src):
        raise SystemExit(f"install.py: missing source rule file: {src}")
    if os.path.isfile(dest) and _same(src, dest):
        return "unchanged"
    if os.path.isfile(dest) and not force:
        return "skipped"
    if dry_run:
        return "wrote"
    parent = os.path.dirname(dest) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".web-forager-", suffix=".tmp")
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return "wrote"


BEGIN_MARKER = "<!-- web-forager:begin -->"
END_MARKER = "<!-- web-forager:end -->"
# Hosts whose global file also carries the user's own instructions. Copying
# over it would destroy them, so web-forager owns only a marked block.
APPEND_HOSTS = {"claude"}


def _append_block(src_rel: str, dest: str, force: bool, dry_run: bool) -> str:
    """Insert or update a marked block; never replace the rest of the file."""

    src = os.path.join(REPO_ROOT, src_rel)
    if not os.path.isfile(src):
        raise SystemExit(f"install.py: missing source rule file: {src}")
    with open(src, encoding="utf-8") as handle:
        block = f"{BEGIN_MARKER}\n{handle.read().rstrip()}\n{END_MARKER}\n"

    text = ""
    if os.path.isfile(dest):
        with open(dest, encoding="utf-8", newline="") as handle:
            text = handle.read()

    if BEGIN_MARKER in text and END_MARKER in text:
        start = text.index(BEGIN_MARKER)
        finish = text.index(END_MARKER, start) + len(END_MARKER)
        current = text[start:finish].replace("\r\n", "\n") + "\n"
        if current == block:
            return "unchanged"
        if not force:
            return "skipped"
        updated = text[:start] + block + text[finish:].lstrip("\r\n")
    elif text.strip():
        updated = text.rstrip("\r\n") + "\n\n" + block
    else:
        updated = block

    if dry_run:
        return "wrote"
    parent = os.path.dirname(dest) or "."
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".web-forager-", suffix=".tmp")
    os.close(fd)
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(updated)
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return "wrote"


def _select(only: str | None, keys) -> list[str]:
    if not only:
        return list(keys)
    wanted = [part.strip() for part in only.split(",") if part.strip()]
    unknown = [name for name in wanted if name not in keys]
    if unknown:
        raise SystemExit(
            "install.py: unknown host(s): "
            + ", ".join(unknown)
            + "\nknown: "
            + ", ".join(keys)
        )
    return wanted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="Copy the web-forager rule file into every supported agent host.",
    )
    parser.add_argument("--project", metavar="DIR", help="install project-scoped rules into DIR")
    parser.add_argument(
        "--global",
        dest="global_scope",
        action="store_true",
        help="install user-scoped rules for detected hosts",
    )
    parser.add_argument("--only", metavar="HOSTS", help="comma-separated subset, e.g. cursor,opencode")
    parser.add_argument("--force", action="store_true", help="replace an existing rule file or marked block that differs")
    parser.add_argument("--dry-run", action="store_true", help="show what would be written, write nothing")
    parser.add_argument("--list", action="store_true", help="show every host and its destination, then exit")
    args = parser.parse_args(argv)

    if args.list:
        print("project scope (--project DIR):")
        for key, (rel, _src) in PROJECT_RULES.items():
            print(f"  {key:<10} {rel}")
        print("global scope (--global), written only when the host is present:")
        for key, (dest, _src) in global_rules().items():
            state = "" if os.path.isdir(os.path.dirname(dest)) else "  (absent)"
            mode = "  (append)" if key in APPEND_HOSTS else ""
            print(f"  {key:<10} {dest}{state}{mode}")
        return 0

    if not args.project and not args.global_scope:
        parser.error("choose --project DIR and/or --global (or --list)")

    results: list[tuple[str, str, str]] = []
    if args.project:
        project = os.path.abspath(args.project)
        os.makedirs(project, exist_ok=True)
        for key in _select(args.only, PROJECT_RULES):
            rel, src_rel = PROJECT_RULES[key]
            dest = os.path.join(project, rel)
            results.append((key, dest, _install(src_rel, dest, args.force, args.dry_run)))

    if args.global_scope:
        targets = global_rules()
        for key in _select(args.only, targets):
            dest, src_rel = targets[key]
            host_dir = os.path.dirname(dest)
            if not os.path.isdir(host_dir):
                results.append((key, dest, "absent"))
                continue
            if key in APPEND_HOSTS:
                results.append((key, dest, _append_block(src_rel, dest, args.force, args.dry_run)))
            else:
                results.append((key, dest, _install(src_rel, dest, args.force, args.dry_run)))

    width = max(len(key) for key, _dest, _state in results)
    for key, dest, state in results:
        print(f"  {key:<{width}}  {state:<9}  {dest}")

    wrote = sum(1 for _key, _dest, state in results if state == "wrote")
    print(
        f"\n{wrote} file(s) written"
        + (" (dry run)" if args.dry_run else "")
        + ". Start a new session in the host to pick the rule up."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
