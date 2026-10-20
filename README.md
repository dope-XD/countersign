# Countersign

A voice can ask the bank for anything. The customer's own phone has to sign before anything risky happens.

RAKSHAM 2026 · Problem statement 01 (voice-cloning fraud) · Team losers: Pushkar Joshi, Sarah Mittal, Reshaan Nadar.

## What's here

| Part | Where | What it does |
|---|---|---|
| Engine | `engine/` | FastAPI app: live call audio over websockets (8 kHz G.711), S1–S4 signals, fusion, policy, passkey step-up, cases, Entry B guard |
| S1 synthetic speech | `engine/signals/antideepfake_model.py`, `sls_model.py`, `s1_synth.py` | ensemble of NII AntiDeepfake W2V-Large + XLS-R-1B (XLS-R + SLS kept as fallback), ported from fairseq to transformers |
| S2 speaker drift | `engine/signals/s2_drift.py` | ECAPA-TDNN, this call only, nothing stored |
| S3 liveness | `engine/signals/s3_liveness.py` | random challenge, reply timing, faster-whisper word check, S1 on the reply |
| S4 context | `engine/signals/s4_context.py`, `engine/mocks/world.py` | caller ID, SIM swap, DoT FRI, repeat calls (mocked feeds) |
| Policy | `engine/policy.yaml`, `engine/policy.py` | tier × request risk, enforced server-side |
| Passkeys | `engine/stepup/passkeys.py` | WebAuthn, challenge bound to the exact request shown on the phone |
| Web | `web/` | caller softphone, agent console, bank app (PWA), fraud desk, metrics, demo panel, IndiaCall recorder |
| ML | `ml/` | checkpoint port, telephony augmentation, fine-tuning, benchmarks, IndiaCall simulator, clone generators |

## Quick start (Windows, PowerShell)

```powershell
.\run.ps1            # builds the web app if needed, starts the engine on http://localhost:8000
```

Then open http://localhost:8000/demo. Staff pages (agent console, fraud desk, demo panel, metrics, recorder) ask for the **staff PIN**, which the engine prints in its console at startup. Set your own with `$env:COUNTERSIGN_STAFF_PIN`. The bank app and the softphone don't need it. For phones, see [docs/RUNBOOK.md](docs/RUNBOOK.md) (HTTPS tunnel, passkeys).

## Checks and tests

```powershell
.\check.ps1          # ruff lint + format, pytest (unit + API regression), eslint, tsc, web build
git config core.hooksPath .githooks   # once per clone: runs the fast checks on every commit
```

Code style: `ruff format` for Python, ESLint for the web app. Please keep `.\check.ps1` green.

## Docs

- [docs/RUNBOOK.md](docs/RUNBOOK.md): setup, tunnel, phones, troubleshooting
- [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md): the four scenes for the judges
- [docs/ML.md](docs/ML.md): detector port, data, fine-tuning, evaluation
- [docs/CLONES.md](docs/CLONES.md): making consented clones for IndiaCall
- [docs/CONSENT.md](docs/CONSENT.md): consent form for teammates
- [docs/MODEL_CARD.md](docs/MODEL_CARD.md) and [docs/DATA_SHEET.md](docs/DATA_SHEET.md)

## Disclosure

Code written with Claude Code (Anthropic) and reviewed by the team. S1 uses NII's AntiDeepfake weights (Yamagishi Lab, CC BY-NC-SA 4.0, research and education only). Mocked in the prototype: core banking, DoT FRI, telco SIM-swap feed, NCRP/1930 and DIP submission.
