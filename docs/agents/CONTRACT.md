# The contract between the engine and the app

The engine (A) implements this; `RealRepository` (C) calls it; screens (B) see it only through `data/Models.kt` and `data/Repository.kt`. Only A edits this file, through a `contract-change` issue (`PROTOCOL.md`).

- **Dev server:** `https://pseudoskeletal-yung-implausibly.ngrok-free.dev` (the ngrok account's free fixed domain), A's laptop. It's down when A posts so on Standup. Locally: `http://<A's LAN IP>:8000`.
- **Auth:** every `/api/m/*` call except `signup` and `claim` sends `X-Device-Token: <token>` (from sign-up) and `ngrok-skip-browser-warning: 1`.
- **Errors:** non-2xx with `{"detail": "One sentence a user can read."}`. Show it as is.
- **Times:** server times are Unix seconds (float). `Models.kt` turns them into epoch milliseconds.
- **Test numbers:** with `COUNTERSIGN_ALLOW_TEST_NUMBERS=1` (on the dev server), sign-up also accepts emulator numbers such as `5555215554`.

## Accounts

### `POST /api/m/signup`
```json
{"name": "Sunita Sharma", "mobile": "9876543210", "lang": "hi", "check_channel": "ring", "share_call_status": true,
 "public_key": "<base64 SPKI DER of the Keystore EC P-256 key>", "device": "Pixel 7"}
```
→ `{"token": "c_ab12.1767225600.9f…", "me": Me}`

`Me` = `{"id": "c_ab12", "name": "Sunita Sharma", "mobile": "+919876543210", "lang": "hi", "check_channel": "ring", "share_call_status": true, "listen_calls": true, "stronger_check": true, "sms_fallback": true}`

409 if the number already has an account; 429 if too many sign-ups from this phone.

### `POST /api/m/claim` (team phones, staff PIN in `X-Staff-Pin`)
`{"customer_id": "sunita", "public_key": "…", "device": "Team phone"}` → same as sign-up.

### `POST /api/m/prefs`
Any of `{"lang": "en"|"hi", "check_channel": "ring"|"notify", "share_call_status": bool, "listen_calls": bool, "stronger_check": bool, "sms_fallback": bool}` → `Me`

## Home

### `GET /api/m/home`
```json
{
  "me": Me,
  "family": [{"id": "c_cd34", "label": "Rahul", "name": "Rahul Sharma", "mobile": "+919812345678",
              "since": 1761300000.0, "online": true, "new_link": false}],
  "join_requests": [{"customer_id": "c_ef56", "name": "Priya Sharma", "label": "Mummy"}],
  "approvals": [Approval],
  "checks": [Check],
  "scam": Scam | null
}
```
- `online`: their app reported in within the last 2 minutes.
- `new_link`: linked under 24 hours ago (such a link can't give ✓ Verified).
- `checks`: the latest 10, newest first.

## Family (unchanged from today)

| Call | Body | Returns |
|---|---|---|
| `POST /api/m/family/invite` | — | `{"code": "482913", "expires_in": 600, "qr": "csbank://family?code=482913"}` |
| `POST /api/m/family/join` | `{"code": "482913", "label": "Mummy"}` (what I call the inviter) | `{"status": "waiting", "inviter": "Sunita Sharma"}` |
| `POST /api/m/family/confirm` | `{"customer_id": "c_cd34", "label": "Rahul"}` (what I call the joiner) | `{"family": [Member]}` |
| `POST /api/m/family/decline/{customer_id}` | — | `{"ok": true}` |
| `DELETE /api/m/family/{id}` | — | `{"family": [Member]}` |

## Calls and checks

### `POST /api/m/call-event`
The phone reports its own calls. **Raw numbers never leave the phone**: the app matches the number against its family list (last 10 digits) and sends only the member id, or `null` when the number isn't family.
```json
{"call_id": "local-uuid", "event": "ringing", "kind": "phone", "peer": "c_cd34", "elapsed_ms": 350}
```
- `event`: `ringing` (incoming), `outgoing`, `answered`, `ended`.
- `kind`: `phone` or `internet` (WhatsApp-style).
- `elapsed_ms`: milliseconds since the event happened on the phone (the time the request was queued). The server subtracts it from its own clock.

→ `{"ok": true}`

### `POST /api/m/checks`
Ask "is this caller really my family member's phone?".
```json
{"call_id": "local-uuid", "claimed": "c_cd34", "number_matched": true, "via": "auto"}
```
- `via`: `auto` when the incoming number was a family member's; `manual` when the user tapped "Says they're family? Check".

→ `Check`. The engine answers at once, with `"verdict": "checking"` if it's still waiting (up to ~6 s) for the other phone's events. The final verdict follows as a `call_check` event and from `GET /api/m/checks/{id}`.

`Check`:
```json
{"id": "chk_91af", "call_id": "local-uuid", "member": "c_cd34", "label": "Rahul",
 "verdict": "not_them", "number_matched": true, "spoof_suspected": true,
 "ring": "none", "created_at": 1761300100.0, "decided_at": 1761300103.2}
```

| `verdict` | Meaning | Card |
|---|---|---|
| `checking` | waiting for the other phone | grey, spinner |
| `verified` | their phone is calling you right now (link ≥ 24 h) | ✓ green |
| `likely` | their phone started a call at that moment, the number wasn't seen | ✓ green, softer |
| `not_with_you` | their phone is on a call, but not with you | ✗ red |
| `not_them` | their phone isn't on any call | ✗ red; `spoof_suspected` adds "caller ID may be faked" |
| `cant_reach` | their app hasn't been seen for 2+ minutes | ? grey: ring or call them |

- `ring`: `none`, `ringing`, `yes` (confirmed with their fingerprint, so it shows as ✓), `no` (✗, scam), `no_answer`.

### `GET /api/m/checks` → `[Check]` · `GET /api/m/checks/{id}` → `Check`

### `POST /api/m/checks/{id}/ring`
Rings the claimed member: "Is it you on Mummy's call?". → `Check` with `"ring": "ringing"`. Their phone gets an `approval` event of kind `call_check`.

### `POST /api/m/scam/dismiss`
The user pressed "I understand" on the pay guard. → `{"scam": null}`. The pay guard stays off for this call.

`Scam`:
```json
{"check_id": "chk_91af", "member": "c_cd34", "label": "Rahul", "reason": "not_them", "until": 1761300700.0}
```
`reason` is `not_them`, `not_with_you` or `ring_no`. It's on from a ✗ verdict or a ring "No" until 10 minutes after the call ends, or until dismissed. While it's on, the app shows the pay guard over payment apps.

## Call listener

The phone listens to its own calls (an accessibility service records the mic; on speaker it hears the caller too) and decides how much the call looks like a scam. **Nothing is ever played into the call.** How the phone does it: `docs/agents/platform.md`, "Call listener".

**Levels:** `none` < `watch` (keep quiet) < `warn` (amber card) < `scam` (red card, family alarmed, pay guard on). `scam` needs either two kinds of evidence (what was said, from `cues` or an LLM judge, plus a strong context signal or the caller check), or at least four cue categories that include a request (money, a code or PIN, a remote-access app) and form a known scam pattern, or the user pressing "Alert family" (`user`). One keyword never makes `scam`; talk *about* scams ("did you see the news…") can't reach `scam` from cues alone. Exact thresholds: `fusion.json`. Phone code: `data/listen/ScamScorer.kt` and `Fusion.kt` (A owns them; C calls them).

**Types:** `digital_arrest`, `bank_kyc`, `otp_upi`, `remote_access`, `family_emergency`, `courier_customs`, `trai_sim`, `job_task`, `investment`, `reward`, `impersonation`, `unknown`.

**Rules:** `android/app/src/main/assets/scam_patterns.json` (cue categories and phrases) and `fusion.json` (thresholds), owned by A, read by both the app and the engine. Test transcripts: `android/app/src/test/resources/scam_transcripts.json`.

### `POST /api/m/scam-alert`
Sent once when a call first reaches `scam` (or the user presses "Alert family"). **Ids only: no words, no audio.**
```json
{"call_id": "local-uuid", "level": "scam", "type": "digital_arrest",
 "cues": ["authority", "threat", "secrecy", "money_ask"], "sources": ["cues", "server"]}
```
→ `{"scam": Scam, "alarmed": ["c_cd34"], "text_these": ["c_ef56"]}`
- Turns on scam context (`Scam.reason` = `listener:digital_arrest`), so the pay guard shows.
- `alarmed`: members who got a `family_alarm` event. `text_these`: members whose app is offline. If `sms_fallback` is on, the phone texts them from its own SIM. If the request fails (no internet), the phone texts every member.
- A second alert for the same `call_id` doesn't alarm anyone again.

### `WS /ws/listen?token=<device token>&call_id=<id>&lang=en|hi`
The stronger check, only when `stronger_check` is on and the server is reachable. Audio goes to the bank's own server only, is never stored, and is dropped when the socket closes.
- Phone → server, binary: 16 kHz mono 16-bit little-endian PCM, 20–200 ms per frame, only while the call is active.
- Phone → server, text: `{"type": "context", "signals": ["unknown_number", "remote_app_opened"], "caller_check": "not_them"}` whenever context changes.
- Server → phone, text, every few seconds and on change:
```json
{"type": "listen_verdict", "level": "warn", "scam_type": "digital_arrest", "p_scam": 0.71,
 "cues": ["authority", "threat"], "abstain": false, "at": 1761300150.0}
```
The phone fuses this with its own result (`fusion.json`). The server's verdict outweighs the phone's when both are present.

### Context signal ids (sent in `context`, also used on the phone)
`unknown_number`, `international_number`, `video_call_unknown`, `remote_app_opened` (AnyDesk, TeamViewer, RustDesk, QuickSupport), `payment_app_opened`, `long_call` (over 15 minutes), `caller_check_failed`.

### `GET /api/m/models` → `[{"name": "shruti-hi-en", "lang": "hi", "size_mb": 30, "sha256": "…", "url": "/download/models/shruti-hi-en.zip"}]`
The on-phone speech models for each language. The app downloads its language's model once during onboarding.

## Approvals (the ring screen)

`Approval`:
```json
{"id": "apv_77", "kind": "call_check", "from": "Sunita", "question": "Is it you on Mummy's call?",
 "detail": "Someone on a call to Mummy says they're you.", "challenge": "b64…", "deliver": "ring",
 "expires_at": 1761300220.0, "status": "pending"}
```
- `kind`:
  - `call_check`: a family ring;
  - `app_approval`: a bank agent asking "Is this you on the phone with us?".

### `POST /api/m/approvals/{id}/decide`
`{"decision": "approve", "signature": "<base64 SHA256withECDSA over approve:<id>:<challenge>>"}` or `{"decision": "decline"}` → `Approval` with its new `status`.

## Events: `wss://<server>/ws/events?topics=app:<my id>`

One JSON object per message; `type` says which.

| `type` | Payload | The app |
|---|---|---|
| `call_check` | `{"check": Check}` | updates the overlay card and home |
| `approval` | `{"approval": Approval}` | rings or notifies (as `deliver` says) |
| `spoof_alert` | `{"by": "Sunita", "label": "Mummy", "at": 1761300103.0}` | "Someone is calling Mummy using your number" |
| `scam` | `{"scam": Scam \| null}` | turns the pay guard on or off |
| `family_request` | `{"customer_id": "c_ef56", "name": "Priya Sharma"}` | notification + home |
| `family_joined` | `{"customer_id": "c_cd34", "name": "Rahul Sharma"}` | notification + home |
| `family_alarm` | `{"from": "c_ab12", "label": "Mummy", "scam_type": "digital_arrest", "level": "scam", "at": 1761300155.0}` | full-screen alarm: "Mummy may be on a scam call", with Call / Message / OK |
| `online` | `{"member": "c_cd34", "online": false}` | the face's dot. **Not sent yet**: refresh `home` for now. |

## Test accounts on the dev server

- Seeded: `sunita` (Mom) and `rahul` (son), already family. Team phones claim them with the staff PIN (ask A in person, never in an issue).
- Emulators: sign up with the emulator's own number (`5555215554` for `emulator-5554`) so `adb emu gsm call` matches.
