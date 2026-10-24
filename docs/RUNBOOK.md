# Runbook: the live demo, with no laptop in the path

Everything the jury sees runs on two Android phones and the relay. The laptop is only for showing the eval.

## Before the jury (15 minutes)

1. **Relay up:** open `<relay URL>/health` in a browser. On Render's free plan the first request after 15 idle minutes
   takes about a minute; open it early, and keep a phone app open (its socket keeps the relay awake).
2. **Two phones** (Android 12+), each with the APK installed:
   - Language → name and number → every permission card (Microphone, Call listener in Accessibility; on Android 13+
     first App info → ⋮ → "Allow restricted settings"), SMS, Notifications, Full-screen alerts.
   - Settings → **Download the scam check** (one time, Wi-Fi). Wait for "Scam check is ready".
   - Phone A ("Mummy") → Add family → Show my code; phone B ("Rahul") → Scan their code → "Mummy". Accept on A.
3. A third phone (or any phone) plays the scammer. Scripts: `android/app/src/test/resources/scam_transcripts.json`
   and `data/listener/adversarial.jsonl`, in English, Hinglish and Hindi.

## The journey (5 minutes; the jury can change any line)

| Step | Do | The jury sees |
|---|---|---|
| 1 | The scammer calls Mummy, says "I'm Rahul's friend" | the card: "Says they're family? Check" → tap Rahul → "Not Rahul's phone" ✗ |
| 2 | Mummy puts the call **on speaker**; the scammer reads a digital-arrest script | "Listening for scams", then the amber card: "This sounds like a 'digital arrest' scam" + *why* (police, threat, keep it secret) |
| 3 | The scammer asks for money / AnyDesk | red: "This is likely a scam. Hang up." Rahul's phone rings full screen: "Mummy may be on a scam call" → Call Mummy / Message |
| 4 | Mummy opens GPay | the red pay guard: "Stop. Don't send money or share an OTP." |
| 5 | Force-stop Rahul's app and repeat on a new call | an SMS reaches Rahul from Mummy's SIM |
| 6 | A harmless call: a delivery or bank fraud-alert script | stays below red; if amber shows, tap **I know this caller** → confirm → "Cleared. Family told it's fine." and Rahul gets "False alarm: Mummy says it's fine" |
| 7 | Home → **Check a recording or message**: pick a jury recording or paste their SMS | the verdict, why, the voice check and what it heard, all on the phone |
| 8 | Repeat 2–3 in Hindi | the same, in Hindi |

## The numbers, live

`<relay URL>/api/metrics` shows the measured accuracy (`models/metrics.json`) and, since the relay started, the scam
alerts and the false alarms people reported (ids only, for human review). On a laptop:
`python -m ml.eval.kit <jury folder>` prints the same verdicts as the phone.

## Privacy check

While the demo runs, `adb logcat -s Listen CallListener CallRisk ScamAlert` shows only levels, types and cue ids. The
only requests leaving the phone are `call-event`, `checks`, `scam-alert`, `scam-alert/clear` and the one model download.

## If something fails

- **No amber on speaker:** the phone maker's echo cancellation may remove the caller (`docs/RESULTS.md`, failure 2). Use
  Check a recording for the same script, and say so.
- **Family phone doesn't ring:** the relay was asleep or the app was killed; the SMS fallback still arrives.
- **"Download the scam check first":** Settings → Download.
