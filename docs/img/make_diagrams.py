"""The architecture diagrams (docs/ARCHITECTURE.md, the report): system map, one call step by step, how it decides.

    python docs/img/make_diagrams.py      # writes docs/img/{system,call-timeline,decision}.svg

Plain SVG in the app's colours (android/.../ui/Theme.kt) with system-font fallbacks, so the files read the same on
GitHub, in a browser and in print. 1200 px wide; no text under 15 px, so it stays readable printed across an A4 page.
The words on the phone mock-ups are the app's own (res/values/strings.xml).
"""

from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent
FONT = "Inter, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"

BRAND, BRAND_SOFT = "#0B5CAD", "#E6EEF7"
INK, MUTED, LINE, PAPER = "#14202B", "#5B6B79", "#D5DBE1", "#F4F6F8"
AMBER, AMBER_SOFT, AMBER_BAR = "#9A5B00", "#FFF1D6", "#F2A42B"
RED, RED_SOFT = "#B3261E", "#FCE4E2"
GREEN, GREEN_SOFT = "#137A3F", "#E3F4E9"
NIGHT = "#1B222C"
T, S = 21, 17  # box title and line sizes


class Svg:
    def __init__(self, w: int, h: int):
        self.w, self.h, self.parts = w, h, []
        marks = "".join(
            f'<marker id="{k}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto-start-reverse">'
            f'<path d="M0 0L10 5L0 10z" fill="{c}"/></marker>'
            for k, c in (("a", MUTED), ("ab", BRAND), ("ar", RED), ("ag", GREEN))
        )
        self.parts.append(f"<defs>{marks}</defs>")

    def rect(self, x, y, w, h, fill="#fff", stroke=LINE, r=14, sw=1.5, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}/>')

    def text(self, x, y, s, size=S, weight=400, fill=INK, anchor="start", rotate=None):
        """One line, or several (a list): each next line 1.28× the size lower."""
        lines = s if isinstance(s, list) else [s]
        rot = f' transform="rotate({rotate} {x} {y})"' if rotate is not None else ""
        for i, line in enumerate(lines):
            self.parts.append(
                f'<text x="{x}" y="{y + i * size * 1.28:.1f}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" '
                f'fill="{fill}" text-anchor="{anchor}"{rot}>{escape(line)}</text>'
            )

    def box(self, x, y, w, h, title, sub=None, fill="#fff", stroke=LINE, tfill=INK, sfill=MUTED, tsize=T, ssize=S):
        self.rect(x, y, w, h, fill, stroke, sw=2 if stroke != LINE else 1.5)
        self.text(x + 18, y + 33, title, tsize, 700, tfill)
        if sub:
            self.text(x + 18, y + 33 + tsize * 1.4, sub, ssize, 450, sfill)

    def line(self, pts, color=MUTED, marker="a", dash=None, both=False, sw=2.5):
        d = " ".join(f"{'M' if i == 0 else 'L'}{x} {y}" for i, (x, y) in enumerate(pts))
        m = (f' marker-end="url(#{marker})"' if marker else "") + (f' marker-start="url(#{marker})"' if both else "")
        ds = f' stroke-dasharray="{dash}"' if dash else ""
        self.parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{sw}" stroke-linejoin="round"{ds}{m}/>')

    def label(self, x, y, s, size=16, fill=MUTED):
        w = len(s) * size * 0.55 + 16
        self.rect(x - w / 2, y - size - 4, w, size + 12, "#fff", "#fff", r=6, sw=0)
        self.text(x, y + 1, s, size, 600, fill, "middle")

    def save(self, name):
        body = "\n".join(self.parts)
        (OUT / name).write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {self.w} {self.h}" width="{self.w}" height="{self.h}">\n'
            f'<rect width="{self.w}" height="{self.h}" fill="#fff"/>\n{body}\n</svg>\n'
        )


def lock(s: Svg, x, y, color=INK):
    s.parts.append(
        f'<g transform="translate({x} {y})" fill="none" stroke="{color}" stroke-width="2.4" stroke-linecap="round">'
        '<rect x="0" y="10" width="20" height="14" rx="3"/><path d="M4.5 10V6.5a5.5 5.5 0 0 1 11 0V10"/></g>'
    )


# ---------------------------------------------------------------- the system map
def system():
    s = Svg(1200, 720)
    s.rect(20, 20, 712, 568, PAPER, LINE, r=24)
    s.text(46, 64, "Mummy's phone", 28, 800)
    s.text(46, 94, "does all the listening and judging", S, 450, MUTED)

    s.box(44, 120, 214, 86, "Call audio", "on speaker, in memory")
    s.box(44, 226, 214, 86, "Voice check", "first 20 s of the caller")
    s.box(44, 332, 214, 100, "What it sees", ["unknown number,", "AnyDesk, caller check ✗"])
    s.box(292, 120, 196, 86, "Speech to text", "on the phone")
    s.box(514, 168, 204, 160, "Two judges", ["our model reads", "the whole call;", "cue rules add", "the why"], BRAND, BRAND, "#fff", "#DCE8F5")
    s.line([(258, 163), (292, 163)])
    s.line([(488, 163), (500, 163), (500, 205), (514, 205)])
    s.line([(258, 269), (514, 269)])
    s.line([(258, 386), (500, 386), (500, 305), (514, 305)])

    s.line([(616, 328), (616, 466)], BRAND, "ab")
    s.line([(616, 446), (151, 446), (151, 466)], BRAND, "ab")
    s.line([(616, 446), (392, 446), (392, 466)], BRAND, "ab")
    s.box(44, 466, 214, 104, "The card", ["amber or red,", "with the why"], AMBER_SOFT, AMBER)
    s.box(292, 466, 200, 104, "At amber", ["a second opinion", "(optional)"])
    s.box(514, 466, 204, 104, "At red", ["alert the family,", "once per call"], RED_SOFT, RED, RED, INK)

    s.box(800, 40, 380, 126, "Relay", ["a free server with no AI:", "passes ids between phones"], "#fff", INK)
    s.box(
        800,
        250,
        380,
        160,
        "Rahul's phone",
        ["rings full screen, even on silent:", "“Mummy may be on a scam call”", "Call Mummy · Message Mummy"],
        RED_SOFT,
        RED,
        RED,
        INK,
    )
    s.box(800, 476, 380, 126, "Detection server (optional)", ["a stronger check after amber;", "audio in memory, then dropped"], "#fff", LINE)

    s.line([(718, 496), (762, 496), (762, 103), (800, 103)], BRAND, "ab")
    s.rect(750, 250, 24, 100, PAPER, PAPER, r=0, sw=0)
    s.text(768, 300, "ids only", 16, 650, BRAND, "middle", rotate=-90)
    s.line([(990, 166), (990, 250)], BRAND, "ab", both=True)
    s.label(990, 214, "caller check · family alarm", 16, BRAND)
    s.line([(718, 536), (782, 536), (782, 372), (800, 372)], RED, "ar", dash="7 6")
    s.text(1180, 440, "SMS from her SIM if his app is off", 16, 650, RED, "end")
    s.line([(392, 570), (392, 626), (990, 626), (990, 602)], MUTED, "a", both=True)
    s.label(690, 632, "audio after amber · the verdict back, which can only raise the level", 16)

    s.rect(20, 660, 1160, 48, GREEN_SOFT, GREEN_SOFT, r=12)
    lock(s, 38, 667, GREEN)
    s.text(72, 691, "Words and audio stay on the phone · the relay sees ids only · a 20 s encrypted clip only for a confirmed scam, 30 days", 16, 650, GREEN)
    s.save("system.svg")


# ---------------------------------------------------------------- one call, step by step
def phone(s: Svg, x, y, w=212, h=300, screen=NIGHT):
    s.rect(x, y, w, h, "#0A0D11", "#0A0D11", r=28)
    s.rect(x + 7, y + 7, w - 14, h - 14, screen, screen, r=22)
    s.rect(x + w / 2 - 26, y + 15, 52, 10, "#05070A", "#05070A", r=5)


def card(s: Svg, x, y, w, lines, fill, stroke, head=INK):
    h = 24 + len(lines) * 19
    s.rect(x, y, w, h, fill, stroke, r=10, sw=2.5)
    for i, (txt, bold) in enumerate(lines):
        s.text(x + 11, y + 24 + i * 19, txt, 15, 700 if bold else 500, head if bold else INK)
    return h


def timeline():
    s = Svg(1200, 664)
    cols = [12, 250, 488, 726, 964]
    for i, x in enumerate(cols):
        phone(s, x + 6, 16, screen=RED_SOFT if i == 4 else NIGHT)
        if i < 4:
            s.text(x + 112, 62, "Unknown number", 15, 650, "#fff", "middle")
            s.line([(x + 220, 166), (x + 244, 166)])
    px = [c + 20 for c in cols]
    w = 184
    card(s, px[0], 84, w, [("Says they're family?", True), ("Tap their face", False)], "#fff", LINE)
    s.rect(px[0], 160, w, 36, RED_SOFT, RED, r=18, sw=2)
    s.text(px[0] + w / 2, 184, "✗ Not Rahul's phone", 15, 750, RED, "middle")
    card(s, px[1], 84, w, [("Listening for scams", True), ("Checked on this", False), ("phone.", False)], "#fff", BRAND)
    h = card(
        s,
        px[2],
        80,
        w,
        [("This sounds like a", True), ("“digital arrest”", True), ("scam.", True), ("Why: says police;", False), ("keep it secret", False)],
        AMBER_SOFT,
        AMBER,
        AMBER,
    )
    s.rect(px[2] + 10, 80 + h + 8, w - 20, 30, RED, RED, r=8)
    s.text(px[2] + w / 2, 80 + h + 29, "Alert family", 15, 700, "#fff", "middle")
    card(s, px[3], 84, w, [("This is likely a", True), ("scam. Hang up.", True), ("Family alerted", False)], RED_SOFT, RED, RED)
    s.text(px[4] + 6, 76, "!", 34, 850, RED)
    s.text(px[4] + 6, 120, ["Mummy may", "be on a", "scam call"], 21, 800, RED)
    s.rect(px[4] + 2, 220, w - 4, 32, GREEN, GREEN, r=8)
    s.text(px[4] + w / 2, 242, "Call Mummy", 15, 700, "#fff", "middle")
    s.rect(px[4] + 2, 258, w - 4, 30, "#fff", LINE, r=8)
    s.text(px[4] + w / 2, 279, "Message Mummy", 15, 650, INK, "middle")

    steps = [
        ("It rings", ["Is it Rahul? His", "own phone is asked."]),
        ("On speaker", ["Speech to text on", "the phone. Nothing", "is saved."]),
        ("Amber", ["The scam named,", "and why."]),
        ("Red", ["Two independent", "sources agree."]),
        ("Rahul's phone", ["Rings over silent;", "SMS if his app is", "off; a call after 60 s."]),
    ]
    for n, ((title, cap), x) in enumerate(zip(steps, cols, strict=True), start=1):
        s.parts.append(f'<circle cx="{x + 24}" cy="352" r="17" fill="{BRAND}"/>')
        s.text(x + 24, 358, str(n), 17, 800, "#fff", "middle")
        s.text(x + 50, 360, title, T, 800)
        s.text(x + 8, 396, cap, S, 450, MUTED)

    s.rect(12, 470, 1176, 184, GREEN_SOFT, GREEN_SOFT, r=20)
    s.text(36, 508, "Wrong? Two taps.", 24, 800, GREEN)
    flow = [
        ("I know this caller", ["or “It's not a scam”"]),
        ("Is this call fine?", ["→ Yes, it's fine"]),
        ("Warnings stop", ["for this call"]),
        ("Rahul sees", ["“False alarm: Mummy", "says it's fine”"]),
    ]
    xs = [36, 320, 604, 888]
    for (a, b), x in zip(flow, xs, strict=True):
        s.box(x, 526, 264, 112, a, b, "#fff", GREEN, INK, MUTED)
    for x in xs[:-1]:
        s.line([(x + 264, 582), (x + 284, 582)], GREEN, "ag")
    s.save("call-timeline.svg")


# ---------------------------------------------------------------- how it decides
def decision():
    s = Svg(1200, 560)
    s.box(20, 40, 246, 150, "What was said", ["the call so far, in", "English, Hinglish", "or Hindi"])
    s.box(20, 250, 246, 186, "What it saw", ["unknown number,", "AnyDesk opened,", "caller check ✗,", "computer voice"])
    s.line([(266, 115), (292, 115)], MUTED, None)
    s.line([(266, 343), (292, 343)], MUTED, None)
    s.line([(292, 115), (292, 430)], MUTED, None)
    s.line([(292, 130), (316, 130)])
    s.line([(292, 410), (316, 410)])

    s.box(
        316,
        20,
        404,
        246,
        "Our trained model",
        ["reads the whole call: is this", "caller doing what scammers", "do? Trained on 31,000", "Indian bank calls."],
        BRAND_SOFT,
        BRAND,
    )
    bx, by, bw = 336, 196, 364
    s.rect(bx, by, bw, 14, "#fff", LINE, r=7)
    s.rect(bx, by, 52, 14, GREEN, GREEN, r=7)
    s.rect(bx + 46, by, 278, 14, AMBER_BAR, AMBER_BAR, r=0, sw=0)
    s.rect(bx + 320, by, 44, 14, RED, RED, r=7)
    s.text(bx + 52, by + 40, "amber", 15, 700, AMBER)
    s.text(bx + bw, by + 40, "red, twice in a row", 15, 700, RED, "end")

    s.box(
        316,
        290,
        404,
        250,
        "Cue rules",
        [
            "19 kinds of scam move, in three",
            "languages: “says police”, “asks",
            "for the OTP”, “keep it secret”.",
            "“We'll never ask for your OTP”",
            "doesn't count. Talk about",
            "scams never makes red.",
        ],
        "#fff",
        LINE,
    )

    s.box(
        752, 150, 228, 250, "Together", ["amber: the higher", "of the two judges", "", "red: two", "independent sources", "agree"], INK, INK, "#fff", "#C9D2DB"
    )
    s.line([(720, 143), (736, 143), (736, 230), (752, 230)])
    s.line([(720, 415), (736, 415), (736, 340), (752, 340)])

    levels = [("Calm", "#fff", LINE, MUTED), ("A few signs", PAPER, MUTED, INK), ("Amber", AMBER_SOFT, AMBER, AMBER), ("Red", RED_SOFT, RED, RED)]
    for i, (name, f, st, tc) in enumerate(levels):
        y = 404 - i * 92
        s.rect(1016, y, 164, 64, f, st, r=14, sw=2.5)
        s.text(1098, y + 40, name, 20, 800, tc, "middle")
    s.line([(980, 275), (1012, 275)])
    s.line([(1000, 462), (1000, 132)], MUTED, "a", sw=2)
    s.text(1180, 504, "never goes down in a call;", S, 500, MUTED, "end")
    s.text(1180, 528, "two taps clear a mistake", S, 500, MUTED, "end")
    s.save("decision.svg")


if __name__ == "__main__":
    system()
    timeline()
    decision()
    print("wrote", ", ".join(p.name for p in sorted(OUT.glob("*.svg"))))
