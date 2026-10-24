# Finalist pre-event disclosure: team losers

The same text as the paper form. Everything that existed before check-in is declared below.

- **Baseline.** Check-in was before 11:14 on 24 Oct 2026. The last commit before it is `6997328` (22 Oct, 12:01 IST), now tagged [`check-in`](https://github.com/dope-XD/countersign/releases/tag/check-in). Everything up to and including that commit is pre-existing (2A–2C). History has not been rewritten.
- **Open question for the team before signing.** Commits `578d8b7` and `687ec43` (11:14–11:15 on 24 Oct) add about 12,000 lines in one minute. If any of that work was written before check-in, it moves into 2C and the baseline becomes `687ec43`.
- **Measured on-site share:** `python tools/onsite_share.py` (README, "Built before / built at the finale").

## 1. Team and repository

| Field | Entry |
|---|---|
| Team name | losers |
| Members | Pushkar Joshi (lead), Sarah Mittal, Reshaan Nadar |
| Round 1 submission ID | *(team to fill in)* |
| Repository | https://github.com/dope-XD/countersign |
| Initial commit at check-in | `6997328345f6ca88fecb23ea49c871ed7c5366f3` |
| Track | 1: Voice cloning fraud detection |
| Product statement (as approved in Round 1) | *(team to paste the exact sentence)* |

## 2A. Pre-trained models, embeddings and third-party APIs

| Model / API | Provider / framework | How we use it | Licence |
|---|---|---|---|
| AntiDeepfake wav2vec-large (`nii-yamagishilab/wav2vec-large-anti-deepfake`) | NII, Hugging Face → `transformers` | **On site:** only its first K layers, frozen, with our own logistic head trained on our data; exported to ONNX int8 for the phone (`ml/voice_clone.py`) | CC BY-NC-SA 4.0 (weights), BSD-3 (code) |
| AntiDeepfake XLS-R-1B, XLS-R-SLS | NII; Hugging Face | Before check-in: the laptop voice model (S1). **Cut** from the demo path on site | CC BY-NC-SA 4.0; MIT |
| Omnilingual ASR 300M CTC int8 | Meta, via sherpa-onnx | On-phone speech-to-text, off the shelf; chosen on site by our bake-off (`ml/eval/asr_bakeoff.py`) | Apache-2.0 |
| Silero VAD | snakers4, via sherpa-onnx | Splits speech on the phone | MIT |
| sherpa-onnx 1.13.8, onnxruntime-android 1.22 | k2-fsa; Microsoft | On-phone runtimes | Apache-2.0; MIT |
| Our scam classifier | ours, trained on site | Hashed character n-grams + logistic regression, `ml/listener_clf.py`; runs in pure Kotlin | ours |
| Test-set voices: Microsoft edge-tts (en-IN, hi-IN) | Microsoft | Only to speak our test scripts for evaluation and the spot-check kit; never in the product | Microsoft service terms |
| Amazon Connect + Kinesis Video Streams, RunPod, ngrok | AWS; RunPod; ngrok | Before check-in only; not in the final demo path | Pay per use / free tier |
| Render (free web service) | Render | Hosts the relay (no ML) | Free tier |

Brought in before check-in, then removed on site (PR #33): ElevenLabs TTS/STT and the Groq, Gemini and Mistral LLM APIs used by the old bank assistant. Cut on site: the Ollama LLM judge and faster-whisper on the laptop (PRs #58, #66 closed).

## 2B. Datasets

All public or self-generated; no banking or customer data.

| Dataset | Format | Licence / provenance | Use |
|---|---|---|---|
| ysangam/Indian_Cyber_Scam_PhoneCall_Hinglish_Dataset | text | Apache-2.0 | classifier train/dev/test (743 distinct of 10,000 rows) |
| BothBosu/scam-dialogue | text | Apache-2.0 | classifier train/dev; its test file held out |
| anmolshrivastav/scam_ham_india_14_languages | text | MIT | classifier train/dev (en/hi/Hinglish); its test suite held out |
| bolewara/hinglish-scam-text-dataset (UCI SMS + Hinglish) | text | CC BY 4.0 | test only |
| Our template calls (`ml/listener_synth.py`), our 27 hand-written calls, our 30 adversarial calls | text | ours | train/dev; test; test |
| ASVspoof 2019 LA train, IndicSynth Hindi (3 shards), FLEURS hi_in | audio | ODC-By; CC BY-NC 4.0; CC BY 4.0 | voice-clone train/dev |
| In-the-Wild, ReplayDF | audio | Apache-2.0 mirror; CC BY-NC 4.0 | voice-clone test only |
| FLEURS hi_in validation | audio | CC BY 4.0 | real voices in the test sets and the kit |

Known overlap: ASVspoof 2019 and FLEURS are in AntiDeepfake's own training data (`docs/ML.md`).

## 2C. Pre-built code and scaffolds

Everything in the repository at `6997328` (18–22 Oct) is the Round 1 prototype:

| Component | What it is | Why it existed |
|---|---|---|
| `engine/` (~7.9k lines) | FastAPI voice-trust engine: S1 synthetic-voice detector, S2 speaker drift, S3 liveness, S4 context, fusion, policy, cases, mobile API, Amazon Connect ingest | Round 1 detection core |
| `ml/` (~3.7k lines) | dataset fetch and manifests, codec augmentation, S1 fine-tune and calibration, benchmarks | Round 1 model work |
| `web/` (~2.4k), `android/` (~3.3k, the first CS Bank app) | React demo consoles; bank app with onboarding, family, pay, call | Round 1 demo |
| `integrations/connect`, `deploy/runpod`, `docs/` | Amazon Connect spike; GPU hosting; runbook, model card, data sheet, consent | Groundwork and docs |

## 3. Built live at the finale

Declared on the form before building; what was actually built, and what was cut and why, is in [PLAN_VS_BUILT.md](PLAN_VS_BUILT.md).

| Area | Built on site |
|---|---|
| Detection | Everything on the phone: on-phone speech-to-text, the cue scorer, our scam classifier (Kotlin = Python on shared vectors), the voice-clone check (first K layers + our head, ONNX int8), context signals and fusion; "Check a recording or message" |
| Alert and response | The call card says why it fired; pay guard; family alarm that rings full screen, Call / Message; SMS when the family's app is off; "Not a scam" in one tap, which tells the family |
| Safeguards | Scam needs two kinds of evidence; one model never makes scam alone; audio and words never leave the phone; alerts carry ids only; false alarms kept as ids-only records for human review |
| Measurement | `python -m ml.eval.run_all`, `python -m ml.eval.kit`, `docs/RESULTS.md` with false positives and named failure cases on held-out public data |

## 4. Undertaking and 5. Signatures

Each member reads and ticks the declarations on the paper form themselves. `data/runtime/` (keys, staff PIN) is gitignored and holds no real customer data.
