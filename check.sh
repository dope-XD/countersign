#!/usr/bin/env bash
# Run every check before you commit or push (macOS / Linux / Git Bash). Exit code is non-zero if anything fails.
#   ./check.sh            engine checks, plus the Android build if android/ has an SDK set up
#   ./check.sh --android  Android build and lint only (agents B and C)
cd "$(dirname "$0")"
failed=()
step() { echo "==> $1"; shift; "$@" || { failed+=("$1"); echo "FAILED"; }; }

if [ "$1" != "--android" ]; then
  py=.venv/bin/python; [ -x "$py" ] || py=.venv/Scripts/python.exe
  step "ruff lint"   "$py" -m ruff check engine ml
  step "ruff format" "$py" -m ruff format --check engine ml
  step "pytest"      "$py" -m pytest -q
fi
if [ -f android/local.properties ] || [ -n "$ANDROID_HOME" ]; then
  step "android build + lint" bash -c "cd android && ./gradlew -q assembleDebug lintDebug"
fi

if [ ${#failed[@]} -gt 0 ]; then echo; echo "${#failed[@]} check(s) failed"; exit 1; fi
echo; echo "All checks passed."
