# Data sheet

## What the running system keeps

| Data | Kept | Where / how long |
|---|---|---|
| Raw call audio | No | 20 s rolling buffer in memory, wiped when the call ends |
| Evidence clip (≤20 s) | Only on RED | AES-256-GCM, key from a KMS (mocked by `data/runtime/kms.key`); deleted after 30 days, or at once on a false alarm |
| Scores, tier, reason codes, model version | Yes | SQLite case store and audit log |
| Speaker embeddings | No | Memory only, wiped at call end |
| Voiceprints | Never collected | — |
| Challenge transcripts | No | Only pass/fail and timings are kept |
| Voice notes from the app | No | Decoded, scored, discarded |
| Passkey public keys | Yes | Needed to verify approvals; no biometric data (that stays on the phone) |

`/demo` → "What Countersign holds right now" shows these counts live.

## Datasets used to build and test S1

| Dataset | License | Content | Use |
|---|---|---|---|
| ASVspoof 2019 LA | ODC-By / research | English, bona fide + 19 attack systems | train, test |
| In-the-Wild (Müller et al. 2022) | Apache-2.0 (mirror) | public figures, real and deepfake | test |
| IndicSynth (IIIT-Delhi, ACL 2025) | CC-BY-NC-4.0 | synthetic Hindi | train |
| FLEURS hi_in (Google) | CC-BY-4.0 | real read Hindi | train |
| Kathbath (AI4Bharat), optional | CC-BY-4.0 | real Hindi | train |
| MLAAD Hindi, optional | CC-BY-NC-4.0 | synthetic Hindi from modern TTS | train |
| IndiaCall (ours) | consent form | 3 teammates, real and cloned, Hindi/English/Hinglish | test only, deleted after the event |

All use is non-commercial research for a student hackathon prototype.
