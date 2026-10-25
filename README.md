# Countersign

**A family app that stops "digital arrest", KYC and fake-relative scam calls while they happen, on the phone itself.**

**Countersign in two minutes** (an overview; the working app is shown live on the phone):

https://github.com/user-attachments/assets/9b032668-20ea-406b-acd6-e2d188ba4b15

Every number in the video is from [docs/RESULTS.md](docs/RESULTS.md); the clip marked "Real app, recorded" is the app
on an emulator. The video is made in code: [video/](video/README.md).

An Indian scam call today: someone rings Mummy saying they're CBI, or her bank, or "Rahul's friend, Rahul's had an
accident". Within the hour she has shared an OTP or sent money by UPI. Countersign is installed by the whole family:

1. **Is it really Rahul?** When a caller claims to be family, the app asks Rahul's own phone whether it's on this call.
   "Not Rahul's phone" appears on top of the dialer.
2. **Does this call sound like a scam?** On speaker, the phone listens, turns speech into text *on the phone*, and runs
   our conversation check: a model that reads the whole call so far and judges what the caller is doing (claiming to be
   police, threatening arrest, asking for the OTP or a transfer), not which words appear; plus the voice-clone check and
   what the phone sees (unknown number, AnyDesk opened). The card turns amber with the scam named and *why it fired*.
3. **It acts.** At red, the family's phones ring full screen ("Mummy may be on a scam call", Call / Message), an SMS
   goes out if their app is off, and a red screen stops her in GPay or PhonePe.
4. **A mistake costs one tap.** "I know this caller" / "It's not a scam" clears it at once and tells the family.

The phone checks every call itself. Only a call it already finds suspicious (amber) is also streamed to the detection server for a stronger check, where audio is held in memory and dropped; only a call confirmed as a scam keeps a 20 s encrypted evidence clip for the fraud desk, deleted after 30 days. Transcripts are never stored. Family messages carry ids only.

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
| Phone | **our conversation model**: multilingual-e5-small fine-tuned on ICFD-31k + our sets, judged over the whole call; our own Kotlin tokenizer (= Hugging Face) | `data/listen/Conversation.kt`, `ConversationModels.kt`, `ml/conv_model.py` |
| Phone | scam-move matcher (the plain-words "why") and the call accumulator (thresholds set on dev at fixed false-positive rates) | `ml/moves.py`, `assets/moves.json`, `assets/conv.json`, `ml/eval/conv_eval.py` |
| Phone | basic mode, before the model pack is installed: cue scorer + our small n-gram classifier | `data/listen/ScamScorer.kt`, `ScamClassifier.kt`, `assets/scam_patterns.json` |
| Phone | **our voice-clone check**: first K layers of AntiDeepfake W2V-Large + our head, ONNX int8 | `VoiceCheck.kt`, `ml/voice_clone.py` |
| Phone | evidence rules: red needs the conversation held above its threshold, or the conversation at amber plus what the phone saw; the voice check never makes red | `Conversation.kt` (Accumulator), `Analyzer.kt` |
| Phone | caller check, context signals, pay guard, family alarm, SMS fallback | `CallContext.kt`, `ScamAlert.kt`, `Overlay.kt` |
| Detection server (a team laptop now; the bank's servers later) | the stronger check for suspicious calls (`/ws/listen`: Omnilingual 1B, the same conversation check, full S1), the bank contact-centre path (S1–S4, policy, step-up, agent console, fraud desk), family links, caller checks, alarms | `engine/app.py`, `engine/listener/live.py` |
| Relay (optional, no ML) | the same family messaging without the detection server, on a free host | `engine/relay.py` |

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

Measured at 7f804d6 2026-10-24 20:27:49 +0530 with `python tools/onsite_share.py` (non-blank lines, `git blame`, after tag `check-in`):

| Kind | Folder | Lines | Written at the finale |
|---|---|---:|---:|
| code | **all** | 24802 | 61% (15039) |
| code | android | 9811 | 99% (9698) |
| code | engine | 6528 | 40% (2579) |
| code | ml | 4590 | 53% (2427) |
| code | web | 2266 | 8% (187) |
| code | integrations | 1320 | 0% (0) |
| code | (root) | 100 | 34% (34) |
| code | deploy | 74 | 1% (1) |
| code | tools | 65 | 100% (65) |
| code | .github | 48 | 100% (48) |
| docs | **all** | 1454 | 72% (1043) |
| docs | docs | 1115 | 84% (939) |
| docs | integrations | 177 | 0% (0) |
| docs | (root) | 70 | 96% (67) |
| docs | deploy | 38 | 13% (5) |
| docs | android | 33 | 73% (24) |
| docs | web | 13 | 0% (0) |
| docs | .github | 8 | 100% (8) |
