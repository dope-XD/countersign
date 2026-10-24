# Model cards: what runs on the phone

Three models and one rule set run on the phone; none of them sends anything off it. Every number below is from
`docs/RESULTS.md` (`python -m ml.eval.run_all`), on data the model never trained on.

## 1. Our scam classifier (`ScamClassifier.kt`, `ml/listener_clf.py`)

- **What it does:** p_scam for a call transcript or a message. It fills fusion's classifier slot; it never makes the red card on its own.
- **Model:** hashed character 2–5-grams and word 1–2-grams (2^18 features, Devanagari folded to Latin), logistic regression, 1 MB of weights. Pure Kotlin; identical to the Python twin on 30 shared vectors.
- **Data:** train/dev from the Indian Hinglish call set, BothBosu, the india14 SMS set (en/hi/Hinglish) and our template calls; all de-duplicated, no test text in train or dev. Licences: Apache-2.0, MIT, ours.
- **Measured:** Indian held-out sets pooled, fused with the cues: 95.5% of scams at amber, 2.7% of harmless at amber, 0% at red. Leave-one-dataset-out: 67–94% of scams at amber, but up to 56% false amber on a style it never saw (US sales calls).
- **Limits:** short phishing SMS without call words; scams with no cue words get amber at most; it abstains for the first ~25 words of a call.

## 2. The voice-clone check (`VoiceCheck.kt`, `ml/voice_clone.py`)

- **What it does:** P(AI voice) from the first ~20 s of speech. It is **one piece of evidence**: it needs a scam cue to reach amber and never makes red.
- **Model:** the first 6 transformer layers of NII's AntiDeepfake wav2vec 2.0 Large (frozen) + our logistic head, ONNX with int8 matrix multiplies (127 MB; within 0.003 of fp32). The depth (4/6/8) was picked on dev.
- **Data:** our head is trained on ASVspoof 2019 LA train, IndicSynth Hindi and FLEURS Hindi train, through phone channels. Threshold: the equal-error point on a separate calibration set (gTTS vs unseen FLEURS speakers).
- **Measured (EER):** In-the-Wild 23–25%, ReplayDF (played through loudspeakers) 35%, stock Indian TTS vs real Hindi 10.5% clean, 17.5% on a phone line, 19.3% over a speakerphone. At the threshold, 11–14% of real voices on a phone line are flagged: too many to act on alone, which is why it is only evidence.
- **Licence:** CC BY-NC-SA 4.0 (derived from AntiDeepfake). Research and demo only; a commercial pilot retrains the head on a licensable backbone.

## 3. Speech-to-text (`Speech.kt`)

- Off the shelf: Meta's Omnilingual ASR 300M CTC (int8, Apache-2.0) and Silero VAD (MIT) on sherpa-onnx. Chosen by our bake-off on Indian-English and Hindi calls (`ml/eval/asr_bakeoff.py`): WER 28% clean and on G.711, 57% over a speakerphone.

## Rules and fusion (`scam_patterns.json`, `fusion.json`)

- 15 cue categories, 12 scam types, negation handling, English/Hindi/Hinglish. Red needs two kinds of evidence (what was said plus what the phone saw, or a known scam pattern of at least four categories with a request), or the user's own "Alert family". Talk about scams can't reach red. Thresholds fitted on dev and frozen.

## Responsible use

- **Intended use:** warn a person and their family during a call, and let them check a recording or message. Not for identifying people, and not as evidence against anyone.
- **Human in the loop:** the family member and the user decide; "Not a scam" clears any card in one tap, tells the family, and keeps one ids-only record for weekly human review (`/api/metrics`).
- **Privacy:** every call is checked on the phone. Only calls the phone already finds suspicious are streamed to the detection server, which holds audio in memory and drops it; a confirmed scam keeps a 20 s AES-256 clip for the fraud desk for 30 days (Round 1 plan). Transcripts are never stored anywhere.
- **Fairness:** false positives reported per language (en, hi, Hinglish) in RESULTS.md; target no language above 2× the overall false-positive rate. Other Indian languages are out of scope (4% recall) and said so.

## Legacy: the laptop voice model (S1), cut on site

The Round 1 bank-side detector (an AntiDeepfake W2V-Large + XLS-R-1B ensemble on a laptop GPU) is no longer in the demo path. Its benchmarks stay in `models/metrics.json` under `laptop_s1_legacy` and in `docs/ML.md`.
