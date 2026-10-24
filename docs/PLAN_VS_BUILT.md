# Plan vs built

What the Round 1 plan and our finale disclosure (section 3) promised, against what is in the repository now. Every
"built" links to the code and to a test or measurement.

> **Round 1 48-hour plan text: to be pasted by the team.** The rows under "Round 1 plan" are filled in once it is here;
> the rows below cover the finale plan we declared at check-in and the final-build plan of 24 Oct, 19:30.

## Round 1 plan

| Promise | Status | Evidence / reason |
|---|---|---|
| *(team to paste each promise)* | | |

## Finale plan (declared at check-in) and the final build

| Promise | Status | Evidence / reason |
|---|---|---|
| Caller check: is the claimed family member's phone really on this call? | **Built** | `engine/callcheck.py`, `CallCheckCard.kt`; `engine/tests/test_calls.py` |
| Scam-pattern scorer on the phone (cue categories, scam types, negations) | **Built** | `ScamScorer.kt` = `engine/listener/rules.py`; `ScamScorerTest`, `test_listener.py` |
| Fuse cues, caller check and context: "scam" needs two kinds of evidence | **Built** | `Fusion.kt` = `fusion.py`; `AnalyzerTest`, `test_listener.py` |
| Warn and scam cards that say why they fired; one-tap "I know this caller" | **Built** | `CallCheckCard.kt` (`whyLine`), `notAScam`, `POST /api/m/scam-alert/clear`; `test_relay.py` |
| Pay guard over UPI apps | **Built** | `PayGuardScreen.kt`, `Overlay.kt` |
| Family alarm that rings, Call / Message; SMS when their app is off | **Built** | `FamilyAlarmScreen.kt`, `FamilyAlarmActivity.kt`, `ScamAlert.kt`; `test_relay.py` |
| Evaluation of the listener on public data | **Built, beyond plan** | `ml.eval.run_all`, `docs/RESULTS.md`: held-out sets, leave-one-dataset-out, false positives, failure cases |
| Server "stronger check": speech-to-text + a local LLM judge on the laptop | **Cut** | The team decided everything runs on the phone: the laptop tunnel had been down since 16:40 and was a single point of failure. Our own on-phone classifier took the judge's slot (PRs #58, #66 closed) |
| S1 voice model on the laptop | **Replaced** | Over a speakerphone its EER was 24–40%. Replaced by a small on-phone voice-clone check (first K layers + our head, ONNX int8), which can only raise amber (`ml/voice_clone.py`, RESULTS.md) |
| On-phone LLM (Gemma 3n) | **Cut** | 3–4 GB RAM and slow on a mid-range phone; our classifier is measurable and fast (#43 closed) |
| Bank-side flows (agent console, kill switch, payments) | **Cut earlier** | Removed in #33; the product is the family app |

## Added in the final build (not in either plan)

| What | Why | Evidence |
|---|---|---|
| Our scam classifier (char n-grams, logistic regression), Kotlin = Python | a measurable, fast model of our own in the judge slot | `ml/listener_clf.py`, `ScamClassifierTest` |
| On-phone speech-to-text chosen by a bake-off | the phone has to understand Hinglish without a server | `ml/eval/asr_bakeoff.py`, `models/eval/asr_bakeoff.json` |
| "Check a recording or message" on the phone | the jury's spot-check kit runs on the phone itself | `CheckScreen.kt`, `ml/eval/kit.py` |
| The relay with no ML (Render) | phone-to-phone messages without the laptop | `engine/relay.py`, `test_relay.py` |
