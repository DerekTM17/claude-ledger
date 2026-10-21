## Ledger: what shipped and what's next, across all projects

`ledger` tracks each project's `docs/CHANGELOG.md` (finished work) and `docs/BACKLOG.md` (open work). The command is on PATH; if it's missing, use `~/projects/ledger/.venv/bin/ledger`. Project names are the folder names; `ledger status` lists them.

- **First, run `ledger rules` and follow them.** People who don't write code read ledger. It refuses text that breaks the rules; fix the text and run the command again.
- **Start of meaningful work:** `ledger status` shows every project's last finished work and next task.
- **Finished something meaningful:** `ledger ship <project> "What changed" --why "Why it matters."` Do it without asking. Technical detail goes in the commit message, never in ledger.
- **New task or idea:** `ledger idea <project> "Headline" --note "Working detail"`.
- **Finished a backlog item:** `ledger done <project> "words from its headline"`.
- Never edit CHANGELOG.md, BACKLOG.md or BACKLOG-DONE.md by hand. The commands commit for you.
- More detail, including catching up on sessions that ended without an entry: the `ledger-capture` skill.
