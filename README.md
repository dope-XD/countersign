# Countersign

**An app that catches scam calls while they are happening, and tells your family.**

**Watch the 2 minute video first** (it shows the idea, then the real app):

https://github.com/user-attachments/assets/9b032668-20ea-406b-acd6-e2d188ba4b15

The part marked "Real app, recorded" is the actual app on an emulator. The video itself is made with code, in [video/](video/README.md).

## The problem

Your mum gets a call. A man says he is from the police, or her bank, or he says "I'm Rahul's friend, Rahul had an accident, send money quick". He sounds real. Within an hour she has told him the OTP or sent money on UPI.

This happens to lot of families in India every day.

## What Countersign does

Everybody in the family installs the app. Then, when Mummy gets a call:

1. **"Is it really Rahul?"** If the caller says he is family, the app quietly asks Rahul's own phone: are you on this call? If not, Mummy sees **"Not Rahul's phone"** on top of the call.
2. **"Does this sound like a scam?"** If Mummy puts the call on speaker, her phone listens and understands the call, right there on the phone. If it sounds like a scam, a card pops up: yellow for "be careful", red for "this is a scam, hang up". It also says *why* (for example: "says he is police", "asks you to keep it secret").
3. **It calls for help.** On red, Rahul's phone rings loud, even on silent: "Mummy may be on a scam call". If Rahul's app is off, he gets an SMS. And if Mummy opens GPay or PhonePe, a big red screen says "Stop. Don't send money."
4. **Wrong alarm? One tap.** "I know this caller" clears it, and the family is told everything is fine.

Nothing Mummy says is uploaded anywhere. The listening happens on her phone. The family only gets a short message like "scam call, type: digital arrest".

## What you need

- An Android phone, Android 12 or newer. Two phones is better (one for "Mummy", one for "Rahul"). A third phone to play the scammer is even better, but any phone that can make a call works.
- Wi-Fi, for one download (about 800 MB, only once).
- The app (the APK file). Ask our team for it, or build it yourself (see the end of this page).

## Start the app (10 minutes)

1. Install the APK on the phone. If the phone says "unknown app", allow it.
2. Open **Countersign**.
3. Pick your language: **English** or **हिंदी**.
4. Type your name and your phone number.
5. Now the app shows some cards asking for permissions. Tap each one and say **Allow**. They are all explained in simple words on the card.
   - For **Call listener**, the phone opens Accessibility settings. Find Countersign there and turn it on.
   - On Android 13 and newer, the phone may block it the first time. Then go to **Settings → Apps → Countersign → ⋮ (top right) → Allow restricted settings**, and try again.
6. Open **Settings** in the app and tap **Download the scam check**. Wait till it says it is ready. Do this on Wi-Fi.

Done. The shield on the home screen turns green when everything is set.

## Try it in 2 minutes (no call needed)

This is the easiest way to see it work.

1. On the home screen, tap **Check a recording or message**.
2. Paste this message and tap check:

   > Sir I am calling from your bank. Your KYC has expired and your account will be blocked today. I have sent you an OTP, please tell me the OTP now to update your KYC, otherwise your account will be closed.

   You should see a **red** card that says it is a scam, and why. Or try one in Hinglish:

   > Madam main CBI officer bol raha hoon. Aapke naam pe money laundering ka case hai, arrest warrant nikla hai. Video call pe rahiye, kisi ko mat batana. Apne saare paise RBI ke safe account mein transfer kariye, verification ke baad wapas mil jayenge.

3. Now paste a normal message:

   > Hello madam, Amazon delivery here. I am at your gate with your parcel, please come down.

   This one should stay calm.
4. You can also pick a voice recording (a .wav or .mp3 file) of a call. Some sample calls are in the `data/kit` folder of this project.

Everything here is checked on the phone. Nothing is sent to the internet.

## Try a real scam call (15 minutes, 3 phones)

**Get ready**

- Phone 1 is **Mummy**. Phone 2 is **Rahul**. Both have the app and did "Start the app" above.
- On Mummy's phone: **Add family → Show my code**.
- On Rahul's phone: **Add family → Scan their code**, and name her "Mummy".
- On Mummy's phone, accept Rahul.
- Phone 3 is the **scammer**. It does not need the app.

**Now play it**

| Step | What you do | What should happen |
|---|---|---|
| 1 | Scammer calls Mummy and says "I'm Rahul's friend" | On Mummy's screen: "Says they're family? Check". Tap Rahul. Rahul's phone asks "Is it you on Mummy's call?". He taps **No**. Mummy sees ✗ |
| 2 | Mummy puts the call **on speaker**. Scammer says: "I am Inspector Sharma from Mumbai police. A parcel in your name had drugs. There is an arrest warrant. Stay on video call and don't tell anyone." | First "Listening for scams", then a **yellow** card: "This sounds like a digital arrest scam" |
| 3 | Scammer says: "Transfer your money to the RBI safe account to clear your name" | The card turns **red**: "This is likely a scam. Hang up." Rahul's phone rings full screen |
| 4 | Mummy opens GPay or PhonePe | A red screen: "Stop. Don't send money or share an OTP." |
| 5 | On Rahul's phone, force stop the app. Call again and repeat | Rahul gets an **SMS** from Mummy's phone instead |
| 6 | Now a normal call, like a delivery guy | It stays calm. If it does show yellow, tap **I know this caller**. Rahul sees "False alarm" |
| 7 | Do it again in Hindi | Same thing, in Hindi |

More scam scripts to read out (English, Hinglish, Hindi) are in `android/app/src/test/resources/scam_transcripts.json` and `data/listener/adversarial.jsonl`.

**Important: put the call on speaker.** On the normal earpiece the phone mostly hears only Mummy, not the caller. Some phones also clean the caller's voice out of the mic even on speaker. If the card don't move, try the same script with "Check a recording" above.

## Just want to look at the screens?

You can see every screen and every alert without any calls, using pretend data. This works on a computer with the Android emulator too.

1. Build the app in pretend mode (needs Android Studio installed):
   ```bash
   cd android && ./gradlew assembleDebug -Pcountersign.fake=true
   ```
2. Install it:
   ```bash
   adb install -r app/build/outputs/apk/debug/app-debug.apk
   ```
3. On the home screen, **press and hold the shield**. Every long press shows the next situation: a call being checked, a fake caller, the yellow card, the red card, the pay guard, the family alarm, a false alarm, and more.

## If something goes wrong

- **The card never shows up during a call:** check the Call listener is on (Accessibility settings), the call is on speaker, and the scam check is downloaded (Settings).
- **It says "Download the scam check first":** Settings → Download the scam check, on Wi-Fi.
- **Rahul's phone didn't ring:** the server might be waking up (it can take a minute the first time) or Rahul's app was closed. The SMS should still come.
- **The first sign-up is slow:** same reason, the free server sleeps. Wait a minute and try again.
- **The emulator screen is black:** start it with `-gpu host`, older graphics drivers have this problem.

## Is it private?

- The phone turns the call into text and checks it **on the phone**. The words are never saved and never sent.
- The family only gets: "Mummy may be on a scam call" plus the type of scam. No recording, no words.
- Only if a call already looks suspicious, the phone can also ask our stronger check on the team laptop. There the audio is kept in memory only and thrown away, except a 20 second locked clip when it is confirmed a scam (for the bank's fraud team, deleted after 30 days).

---

## For developers

How every part works, from the call ringing to the alarm on a family phone: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

**Build the app**

```bash
cd android && ./gradlew assembleDebug
```

The APK ends up in `android/app/build/outputs/apk/debug/`. It talks to our free server at `https://countersign-relay.onrender.com` by default.

**Run the server yourself** (Python 3.11+)

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
```

```bash
.venv/bin/uvicorn engine.relay:app --port 8000
```

That is the small server that links families and passes alarms (no AI in it). The bigger one with the stronger check and the bank pages is `engine.app`, see [docs/RUNBOOK.md](docs/RUNBOOK.md).

**Check the same recordings on a laptop** (same answers as the phone)

```bash
.venv/bin/python -m ml.eval.kit data/kit
```

**Run all the tests:** `./check.sh` (Mac/Linux) or `.\check.ps1` (Windows).

**Where things are**

| Folder | What's in it |
|---|---|
| `android/` | the app. The scam check is in `android/app/src/main/java/app/countersign/bank/data/listen/` |
| `engine/` | the servers, and a Python copy of the scam check (both give the same answers) |
| `ml/` | how the models were trained and tested |
| `docs/` | more detail: [how it's tested](docs/RESULTS.md), [the demo runbook](docs/RUNBOOK.md), [hosting](docs/DEPLOY.md), [the app ↔ server contract](docs/agents/CONTRACT.md), [how someone might beat it](docs/ADVERSARIAL.md) |

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
