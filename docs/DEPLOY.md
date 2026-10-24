# Deployability: who runs it, what it costs, what a pilot needs

## What runs where

| Part | Runs on | Cost |
|---|---|---|
| Speech-to-text, cue scorer, our classifier, voice-clone check, fusion, alerts | the user's phone (Android 12+, arm64) | none; one ~400 MB download |
| Relay: family links, caller checks, scam alert, family alarm, "Not a scam" | one small container, no GPU (`Dockerfile.relay`) | free tier for a demo; about one 1 vCPU / 1 GB instance per ~10,000 active families (a few small JSON requests per call) |
| Model pack | a GitHub release or any CDN | one download per install |

No audio or transcript ever reaches a server, so the backend has nothing to store, secure or subpoena beyond ids.

## Demo hosting (today)

- **Relay:** Render free web service from `render.yaml` (Docker, Singapore), https://countersign-relay.onrender.com.
  Accounts, phone keys and cases live in **Supabase Postgres** (`DATABASE_URL`), so a restart or redeploy keeps everyone
  signed in. A **Cloudflare Worker** (`deploy/keepalive/`) calls `/health` every 10 minutes, so Render never sleeps and
  Supabase never pauses; `/health` runs a query and returns 503 if the database is unreachable. Numbers: `/api/metrics`.
- **Model pack:** GitHub release `models-v1` (`python -m ml.pack_models --release`), checked by sha256 on the phone.
- **APK:** GitHub releases, signed with the repository's demo key (a real deployment signs with the operator's own key).

## Setting up the relay (free: Render + Supabase + Cloudflare)

Each free plan has one catch, and each is covered:

| Service | Job | Free-plan catch → handled by |
|---|---|---|
| Render | runs the relay | sleeps after 15 idle minutes (~1 min to wake); disk wiped on restart → keep-alive; data in Supabase |
| Supabase | Postgres for the relay | pauses after 7 days without database activity, restored only by a click → keep-alive (`/health` queries it) |
| Cloudflare Worker | calls `/health` every 10 min | none at 144 requests a day; backup: `.github/workflows/keepalive.yml` |

1. **Supabase:** new project `countersign` in **Southeast Asia (Singapore)**.
   - Press **Generate a password**: generated ones are letters and digits, so nothing needs URL encoding.
   - **Connect → Direct → Method: Session pooler**, copy the string, and put the password in place of `[YOUR-PASSWORD]`.
   - Don't use "Direct connection": it's IPv6 only, and Render's free plan has no IPv6. Symbols in a password need
     URL encoding (`@` → `%40`, `#` → `%23`, `/` → `%2F`, `:` → `%3A`, `%` → `%25`).
   - The relay creates its tables on first start (`engine/db.py`).
2. **Render:** New → Blueprint → this repository (`render.yaml`). On the service's **Environment** tab:
   - `DATABASE_URL` = that string (`sync: false`, so it's never in git).
   - `COUNTERSIGN_SECRET` is generated. **Never change it**: it signs every phone's token.
3. **Keep-alive:** in `deploy/keepalive/`, run `npx wrangler login`, then `npx wrangler deploy`. Its logs should show a 200
   every 10 minutes.
4. **Check:** `/health` → `"ok": true, "db": "postgres"`.

| What you see | Cause | Fix |
|---|---|---|
| Phones told "sign up again" | `COUNTERSIGN_SECRET` changed, or `DATABASE_URL` missing (the relay fell back to its wiped disk) | restore the secret; set `DATABASE_URL`; `/health` must say `postgres` |
| `/health` → 503 | Supabase paused or unreachable | Supabase dashboard → **Restore project**; check the string |
| First request takes ~1 min | the keep-alive isn't running | check the Worker's logs (the app also retries a slow request once) |
| Relay suspended | Render's 750 free hours a month are shared by the workspace's free services (this needs ≤ 744) | keep it the only always-on free service, or use the $7 Starter plan |

Render's free plan may also restart the service without warning. Accounts survive and phones reconnect by themselves;
only a caller check running at that moment is lost. The $7 Starter plan removes this.

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
