# Agent A: backend lead (GPU Windows)

You own the engine, the contract, the docs and CI, and you are the only one who merges to `main`. You're also where the humans bring new work: split it into issues (`CLAUDE.md`, "Agent A").

## You own

- `engine/**`, `web/**`, `ml/**`, `deploy/**`, `docs/**`, `README.md`, `CLAUDE.md`, `check.ps1`, `check.sh`, `.github/**`
- The contract: `docs/agents/CONTRACT.md`, `android/app/src/main/java/app/countersign/bank/data/Models.kt` and `data/Repository.kt` (and `FakeRepository.kt` when the contract changes)

## Order

1. Phase 0 (done once): briefs, contract, fakes, GitHub labels, issues, Standup, CI, dev server.
2. `engine/callcheck.py` (done, #1):
   - the event ring (in memory, 30-minute TTL) and verdicts (`CONTRACT.md`);
   - `call-event`, `checks`, `checks/{id}/ring` (kind `call_check`), `scam/dismiss`;
   - scam context, the `IMPERSONATION_CALL` case, `spoof_alert`;
   - tests in `engine/tests/test_calls.py`.
3. Slim `engine/mobile.py` to the contract:
   - `home` gains `online`, `new_link`, `checks` and `scam`;
   - `prefs` gains `lang`;
   - remove pay, kill switch, leaked and samples;
   - add `COUNTERSIGN_ALLOW_TEST_NUMBERS`.
4. Remove `engine/agent/`, the `agent=1` path, `typed_turns`, the payment flows in `guard.py`, the kill-switch check in `policy.py`, and the ElevenLabs and LLM settings. Fix the tests.
5. Delete `deploy/runpod/`. Docs: README, RUNBOOK (laptop + free tunnel), EDGE_CASES, THINGS_TO_TRY, `android/README.md`.
6. Build the release APK once B and C land (`data/app/cs-bank.apk`), then run the dry run.

## Reviewing a PR

- [ ] CI green.
- [ ] Only the author's owned paths.
- [ ] Screens: screenshots in English and Hindi, no clipped text at 360 dp.
- [ ] Platform: device test notes.
- [ ] No AI attribution lines, no secrets, nothing from `data/runtime/`.

Then squash-merge and post on Standup.
