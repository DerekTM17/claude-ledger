#!/usr/bin/env python3
"""Point every AI tool at ledger's one copy of its instructions.

- Symlinks each tool's `ledger-capture` and `session-checkpoint` skill
  directories to skills/ in this repo, so there is one copy to keep current.
- Replaces the `## Ledger…` section of each tool's AGENTS.md with
  skills/ledger-capture/agents-block.md.
- Adds ledger's SessionStart / SessionEnd hooks to ~/.claude/settings.json,
  pointing at this checkout's .venv.

Anything replaced is first copied to ~/.local/share/ledger/instructions-backup/<timestamp>/.
Safe to re-run; it changes nothing when everything is already current.
Usage: scripts/install_instructions.py [--dry-run]
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKILLS = ["ledger-capture", "session-checkpoint"]
BLOCK = REPO / "skills" / "ledger-capture" / "agents-block.md"
HOME = Path.home()
SKILL_DIRS = [
    HOME / ".claude/skills",
    HOME / ".codex/skills",
    HOME / ".config/opencode/skills",
]
SETTINGS = HOME / ".claude/settings.json"
LEDGER_BIN = REPO / ".venv" / "bin" / "ledger"
# `test -x … || exit 0` keeps a session working if the venv is ever missing.
HOOKS = {
    event: f"test -x {LEDGER_BIN} && {LEDGER_BIN} hook {arg} || exit 0"
    for event, arg in (("SessionStart", "session-start"), ("SessionEnd", "session-end"))
}
AGENTS_FILES = [
    HOME / ".claude/CLAUDE.md",
    HOME / ".codex/AGENTS.md",
    HOME / ".config/opencode/AGENTS.md",
    HOME / "AGENTS.md",
]


def replace_section(text: str, block: str) -> str:
    """Swap the `## Ledger…` section (up to the next `## ` or EOF) for `block`."""
    lines = text.rstrip("\n").split("\n")
    block_lines = block.rstrip("\n").split("\n")
    start = next((i for i, l in enumerate(lines) if l.startswith("## Ledger")), None)
    if start is None:
        return "\n".join(lines + [""] + block_lines) + "\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    tail = lines[end:]
    new = lines[:start] + block_lines + ([""] + tail if tail else [])
    return "\n".join(new) + "\n"


def main(dry: bool) -> int:
    backup = HOME / ".local/share/ledger/instructions-backup" / datetime.now().strftime("%Y%m%d-%H%M%S")

    def save(p: Path) -> None:
        dest = backup / p.relative_to(HOME)
        dest.parent.mkdir(parents=True, exist_ok=True)
        (shutil.copytree if p.is_dir() else shutil.copy2)(p, dest)

    block = BLOCK.read_text(encoding="utf-8")
    for name in SKILLS:
        src = REPO / "skills" / name
        for link in (d / name for d in SKILL_DIRS):
            if link.is_symlink() and link.resolve() == src.resolve():
                print(f"ok       {link}")
                continue
            print(f"{'would link' if dry else 'link'}  {link} -> {src}")
            if dry:
                continue
            if link.exists() or link.is_symlink():
                if not link.is_symlink():
                    save(link)
                shutil.rmtree(link) if (link.is_dir() and not link.is_symlink()) else link.unlink()
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(src, target_is_directory=True)
    for f in AGENTS_FILES:
        if not f.exists():
            print(f"skip     {f} (missing)")
            continue
        old = f.read_text(encoding="utf-8")
        new = replace_section(old, block)
        if new == old:
            print(f"ok       {f}")
            continue
        print(f"{'would update' if dry else 'update'} {f}")
        if not dry:
            save(f)
            f.write_text(new, encoding="utf-8")
    install_hooks(dry, save)
    return 0


def install_hooks(dry: bool, save) -> None:
    """Add each ledger hook to ~/.claude/settings.json unless an entry that
    runs `ledger hook <arg>` is already there. Other hooks are left alone."""
    settings = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
    hooks = settings.setdefault("hooks", {})
    changed = False
    for event, command in HOOKS.items():
        arg = command.split(" hook ")[1].split()[0]
        present = any(
            f"hook {arg}" in h.get("command", "") and "ledger" in h.get("command", "")
            for group in hooks.get(event, []) for h in group.get("hooks", [])
        )
        if present:
            print(f"ok       {SETTINGS} {event}")
            continue
        print(f"{'would add' if dry else 'add'}  {SETTINGS} {event} hook")
        hooks.setdefault(event, []).append({"hooks": [{"type": "command", "command": command}]})
        changed = True
    if changed and not dry:
        if SETTINGS.exists():
            save(SETTINGS)
        SETTINGS.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main("--dry-run" in sys.argv[1:]))
