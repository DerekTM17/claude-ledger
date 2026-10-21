---
name: ledger-capture
description: Use when finishing a meaningful chunk of work in a ledger-tracked project, to record it with `ledger ship`; when a backlog item is finished (`ledger done`) or a new one comes up (`ledger idea`); and when the session greeting says earlier sessions "ended without a changelog entry" (the user may say "capture the missed sessions").
---
# ledger-capture

Ledger records what each project finished (`docs/CHANGELOG.md`) and what's
next (`docs/BACKLOG.md`). People who don't write code read it, so ledger
enforces plain-language rules and refuses text that breaks them.

## First: read the rules

Run `ledger rules` once per session before writing anything. Follow them
exactly. Don't restate them from memory; they can change.

## Record finished work (default, don't ask first)

When you finish a meaningful piece of work in a project with a
`docs/CHANGELOG.md`, run:

    ledger ship <project> "What changed, in plain words" --why "Why it matters."

- Write for someone who uses the project, not someone who reads its code.
  "Social icons now show the right brand logos", not "Refactor icon map".
- Technical detail (file names, functions, commit hashes, PR numbers) goes in
  the commit message. It never goes in ledger.
- One entry per outcome, not per commit. Skip typo fixes, formatting and
  changes nobody can see. When in doubt, skip.
- If ledger refuses the entry, read each message, rewrite, and run it again.
  Never work around the rules by editing CHANGELOG.md by hand.

## Backlog

- New task or idea: `ledger idea <project> "Headline" --note "Working detail"`.
  The headline is plain and short. The note is for whoever picks it up; code
  names and paths are fine there.
- Finished a backlog item: `ledger done <project> "words from its headline"`.
  If several items match, use more words. It moves to the Done list.
- Never edit BACKLOG.md or BACKLOG-DONE.md by hand. The commands commit for you.

## Sessions that ended without an entry

The session greeting may say `⚠️ N earlier sessions ended without a changelog
entry`. When the user says "capture the missed sessions" (or asks what was
missed):

1. Read the latest stubs in `docs/SESSIONS.md`, if the file exists.
2. Run `git log --oneline -30` in the project and find the commits since the
   last CHANGELOG entry's date.
3. Group the commits into outcomes. Run `ledger ship` once per outcome that is
   worth recording, following the rules above.
4. Recording any entry clears the warning for those sessions.
