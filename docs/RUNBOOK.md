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

Open http://localhost:8000/demo and enter the staff PIN. The engine log prints it at startup (`Staff PIN for agent console…`); pin your own with `$env:COUNTERSIGN_STAFF_PIN = "…"`. The demo panel shows model status, QR codes for phones, scenario switches and exactly what is stored. The CS Bank app and the backup softphone (`/call`) never ask for the PIN.

## Phones

The CS Bank app talks to the engine through a tunnel with a fixed hostname. The app's default server is baked in at build time (`android/README.md`); judges can also change it on the last sign-up screen.

1. Make a free ngrok account and claim the free static domain (Dashboard → Domains), e.g. `countersign-demo.ngrok-free.app`.
2. `ngrok config add-authtoken <token>` (once).
3. `ngrok http --url=countersign-demo.ngrok-free.app 8000`
4. Build the release APK with that server and copy it to `data/app/cs-bank.apk`. `/demo` shows its QR code.

Team phones: install the app and choose **Team demo account**, then Rahul or Sunita and the staff PIN. Accounts, families and phone keys survive engine restarts (`data/runtime/countersign.db`), and **Reset demo world** keeps them. It only puts Rahul and Sunita back to their seed.

## Judges trying it themselves

1. Put the APK in `data/app/cs-bank.apk` and the QR code from `/demo` on the closing slide and at the table. `docs/THINGS_TO_TRY.md` is the card to print.
2. Optional: two or three consented clone clips for attack mode (10–16 s each) in `data/app/samples/`, labelled in `data/app/samples/labels.json`, e.g. `{"reshaan_f5.wav": "Reshaan's voice, cloned with F5-TTS"}`.
3. On the pod, put both in `/workspace/countersign/data/app/` (RunPod file browser or `runpodctl send`).
4. For a natural voice, set `ELEVENLABS_API_KEY` and `COUNTERSIGN_TTS_VOICE`, and at least one LLM key (`GROQ_API_KEY`, `GEMINI_API_KEY`, `MISTRAL_API_KEY`). Without them the assistant still works: the phone reads its lines and keywords understand the caller.

Each sign-up is its own account, so judges only see their own family's checks.

## Venue checklist

- Run the tunnel over a phone hotspot, not venue Wi-Fi.
- Laptop on power, `nvidia-smi` shows the RTX 5070, engine log says `S1 loaded ... on cuda`.
- `/demo` → Engine card shows S1 `sls`, S2 `ecapa`, ASR `small`.
- Phones: screen lock set (the app's key needs it), brightness up, Do Not Disturb off, CS Bank allowed to run in the background.
- Press **Reset demo world** before each run.

## If something breaks

| Symptom | Fix |
|---|---|
| "Can't reach CS Bank" in the app | Wrong server on the sign-up screen, or the tunnel is down. Check `https://<domain>/api/health` in the phone's browser. |
| A family check doesn't ring | Android 14+: Settings → Apps → CS Bank → allow full-screen alerts; battery set to unrestricted. The check is still on the Home screen. |
| "This phone's account isn't on the bank server" | The engine's database was replaced. Sign up again. |
| Agent console never leaves LISTENING | Caller mic muted, or < 4 s of speech so far. Check the level ring on the caller's screen. |
| Engine slow / p95 above 300 ms | Another GPU app is running; close it. `-Dummy` mode for UI-only work. |
| No internet at all | Phones on the laptop's hotspot, app server set to `http://<laptop IP>:8000`. |
| faster-whisper fails on GPU | It falls back to CPU automatically (slower liveness check, still works). |

## Checks

```powershell
.\check.ps1
```

This runs ruff, the formatter check, pytest (unit and end-to-end API tests, no GPU needed), ESLint, the TypeScript check and the web build. The pre-commit hook (`git config core.hooksPath .githooks`) runs the fast subset on every commit.
