# Making the IndiaCall clones

Only for teammates who signed [CONSENT.md](CONSENT.md) and gave consent on `/record`.

## 1. Record

Each teammate opens `/record` (on the laptop at `http://localhost:8000/record`, or a phone over the tunnel) and records all 36 lines, which takes about 12 minutes. Files land in `data/indiacall/recordings/<speaker>/`.

## 2. Clones environment

The clone tools pin their own library versions, so they get a separate venv that reuses the system PyTorch (2.11 cu128 is already installed in `C:\Python311`):

```powershell
C:\Python311\python.exe -m venv --system-site-packages .venv-clones
.venv-clones\Scripts\python -m pip install coqui-tts f5-tts chatterbox-tts soundfile
git clone https://github.com/Plachtaa/seed-vc ..\seed-vc
.venv-clones\Scripts\python -m pip install -r ..\seed-vc\requirements.txt
```

IndicF5 is gated: accept its terms at https://huggingface.co/ai4bharat/IndicF5 and run `huggingface-cli login` first.

## 3. Generate

```powershell
.venv-clones\Scripts\python -m ml.clones.generate xtts
.venv-clones\Scripts\python -m ml.clones.generate f5
.venv-clones\Scripts\python -m ml.clones.generate indicf5
.venv-clones\Scripts\python -m ml.clones.generate chatterbox
.venv-clones\Scripts\python -m ml.clones.generate seedvc --seedvc-dir ..\seed-vc
```

Outputs go to `data/indiacall/clones/<generator>/<speaker>/`, each with a `SYNTHETIC_LABEL.txt`. Generators give us the attacker levels:

| Level | Audio | Generators |
|---|---|---|
| L1 replay | pre-made clone clips; the challenge reply is an unrelated clip | xtts, f5, indicf5, chatterbox |
| L2 typed TTS | clone says the challenge after a typing delay | same |
| L3 live conversion | another teammate speaks; Seed-VC converts to the victim | seedvc |
| L4 | L3 + caller ID spoofed to the registered number + SIM swap | seedvc |

## 4. Live L3 on stage

Route Seed-VC's real-time GUI (`python real-time-gui.py` in `seed-vc`) into a Voicemeeter virtual cable, then pick that cable as the microphone on `/call`.

## 5. Delete after the event

```powershell
.venv-clones\Scripts\python -m ml.clones.generate purge
Remove-Item -Recurse data\indiacall\recordings
```
