# Plan vs built

Our Round 1 submission was a three-page architecture: *End-to-end system and data flow*, *Detection logic*, and
*Human review, escalation, security and privacy*. Every row below is a promise from those pages, with what is in the
repository now and the evidence (code, a test or a measurement). "Changed" means built differently, with the reason.

## Page 1: system and data flow

| Round 1 promise | Status | What is built / why it changed |
|---|---|---|
| Runs in a trusted cloud boundary; hears only calls the bank receives and voice notes the customer shares | **Built, widened** | The engine runs on a team laptop today (`engine/app.py`, reached through a tunnel), the stand-in for the bank's cloud. On site we added the customer's own phone as a listener (Entry B), because most Indian scams reach the victim on their personal number, not the bank's |
| Entry A: caller → contact centre / IVR (Amazon Connect or SIP, tracks forked at 8 kHz) → ingest | **Built** (before the finale) | `/ws/caller`, `integrations/connect`, `engine/ingest/connect.py`; the web caller page stands in for a phone line |
| Ingest: VAD, 4 s windows every 2 s, audio in memory only | **Built** | `engine/session.py`; and the same rule on the phone (`Speech.kt`, Silero VAD) and in `/ws/listen` |
| S1 synthetic speech, S2 speaker drift, S3 liveness, S4 context | **Built** | `engine/signals/`; S1 is now the AntiDeepfake W2V-Large (the ensemble's second model was on the GPU laptop), loaded with its calibration. On the phone: a 6-layer version of the same model (`ml/voice_clone.py`) |
| Fusion → calibrated score, tier and reason codes | **Built, extended** | Bank side `engine/fusion.py`; call side `fusion.json` (cues + our classifier + context + voice + server), Kotlin = Python on shared vectors |
| Policy engine: tier × context × requested action | **Built** | `engine/policy.py`, `policy.yaml`; `test_api.py` |
| Agent console (Voice Trust Card) → fraud desk (human analyst) | **Built** | `web/src/pages/Agent.tsx`, `FraudDesk.tsx`; served by the laptop engine at `/agent`, `/fraud` |
| Step-up: approval request to the customer's registered phone, passkey signature | **Built** | `engine/stepup/devicekeys.py`; the app's ring screen and fingerprint (`ApprovalActivity`, `RingScreen.kt`) |
| Case store + audit log; reporting (NCRP / 1930, DoT DIP) | **Built / partly** | `engine/cases.py`, audit table; the 1930 / DIP report is drafted in the case, not filed to a live API |
| B1 guard on the customer's phone (call active + new payee + unusual amount) | **Built, changed** | The pay guard (`PayGuardScreen.kt`, `Overlay.kt`) stops payment apps during a call the caller check or the listener flags. It doesn't see payee or amount (only the bank's app can) |
| B2 voice notes the customer chooses to share, scored, verdict in plain words | **Built, changed** | "Check a recording or message" (`CheckScreen.kt`): any recording or text, checked on the phone itself, nothing uploaded |
| B3 Family Circle: "did you ask for this payment?" | **Built, widened** | The caller check asks the claimed member's phone directly; the family alarm rings them; a **work circle** covers a boss or colleague ordering a payment |

## Page 2: detection logic

| Round 1 promise | Status | Evidence |
|---|---|---|
| S1 XLS-R + SLS, fine-tuned on phone codecs and Indic | **Replaced (before the finale)** | AntiDeepfake models won the phone-channel benchmark (`docs/ML.md`) |
| S2 ECAPA drift, no stored voiceprint | **Built** | `engine/signals/s2_drift.py` (loads on the laptop) |
| S3 random challenge, reply timing + ASR | **Built** | `engine/signals/s3_liveness.py`, agent console "challenge" |
| S4 caller ID, SIM swap, FRI, live app session | **Built (mocked sources)** | `engine/signals/s4_context.py`; telco and DoT feeds are simulated in the demo panel (`/demo`) |
| Logistic fusion, GREEN < 0.30 / AMBER / RED ≥ 0.70, top-3 reason codes | **Built** | `engine/fusion.py`; the same 0.70 RED cut-off is used for S1 in `/ws/listen` |
| Tier × request table (balance … change mobile, add payee, raise limit) | **Built** | `engine/policy.yaml` |
| "Which layer stops which attacker", performance targets (p95 ≤ 300 ms per window on one GPU) | **Measured** | `models/eval/load_rtx5070-laptop*.json` (before the finale); `docs/ADVERSARIAL.md` |
| Design expectations "to be measured at the finale" | **Measured** | `docs/RESULTS.md`: held-out sets, false positives, the spot-check kit, named failure cases |

## Page 3: human review, escalation, security and privacy

| Round 1 promise | Status | Evidence |
|---|---|---|
| L0 automatic (can hold, never refuse service) → L1 agent (can't override RED) → L2 analyst (decide in 15 min) | **Built** | `policy.py`, agent console, fraud desk |
| Fraud confirmed / false alarm / unsure outcomes; two analysts before a label enters training | **Built / partly** | `cases.resolve`; on the phone, "Not a scam" keeps an ids-only record for weekly review (`/api/metrics`); no automatic retraining |
| Raw call audio: not kept, 20 s rolling memory buffer | **Built** | `session.py`, `live.py`, `Speech.kt` |
| Evidence clip ≤ 20 s for RED only, AES-256, deleted after 30 days | **Built** | `cases.store_clip`; `/ws/listen` opens a RED case with the clip (tested with the kit scam call) |
| Scores, tier, reason codes, model version kept | **Built** | case store; `model_version` on every case |
| Speaker embeddings memory only; voiceprints never collected; challenge transcripts not kept | **Built** | S2 per call; transcripts never stored (phone or server) |
| Call state on the customer's phone checked on the phone; only "guard fired" sent | **Built** | `CallContext.kt`; only context ids and scam-alert ids leave the phone |
| Family Circle: both consent, either can remove | **Built** | invite + confirm; "Remove from family" |
| Attacks on Countersign (stream injection, probing, insiders, poisoned labels, outages) | **Built / described** | TLS through the tunnel, device tokens, rate limits, role-gated clip access with audit; the phone keeps working alone when the server is down |
| DPDP, CERT-In, RBI rules | **Described** | `docs/DEPLOY.md` |
| Fairness: no group above 2× the overall false-positive rate | **Measured per language** | `docs/RESULTS.md`, "Per language" |

## Changed or cut on site, and why

| What | Why |
|---|---|
| **The customer's own phone became a listener** (Entry B grew from voice notes to live calls) | Round 1 could only protect calls into the bank. Most "digital arrest", KYC and fake-relative scams call the victim directly, so the phone now listens on speaker, explains itself in plain words, and alarms the family |
| **Hybrid detection** instead of all-server | The phone checks every call itself (on-device processing, a rubric safeguard); only calls it already finds suspicious go to the server's stronger check. Less audio leaves the phone, and the phone still works when the server is down |
| The local LLM judge and the earlier "stronger check for every call" | Replaced by our own classifier: measurable on held-out data, fast, and it runs on the phone |
| On-phone LLM (Gemma 3n) | 3–4 GB of RAM and slow on a mid-range phone |
| The bank's virtual voice agent, payments, kill switch, paid APIs (ElevenLabs, LLM APIs) | Removed in PR #33: not needed for detection, and they cost money per call |
| Amazon Connect as the live demo entry | Kept in the code; the demo uses the web caller page and real phones, which don't need an AWS account on stage |
