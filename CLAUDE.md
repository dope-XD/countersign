# Countersign: read this first

Three Claude Code sessions on three laptops build this repo together. Each one is an **agent** with its own role:

| Agent | Laptop | Role | Brief |
|---|---|---|---|
| **A** | Windows + RTX GPU | Backend lead: engine, contract, docs, CI. **Only A merges to `main`.** | `docs/agents/backend.md` |
| **B** | Mac | Android UI: every screen, strings (English + Hindi), theme | `docs/agents/ui.md` |
| **C** | Windows #2 | Android phone features (call events, overlay, pay guard, ring) and QA | `docs/agents/platform.md` |

**At the start of every session:** if the human hasn't said which agent you are, ask them (A, B or C). Then read your brief and `docs/agents/PROTOCOL.md`. `docs/agents/CONTRACT.md` is the API between the engine and the app. `docs/agents/START.md` is how each laptop is set up.

## Rules for every agent

- **No AI attribution anywhere.** No `Co-Authored-By: Claude` trailers, no "Generated with Claude Code" lines, in commits, PRs, issues, comments or docs.
- **Stay in your owned paths** (your brief lists them). If you need a change in someone else's files, ask on a GitHub issue with a `needs:<role>` label. Never edit their files.
- **B and C never push to `main`.** Work on a branch `<role>/<issue#>-<slug>`, open a PR with `Closes #n`, and let A merge it.
- **The contract** (`docs/agents/CONTRACT.md`, `android/.../data/Models.kt`, `android/.../data/Repository.kt`) changes only through a `contract-change` issue, and only A edits it.
- Run `check.ps1` (Windows) or `check.sh` (Mac) before you open a PR. B and C can run `./check.sh --android`.
- Never commit `data/runtime/` (the staff PIN and keys live there) or real people's data.
- Plain, short writing for users: no jargon on screen (see `docs/agents/ui.md`).

## Agent A: turning the human's requests into work

Agent A is where the humans bring new work. For every new request, before writing code:

1. Split it into the smallest pieces that each have **one owner** by path: engine, web, docs or CI → A (`role:backend`); screens, strings, theme → B (`role:ui`); services, permissions, overlay window, `RealRepository`, manifest, gradle, device testing → C (`role:platform`).
2. If the pieces need a new endpoint, field or event, change the contract **first** (one small PR that A merges itself), so B and C can build against it at once. B builds on `FakeRepository`; C builds on the real API.
3. Open one GitHub issue per piece with `gh issue create`. Each needs a role label, a milestone, the exact files, a "done when" line, and any `needs:` dependency. Then comment on the Standup issue: "new: #n (ui), #m (platform)". B and C pick it up on their next `/loop` tick, without a human.
4. A does only the `role:backend` pieces itself, then reviews and merges B's and C's PRs. Tell the human in a line or two which agent got what.

A quick question or a one-file backend fix doesn't need an issue. Anything B or C has to do does.
