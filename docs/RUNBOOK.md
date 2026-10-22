# Runbook

## Setup (once)

```powershell
cd countersign
python -m venv .venv
uv pip install --python .venv\Scripts\python.exe torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
cd web; npm install; npm run build; cd ..
```

Detector weights (1.4 GB download, then converted):

```powershell
curl.exe -L -o models\src\sls_v1_epoch_2.pth https://huggingface.co/sukhdeveyash/XLS-R-SLS-Deepfake-Detection/resolve/main/v1/epoch_2.pth
.venv\Scripts\python -m ml.port_sls_checkpoint models\src\sls_v1_epoch_2.pth models\s1_sls_hf.pt
```

Calibrate it, which is required: raw SLS scores are badly overconfident, and the GREEN/AMBER/RED cut-offs assume calibrated scores:

```powershell
.venv\Scripts\python -m ml.fetch_data; .venv\Scripts\python -m ml.build_manifest
.venv\Scripts\python -m ml.calibrate_s1 --checkpoint models\s1_sls_hf.pt
```

The engine uses `models\s1_sls_phone.pt` (the phone/Indic fine-tune, see docs/ML.md) when it exists, and otherwise the converted checkpoint. `models\s1_calibration.json` holds one calibration per model version. The engine log says which model and calibration it loaded.

Windows caveat: in a single Python process, never import `pyarrow` before `transformers`/`sentencepiece`. That order crashes with an access violation (a DLL clash). The engine never imports pyarrow.

## Run

```powershell
.\run.ps1
```

Open http://localhost:8000/demo and enter the staff PIN. The engine log prints it at startup (`Staff PIN for agent console…`); pin your own with `$env:COUNTERSIGN_STAFF_PIN = "…"`. The demo panel shows model status, QR codes for phones, scenario switches and exactly what is stored. Customer pages (`/bank/...`, `/call`) never ask for the PIN.

## Phones (passkeys and mic need HTTPS)

Browsers only allow passkeys and microphone access on HTTPS (or localhost). Use a tunnel with a **fixed** hostname, because passkeys are bound to the hostname they were created on.

1. Make a free ngrok account and claim the free static domain (Dashboard → Domains), e.g. `countersign-demo.ngrok-free.app`.
2. `ngrok config add-authtoken <token>` (once).
3. `ngrok http --url=countersign-demo.ngrok-free.app 8000`
4. Open `https://countersign-demo.ngrok-free.app/demo` on the laptop and scan the QR codes with the phones.

The engine derives the passkey RP ID from the host by default (`COUNTERSIGN_RP_ID=auto`). For the event, pin it:

```powershell
$env:COUNTERSIGN_RP_ID = "countersign-demo.ngrok-free.app"
$env:COUNTERSIGN_ORIGINS = "https://countersign-demo.ngrok-free.app,http://localhost:8000"
```

Log each demo phone in by scanning its customer's QR on `/demo`. Each code is one-time and lasts 10 minutes; tap it for a new one. Then bind each phone once: Security → Bind this phone. Passkeys survive engine restarts (`data/runtime/countersign.db`), and **Reset demo world keeps them**.

For real call detection and notifications, install the CS Bank app on the demo phones (`android/README.md`): open the bank from the app, then Security → Turn on call alerts.

ngrok's free tier shows an interstitial page on first visit from each browser; tap "Visit Site" once per phone before the demo.

## Judges trying it themselves

1. Copy two or three consented clone clips (10–16 s each, someone asking to change their number) to `data/try/samples/`, with labels in `data/try/samples/labels.json`, e.g. `{"reshaan_f5.wav": "Reshaan's voice, cloned with F5-TTS"}`.
2. Build the app (`android/README.md`) and copy `android/app/build/outputs/apk/debug/app-debug.apk` to `data/try/cs-bank.apk`.
3. On the pod, put both in `/workspace/countersign/data/try/`: upload them in the RunPod file browser or with `runpodctl send`.
4. Put the `/try` QR from `/demo` on the closing slide and at the table.

Each scan makes a new private account, so judges never see each other's approvals. Accounts survive **Reset demo world**.

## Venue checklist

- Run the tunnel over a phone hotspot, not venue Wi-Fi.
- Laptop on power, `nvidia-smi` shows the RTX 5070, engine log says `S1 loaded ... on cuda`.
- `/demo` → Engine card shows S1 `sls`, S2 `ecapa`, ASR `small`.
- Phones: screen lock set (passkeys need it), brightness up, Do Not Disturb off, ngrok page already accepted.
- Press **Reset demo world** before each run.

## If something breaks

| Symptom | Fix |
|---|---|
| Phone shows "doesn't support passkeys" | You opened the LAN IP over http. Use the https tunnel URL. |
| "The RP ID is invalid for this domain" | `COUNTERSIGN_RP_ID` doesn't match the hostname in the address bar. |
| Approval sheet never appears on Rahul's phone | Keep `/bank/rahul` open in the foreground; the green dot must be on. |
| Agent console never leaves LISTENING | Caller mic muted, or < 4 s of speech so far. Check the level ring on the caller's screen. |
| Engine slow / p95 above 300 ms | Another GPU app is running; close it. `-Dummy` mode for UI-only work. |
| No internet at all | Laptop-only: open everything on `http://localhost:8000` in Chrome; passkeys work on localhost with Windows Hello. |
| faster-whisper fails on GPU | It falls back to CPU automatically (slower liveness check, still works). |

## Checks

```powershell
.\check.ps1
```

This runs ruff, the formatter check, pytest (unit and end-to-end API tests, no GPU needed), ESLint, the TypeScript check and the web build. The pre-commit hook (`git config core.hooksPath .githooks`) runs the fast subset on every commit.
