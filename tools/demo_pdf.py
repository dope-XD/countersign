"""docs/DEMO_SCRIPT.md → docs/DEMO_SCRIPT.pdf, ready to print (A4). The judge's lines (the quote blocks) come out in big
grey boxes, every scene starts on a new page, Hindi uses a Devanagari font. Printed by Edge or Chrome, headless.

    python tools/demo_pdf.py
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import markdown

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "DEMO_SCRIPT.md"
OUT = ROOT / "docs" / "DEMO_SCRIPT.pdf"
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "msedge",
    "google-chrome",
    "chromium",
]

CSS = """
@page { size: A4; margin: 14mm 14mm 16mm 14mm; }
body { font-family: "Segoe UI", "Nirmala UI", "Noto Sans", "Noto Sans Devanagari", sans-serif; font-size: 11.5pt;
       line-height: 1.45; color: #111; }
h1 { font-size: 22pt; margin: 0 0 6pt; }
h2 { font-size: 16pt; margin: 14pt 0 6pt; border-bottom: 2px solid #111; padding-bottom: 3pt; }
h2:has(+ p strong) { }
hr { border: 0; page-break-after: always; break-after: page; }
blockquote { background: #e9e9e9; border-left: 6px solid #444; margin: 8pt 0; padding: 8pt 12pt;
             font-size: 15pt; line-height: 1.5; page-break-inside: avoid; break-inside: avoid; }
blockquote p { margin: 4pt 0; }
blockquote strong { font-size: 11pt; text-transform: uppercase; letter-spacing: .5pt; color: #333; }
table { border-collapse: collapse; width: 100%; font-size: 10pt; page-break-inside: avoid; }
th, td { border: 1px solid #999; padding: 4pt 6pt; vertical-align: top; text-align: left; }
th { background: #ddd; }
code { font-family: Consolas, monospace; font-size: 9.5pt; background: #f2f2f2; padding: 0 2pt; }
ul, ol { margin: 4pt 0 4pt 16pt; padding: 0; }
li { margin: 2pt 0; }
"""


def browser() -> str:
    for b in BROWSERS:
        if Path(b).exists() or shutil.which(b):
            return b
    sys.exit("Need Edge or Chrome to print the PDF.")


def main() -> None:
    body = markdown.markdown(SRC.read_text(encoding="utf-8"), extensions=["tables", "nl2br"])
    html = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Countersign demo script</title><style>{CSS}</style></head><body>{body}</body></html>'
    with tempfile.TemporaryDirectory() as d:
        page = Path(d) / "demo.html"
        page.write_text(html, encoding="utf-8")
        subprocess.run(
            [browser(), "--headless=new", "--disable-gpu", "--no-pdf-header-footer", f"--print-to-pdf={OUT}", page.as_uri()],
            check=True,
            capture_output=True,
            timeout=120,
        )
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
