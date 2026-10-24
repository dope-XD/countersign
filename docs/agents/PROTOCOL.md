# How agents A, B and C work together

All coordination goes through GitHub (`dope-XD/countersign`): issues for work, PRs for code, one pinned **Standup** issue (label `standup`) for news. The humans don't relay anything routine.

## Every work block (each `/loop` tick)

```bash
git checkout main && git pull --rebase origin main
gh issue list -l role:<me> -s open           # my work
gh issue list -l needs:<me> -s open          # someone is waiting on me
gh issue view $(gh issue list -l standup --json number -q '.[0].number') --comments | tail -40   # recent news
```

Then work in this order:

1. Answer any `needs:<me>` issue that's waiting on you.
2. Carry on with the issue you've claimed, if there is one.
3. Otherwise claim the next open `role:<me>` issue, lowest milestone first (P1, then P2, then P3), then the lowest number.
4. If there's nothing to do, say so in one line and stop until the next tick.

Labels: `role:backend` = A, `role:ui` = B, `role:platform` = C.

## Claiming and finishing an issue

1. Claim it: `gh issue comment <n> -b "on it"`. Also assign yourself if you have your own GitHub account; agents that share one only comment.
2. Make a branch: `git checkout -b <role>/<n>-<slug>`, e.g. `ui/12-home-screen` or `platform/15-call-events`.
3. Keep the PR small: one issue per PR, inside your owned paths. Run `./check.sh --android` (B, C) or `.\check.ps1` (A).
4. Push and open the PR:
   ```bash
   git push -u origin HEAD
   gh pr create --fill --body "Closes #<n>"
   ```
   Fill in the PR template. B adds screenshots in English and Hindi; C adds what was tested on which device.
5. Comment on Standup: `PR #<pr> for #<n> ready`.
6. Go on to the next issue. Don't wait for the merge. If the next issue depends on the open PR, branch from your PR branch.

## Needing something from another agent

- **Open an issue**, or comment on an existing one, labelled `needs:<their role>`. Say exactly what you need: an endpoint and its JSON, a string key, a `Models.kt` field, a composable's parameters.
- **Never edit their files.** If it blocks you, label your own issue `blocked` and work on the next one.
- **Contract changes** (`CONTRACT.md`, `data/Models.kt`, `data/Repository.kt`) go in a `contract-change` issue. A makes the change in one PR, merges it, and posts "contract changed, pull now" on Standup. B and C then rebase their branches: `git fetch origin && git rebase origin/main`.

## Merging (A only)

- CI must be green and the PR must stay inside its owner's paths.
- A squash-merges (`gh pr merge <n> --squash --delete-branch`) with a plain message and no AI lines.
- A then comments on Standup: `merged #<pr> (<what>), pull main`.
- If a PR touches someone else's files, A asks for that part to be split out instead of merging it.
- A reviews open PRs at least every tick and merges within about 30 minutes.

## Standup

- Every ~2 hours, and whenever you switch issues, each agent comments three lines on the Standup issue:
  ```
  B: done #12 home screen (PR #20) · doing #14 overlay card · blocked: none
  ```
- A announces dev-server changes there: a restart, a new URL, a database reset, a new APK.

## Keeping every agent going: `/loop`

A Claude Code session only acts when it receives a message. Nothing on GitHub can wake it. So each laptop runs Claude Code's `/loop`, which re-sends the same prompt to the session every 10 minutes. Start it right after the session knows its role, and paste these exactly:

**A (lead, GPU Windows)**
```
/loop 10m You are agent A (backend lead). Follow docs/agents/PROTOCOL.md: pull main, review open PRs and merge the green ones that stay in their owner's paths (post on Standup), answer needs:backend issues, then continue your current role:backend issue or claim the next one. If nothing is open, say so in one line.
```

**B (Android UI, Mac)**
```
/loop 10m You are agent B (Android UI). Follow docs/agents/PROTOCOL.md: pull main, check issues labelled role:ui or needs:ui and new Standup comments, then continue your current issue or claim the next one. If nothing is open, say so in one line.
```

**C (phone features + QA, Windows #2)**
```
/loop 10m You are agent C (phone features and QA). Follow docs/agents/PROTOCOL.md: pull main, check issues labelled role:platform or needs:platform and new Standup comments, then continue your current issue or claim the next one. If nothing is open, say so in one line.
```

**How the loop behaves**

- While an agent is mid-task it keeps working inside its turn. The next tick picks up whatever arrived in the meantime.
- The loop only runs while the Claude app is open with that session, and the laptop is awake. Turn on the app's keep-awake setting, keep the laptop plugged in, and keep the lid open.
- After a restart, a closed lid or quitting the app, start the loop again with the same command.
- To stop a loop, press Esc or ask Claude to stop the loop.

**Backstop.** Each human glances at Standup about once an hour. If an agent has been quiet for 2 hours, re-prompt it.

## Dev server

A runs the engine and a free ngrok tunnel on the GPU laptop. The URL is in `CONTRACT.md`. A posts on Standup when it's down or restarted.
