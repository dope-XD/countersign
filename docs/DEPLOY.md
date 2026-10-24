# Deployability: who runs it, what it costs, what a pilot needs

## What runs where

| Part | Runs on | Cost |
|---|---|---|
| Speech-to-text, cue scorer, our classifier, voice-clone check, fusion, alerts | the user's phone (Android 12+, arm64) | none; one ~400 MB download |
| Relay: family links, caller checks, scam alert, family alarm, "Not a scam" | one small container, no GPU (`Dockerfile.relay`) | free tier for a demo; about one 1 vCPU / 1 GB instance per ~10,000 active families (a few small JSON requests per call) |
| Model pack | a GitHub release or any CDN | one download per install |

No audio or transcript ever reaches a server, so the backend has nothing to store, secure or subpoena beyond ids.

## Demo hosting (today)

- **Relay:** Render free web service from `render.yaml` (Docker, Singapore). It sleeps after 15 idle minutes and wakes in
  about a minute; state is in memory and SQLite on the container's disk and **is lost on a restart or redeploy**. Phones
  then sign up and re-link in a minute. Health: `/health`; numbers: `/api/metrics`.
- **Model pack:** GitHub release `models-v1` (`python -m ml.pack_models --release`), checked by sha256 on the phone.
- **APK:** GitHub releases, signed with the repository's demo key (a real deployment signs with the operator's own key).

## Who would run it

1. **A bank or UPI app (preferred):** the listener and caller check ship inside its app as an SDK. The pay guard becomes
   a hold on the bank's own payment screen, which needs no overlay permission. The relay sits in the bank's cloud. Our
   ids-only scam alert maps to the bank's fraud-case queue (the Round 1 engine's cases module already models that).
2. **A telco:** the caller check fits network-side caller verification; the listener stays on the handset.
3. **Law enforcement (I4C / 1930 helpline):** the ids-only false-alarm and scam-alert records are aggregate signals for
   which scam types are rising, with no personal data.

## What a pilot needs

- **Licences:** the voice-clone weights derive from AntiDeepfake (CC BY-NC-SA 4.0, research only), so a commercial pilot
  retrains the head on a commercially licensed backbone, or licenses NII's weights. Omnilingual ASR (Apache-2.0), Silero
  VAD (MIT), sherpa-onnx (Apache-2.0) and onnxruntime (MIT) are fine. Two training sets are non-commercial
  (IndicSynth, ReplayDF): commercial training swaps them for licensed or consented data.
- **Data:** 2–4 weeks of consented, real Indian scam-call transcripts (the bank's own fraud reports, I4C samples) to
  retrain the classifier and refit fusion on dev, then a held-out month to measure false positives at real traffic.
- **Consent and permissions:** accessibility and microphone access must be explained in plain words (our onboarding
  cards do); Play Store policy on accessibility use needs a declared, user-facing purpose, which this is.
- **Measured before go-live:** per-phone-maker echo cancellation (does the mic hear the caller on speaker?), time to
  amber, false alarms on 1,000 genuine bank and delivery calls. `docs/RESULTS.md` lists today's numbers and gaps.
- **Human review:** every "Not a scam" record (ids only) goes to a reviewer weekly; recurring false-alarm cue
  combinations feed back into `scam_patterns.json` and the classifier's training data.
