#!/usr/bin/env bash
# Start (or restart) the engine and the ngrok tunnel in a tmux session called "cs".
# Each runs in a loop, so a crash comes back on its own within a few seconds.
#
#   bash /workspace/countersign/deploy/runpod/start.sh
#   tmux attach -t cs            (Ctrl-b d to leave it running)
#   tail -f /workspace/logs/engine.log
set -euo pipefail

W=/workspace
REPO=$W/countersign
cd $REPO
bash deploy/runpod/system.sh

set -a; . $W/countersign.env; set +a
for v in COUNTERSIGN_STAFF_PIN COUNTERSIGN_EVIDENCE_KEY NGROK_DOMAIN NGROK_AUTHTOKEN; do
    [ -n "${!v:-}" ] || { echo "$v is empty in $W/countersign.env"; exit 1; }
done
[ "${COUNTERSIGN_EVAL:-0}" = "0" ] || { echo "COUNTERSIGN_EVAL must be 0 on a public engine"; exit 1; }

tmux kill-session -t cs 2>/dev/null || true
tmux new-session -d -s cs -n engine \
    "while true; do HF_HOME=$W/hf .venv/bin/python -m uvicorn engine.app:app --host 127.0.0.1 --port 8000 --ws-max-size 1048576 --proxy-headers >> $W/logs/engine.log 2>&1; echo restarting >> $W/logs/engine.log; sleep 2; done"
tmux new-window -t cs -n ngrok \
    "while true; do $W/bin/ngrok http --url=$NGROK_DOMAIN 8000 --log=stdout >> $W/logs/ngrok.log 2>&1; sleep 5; done"

echo "Waiting for the models to load..."
for _ in $(seq 1 120); do
    if curl -fs localhost:8000/api/health | grep -q '"s1": *"antideepfake+antideepfake"'; then break; fi
    sleep 5
done
curl -s localhost:8000/api/health; echo
echo "Public: https://$NGROK_DOMAIN/demo"
