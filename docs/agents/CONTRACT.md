# The contract between the engine and the app

The engine (A) implements this; `RealRepository` (C) calls it; screens (B) see it only through `data/Models.kt` and `data/Repository.kt`. Only A edits this file, through a `contract-change` issue (`PROTOCOL.md`).

- **Server:** the detection server (`engine/app.py` on a team laptop now, reached through a tunnel; the bank's servers later). It also passes family links, caller checks, scam alerts and the family alarm between phones. `engine/relay.py` is the same messaging without detection, for a free host. The phone checks every call itself first (hybrid; `/ws/listen`).
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

`Me` = `{"id": "c_ab12", "name": "Sunita Sharma", "mobile": "+919876543210", "lang": "hi", "check_channel": "ring", "share_call_status": true, "listen_calls": true, "sms_fallback": true}`

409 if the number already has an account; 429 if too many sign-ups from this phone.

### `POST /api/m/claim` (team phones, staff PIN in `X-Staff-Pin`)
`{"customer_id": "sunita", "public_key": "…", "device": "Team phone"}` → same as sign-up.

### `POST /api/m/prefs`
Any of `{"lang": "en"|"hi", "check_channel": "ring"|"notify", "share_call_status": bool, "listen_calls": bool, "sms_fallback": bool}` → `Me`

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

**Levels:** `none` < `watch` (keep quiet) < `warn` (amber card) < `scam` (red card, family alarmed, pay guard on). Two judges read what was said, both on the phone: the **conversation check** (with the model pack: `Conversation.kt`, `assets/conv.json`; the model's p for the call so far, averaged over the last two segments) and the **cue rules** (`scam_patterns.json` through `fusion.json`; without the pack, with our small classifier: basic mode). The cue rules include what a *victim* says (`victim_says`: "OTP bata doon?", "kaunsa app download karun") and `digits_read_out`, so the phone can judge a call from its owner's side alone, when it can't hear the caller.
- `watch` / `warn`: the higher of the two judges. A failed caller check or a remote-control app reaches `warn` on its own. The voice-clone check (`synthetic_voice`) lifts `watch` to `warn`, never makes `scam`. A known contact or verified caller gets stricter thresholds.
- `scam` needs **two independent sources** that agree: a judge at `scam` (the conversation model above the red threshold on two segments in a row, or the cue rules' own `scam` rule) plus another source at `warn` or above (the other judge, the smarter check, or a strong context signal); or the call at `warn` plus the smarter check saying scam; or the call at `warn` from what was said plus a strong context signal (`remote_app_opened`, `caller_check_failed`, `screen_share_started`, `unknown_video_long`, `video_call_unknown`, `international_number`, `digits_read_out`). A context signal counts once: it never also counts as a cue towards that `warn`. Or the user pressing "Alert family" (`user`), or the server's stronger check.
- **The smarter check** (source `llm`; optional download, pack part `llm`, flagships only): an on-phone language model (Gemma 4 E2B, LiteRT-LM) reads the last ~1,500 characters and the signal list once the call is at `warn`, about every 15 s. It answers `scam`, `unsure` or `ok` with a type and one plain reason in English and Hindi (`Risk.reason`, shown on the card). `scam` counts as a source as above; `ok` and `unsure` never lower the level. Prompt: `assets/llm_prompt.txt`, shared with `ml/eval/llm_confirm.py`.
- `cues` are the moves the caller made and the cue categories that fired (same ids as the cue categories, so the app's words don't change).

**Everything runs on the phone** (`data/listen/`): speech-to-text (sherpa-onnx), the conversation model and the move matcher (`ConversationModels.kt`, ONNX from the model pack, our `E5Tokenizer`), the accumulator (`Conversation.kt`), the voice-clone model (ONNX), and `Analyzer.kt`, which puts them together for a live call and for "Check a recording or message". Basic mode: `ScamScorer.kt` (cues), `ScamClassifier.kt`, `Fusion.kt`. Python twins (`engine/listener/`, `ml/listener_clf.py`) give the same answers on shared test vectors, so `python -m ml.eval.kit` reproduces the phone's verdicts on a laptop.

**False alarms.** "Not a scam" / "I know this caller" on a warn or scam card (`Repository.notAScam(reason)`): for this call the risk goes to none (`LiveCall.cleared`), the listener stays quiet, the pay guard goes off, and the family gets `family_alarm_cleared` if they were alarmed. One ids-only feedback record is kept for human review and counted as a false positive in `/api/metrics`.

**Check a recording or message** (`Repository.checkRecording(uri)` / `checkText(text)` → `Analysis`): the same pipeline on an audio file or pasted text, entirely on the phone. Nothing is uploaded.

**Types:** `digital_arrest`, `bank_kyc`, `otp_upi`, `remote_access`, `family_emergency`, `courier_customs`, `trai_sim`, `job_task`, `investment`, `reward`, `boss_payment` (a boss or CEO ordering an urgent, secret payment to a new account), `impersonation`, `unknown`.

**Rules:** `android/app/src/main/assets/scam_patterns.json` (cue categories and phrases; `victim_says` is what a victim says back), `fusion.json` and `conv.json` (thresholds), owned by A, read by both the app and the engine. Test transcripts: `android/app/src/test/resources/scam_transcripts.json`.

### `POST /api/m/scam-alert`
Sent once when a call first reaches `scam` (or the user presses "Alert family"). **Ids only: no words, no audio.**
```json
{"call_id": "local-uuid", "level": "scam", "type": "digital_arrest",
 "cues": ["authority", "threat", "secrecy", "money_ask"], "sources": ["cues", "phone_ai", "llm"]}
```
→ `{"scam": Scam, "alarmed": ["c_cd34"], "text_these": ["c_ef56"]}`
- Turns on scam context (`Scam.reason` = `listener:digital_arrest`), so the pay guard shows.
- `alarmed`: members who got a `family_alarm` event. `text_these`: members whose app is offline. If `sms_fallback` is on, the phone texts them from its own SIM. If the request fails (no internet), the phone texts every member.
- A second alert for the same `call_id` doesn't alarm anyone again.

### `POST /api/m/scam-alert/clear`
"Not a scam" / "I know this caller". **Ids only.**
```json
{"call_id": "local-uuid", "reason": "know_caller", "level": "warn", "type": "bank_kyc",
 "cues": ["authority", "verification_pretext"], "sources": ["cues", "phone_ai"]}
```
→ `{"scam": null, "cleared": ["c_cd34"]}`
- `reason`: `know_caller` or `not_a_scam`. `level`: what the card showed (`watch`, `warn` or `scam`).
- Turns the listener's pay guard off. Family alarmed for this `call_id` get `family_alarm_cleared`; `cleared` lists them.
- Keeps one feedback record (reason, level, type, cue ids, sources, time) for human review. No words, no audio.
- A later `scam-alert` for the same `call_id` alarms nobody.

### `WS /ws/listen?call_id=<id>&lang=en|hi` (the server's stronger check; device token in the `X-Device-Token` header)
**Hybrid:** the phone always checks the call itself first. Only once its own level reaches `warn` does it open this
socket, so only calls the phone already finds suspicious are ever heard by a server (today a team laptop, later the
bank's own servers). Never after "Not a scam".
- Phone → server, binary: 16 kHz mono 16-bit little-endian PCM, 100 ms per message.
- Phone → server, text: `{"type": "context", "signals": ["unknown_number"], "caller_check": "not_them"}`.
- Server → phone, text, on change and every 5 s:
  `{"type": "listen_verdict", "level": "scam", "scam_type": "digital_arrest", "p_scam": 0.99, "cues": ["authority", "threat"], "voice": 0.25, "at": 1761300150.0}`
- The server runs a larger speech-to-text (Omnilingual 1B), the same conversation check (basic mode if its models are missing) and the full 24-layer voice model (S1). Its level can raise the phone's, never lower it (source `server`).
- **What the server keeps** (Round 1 plan): audio in memory only, in a rolling 20 s buffer, dropped when the socket closes. If the call reaches `scam`, a fraud case opens with the tier, scam type and cue ids, and that last 20 s is kept as an AES-256 encrypted clip, deleted after 30 days or when the case closes. Transcripts are never stored.

### `POST /api/m/family-alarm/ack`
`{"member": "c_ab12", "action": "call" | "message" | "ok"}`: the alarmed family member acted. The phone on the scam
call gets `family_alarm_ack` and stops escalating. If nobody acks within 60 s, that phone texts every member and calls
the first one itself (needs the "Call family for you" permission).

### Circles
A family link has `circle`: `family` or `work` (a boss or colleague who could order a payment; the CEO-fraud case).
The joiner picks it in `POST /api/m/family/join` (`"circle": "work"`); both sides get the same tag; `Member.circle`.

### Context signal ids (sent in `context`, also used on the phone)
`unknown_number`, `international_number`, `video_call_unknown`, `remote_app_opened` (AnyDesk, TeamViewer, RustDesk, QuickSupport, AirDroid, Splashtop), `screen_share_started` (Android's "start recording or casting?" prompt appeared during the call), `payment_app_opened`, `long_call` (over 15 minutes), `unknown_video_long` (an internet video call from someone not in contacts, over 10 minutes: the digital-arrest pattern), `caller_check_failed`, `synthetic_voice` (the voice-clone model on the first ~20 s of the caller's speech; warn at most), `digits_read_out` (this phone's owner read 4 to 8 digits out in a row on an unknown call: likely an OTP or card number), `series_1600` (the number is a 1600-series number, which Indian banks and regulators must use for service calls), `bank_claim_not_1600` (derived on the phone: the caller claims to be a bank or authority on an unknown number that isn't 1600-series; one piece of evidence, never strong on its own, since many genuine bank calls still come from other numbers).

**Pay guard after the call:** a call that reached `warn` or `scam` keeps the pay guard on for 30 minutes after it ends (scammers often say "call back after you transfer").

### `GET /api/m/models` → `[{"name": "countersign-pack-v2", "size_mb": 798, "sha256": "…", "url": "https://github.com/dope-XD/countersign/releases/download/models-v2/countersign-pack-v2.zip", "parts": ["asr", "vad", "voice", "conv"]}, {"name": "gemma-4-e2b", "size_mb": 2588, "sha256": "…", "url": "https://huggingface.co/litert-community/gemma-4-E2B-it-litert-lm/resolve/<commit>/gemma-4-E2B-it.litertlm", "parts": ["llm"], "optional": true, "min_ram_gb": 8}]`
One model pack for every language: speech-to-text (Hindi-capable + English), Silero VAD, the voice-clone model and the two conversation models (`conv` in `pack.json`: `model`, `base`). The app downloads it once (`Repository.downloadModels()`, progress in `modelState`) and checks the sha256. The scam classifier and the cue rules are small and ship inside the APK.

The entry with `"optional": true` and part `llm` is the smarter check: one `.litertlm` file, not a zip. The app offers it only on phones with at least `min_ram_gb` of RAM, downloads it on Wi-Fi only (`Repository.downloadSmartCheck()`, progress in `smartCheck`) and checks the sha256. Phones without it keep everything else.

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
| `family_alarm_ack` | `{"by": "c_cd34", "action": "call", "at": 1761300170.0}` | stop escalating: someone in the family is on it |
| `family_alarm_cleared` | `{"from": "c_ab12", "label": "Mummy", "reason": "know_caller", "at": 1761300190.0}` | the alarm screen turns to "False alarm: Mummy says it's fine", with OK |
| `online` | `{"member": "c_cd34", "online": false}` | the face's dot. **Not sent yet**: refresh `home` for now. |

## Test accounts on the dev server

- Seeded: `sunita` (Mom) and `rahul` (son), already family. Team phones claim them with the staff PIN (ask A in person, never in an issue).
- Emulators: sign up with the emulator's own number (`5555215554` for `emulator-5554`) so `adb emu gsm call` matches.
