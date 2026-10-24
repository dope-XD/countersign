"""How much of the repository was written at the finale: `git blame` every tracked code and doc file at HEAD and count
the lines whose author time is after the check-in tag (the last commit before check-in, 22 Oct 2026 12:01 IST).

    python tools/onsite_share.py            # totals and per top-level folder
    python tools/onsite_share.py --md       # the same as a Markdown table (for README.md)

Counts non-blank lines. Skips generated and data files (data/, models/, lock files, test vectors, model weights).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CODE = {".py", ".kt", ".kts", ".ts", ".tsx", ".js", ".sh", ".ps1", ".yml", ".yaml", ".toml", ".css", ".html", ".xml"}
DOCS = {".md"}
SKIP_PREFIX = ("data/", "models/", "web/package-lock.json", "android/gradle/", "android/app/src/test/resources/")
SKIP_SUFFIX = (".json", ".bin", ".jar", ".keystore", ".png", ".svg", ".csv")


def git(*a: str) -> str:
    return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def checkin_time() -> int:
    return int(git("log", "-1", "--format=%at", "check-in").strip())


def blame_counts(path: str, after: int) -> tuple[int, int]:
    out = git("blame", "--line-porcelain", "HEAD", "--", path)
    total = new = 0
    t = 0
    for line in out.splitlines():
        if line.startswith("author-time "):
            t = int(line.split()[1])
        elif line.startswith("\t") and line[1:].strip():
            total += 1
            new += t > after
    return total, new


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", action="store_true")
    a = ap.parse_args()
    after = checkin_time()
    files = [f for f in git("ls-files").splitlines() if not f.startswith(SKIP_PREFIX) and not f.endswith(SKIP_SUFFIX)]
    agg: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0])
    for f in files:
        ext = Path(f).suffix
        kind = "code" if ext in CODE else "docs" if ext in DOCS else None
        if kind is None:
            continue
        total, new = blame_counts(f, after)
        top = f.split("/", 1)[0] if "/" in f else "(root)"
        for key in ((kind, "all"), (kind, top)):
            agg[key][0] += total
            agg[key][1] += new
    head = git("log", "-1", "--format=%h %ci").strip()
    rows = sorted(agg.items(), key=lambda kv: (kv[0][0], kv[0][1] != "all", -kv[1][0]))
    if a.md:
        print(f"Measured at {head} with `python tools/onsite_share.py` (non-blank lines, `git blame`, after tag `check-in`):\n")
        print("| Kind | Folder | Lines | Written at the finale |")
        print("|---|---|---:|---:|")
        for (kind, top), (total, new) in rows:
            print(f"| {kind} | {'**all**' if top == 'all' else top} | {total} | {100 * new / max(1, total):.0f}% ({new}) |")
    else:
        print(f"HEAD {head}; check-in tag at {git('log', '-1', '--format=%h %ci', 'check-in').strip()}")
        for (kind, top), (total, new) in rows:
            print(f"{kind:5} {top:14} {total:7} lines  {100 * new / max(1, total):5.1f}% on site")
    return 0


if __name__ == "__main__":
    sys.exit(main())
