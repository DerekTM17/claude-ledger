# ledger

Cross-project changelog and backlog tracker. CLI + read-only web view over per-project `docs/CHANGELOG.md` and `docs/BACKLOG.md` files.

Built to be driven by Claude Code: hooks note each session, and skills tell Claude when to record work.

## Setting up on a new machine

Works on Linux, macOS and WSL. (Native Windows is untested: the hooks use
`.venv/bin/` and the installer makes symlinks.)

```bash
git clone https://github.com/DerekTM17/claude-ledger.git ~/projects/ledger
cd ~/projects/ledger
python3 -m venv .venv && .venv/bin/pip install -e .
touch ~/.claude/CLAUDE.md                     # so the installer adds the ledger section
.venv/bin/python scripts/install_instructions.py --dry-run   # preview
.venv/bin/python scripts/install_instructions.py
```

The installer, which is safe to re-run:

- links the `ledger-capture` and `session-checkpoint` skills into
  `~/.claude/skills/` (and the Codex / OpenCode skill folders);
- adds the `## Ledger` instructions section to `~/.claude/CLAUDE.md` and any
  existing `AGENTS.md`;
- adds the `SessionStart` / `SessionEnd` hooks to `~/.claude/settings.json`.

Anything it replaces is backed up first under
`~/.local/share/ledger/instructions-backup/`.

Then put `ledger` on PATH (e.g. `ln -s ~/projects/ledger/.venv/bin/ledger ~/.local/bin/`)
and give each project you want tracked a git repo under `~/projects/`.
`ledger status` should list them.

If you launch Claude Code from somewhere other than your home directory, set
`LEDGER_MEMORY_ROOT` to that launch folder's `~/.claude/projects/<slug>/memory`
so the dashboard can show each project's memory note.

## Quick start

```bash
ledger status                                   # cross-project terminal dashboard
ledger idea trackforge "easing on curve snap"   # append to BACKLOG (Soon)
ledger ship trackforge "curve snap fix"         # prepend a CHANGELOG entry
ledger edit trackforge                          # open BACKLOG.md in $EDITOR
ledger search "rate limit"                      # grep across all projects
ledger serve                                    # start the web dashboard
```

## Web dashboard — persistent via systemd-user

```bash
mkdir -p ~/.config/systemd/user
cp systemd/ledger-web.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now ledger-web
systemctl --user status ledger-web
```

Then open http://localhost:7777/.

### Fallback (systemd-user unavailable)

```bash
nohup .venv/bin/ledger serve >/tmp/ledger-web.log 2>&1 &
```

## Project discovery

By default `ledger` scans `~/projects/*/` for any directory containing `.git/`. Override via `~/.config/ledger/projects.yaml`:

````yaml
include:
  - path: ~/AI-Projects-Core/ollama-desktop-extension
    slug: ollama-desktop
exclude:
  - dashboards
memory_overrides:
  netgraph-ai: project_netgraph_ai.md
````
