# CS Bank (Android)

The customer's bank app for the demo phones. It shows the same bank pages as `/bank/<customer>`, but adds the two things a web page can't do:

- **Call alerts.** It notices when the phone is on a call and tells the engine. That covers normal calls (the telephony call state) and internet calls such as WhatsApp (the phone's audio mode switches to "in communication"). The UPI guard then pauses a payment to a new payee during the call and for 10 minutes after it. Only the fact of the call is sent, never the number or the audio. Android wouldn't let the app hear a call anyway.
- **Notifications.** Approval requests ("Did you ask us to…?", "Did you ask Mum for ₹50,000?") arrive as notifications, even with the bank pages closed.

The bank pages run in Chrome as a Trusted Web Activity, not in a WebView, so passkeys work exactly as they do in the browser. Passkeys already bound on a phone keep working.

## Build

You need the Android SDK (platform 36, build-tools 36) and JDK 17 or newer. The wrapper uses Gradle 9.5.1 with AGP 9.3.3.

```powershell
cd android
.\gradlew assembleDebug                                                  # app\build\outputs\apk\debug\app-debug.apk
.\gradlew assembleDebug -Pcountersign.server=https://<your-domain>       # different default server
```

`local.properties` (gitignored) points at the SDK, e.g. `sdk.dir=C\:/Users/<you>/AppData/Local/Android/Sdk`.

Every build is signed with the demo key in `app/countersign-demo.keystore`, so all teammates' APKs share one certificate. That key is for the demo only; a bank signs with a key that never leaves it.

## Install

Turn on USB debugging on the phone (Settings → About → tap Build number 7 times → Developer options → USB debugging), plug it in, and run:

```powershell
adb install -r app\build\outputs\apk\debug\app-debug.apk
```

You can also copy the APK to the phone and open it (allow installs from that source). Android 12 or newer is required.

## Full-screen pages (optional)

Chrome hides its address bar only once the site vouches for the app. Set this on the engine and restart it:

```powershell
$env:COUNTERSIGN_ANDROID_CERT_SHA256 = "49:4D:97:51:C6:18:8B:3B:C5:2E:61:41:6C:36:1D:71:DC:9E:BD:C7:99:5F:0D:96:20:F7:20:A6:E4:01:8B:2C"
```

The engine then serves `/.well-known/assetlinks.json`. Without it the app still works, with a thin address bar.

## Using it

1. **Log the phone in.** On the phone, scan the customer's login QR on `/demo`. It opens Chrome and logs that phone in. The app shares Chrome's login for the site.
2. **Set up the app.** Open CS Bank, check the server (the tunnel URL) and pick whose phone it is, then tap **Open my bank**.
3. **Turn on call alerts.** In the bank: **Security → Turn on call alerts**. Allow phone access and notifications. CS Bank's ongoing notification shows the alerts are on.
4. **Bind a passkey** if this phone has none (**Security → Bind this phone**).

Scene 3 with a real call: Sunita's phone takes a real WhatsApp or normal call from "Rahul" (the clone). The CS Bank notification switches to "On an internet call", and a UPI payment to a new payee is paused with "You're on an internet call (like WhatsApp) right now". Rahul's phone gets the family check as a notification. `/demo` shows the call state as the phone reports it.

## How it is built

| File | What it does |
|---|---|
| `MainActivity` | Setup and status: server, whose phone, alerts on or off. Opens the bank pages in Chrome. Notifications land here and go straight to the bank. |
| `LinkActivity` | Receives the device token from the bank page (`intent://link?...#Intent;scheme=countersign`). It accepts it only for the server and customer chosen on the setup screen, so another website can't point the app elsewhere. |
| `CallWatchService` | Foreground service. Uses the telephony call state and audio mode to `POST /api/app/<customer>/call-state`, and `/ws/events` to raise notifications. Authenticates with the `X-Device-Token` header. |

The device token can report call state and receive that customer's app events, nothing else. Approving still needs the passkey. Engine side: `engine/app.py` (`/api/app/{cid}/device`, `/call-state`, `/.well-known/assetlinks.json`), `engine/auth.py` (device tokens), and `engine/guard.py` (on a call right now).

Limits: Android only, because iOS doesn't let an app watch calls in the background. Call alerts need the app's foreground service running, which the ongoing notification shows.
