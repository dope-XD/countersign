# Agent C: phone features and QA (Windows #2)

You make the app actually work on a phone: call events, the caller check, the overlay window, the pay guard and the ring. Then you test it all on two emulators and on real phones.

## You own

- Everything under `android/` **except**:
  - B's `ui/**`, `strings.xml`, `values-hi/strings.xml` and `drawable/**`;
  - A's `data/Models.kt` and `data/Repository.kt`.
- In particular, you own:
  - `Core.kt`, `DeviceKey.kt`, `Notify.kt`, `CallWatchService.kt`, `ApprovalActivity.kt`, `MainActivity.kt`;
  - new files: `data/RealRepository.kt`, `FamilyNumbers.kt`, `CallScreener.kt`, `CallRedirector.kt`, `Overlay.kt`, `PayGuard.kt`;
  - `AndroidManifest.xml`, `build.gradle.kts`, `res/xml/**`, and `res/values*/strings_system.xml` (notification text, English + Hindi).
- QA: you file bugs as issues labelled `qa` plus the owner's `role:` label.

## Don't touch

- B's screens and strings: ask with `needs:ui`.
- The contract: ask with `contract-change`.
- `engine/**`: ask with `needs:backend`.

## How the pieces fit

```
CallScreeningService ──incoming number──┐
CallRedirectionService ──outgoing number─┤→ FamilyNumbers (last 10 digits → member id, on the phone only)
TelephonyCallback / audio mode ──state──┘          │
                                                   ▼
                    POST /api/m/call-event   POST /api/m/checks (auto, when the number is family)
                                                   │
             /ws/events  call_check · scam · approval · spoof_alert
                                                   ▼
          RealRepository (StateFlows) ──→ Overlay.kt: a ComposeView in a TYPE_APPLICATION_OVERLAY window
                                          showing B's CallCheckCard / PayGuardScreen
                                    ──→ PayGuard.kt: while scam != null, poll UsageStatsManager every 1 s;
                                          if a payment app is in front, show PayGuardScreen full screen
```

- **Payment apps** (declare them in `<queries>`):
  - `com.google.android.apps.nbu.paisa.user` (GPay)
  - `com.phonepe.app`
  - `net.one97.paytm`
  - `in.org.npci.upiapp` (BHIM)
  - `com.dreamplug.androidapp` (CRED)
  - `in.amazon.mShop.android.shopping`
  - `com.sbi.lotusintouch` (YONO)
  - `com.csam.icici.bank.imobile`
  - `com.snapwork.hdfc`
  - `com.axis.mobile`
- **Roles:** `RoleManager.ROLE_CALL_SCREENING` and `ROLE_CALL_REDIRECTION`. Both services **always let the call through** and only read the number. If the user declines a role, matching falls back to timing (`peer: null`).
- **Raw numbers never leave the phone.** Only member ids do.
- **The overlay window:**
  - needs `SYSTEM_ALERT_WINDOW` (Settings → "Display over other apps");
  - a `ComposeView` in a window service needs a `LifecycleOwner` and a `SavedStateRegistryOwner` set on the view tree.
- **The ring:**
  - `call_check` approvals reuse `ApprovalActivity` and `Ringer`, showing B's `RingScreen`;
  - "Yes" signs with `DeviceKey.sign`.
- **Clean-up:** delete `BankCall.kt` and drop `RECORD_AUDIO`. Once B's replacements land, remove the old payment and bank code paths in `MainActivity` and `Notify`.

## Order

1. `data/RealRepository.kt` on `Api` + the events socket, behind `Repo.instance`.
   - `FakeRepository` stays the default for `-Pcountersign.fake=true`.
   - Swap `Models.kt` parsing from the old root `Models.kt` to the new `data/Models.kt`.
2. `FamilyNumbers.kt`, `CallScreener.kt`, `CallRedirector.kt`, role requests. `CallWatchService` posts `call-event` with `peer` and `elapsed_ms`, and posts `checks` (`via: auto`) when an incoming number is family.
3. `Overlay.kt`: show on ringing and answered, hide on ended, with the permission flow. Use a stub card until B's `CallCheckCard` is merged.
4. `PayGuard.kt` and the `scam` event.
5. Ring flow (`call_check`), `spoof_alert` notification, `strings_system.xml` (English + Hindi).
6. QA (below), then real phones.

## QA script (two emulators against the dev server)

- `emulator-5554` is Mom; sign up as `5555215554`.
- `emulator-5556` is Rahul; sign up as `5555215556`.
- Link them as family.

1. Rahul dials 5554. Mom's card shows **✓ Rahul's phone**.
2. With Rahul idle, `adb -s emulator-5554 emu gsm call 5555215556` (Rahul's number, "spoofed"). Mom's card shows **✗ Not Rahul's phone · caller ID may be faked**, and Rahul's emulator gets "Someone is calling Mummy using your number".
3. `adb -s emulator-5554 emu gsm call 9000000001`. Tap Check → Rahul → ✗. Opening a payment app (or a stand-in APK with that package name) shows the pay guard. With no failed check, it must not show.
4. Ring Rahul. On Rahul's emulator, Yes + PIN: Mom sees ✓ "Rahul says it's him". No: ✗ and the pay guard turns on.
5. Repeat 1–4 in Hindi. Repeat with Rahul's app force-stopped: Mom sees **? Couldn't check**, never ✗.

Write the results in the PR or the QA issue: device, Android version, pass/fail and a screenshot for each step.

## Done means

The QA script passes on two emulators, then on two real phones with SIMs, with a third phone as the scammer. ✗ shows within about 3 s of the ring, and the pay guard shows on opening GPay.
