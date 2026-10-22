#!/usr/bin/env bash
# System packages. These live outside /workspace, so start.sh reinstalls them after a restart.
set -euo pipefail
if ! command -v ffmpeg >/dev/null || ! command -v tmux >/dev/null; then
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends ffmpeg tmux git curl xz-utils ca-certificates
fi
