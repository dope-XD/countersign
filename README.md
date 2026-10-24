# Countersign

**A family app that stops "digital arrest", KYC and fake-relative scam calls while they happen, on the phone itself.**

An Indian scam call today: someone rings Mummy saying they're CBI, or her bank, or "Rahul's friend, Rahul's had an
accident". Within the hour she has shared an OTP or sent money by UPI. Countersign is installed by the whole family:

1. **Is it really Rahul?** When a caller claims to be family, the app asks Rahul's own phone whether it's on this call.
   "Not Rahul's phone" appears on top of the dialer.
2. **Does this call sound like a scam?** On speaker, the phone listens, turns speech into text *on the phone*, and runs
   our scam check: cue words (police, warrant, "don't tell anyone", OTP…), our own classifier, the voice-clone check and
   what the phone sees (unknown number, AnyDesk opened). The card turns amber with the scam named and *why it fired*.
3. **It acts.** At red, the family's phones ring full screen ("Mummy may be on a scam call", Call / Message), an SMS
   goes out if their app is off, and a red screen stops her in GPay or PhonePe.
4. **A mistake costs one tap.** "I know this caller" / "It's not a scam" clears it at once and tells the family.

No audio or words ever leave the phone. A small relay with no ML passes family messages (ids only).

## How well it works

All numbers are measured on public data the model never trained on. They are reproduced by one command on any laptop:
[docs/RESULTS.md](docs/RESULTS.md).

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m ml.eval.run_all          # every table in RESULTS.md (~3 min, CPU)
.venv/bin/python -m ml.eval.kit data/kit     # the 30-item spot-check kit: pass/fail table
.venv/bin/python -m ml.eval.kit <any folder> # a jury's own recordings (.wav/.mp3/.m4a…) and messages (.txt)
```

The same files work on the phone's **Check a recording or message** screen (Home), with the same verdicts. Kotlin and
Python give identical answers on shared test vectors, checked in CI.

## The pieces

| Where | What | Code |
|---|---|---|
| Phone | speech-to-text: Silero VAD + Omnilingual-300M (sherpa-onnx), picked by our bake-off | `android/…/Speech.kt`, `ml/eval/asr_bakeoff.py` |
| Phone | cue scorer: 15 cue categories, 12 scam types, negation, English/Hindi/Hinglish | `data/listen/ScamScorer.kt`, `assets/scam_patterns.json` |
| Phone | **our scam classifier**: hashed character n-grams, logistic regression, trained on 4 public sets + ours | `data/listen/ScamClassifier.kt`, `ml/listener_clf.py` |
| Phone | **our voice-clone check**: first K layers of AntiDeepfake W2V-Large + our head, ONNX int8 | `VoiceCheck.kt`, `ml/voice_clone.py` |
| Phone | fusion: scam needs two kinds of evidence; one model never makes red alone | `data/listen/Fusion.kt`, `Analyzer.kt`, `assets/fusion.json` |
| Phone | caller check, context signals, pay guard, family alarm, SMS fallback | `CallContext.kt`, `ScamAlert.kt`, `Overlay.kt` |
| Relay | sign-up, family, caller checks, scam alert, "Not a scam", events (no ML) | `engine/relay.py` |

The contract between the app and the relay: [docs/agents/CONTRACT.md](docs/agents/CONTRACT.md). Deployment, costs and a
pilot: [docs/DEPLOY.md](docs/DEPLOY.md). How an attacker would get past it: [docs/ADVERSARIAL.md](docs/ADVERSARIAL.md).

## Install and run

- **The app:** the APK from the [latest release](https://github.com/dope-XD/countersign/releases), or
  `cd android && ./gradlew assembleDebug`. First run: language, name and number, the permission cards, then
  Settings → "Download the scam check" (one time). How a demo runs: [docs/RUNBOOK.md](docs/RUNBOOK.md).
- **The relay:** `uvicorn engine.relay:app --port 8000` locally, or `Dockerfile.relay` / `render.yaml` on a free host.
- **Checks:** `./check.sh` (ruff, pytest, Android build + lint + unit tests).

## Built before / built at the finale

The Round 1 prototype (a bank-side voice engine on a laptop GPU) is everything up to the
[`check-in`](https://github.com/dope-XD/countersign/releases/tag/check-in) tag. What we declared, and what was built,
changed or cut on site: [docs/DISCLOSURE.md](docs/DISCLOSURE.md) and [docs/PLAN_VS_BUILT.md](docs/PLAN_VS_BUILT.md).

ONSITE_SHARE
