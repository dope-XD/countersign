# CS Bank (Android)

The demo bank's app, and the only thing judges need. Kotlin and Jetpack Compose, Android 12 or newer.

- **Sign up** with a name and mobile number. The app makes an EC P-256 key in the phone's Android Keystore (in the security chip where there is one). The key only signs after a fingerprint or screen-lock check, and the bank keeps the public half. That key is what "Yes, it was me" means.
- **Family.** Show your code (QR or 6 digits); the other person joins and you confirm on your phone. Each of you names the other ("Mom", "Rohan").
- **Pay.** During or just after a call, a large payment to a new payee pauses. Ask a family member (their phone rings or gets a notification, as they chose at sign-up), and see whether their phone is on a call. Or send it to their own account instead, call their saved number, or send it with a one-hour hold.
- **Family checks and approvals** open full screen and ring when set to "Ring". "Yes" needs the fingerprint or screen lock; "No" needs nothing. The screen can't be captured (`FLAG_SECURE`).
- **Call CS Bank.** An in-app voice call, answered by the bank's AI assistant (`engine/agent/`). Audio goes out as 8 kHz G.711 mu-law, like a phone line, with the phone's echo canceller on. **Try an attack** calls from someone else's number, with your own voice or a cloned-voice clip. The app shows what a fraudster would already know from a leak, and a box to type what the clone "says".
- **Kill switch.** Blocks all payments and account changes in one tap. Turning it off takes the fingerprint and an hour.
- **Call watch.** A foreground service tells the bank when the phone is on a call, and whether it came in or went out: normal calls from the telephony state, WhatsApp-style calls from the audio mode. Only the fact of the call is sent, never the number or audio. Android doesn't let apps hear calls anyway.

## Build

You need the Android SDK (platform 36, build-tools 36) and JDK 17 or newer. The wrapper uses Gradle 9.5.1, AGP 9.3.3 and its built-in Kotlin 2.2.10.

```powershell
cd android
.\gradlew assembleRelease                                                  # app\build\outputs\apk\release\app-release.apk, ~4 MB
.\gradlew assembleRelease -Pcountersign.server=https://<your-domain>       # a different default server
copy app\build\outputs\apk\release\app-release.apk ..\data\app\cs-bank.apk  # the engine offers it at /download/cs-bank.apk
```

`local.properties` (gitignored) points at the SDK, e.g. `sdk.dir=C\:/Users/<you>/AppData/Local/Android/Sdk`. Every build is signed with the demo key in `app/countersign-demo.keystore`, so builds install over each other. That key is for the demo only; a bank signs with a key that never leaves it.

## Install

Scan the QR code on `/demo`, download, allow installs from the browser, open. Or plug in a phone with USB debugging and `adb install -r app\build\outputs\apk\release\app-release.apk`.

The phone needs a screen lock (PIN, pattern or fingerprint). The app asks for notifications, phone state, the microphone and unrestricted battery. On Android 14+ it may also open the "full-screen alerts" setting, which lets a family check ring like a call.

Team phones: choose **Team demo account**, pick Rahul or Sunita, enter the staff PIN.

## How it is built

| File | What it does |
|---|---|
| `Core.kt` | app start, saved settings (server, device token), the event bus, the HTTP client for `engine/mobile.py` |
| `DeviceKey.kt` | the Keystore key: create, public key, sign after `BiometricPrompt` |
| `CallWatchService.kt` | call state and direction to the bank; the events websocket that rings, notifies and updates screens |
| `Notify.kt` | notification channels, family-check ring (`Ringer`), full-screen intent |
| `ApprovalActivity.kt` | the full-screen check: ring, Answer, the question read aloud, Yes/No |
| `BankCall.kt` | the in-app call: mic or clip → mu-law → `/ws/caller`, agent audio → speaker, half duplex |
| `ui/` | Compose screens: onboarding, home, pay and the pause sheet, family, profile, call |

Approvals sign `approve:<approval id>:<challenge>` with SHA256withECDSA. The challenge is SHA-256 over the exact summary shown plus a nonce, so the signature covers that payment or change and nothing else (`engine/stepup/devicekeys.py`).
