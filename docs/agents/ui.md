# Agent B: Android UI (Mac)

You build every screen of the Countersign app. The user is an average Indian adult, maybe 55, on a mid-range Android phone, often reading Hindi. Your screens should feel calm and obvious.

## What the app does

Family members all install it. When someone calls you saying "Mummy, it's Rahul", the app asks Rahul's phone whether it is calling you. If it isn't, the card on top of the dialer says **"Not Rahul's phone"**. If that happens and you then open GPay, a red screen stops you. That's the whole app. Read `CONTRACT.md` for the states.

## You own

- `android/app/src/main/java/app/countersign/bank/ui/**` (screens, the theme, `ui/overlay/`)
- `android/app/src/main/res/values/strings.xml`, `res/values-hi/strings.xml`
- `android/app/src/main/res/drawable/**`, `res/mipmap*/**` (the icon)

## Don't touch

- Services, `Core.kt`, `DeviceKey.kt`, `Notify.kt`, `MainActivity.kt`, the manifest or gradle (C owns them).
- `data/Models.kt` and `data/Repository.kt` (the contract; ask A).
- Anything outside `android/`.

**Getting data.** Screens get data only from `Repository` (`Repo.instance`) and `Models`. During development that's `FakeRepository`. In debug builds, a long press on the home shield cycles through its scenarios (`Scenario`). Need a field or an action? Open a `contract-change` issue with `needs:backend`.

**What C needs from you.** C shows two of your composables in a system overlay window, from a service. Keep these signatures stable; they're your API to C:

```kotlin
@Composable fun CallCheckCard(state: CallCheckUi, onRing: () -> Unit, onCall: () -> Unit, onPickMember: (String) -> Unit, onClose: () -> Unit)
@Composable fun PayGuardScreen(state: PayGuardUi, onRing: () -> Unit, onCall: () -> Unit, onUnderstood: () -> Unit)
```

`CallCheckUi` and `PayGuardUi` are in `data/Models.kt`. Both composables must work without an Activity: no `LocalActivity`, no ViewModels, no navigation. Just state in and lambdas out.

## Design rules

- **One idea per screen, one main button.**
  - At most about 8 words per line and 2 lines of body text.
  - No jargon: never "server", "key", "token", "signature", "verify", "provenance", "OTP" (except on the pay guard).
  - Say "check", "really Rahul", "his phone".
- **Big:**
  - body ≥ 18 sp, headings ≥ 26 sp;
  - main buttons full width and 56 dp tall;
  - touch targets ≥ 48 dp.
  - Must work at 360 dp wide and with the largest system font: no clipped or overlapping text.
- **Never colour alone.** Each verdict is an icon + a word or two + a colour:
  - ✓ green "Really Rahul" / "Rahul's phone";
  - ✗ red "Not Rahul's phone";
  - ? grey "Couldn't check".
  - Buzz on ✗ with `LocalHapticFeedback`.
- **Faces, not lists.** Family members are big circles with initials and a soft colour per person, with the name underneath and an online dot.
- **Navigation depth ≤ 2.** Home → Add family / Settings / History. Back always works. No bottom bar, no drawer, no tabs.
- **The overlay card:**
  - at most the top third of the screen, rounded, with a shadow;
  - never covers the bottom half, where the dialer's end-call button is.
- **The pay guard:** full screen, red, one big headline, one line, then three stacked buttons (Ring Rahul / Call Rahul / I understand).
- **Bilingual from day one.**
  - Every string goes in `strings.xml` and `values-hi/strings.xml`, with Hindi in Devanagari. Hindi should be simple, everyday Hindi, not formal Sanskritised words ("जाँचें" is fine, "सत्यापन" is not).
  - The language is chosen on the first screen and can be changed under Settings (AppCompat per-app locales, or `LocaleManager` on 33+).
- **Accessibility:**
  - `contentDescription` on every icon;
  - contrast ≥ 4.5:1;
  - nothing conveyed only by animation.
- **Delivery:** every screen is a `@Composable` with `@Preview`s in English and Hindi, at 360 dp and at font scale 1.5.

## Screens

| Screen | What's on it |
|---|---|
| **Language** | Two big buttons: "English" / "हिंदी". |
| **About you** | Name, mobile number. One button. |
| **Permissions** | One card at a time: an icon, one line why, "Allow". The cards are: phone calls, caller check (call screening role), notifications, show over other apps, app usage, full-screen alerts (14+), battery. Each "Allow" calls `repo.request(permission, activity)`, and the card moves on when `permissions` flips. "Skip" is a small text button. |
| **Home** | A shield at the top ("You're protected" / "Some things need your OK" with a link to the missing permission). The family faces in a grid, then a "+ Add family" tile. A "Recent checks" row (the last 3, icon + name + time). A gear in the top bar. Join requests show as a card at the top: "Priya wants to join your family" with Accept / No. |
| **Add family** | Two big choices: "Show my code" (a QR + 6 digits, large) and "Scan their code" (or type 6 digits). Then "What do you call them?" ("Rahul", "Mummy"). Then "Waiting for them to accept…". |
| **Member** (tap a face) | A big face, name, online or not, "Remove from family" (with a confirm). |
| **Settings** | Language; how family checks reach you (Ring / Notification); share whether I'm on a call (on/off, one line why); permissions status; "Sign out". |
| **History** | The last 10 checks: a verdict chip, the name, the time, and "rang: yes/no". |
| **Call check card** (overlay) | States: checking ("Checking Rahul…") → verified / likely (✓, fades after 4 s) / not_with_you / not_them (✗ + "Caller ID may be faked" if spoofed) / cant_reach (?). On ✗ and ?: **Ring Rahul**, **Call Rahul**. For an unknown number: a small chip "Says they're family? Check", which opens a row of faces to pick from. While the ring is pending: "Ringing Rahul…", then "Rahul says it's him ✓" or "Rahul says it's NOT him ✗". |
| **Pay guard** (overlay) | "Stop. This caller isn't Rahul." / "Don't send money or share an OTP." Then Ring Rahul / Call Rahul / I understand. |
| **Ring screen** (the asked member's phone) | Full screen: the asker's face, "Is it you on Mummy's call?", "Yes, it's me" (green; asks for the fingerprint) and "No, not me" (red). C wires up `ApprovalActivity`; you build the `RingScreen(state, onYes, onNo)` composable. |

Delete the old bank screens (`ui/Pay.kt`, `ui/Call.kt`, `ui/Profile.kt` and the bank parts of `Main.kt` and `Onboarding.kt`) once your replacements are merged. Coordinate with C, who deletes `BankCall.kt`.

## Done means

Every screen above runs on `FakeRepository` in both languages, has previews, and has passed review with screenshots in the PR. The overlay composables are merged before C wires the overlay window (C works against stubs until then).
