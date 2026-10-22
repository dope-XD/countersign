#!/usr/bin/env bash
# One-time setup of Countersign on a RunPod GPU pod (Ubuntu, CUDA 12.8+ driver).
# Safe to run again. Everything lives under /workspace, the only disk that survives a
# container restart.
#
#   bash /workspace/countersign/deploy/runpod/setup.sh     (or curl it first, see deploy/runpod/README.md)
set -euo pipefail

W=/workspace
REPO=$W/countersign
GIT_URL=${COUNTERSIGN_GIT:-https://github.com/dope-XD/countersign.git}
NODE=v22.11.0
export HF_HOME=$W/hf UV_INSTALL_DIR=$W/bin UV_CACHE_DIR=$W/uv-cache UV_PYTHON_INSTALL_DIR=$W/uv-python
export PATH=$W/bin:$W/node/bin:$PATH
mkdir -p $W/bin $W/logs

if ! command -v git >/dev/null || ! command -v ffmpeg >/dev/null; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends ffmpeg tmux git curl xz-utils ca-certificates
fi

command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
if [ ! -x $W/node/bin/node ]; then
    curl -fsSL https://nodejs.org/dist/$NODE/node-$NODE-linux-x64.tar.xz | tar -xJ -C $W
    mv $W/node-$NODE-linux-x64 $W/node
fi
if [ ! -x $W/bin/ngrok ]; then
    curl -fsSL https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-amd64.tgz | tar -xz -C $W/bin
fi

if [ -d $REPO/.git ]; then git -C $REPO pull --ff-only; else git clone "$GIT_URL" $REPO; fi
cd $REPO

[ -x .venv/bin/python ] || uv venv --python 3.11 .venv
uv pip install --python .venv/bin/python torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128
uv pip install --python .venv/bin/python -r requirements.txt

(cd web && npm ci && npm run build)

# Detector weights: converted from Hugging Face here, at datacenter speed, instead of
# uploading 5 GB from the laptop. The calibration and fusion files come from git.
[ -f models/s1_add_w2vlarge.pt ] || .venv/bin/python -m ml.port_antideepfake nii-yamagishilab/wav2vec-large-anti-deepfake models/s1_add_w2vlarge.pt
[ -f models/s1_add_xlsr1b.pt ] || .venv/bin/python -m ml.port_antideepfake nii-yamagishilab/xls-r-1b-anti-deepfake models/s1_add_xlsr1b.pt

[ -f $W/countersign.env ] || { cp deploy/runpod/countersign.env.example $W/countersign.env; echo "Fill in $W/countersign.env, then run deploy/runpod/start.sh"; }
.venv/bin/python -c "import torch; print('cuda', torch.cuda.is_available(), torch.cuda.get_device_name(0) if torch.cuda.is_available() else '')"
