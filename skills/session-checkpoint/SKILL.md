---
name: session-checkpoint
description: Use when cutting a session at a natural boundary — a task is done, work is pausing, the status line shows a high +$/turn, or the user says "wrap up" / "let's stop here" / "checkpoint this". Writes a resumable handoff to docs/SESSIONS.md so starting a fresh session costs nothing, then captures shipped work via ledger. Also use before a long unrelated task in the same session, where continuing would drag the accumulated context along.
---

# session-checkpoint

Write a handoff good enough that a fresh session picks up where this one left off.

**Why this exists.** Cost tracks (context size × number of API calls): every turn re-reads the whole accumulated context, so a session's marginal cost climbs the longer it runs. Measured locally, 62% of spend sat in ten marathon sessions, one of them 3,539 calls at 226k average context — about 11 cents per call in cache reads alone, where the same work at 60k context would have cost a quarter of that.

Starting fresh resets that to near zero. Sessions run long anyway because ending one *feels* like losing the thread. This removes that reason.

The `SessionEnd` hook already appends a diffstat stub to `docs/SESSIONS.md`. That records what files changed; it does not record what you were *doing*. This does.

## Procedure

1. **Check there's a real boundary.** A checkpoint mid-thought is worse than none — the next session inherits a puzzle. Good boundaries: a task finished and verified, a decision made, a blocker hit that needs the user. If you're mid-edit with tests unrun, finish or revert first.

2. **Write the handoff** to `docs/SESSIONS.md`, appended under today's date as `#### Handoff — <short title>`. Cover, in this order, skipping anything that doesn't apply:
   - **Goal** — what we set out to do, in one sentence.
   - **Done** — what actually landed, and *how it was verified* (command + result, not "should work"). Name commits.
   - **Next** — the concrete next action, specific enough to start cold. Not "continue the refactor" but "wire `parsers/codex.js` model attribution to the per-turn field; `node scripts/reconcile.mjs` should drop terra below 2%".
   - **Decisions** — choices made and *why*, so a fresh session doesn't re-litigate them.
   - **Gotchas** — anything discovered the hard way that isn't obvious from the code.
   - **Resume** — the exact commands to get back to a working state.

3. **Capture shipped work.** If something shipped, invoke the ledger-capture skill (or run `ledger ship`) — the handoff is for resuming, the CHANGELOG is the durable record. They are different artifacts; write both.

4. **Log what surfaced but wasn't done** with `ledger idea <project> "Headline" --note "..."`. Keep the headline short and plain; put the context needed to act on it cold in the note. Findings that live only in a transcript are lost at `/clear`.

5. **Tell the user** the state is captured and recommend a fresh session, with the resume command. Say plainly what is unfinished.

## Quality bar

- **Write for someone with no memory of this session** — including you, tomorrow. Terms you coined mid-session mean nothing cold; spell them out.
- **Verified vs assumed.** If tests weren't run, say so. A handoff that overstates completion is worse than none, because the next session builds on a false floor.
- **Concrete next action, not a direction.** The whole value is that the next session starts without re-deriving anything.
- **Don't dump the diff.** The hook already captured it, and it's the least useful part.
- **Skip the checkpoint entirely** for a short session with nothing in flight — a handoff nobody needs is noise in the log.
