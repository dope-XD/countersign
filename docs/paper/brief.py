"""The 2-page brief for the jury: the paper as two flowchart pages (A4 landscape), same print style as the figures.

    python docs/paper/brief.py      # writes docs/paper/brief/page1.svg, page2.svg; build.mjs prints them to a PDF

Every number is from docs/RESULTS.md (the same ones as paper.tex).
"""

from __future__ import annotations

from html import escape
from pathlib import Path

OUT = Path(__file__).resolve().parent / "brief"
FONT = "'Times New Roman', 'Nimbus Roman', Times, serif"
INK, GREY, FILL, DARK, WHITE = "#111111", "#555555", "#F1F1F1", "#DCDCDC", "#FFFFFF"
W, H = 1123, 794  # A4 landscape at 96 px per inch
BODY, HEAD = 11.6, 13.6


def wrap(text: str, width: float, size: float) -> list[str]:
    """Greedy wrap by an average Times character width; good enough for print, checked by eye."""
    out, line = [], ""
    limit = width / (size * 0.44)
    for word in text.split():
        if len(line) + len(word) + 1 > limit and line:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return out + ([line] if line else [])


class Page:
    def __init__(self):
        self.p = [
            '<defs><marker id="a" viewBox="0 0 10 10" refX="9.5" refY="5" markerWidth="7" markerHeight="7" '
            f'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="{INK}"/></marker></defs>'
        ]

    def text(self, x, y, s, size=BODY, weight=400, anchor="start", italic=False, fill=INK):
        st = ' font-style="italic"' if italic else ""
        self.p.append(
            f'<text x="{x}" y="{y:.1f}" font-family="{FONT}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}"{st}>{escape(s)}</text>'
        )

    def rect(self, x, y, w, h, fill=FILL, dash=False, sw=1.1, r=0):
        d = ' stroke-dasharray="5 4"' if dash else ""
        self.p.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}" fill="{fill}" stroke="{INK}" stroke-width="{sw}"{d}/>')

    def box(self, x, y, w, title, items, fill=FILL, dash=False, tag=None):
        """A titled box; items are bullet strings. Returns its height."""
        lh = BODY * 1.28
        lines = []
        for it in items:
            ws = wrap(it, w - 30, BODY)
            lines += [("• " + ws[0], True)] + [(s, False) for s in ws[1:]]
        h = 12 + HEAD * 1.3 + len(lines) * lh + 8
        self.rect(x, y, w, h, fill, dash)
        self.text(x + 9, y + 8 + HEAD, title, HEAD, 700)
        if tag:
            self.text(x + w - 8, y + 8 + HEAD, tag, 10.5, 400, "end", italic=True, fill=GREY)
        for i, (s, first) in enumerate(lines):
            self.text(x + (10 if first else 19), y + 14 + HEAD * 1.3 + (i + 0.75) * lh, s)
        return h

    def arrow(self, pts, dash=False, both=False):
        d = " ".join(f"{'M' if i == 0 else 'L'}{x} {y}" for i, (x, y) in enumerate(pts))
        ds = ' stroke-dasharray="5 4"' if dash else ""
        ms = ' marker-start="url(#a)"' if both else ""
        self.p.append(f'<path d="{d}" fill="none" stroke="{INK}" stroke-width="1.2"{ds}{ms} marker-end="url(#a)"/>')

    def step(self, x, y, n):
        self.p.append(f'<circle cx="{x}" cy="{y}" r="10" fill="{INK}"/>')
        self.text(x, y + 4, str(n), 11.5, 700, "middle", fill=WHITE)

    def header(self, title, sub, page):
        self.text(36, 40, title, 22, 700)
        self.text(36, 60, sub, 12.5, 400, italic=True, fill=GREY)
        self.text(W - 36, 40, "Team losers · RAKSHAM 2026 Finale · Track 1", 11.5, 400, "end")
        self.text(W - 36, 58, "github.com/dope-XD/countersign", 11.5, 400, "end", fill=GREY)
        self.p.append(f'<path d="M36 72 H{W - 36}" stroke="{INK}" stroke-width="1"/>')
        self.text(W - 36, H - 18, f"{page} / 2", 10.5, 400, "end", fill=GREY)

    def save(self, name):
        (OUT / name).write_text(
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">'
            f'<rect width="{W}" height="{H}" fill="#fff"/>' + "".join(self.p) + "</svg>\n"
        )


def numbers(pg: Page, y: int):
    stats = [
        ("2.3%", "of genuine bank calls warned", "ICFD-31k held out, n = 1,019; keyword baseline 50.1%"),
        ("87.8%", "of scam calls warned", "ICFD-31k test split, n = 4,499; 59.9% reach red"),
        ("75.8%", "of unseen scam types warned", "5 fraud types absent from training, n = 760"),
        ("28 / 30", "spot-check kit correct", "10 calls, 10 messages, 10 voices"),
        ("10 / 10", "fresh scams caught", "written after the system was frozen"),
    ]
    w = (W - 72 - 4 * 12) / 5
    for i, (big, what, src) in enumerate(stats):
        x = 36 + i * (w + 12)
        pg.rect(x, y, w, 70, WHITE)
        pg.text(x + 10, y + 25, big, 21, 700)
        pg.text(x + 10, y + 42, what, 11.6, 700)
        for j, line in enumerate(wrap(src, w - 20, 10.4)[:2]):
            pg.text(x + 10, y + 56 + j * 12, line, 10.4, 400, italic=True, fill=GREY)


# ------------------------------------------------------------------ page 1: how a call is judged
def page1():
    pg = Page()
    pg.header(
        "Countersign: catching impersonation scam calls on the phone",
        "How one call is judged. Everything on this page runs on the protected user's phone; nothing is sent.",
        1,
    )
    numbers(pg, 84)

    top = 182
    # column A: capture → segment → transcribe
    ax, aw = 36, 214
    pg.step(ax + 4, top - 4, 1)
    pg.text(ax + 20, top, "Hear the call", 15, 700)
    h1 = pg.box(ax, top + 12, aw, "Capture", ["Accessibility service keeps the mic during a call", "16 kHz mono, memory only, speakerphone"])
    y2 = top + 12 + h1 + 26
    h2 = pg.box(ax, y2, aw, "Segment: Silero VAD", ["Threshold 0.5; 0.4 s silence ends a segment", "Segments up to 12 s; audio dropped after use"])
    y3 = y2 + h2 + 26
    pg.box(
        ax,
        y3,
        aw,
        "Transcribe: Omnilingual ASR",
        ["Meta, 300M, CTC, int8, sherpa-onnx", "Chosen on our 59 calls: WER 28% vs 65% / 44% for IndicConformer Hindi / English"],
    )
    pg.arrow([(ax + aw / 2, top + 12 + h1), (ax + aw / 2, y2)])
    pg.arrow([(ax + aw / 2, y2 + h2), (ax + aw / 2, y3)])

    # column B: four kinds of evidence
    bx, bw = 290, 372
    pg.step(bx + 4, top - 4, 2)
    pg.text(bx + 20, top, "Collect evidence", 15, 700)
    y = top + 12
    hj1 = pg.box(
        bx,
        y,
        bw,
        "Judge 1: conversation model",
        [
            "multilingual-e5-small (118M) fine-tuned by us; mean pooling + logistic head",
            "Trained on 267,601 windows: ICFD-31k (synthetic bank calls, EN + Hinglish) and our sets ×8",
            "Reads the last 320 tokens of the call; fp32 ONNX, 470 MB (int8 drifted by 0.20)",
            "s = mean of the last two scores; amber at s ≥ 0.142, red at s ≥ 0.9855 twice",
            "Thresholds set on 1,788 genuine dev calls at 3% and 0.5% false positives",
        ],
        tag="what the caller is doing",
    )
    j1y = y
    y += hj1 + 12
    hj2 = pg.box(
        bx,
        y,
        bw,
        "Judge 2: cue rules + move matcher",
        [
            "19 categories in English, Hinglish, Hindi; negation-aware (“we never ask for OTP”)",
            "Amber: 2 strong categories; red: 4 incl. an action and a scam type",
            "Talk about scams never counts towards red",
            "17 written scam moves matched by e5 embeddings give the reason shown",
        ],
        tag="what was said, and why",
    )
    j2y = y
    y += hj2 + 12
    hc = pg.box(
        bx,
        y,
        bw,
        "Phone signals",
        [
            "Unknown or foreign number; AnyDesk / TeamViewer or a payment app opened; call over 15 min",
            "Caller check failed; the user reading out 4–8 digits on an unknown call",
        ],
    )
    cy = y
    y += hc + 12
    pg.box(
        bx,
        y,
        bw,
        "Voice-clone check",
        [
            "First 6 layers of AntiDeepfake wav2vec + our head, int8, 127 MB; first 20 s",
            "Equal error rate 23–35% on phone audio, so it can lift to amber, never to red",
        ],
    )
    vy = y

    # arrows from ASR into the judges, from capture into the voice check
    pg.arrow([(ax + aw, y3 + 30), (268, y3 + 30), (268, j1y + 40), (bx, j1y + 40)])
    pg.arrow([(268, j2y + 40), (bx, j2y + 40)])
    pg.arrow([(ax + aw, top + 50), (258, top + 50), (258, vy + 30), (bx, vy + 30)], dash=True)

    # column C: combine
    cx, cw = 700, 186
    pg.step(cx + 4, top - 4, 3)
    pg.text(cx + 20, top, "Decide", 15, 700)
    comb_y = top + 150
    hcomb = pg.box(
        cx,
        comb_y,
        cw,
        "Combiner",
        [
            "Amber = the higher judge",
            "Cue words alone need Judge 1 at watch or above",
            "Red needs two independent sources: both judges, a judge plus a strong phone signal, the user, or the server",
            "The level never goes down in a call",
        ],
        fill=DARK,
    )
    for yy in (j1y + 60, j2y + 50, cy + 30, vy + 30):
        pg.arrow([(bx + bw, yy), (cx - 14, yy), (cx - 14, comb_y + hcomb / 2), (cx, comb_y + hcomb / 2)])

    # column D: outcomes
    dx, dw = 924, 163
    pg.step(dx + 4, top - 4, 4)
    pg.text(dx + 20, top, "Act", 15, 700)
    o1 = pg.box(dx, top + 12, dw, "Amber card", ["Names the scam and the reason", "“Alert family”, “I know this caller”"], fill=WHITE)
    o2y = top + 12 + o1 + 14
    o2 = pg.box(
        dx,
        o2y,
        dw,
        "Second opinion",
        ["Optional server after amber: ASR 1B, same model, 24-layer voice model", "Audio in memory; can only raise"],
        fill=WHITE,
        dash=True,
    )
    o3y = o2y + o2 + 14
    pg.box(dx, o3y, dw, "Red", ["“This is likely a scam. Hang up.”", "Family alarm (page 2)"], fill=WHITE)
    mid = comb_y + hcomb / 2
    for oy in (top + 40, o2y + 30, o3y + 30):
        pg.arrow([(cx + cw, mid), (905, mid), (905, oy), (dx, oy)])

    pg.text(
        36,
        H - 18,
        "Kotlin on the phone and Python on the server give identical verdicts on shared test vectors, checked in CI. "
        "One 798 MB model download; detection then works offline.",
        10.6,
        400,
        italic=True,
        fill=GREY,
    )
    pg.save("page1.svg")


# ------------------------------------------------------------------ page 2: response, privacy, results
def page2():
    pg = Page()
    pg.header(
        "After the verdict: the family, privacy, and how well it works",
        "The response path, what data goes where, and results on data the model never trained on.",
        2,
    )

    top = 96
    # left: the response flow
    lx, lw = 36, 250
    pg.step(lx + 4, top - 4, 5)
    pg.text(lx + 20, top, "Reach the family at red", 15, 700)
    a = pg.box(lx, top + 12, lw, "Scam alert to the relay", ["Once per call; call id, level, scam type, cue ids", "No words, no audio, no numbers"])
    b_y = top + 12 + a + 22
    b = pg.box(
        lx,
        b_y,
        lw,
        "Family member's app online?",
        [
            "Yes: full-screen alarm over the lock screen, alarm tone at full volume",
            "“Mummy may be on a scam call”, Call / Message",
            "No: SMS from the user's own SIM",
        ],
        fill=DARK,
    )
    c_y = b_y + b + 22
    pg.box(
        lx, c_y, lw, "Acknowledged within 60 s?", ["Yes: escalation stops", "No: text every member and call the first one from the user's phone"], fill=DARK
    )
    pg.arrow([(lx + lw / 2, top + 12 + a), (lx + lw / 2, b_y)])
    pg.arrow([(lx + lw / 2, b_y + b), (lx + lw / 2, c_y)])

    mx, mw = 312, 250
    pg.step(mx + 4, top - 4, 6)
    pg.text(mx + 20, top, "Is it really Rahul?", 15, 700)
    d = pg.box(
        mx,
        top + 12,
        mw,
        "Caller check (no audio)",
        [
            "Each family phone reports its own calls (member ids, never numbers)",
            "The relay looks for Rahul's outgoing call from 45 s before to 5 s after the ring; waits 6 s",
        ],
    )
    e_y = top + 12 + d + 22
    e = pg.box(
        mx,
        e_y,
        mw,
        "Verdict on the card",
        [
            "Rahul's phone called: ✓ verified",
            "No call, his app seen in 2 min: ✗ “Not Rahul's phone”",
            "App unseen: “Couldn't check”, never a false ✗",
            "A cloned voice or spoofed number fails: Rahul's phone never placed the call",
        ],
        fill=DARK,
    )
    pg.arrow([(mx + mw / 2, top + 12 + d), (mx + mw / 2, e_y)])
    f_y = e_y + e + 22
    pg.box(
        mx,
        f_y,
        mw,
        "A false alarm costs two taps",
        [
            "“I know this caller” or “It's not a scam”, then “Yes, it's fine”",
            "Warnings stop; Rahul sees “False alarm”; one ids-only record for review",
        ],
        fill=WHITE,
    )

    # right: privacy and results
    rx, rw = 600, W - 36 - 600
    pg.step(rx + 4, top - 4, 7)
    pg.text(rx + 20, top, "Privacy by construction", 15, 700)
    rows = [
        ("Call audio", "phone memory, dropped per segment; server only after amber, in memory"),
        ("Evidence", "one 20 s AES-256 clip for a confirmed scam, deleted after 30 days"),
        ("Transcript", "phone memory for the call; never stored or sent"),
        ("Numbers", "on the phone only, matched to member ids by the last 10 digits"),
        ("Relay", "member ids, check verdicts, level, scam type, cue ids"),
    ]
    y = top + 14
    for k, v in rows:
        pg.rect(rx, y, rw, 22, WHITE)
        pg.text(rx + 8, y + 15.5, k, BODY, 700)
        pg.text(rx + 92, y + 15.5, v)
        y += 22

    y += 26
    pg.step(rx + 4, y - 4, 8)
    pg.text(rx + 20, y, "Measured on data it never trained on (warned / red, %)", 15, 700)
    y += 10
    cols = [rx + 8, rx + 230, rx + 300, rx + 390]
    table = [
        ("Set", "n", "Countersign", "Keyword baseline"),
        ("ICFD genuine, clear", "1,019", "2.3 / 0.4", "50.1 / 8.9"),
        ("ICFD genuine, ambiguous", "511", "4.5 / 0.8", "70.8 / 15.5"),
        ("ICFD scam, test split", "4,499", "87.8 / 59.9", "94.3 / 51.5"),
        ("ICFD unseen types, clear", "760", "75.8 / 42.9", "90.9 / 34.7"),
        ("ICFD unseen types, subtle", "240", "54.6 / 17.5", "78.3 / 22.5"),
        ("Our team's scam calls", "16", "93.8", "–"),
        ("Adversarial rewrites (scam / genuine)", "16 / 14", "75.0 / 21.4", "–"),
    ]
    for i, row in enumerate(table):
        yy = y + 18 + i * 19
        if i == 0:
            pg.p.append(f'<path d="M{rx} {yy - 14} H{rx + rw}" stroke="{INK}" stroke-width="1.2"/>')
        for x, cell in zip(cols, row, strict=True):
            pg.text(x, yy, cell, BODY, 700 if i == 0 else 400)
        if i in (0, len(table) - 1):
            pg.p.append(f'<path d="M{rx} {yy + 6} H{rx + rw}" stroke="{INK}" stroke-width="{1.2 if i else 0.7}"/>')
    y += 18 + len(table) * 19 + 4
    pg.text(
        rx,
        y,
        "Median time to amber 36–45 s. The keyword baseline flags more scams only because it flags most genuine calls too.",
        10.6,
        400,
        italic=True,
        fill=GREY,
    )

    y += 26
    pg.step(rx + 4, y - 4, 9)
    pg.text(rx + 20, y, "Known limits, and what's next", 15, 700)
    half = (rw - 12) / 2
    pg.box(
        rx,
        y + 12,
        half,
        "Weak today",
        [
            "Polite, scripted English scams",
            "People talking about a scam",
            "Genuine calls in a computer voice reach amber",
            "Earpiece: the caller is barely heard; needs speaker",
            "ICFD-31k is synthetic: needs a pilot on real calls",
        ],
        fill=WHITE,
    )
    pg.box(
        rx + half + 12,
        y + 12,
        half,
        "Next",
        [
            "Full-screen stop over payment apps (designed; the card warns today)",
            "On-phone language model as a third judge (prompt written and tested)",
            "Bank pilot: the call-centre version already runs on our server",
        ],
        fill=WHITE,
    )
    pg.save("page2.svg")


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    page1()
    page2()
    print("wrote", ", ".join(p.name for p in sorted(OUT.glob("*.svg"))))
