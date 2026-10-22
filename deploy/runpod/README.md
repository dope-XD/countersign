# Hosting on a RunPod GPU pod (the finale days)

This setup keeps the engine reachable around the clock for a few days on one rented GPU. It is still the demo deployment from the main README (one process, SQLite, a shared staff PIN), just not on the laptop.

## Pod

- **On-demand, not spot or interruptible.** A spot pod can be taken back in the middle of the demo.
- RTX 4090 or L4, 24 GB. The engine needs about 5 GB of VRAM. Pick an EU data centre: it is the closest RunPod region to India.
- Template: RunPod PyTorch on CUDA 12.8 or newer. Volume disk 40 GB mounted at `/workspace`. Only `/workspace` survives a restart, so the scripts keep everything there.
- Expose no ports. The tunnel goes out from the pod, so the engine only listens on 127.0.0.1.

At $0.35–0.70 an hour, three days costs about $25–50. Terminate the pod and delete its volume afterwards: a stopped pod still bills for the volume.

## Setup (once, about 15 minutes)

In the pod's web terminal:

```bash
cd /workspace && git clone https://github.com/dope-XD/countersign.git   # private repo: https://<token>@github.com/...
bash /workspace/countersign/deploy/runpod/setup.sh
```

`setup.sh` installs ffmpeg, uv, Node 22 and ngrok, builds the venv and the web app, and converts the two AntiDeepfake checkpoints from Hugging Face on the pod. The calibration (`models/s1_calibration.json`) and fitted fusion (`models/fusion.json`, once it exists) come from git, so commit them before you deploy.

Then fill in `/workspace/countersign.env`, which setup copies from `countersign.env.example`:

- `COUNTERSIGN_STAFF_PIN`: long, because this engine is on the internet.
- `COUNTERSIGN_EVIDENCE_KEY`: `python -c "import secrets; print(secrets.token_hex(32))"`.
- `NGROK_AUTHTOKEN` and `NGROK_DOMAIN`: keep the static domain the demo phones already use. Passkeys are bound to the hostname, so the same domain means the phones' existing passkeys keep working. Stop ngrok on the laptop first: one domain, one agent.

## Run

```bash
bash /workspace/countersign/deploy/runpod/start.sh
```

This starts tmux session `cs` with two windows, the engine and the tunnel, each in a restart loop. It waits for the models, then prints `/api/health`. Logs go to `/workspace/logs/`. Run the same command again after a pod restart.

- `tmux attach -t cs` to watch, then Ctrl-b d to leave it running.
- `nvidia-smi` should show the Python process holding about 5 GB.
- Point a free uptime monitor (UptimeRobot or similar) at `https://<domain>/api/health`.

## Before the judges arrive

- Log in to `/agent`, `/fraud` and `/demo` on every staff device. Issued cookies keep working through the PIN lockout, so a stranger guessing PINs can't lock you out.
- Press **Reset demo world** on `/demo`. It keeps the bound passkeys.
- From the laptop: `python -m ml.eval.first_tier --base https://<domain> --calls 5`. The p95 first tier should stay under 8 s.
- Make one real call from a phone on mobile data and run the liveness challenge. Reply lag now includes the EU round trip. The engine subtracts the caller's measured round trip, but check that a real person still passes.

## What the public internet changes

- `/ws/caller` needs no login by design, because the caller may be the attacker. The engine takes at most `COUNTERSIGN_MAX_CALLS` (default 4) live calls and turns the rest away with "all our lines are busy".
- Wrong staff PINs lock PIN checks per client address (the tunnel's `X-Forwarded-For`) after 10 tries, and for everyone after 100 tries in 5 minutes.
- `COUNTERSIGN_EVAL` must stay 0. `start.sh` refuses to start otherwise.
