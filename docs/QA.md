# QA log: what was tested, on which device

| When (24 Oct, IST) | Device | What | Result |
|---|---|---|---|
| 20:40 | Emulator (Android 15, arm64) | Sign-up against the relay; Check a message (Hinglish digital-arrest text) | amber, "says police, court or bank"; no network used for the check |
| 20:53–20:57 | vivo V2504, Android 16 (real phone) | Hindi onboarding, family link with the emulator (code typed), scam alert from the emulator's account → family alarm notification and full-screen alarm in Hindi; "I know this caller" → the alarm turns to "गलत चेतावनी" | all as designed; the relay counted 1 false alarm for review |
| 21:09 | vivo V2504 | Settings → download the model pack (379 MB from the GitHub release), sha256 check, unpack | "धोखा-जाँच तैयार है" |
| 21:30 | Emulator | Check a recording: `data/kit/call_08.wav` (BothBosu test scam, G.711) through VAD + Omnilingual + Analyzer + voice check | red, digital arrest, police · threat · rushes you; voice "real person" (0.01): same as `ml.eval.kit` |
| 21:55 | Emulator | **Live call:** unknown number rings, answered; the call listener records; the kit scam call fed into the listener (debug hook `spike/FeedAudio.kt`) | red ~65 words in (authority, threat, AI voice); scam alert sent; "It's not a scam" → confirm → "Cleared. Family told it's fine."; `scam-alert/clear` reached the relay |
| 23:05 | Emulator + the laptop server (engine on the M4 Mac, CPU) | **Hybrid live call:** the phone reaches amber by itself (cues + classifier), opens `/ws/listen` (token in the header, not the URL), streams the call | red with source SERVER 8 s later; the server opened a RED case with a 20 s encrypted clip (30-day expiry) |
| 23:00 | Laptop server | Agent console at `/agent` behind the staff PIN, served through a Cloudflare quick tunnel | loads, waits for calls |

## Bugs found and fixed by these tests

- **Pick a recording crashed** ("Can only use lower 16 bits for requestCode"): the biometric library brought fragment 1.2.5. Fixed with fragment-ktx 1.8.8.
- **Home spun forever** when the relay wasn't reachable at start. It now says so after 4 s, with Try again.
- **Release builds** would have stripped the classes sherpa-onnx and onnxruntime call by name. Fixed with keep rules.

## Not tested yet

- A live call on the real phone with the caller on speakerphone: does the vivo's mic hear the caller, or does echo cancellation remove them? (#37/#44; needs the Accessibility switch, which the user turns on.)
- The SMS fallback with the family app force-stopped, and the pay guard over GPay, on the real phone.
- The relay on Render (waiting for its URL).
