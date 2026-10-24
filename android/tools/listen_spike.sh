#!/usr/bin/env bash
# #37 spike: which microphone source hears the caller during a call, per phone.
# Team phones and consenting team voices only. Clips land in android/listen_spike/ (gitignored),
# never in git; hand them to A for the eval set (A keeps them in data/listen_spike/).
#
#   ./listen_spike.sh setup    install the debug app, grant the mic, open Accessibility settings
#   ./listen_spike.sh pull     copy the clips to android/listen_spike/<phone>/ and print the table
#   ./listen_spike.sh clear    delete the clips from the phone
#
# On the phone, once: Settings → Apps → CS Bank → ⋮ → "Allow restricted settings" (Android 13+,
# sideloaded apps), then Accessibility → "CS Bank listen test" → on. Then, for each call type
# (normal call, WhatsApp call), call between two team phones and keep talking from BOTH ends for
# about 3 minutes: the tool records 20 s from MIC, VOICE_RECOGNITION, UNPROCESSED and CAMCORDER in
# turn. Switch the speaker on halfway. With several phones plugged in, set ANDROID_SERIAL.
set -euo pipefail
export MSYS_NO_PATHCONV=1 # Git Bash on Windows: keep /sdcard/... paths as they are
cd "$(dirname "$0")/.."
pkg=app.countersign.bank
remote=/sdcard/Android/data/$pkg/files/listen_spike

case "${1:-}" in
  setup)
    ./gradlew -q installDebug
    adb shell pm grant $pkg android.permission.RECORD_AUDIO
    adb shell pm grant $pkg android.permission.READ_PHONE_STATE
    adb shell am start -a android.settings.ACCESSIBILITY_SETTINGS >/dev/null
    echo "Now turn on 'CS Bank listen test' in Accessibility (Android 13+: first 'Allow restricted settings' in App info)."
    ;;
  pull)
    phone=$(adb shell getprop ro.product.model | tr -d '\r' | tr ' ' '_')
    out=listen_spike/$phone
    mkdir -p "$out"
    adb pull "$remote/." "$out" >/dev/null
    echo "Clips in $out"
    echo
    echo "| phone | Android | call | speaker | overlay | source | result | level (dBFS) | silenced | caller audible? | own voice audible? |"
    echo "|---|---|---|---|---|---|---|---|---|---|---|"
    py=$(command -v python3 || command -v python)
    "$py" - "$out/summary.jsonl" <<'PY'
import json, sys
for line in open(sys.argv[1], encoding="utf-8"):
    c = json.loads(line)
    print(f"| {c['phone']} | {c['android']} | {c['call']} | {'on' if c['speaker'] else 'off'} | {'on' if c.get('overlay') else 'off'} | {c['source']} | {c['result']} "
          f"| {c.get('rms_dbfs', '')} | {c.get('silenced', '')} | ? | ? |")
PY
    echo
    echo "Listen to each clip and fill in the two '?' columns, then post the table on #37."
    ;;
  clear)
    adb shell rm -rf "$remote"
    echo "Clips deleted from the phone."
    ;;
  *)
    sed -n '2,13p' "$0"
    exit 1
    ;;
esac
