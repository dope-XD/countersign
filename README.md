# Countersign

Countersign stops voice-clone fraud in Indian banking without trusting the voice. A cloned voice can carry a convincing call; it can't make a "yes" from a phone the attacker doesn't hold. Countersign scores every call for synthetic speech and decides how much proof a request needs. The proof always comes from the right person's phone.

It covers both victims of a voice clone:

- **The bank.** A fraudster calls as a customer to change the registered mobile number, add a payee or raise a limit. CS Bank's AI assistant (or a human agent) works the request through a policy engine: card digits, a fresh code shown in the customer's app read back on the call, and a fingerprint-signed approval on the customer's phone. A RED call adds a 24-hour cool-off and the fraud desk.
- **The family.** "Mom, it's me, I need ₹50,000 now." When a payment to a new payee happens during a call, the CS Bank app pauses it and asks the real son's phone, which rings: "Did you ask Mom for ₹50,000?" Mom also sees whether his phone is on a call at all. If he can't answer ("my phone is broken"), she can send the money to his own account instead, ask the rest of the family, or send it with a one-hour hold she can still cancel.

The judges' entry point is the **CS Bank Android app** (`android/`): sign up, make a family, call the bank, try to break in. This follows the RBI's April 2026 discussion paper on digital-payment fraud, which proposes a trusted person for large payments, a one-hour cancellable delay and a customer kill switch. The app has all three.

Built for RAKSHAM 2026 (IIT Delhi, problem statement 01) by team losers: Pushkar Joshi, Sarah Mittal and Reshaan Nadar. This is a working prototype, not a product. What's mocked is listed under [Limits](#limits).

## How a call is scored

The caller's audio arrives at 8 kHz G.711, the same as a real phone line. Every 2 s the engine takes the latest 4 s window. If at least a third of the window is speech, it runs these four signals:

| Signal | What it does | Code |
|---|---|---|
| S1 synthetic speech | NII AntiDeepfake W2V-Large + XLS-R-1B, score-level ensemble, calibrated on phone-channel audio | `engine/signals/s1_synth.py`, `antideepfake_model.py` |
| S2 speaker drift | ECAPA-TDNN embedding per window, compared with earlier windows in the same call | `engine/signals/s2_drift.py` |
| S3 liveness | a fresh 4-digit code shown in the customer's app, read back on the call (or a spoken phrase when there's no app); reply lag, a word check, S1 on the reply | `engine/signals/s3_liveness.py` |
| S4 context | caller ID against the registered number, recent SIM swap, DoT FRI rating, repeat calls | `engine/signals/s4_context.py` |

`engine/fusion.py` turns S1 to S3 into a risk score and a GREEN / AMBER / RED tier. S4 can raise the tier by one step but never lower it. `engine/policy.yaml` maps tier × request risk to requirements, and `engine/policy.py` refuses to execute a request until every requirement is met. That refusal is the actual control; the detectors only decide how much friction a request gets.

Played through a loudspeaker into a phone mic, AI voices mostly get past S1: room echo removes what it listens for (`docs/ML.md`, "over the air"). That is why the code and the approval carry the guarantee. A recording made earlier can't read a code that didn't exist yet, and a clone can't sign on the owner's phone.

Nothing is enrolled. There are no voiceprints, embeddings live only for the length of the call, and raw audio is a 20 s ring buffer in memory. The only audio written to disk is a 20 s evidence clip on RED calls, encrypted with AES-GCM.

## Requirements

Developed and tested on Windows 11. The helper scripts are PowerShell; the engine itself is ordinary Python.

- Python 3.11
- Node 22
- An NVIDIA GPU with 8 GB or more and a CUDA 12.8 driver. The demo laptop has an RTX 5070 Laptop GPU. Everything falls back to CPU, but liveness and S1 get slow enough to break the timings. For UI work without a GPU, use `-Dummy`.
- ffmpeg on `PATH`, built with `libopencore_amrnb`, `libgsm`, `libilbc` and `libopus`. The engine uses it to decode voice notes and recordings. Benchmarks and training use it for the phone codecs and fail if a codec is missing.
- About 25 GB free disk for datasets, checkpoints and the Hugging Face cache.

## Setup

```powershell
python -m venv .venv
uv pip install --python .venv\Scripts\python.exe torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
cd web; npm install; npm run build; cd ..
git config core.hooksPath .githooks
```

Plain `pip` works if you don't have `uv`. Install torch from the cu128 index first, or pip will pull a CPU build.

### Detector weights

S1 needs converted checkpoints in `models/`. The weights come from Hugging Face and are converted from fairseq layout to `transformers`, so fairseq is never installed.

```powershell
.venv\Scripts\python -m ml.fetch_data                 # public datasets, ~6 GB
.venv\Scripts\python -m ml.build_manifest             # clips + data/manifests/*.csv
.venv\Scripts\python -m ml.port_antideepfake nii-yamagishilab/wav2vec-large-anti-deepfake models\s1_add_w2vlarge.pt
.venv\Scripts\python -m ml.port_antideepfake nii-yamagishilab/xls-r-1b-anti-deepfake models\s1_add_xlsr1b.pt
.venv\Scripts\python -m ml.calibrate_s1 --checkpoint models\s1_add_w2vlarge.pt,models\s1_add_xlsr1b.pt
```

Calibration isn't optional. Raw scores are badly calibrated, and the tier cut-offs assume calibrated probabilities. The result goes into `models/s1_calibration.json`, keyed by model version.

If the two AntiDeepfake files aren't there, the engine falls back to the XLS-R + SLS checkpoint (`models/s1_sls_phone.pt`, then `models/s1_sls_hf.pt`). `docs/ML.md` explains how to build those and why the ensemble replaced them. The startup log says which model and calibration were loaded.

The AntiDeepfake weights are CC BY-NC-SA 4.0: research and education only. A commercial deployment needs a licence from NII or a different model.

## Running it

```powershell
.\run.ps1            # engine + built web app on http://localhost:8000
.\run.ps1 -Dummy     # no models: heuristic S1, no S2, tiny ASR. UI work only
.\run.ps1 -Eval      # lets the IndiaCall simulator fix challenges; never use for a demo
```

Models load in a background thread after startup, and the Engine card on `/demo` shows when they're ready. The engine prints a staff PIN on first start and keeps it in `data/runtime/staff_pin.txt`. Set `COUNTERSIGN_STAFF_PIN` to choose your own.

| Page | Who uses it | PIN |
|---|---|---|
| CS Bank app (`/download/cs-bank.apk`) | **judges and customers**: sign up, family, pay, call the bank, approvals | no |
| `/agent` | human contact-centre agent (and Amazon Connect calls): Voice Trust Card, requests, app code, approvals | yes |
| `/fraud` | fraud analyst: cases, evidence clip, outcome | yes |
| `/demo` | the app QR code, who's on a call, reset, privacy inspector | yes |
| `/metrics` | benchmark and IndiaCall results, over-the-air results | no |
| `/record` | consented speakers recording the IndiaCall script | yes |
| `/call` | backup browser softphone (not linked anywhere) | no |

For front-end work, run the engine and then `npm run dev` in `web/`. Vite proxies `/api` and `/ws` to port 8000, so the page and the API share an origin.

### Phones

The app talks to the engine over HTTPS through a tunnel (`docs/RUNBOOK.md`); its default server is set at build time (`android/README.md`). Build the release APK and copy it to `data/app/cs-bank.apk`, and `/demo` shows its QR code. Team phones take the seeded Rahul and Sunita accounts with "Team demo account" and the staff PIN.

`docs/THINGS_TO_TRY.md` is the judge card (no fixed script). `docs/EDGE_CASES.md` lists every edge case we handle and how.

### The AI assistant

Calls from the app are answered by `engine/agent/`. It understands the caller with a free-tier LLM and speaks with ElevenLabs. Every one of these is optional and has a fallback, so a call never dies:

- **Speech:** `ELEVENLABS_API_KEY` set means ElevenLabs Flash speaks the agent's lines as phone audio. Without it, the caller's phone reads them aloud.
- **Listening:** ElevenLabs Scribe, or faster-whisper on our own GPU (`COUNTERSIGN_STT=local` keeps caller audio on our server).
- **Understanding:** `GROQ_API_KEY`, then `GEMINI_API_KEY`, then `MISTRAL_API_KEY`, then a keyword classifier.

The LLM only classifies what the caller said. Account facts and every step-up line come from the bank's data and `policy.yaml`, so the assistant can't be talked into skipping a step.

## Configuration

Every setting is an environment variable with a `COUNTERSIGN_` prefix, read once at startup (`engine/config.py`).

| Variable | Default | |
|---|---|---|
| `S1` | `auto` | `auto` loads the best checkpoint on disk and falls back to the dummy scorer if loading fails. `dummy` never loads a model. Anything else fails loudly when the checkpoint won't load. |
| `S1_CKPT` | best on disk | one checkpoint, or several separated by commas for an ensemble |
| `S2` | `1` | `0` turns speaker drift off |
| `ASR` | `small` | faster-whisper size for the liveness word check, `off` to disable |
| `DEVICE` | `cuda` | `cpu` to force CPU |
| `AMBER_AT`, `RED_AT` | `0.30`, `0.70` | tier cut-offs. Override the fitted values in `models/fusion.json` when set. |
| `STAFF_PIN` | generated | staff PIN |
| `MAX_CALLS` | `4` | live calls at once; the softphone needs no login, so further callers hear "all our lines are busy" |
| `CONNECT_SECRET` | empty (off) | the Amazon Connect Lambda's `CONNECT_HMAC_SECRET`; turns on `/api/ingest/connect/start` |
| `CONNECT_AWS_PROFILE` | default credentials | AWS profile allowed `kinesisvideo:GetDataEndpoint` and `GetMedia` on the Connect streams |
| `APP_DIR` | `data/app` | the CS Bank APK (`cs-bank.apk`) and the cloned-voice clips the app's attack mode can play (`samples/*.wav`, labels in `samples/labels.json`, consented clones only). Gitignored. |
| `TTS_VOICE`, `TTS_MODEL` | ElevenLabs default voice, `eleven_flash_v2_5` | the assistant's voice (pick an Indian English voice in the ElevenLabs library). Needs `ELEVENLABS_API_KEY`. |
| `STT` | `elevenlabs` | `local` transcribes callers with faster-whisper on our GPU only |
| `LLM_PROVIDERS` | Groq, Gemini, Mistral | JSON list of OpenAI-compatible providers `[{"base_url", "model", "key_env"}]`, tried in order |
| `EVIDENCE_KEY` | generated | 32-byte hex AES key for evidence clips (stands in for a KMS) |
| `EVAL` | `0` | simulator mode, as `-Eval` |
| `DATA`, `MODELS`, `RUNTIME` | `data`, `models`, `data/runtime` | where things live |

`data/runtime/` holds the SQLite store (customers, families, phone keys, cases), the evidence key, the cookie secret and the staff PIN. It is gitignored; keep it that way.

## Checks

```powershell
.\check.ps1          # ruff, ruff format --check, pytest, eslint, tsc, web build
.\check.ps1 -Fast    # the same without the web build
```

The pre-commit hook runs ruff and pytest, and eslint plus tsc when web files are staged. The tests need no GPU and no models: they run the real HTTP and websocket surface with a dummy S1 and a software phone key (`ml/eval/soft_device.py`). The Amazon Connect spike has its own tests, which `check.ps1` doesn't run:

```powershell
.venv\Scripts\python -m pytest integrations/connect
```

## Evaluation

There are two kinds of numbers, and `docs/ML.md` has the details for both.

- **Detector benchmarks** (`ml.eval.benchmark`). S1 alone on In-the-Wild and our Hindi dev set, through G.711, AMR-NB and Opus, with and without packet loss and room noise. Each result reports EER, plus the share of genuine and fake clips at or above the AMBER and RED cut-offs, because that is what the engine acts on.
- **IndiaCall** (`ml.eval.indiacall_sim`, `fit_fusion`, `report`). Consented recordings of real people and clones of the teammates' voices, streamed as live calls through the running engine, with the policy and phone-key approvals on. The recordings aren't in the repo. Speakers record them on `/record` after signing `docs/CONSENT.md`, and `docs/CLONES.md` covers making the clones. Volunteers record genuine speech only and are never cloned.

`ml.eval.report` writes `models/metrics.json`, which `/metrics` displays.

## Layout

```
engine/            FastAPI app, call sessions, signals, fusion, policy, approvals, cases
  mobile.py        the CS Bank app's API: sign-up, family, pay, approvals, kill switch
  guard.py         the payment pause, family check, golden-hour hold
  agent/           the AI assistant: dialogue, LLM, ElevenLabs voice
  signals/         S1-S4
  stepup/          phone keys and request-bound approvals
  mocks/world.py   customers, FRI ratings, SIM swaps: the parts a bank would supply
  tests/           API and unit tests
web/               React app: agent console, fraud desk, demo, metrics, recorder, backup softphone
android/           CS Bank Android app (Kotlin, Compose)
ml/                data, checkpoint ports, calibration, training, benchmarks, IndiaCall
integrations/      Amazon Connect live-media spike (Kinesis Video Streams reader, Lambda)
models/            calibration, benchmark results, metrics (checkpoints are gitignored)
docs/              runbook, demo script, ML notes, model card, data sheet, consent
```

## Limits

- **Mocked**: core banking, the DoT FRI feed, the telco SIM-swap feed, and NCRP/1930 and DIP submission. Each is one in-memory module or a row in the reports table.
- **Telephony**: calls reach the engine from the browser softphone or from Amazon Connect (`engine/ingest/connect.py`, set up per `integrations/connect/README.md`). Other contact centres would need a SIPREC fork or their own media API.
- **Deployment**: one process, one GPU, SQLite and a shared staff PIN, sized for a demo laptop and not for a contact centre. `deploy/runpod/` runs the same thing on a rented GPU for a few days.
- **Detection**: S1 will miss generators it hasn't seen, degrades on heavy codecs, and mostly misses AI voices played through a speaker into a phone mic; `docs/MODEL_CARD.md` and `docs/ML.md` have the numbers. The design assumes that will happen, which is why risky changes need the app code and the phone's signed approval whatever S1 says.
- **Phone calls**: the app can't hear normal phone calls (Android blocks it), so the family check runs on call state, never audio.
- **Data**: we use only public, consented or synthetic data. Dataset licences are in `docs/DATA_SHEET.md`.
