"""The paper's figures (docs/paper/paper.tex), in a plain print style: grey boxes, thin black lines, serif labels.

    python docs/paper/figures.py      # writes docs/paper/fig/*.svg; build.mjs turns them into PDFs for LaTeX

Full-width figures are drawn 1000 px wide for a 7.1 in text block, so 16 px type prints at about 8 pt.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent / "fig"
FONT = "'Times New Roman', 'Nimbus Roman', Times, serif"
INK, GREY, FILL, DARK = "#111111", "#555555", "#F1F1F1", "#E2E2E2"
SZ = 16


class Fig:
    def __init__(self, w: int, h: int):
        self.w, self.h, self.p = w, h, []
        self.p.append(
            '<defs><marker id="a" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{INK}"/></marker></defs>'
        )

    def box(self, x, y, w, h, lines, fill=FILL, bold_first=True, size=SZ, dash=False, align="middle", stroke=INK, sw=1.2):
        d = ' stroke-dasharray="5 4"' if dash else ""
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')
        n = len(lines)
        lh = size * 1.25
        y0 = y + h / 2 - (n - 1) * lh / 2 + size * 0.35
        tx = x + w / 2 if align == "middle" else x + 10
        for i, s in enumerate(lines):
            self.text(tx, y0 + i * lh, s, size, 700 if (bold_first and i == 0) else 400, align)

    def text(self, x, y, s, size=SZ, weight=400, anchor="start", italic=False, fill=INK):
        st = ' font-style="italic"' if italic else ""
        self.p.append(
            f'<text x="{x}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}"{st}>{escape(s)}</text>'
        )

    def arrow(self, pts, dash=False, both=False, sw=1.3):
        d = " ".join(f"{'M' if i == 0 else 'L'}{x} {y}" for i, (x, y) in enumerate(pts))
        ds = ' stroke-dasharray="5 4"' if dash else ""
        ms = ' marker-start="url(#a)"' if both else ""
        self.p.append(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="{sw}"{ds}{ms} marker-end="url(#a)"/>')

    def label(self, x, y, s, size=14, anchor="middle"):
        self.text(x, y, s, size, 400, anchor, italic=True, fill=GREY)

    def save(self, name):
        (OUT / name).write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}">'
            f'<rect width="{self.w}" height="{self.h}" fill="#fff"/>' + "".join(self.p) + "</svg>\n"
        )


def architecture():
    f = Fig(1000, 480)
    f.p.append(f'<rect x="8" y="8" width="632" height="384" fill="none" stroke="{INK}" stroke-width="1.2" stroke-dasharray="6 4"/>')
    f.text(20, 32, "Protected user's phone (Countersign app): all detection on the device", 16, 700)
    f.box(24, 56, 150, 62, ["Microphone", "speakerphone audio"], "#fff")
    f.box(206, 56, 168, 62, ["VAD + ASR", "Omnilingual 300M"])
    f.box(406, 44, 222, 70, ["Judge 1", "fine-tuned e5-small,", "whole call so far"])
    f.box(406, 134, 222, 70, ["Judge 2", "cue rules + move matcher", "(gives the reasons)"])
    f.box(24, 150, 150, 62, ["Voice-clone check", "first 20 s of speech"])
    f.box(24, 236, 150, 62, ["Context signals", "number, apps, check"])
    f.box(406, 226, 222, 62, ["Combiner", "two-source rule for red"], DARK)
    f.box(24, 322, 150, 54, ["Call card", "level + reasons"], "#fff")
    f.box(206, 322, 168, 54, ["Scam alert", "once per call"], "#fff")
    f.box(406, 322, 222, 54, ["SMS fallback", "and escalation"], "#fff")
    f.arrow([(174, 87), (206, 87)])
    f.arrow([(374, 79), (406, 79)])
    f.arrow([(390, 79), (390, 169), (406, 169)])
    f.arrow([(628, 79), (634, 79), (634, 257), (628, 257)])
    f.arrow([(517, 204), (517, 226)])
    f.arrow([(174, 181), (380, 181), (380, 242), (406, 242)])
    f.arrow([(174, 267), (406, 267)])
    f.arrow([(517, 288), (517, 304), (99, 304), (99, 322)])
    f.arrow([(290, 304), (290, 322)])
    f.arrow([(374, 349), (406, 349)])
    f.box(704, 40, 288, 100, ["Relay server (no ML)", "call events, caller checks,", "alerts: identifiers only"])
    f.box(704, 220, 288, 100, ["Family member's phone", "full-screen alarm; reports", "its own calls"])
    f.box(24, 416, 616, 56, ["Detection server (optional): second opinion after amber; audio in memory only"], "#fff", dash=True, size=15)
    f.arrow([(290, 376), (290, 386), (656, 386), (656, 90), (704, 90)])
    f.label(680, 82, "alert", 14)
    f.arrow([(628, 362), (676, 362), (676, 290), (704, 290)], dash=True)
    f.label(690, 282, "SMS", 14)
    f.arrow([(848, 140), (848, 220)], both=True)
    f.label(856, 184, "alarm, call events", 14, "start")
    f.arrow([(224, 392), (224, 416)], dash=True, both=True)
    f.label(234, 409, "audio after amber; verdict back", 14, "start")
    f.save("architecture.svg")


def decision():
    f = Fig(1000, 330)
    f.box(10, 40, 170, 80, ["ASR segments", "English, Hinglish,", "Hindi"], "#fff")
    f.box(10, 190, 170, 100, ["Phone context", "unknown number,", "remote-access app,", "caller check failed"], "#fff")
    f.box(
        230,
        14,
        300,
        126,
        ["Judge 1: conversation model", "pₜ = P(scam move so far)", "sₜ = mean(pₜ, pₜ₋₁)", "amber: sₜ ≥ 0.142", "red: sₜ ≥ 0.9855 twice in a row"],
        FILL,
        size=15,
    )
    f.box(
        230,
        168,
        300,
        126,
        [
            "Judge 2: cue rules",
            "19 categories, negation-aware;",
            "amber: ≥ 2 strong categories",
            "red: ≥ 4 incl. an action and a type;",
            "talk about scams never counts",
        ],
        FILL,
        size=15,
    )
    f.box(
        580,
        70,
        210,
        176,
        ["Combiner", "amber = higher judge", "(cue-only amber needs", "Judge 1 ≥ watch)", "red ⇐ two independent", "sources agree"],
        DARK,
        size=15,
    )
    f.arrow([(180, 80), (230, 80)])
    f.arrow([(205, 80), (205, 230), (230, 230)])
    f.arrow([(180, 240), (215, 240), (215, 116), (230, 116)])
    f.arrow([(180, 262), (230, 262)])
    f.arrow([(530, 78), (555, 78), (555, 130), (580, 130)])
    f.arrow([(530, 232), (555, 232), (555, 190), (580, 190)])
    levels = ["red", "amber", "watch", "none"]
    for i, name in enumerate(levels):
        y = 30 + i * 62
        f.box(850, y, 140, 46, [name], "#fff" if i > 1 else (DARK if i == 0 else FILL), bold_first=True, size=16)
    f.arrow([(835, 262), (835, 30)])
    f.arrow([(790, 158), (830, 158)])
    f.label(990, 292, "levels never decrease within a call", 14, "end")
    f.label(990, 310, "(except an explicit user override)", 14, "end")
    f.save("decision.svg")


def sequence():
    f = Fig(1000, 490)
    lanes = [("Protected user's phone", 110), ("Relay server", 390), ("Family member's phone", 640), ("Detection server", 890)]
    for name, x in lanes:
        f.box(x - 100, 10, 200, 38, [name], DARK, size=15)
        f.p.append(f'<path d="M{x} 48 V482" stroke="{GREY}" stroke-width="1" stroke-dasharray="3 4"/>')
    msgs = [
        (80, 640, 390, "its own call events, as they happen", False),
        (110, 110, 390, "call event (member id, no number)", False),
        (140, 110, 390, "caller check: is that member on this call?", False),
        (170, 390, 110, "verdict: not the member's phone", False),
        (215, 110, 890, "after amber: audio stream (memory only)", True),
        (245, 890, 110, "verdict (may only raise the level)", True),
        (290, 110, 390, "at red: scam alert (type, cue ids)", False),
        (320, 390, 640, "family alarm (full screen)", False),
        (350, 110, 640, "SMS if the family app is offline", True),
        (380, 640, 390, "acknowledged (call / message / OK)", False),
        (410, 390, 110, "stop escalation; else text and call after 60 s", False),
        (440, 110, 390, "false alarm: two taps", False),
        (470, 390, 640, "“false alarm” notice", False),
    ]
    for y, a, b, txt, dash in msgs:
        f.arrow([(a, y), (b, y)], dash=dash)
        mid = (a + b) / 2
        f.text(mid, y - 6, txt, 14.5, 400, "middle")
    f.save("sequence.svg")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    architecture()
    decision()
    sequence()
    print("wrote", ", ".join(p.name for p in sorted(OUT.glob("*.svg"))))
