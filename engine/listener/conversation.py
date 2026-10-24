"""The conversation check: what the phone runs on a call, in Python (port of record for data/listen/Conversation.kt).

    python -m engine.listener.conversation           # assets/e5_vocab.txt
    python -m engine.listener.conversation vectors   # test/resources/conv_vectors.json (needs the models)

    recognised segment ─► call so far (last ~1,200 characters, one script) ─► conversation model ─► p
                     └─► scam-move matcher (base e5) ─► the move it makes, for "why"
    p over segments + context + voice ─► Accumulator ─► none / watch / warn / scam, with plain-words reasons

The conversation model (ml/conv_model.py) is multilingual-e5-small fine-tuned on ICFD-31k and our sets to answer "has
the caller made a scam move yet?" for the call so far. It decides; the move matcher only names what was said
(ml/moves.py), so the "why" is the move that made the risk rise, never a word list. Thresholds (conv.json) are set on
dev calls only, at a fixed share of genuine calls (ml/conv_calibrate.py).

The tokenizer is our own SentencePiece-unigram Viterbi over the e5 vocabulary (NFKC, then Metaspace), so the phone and
the laptop give the same token ids as Hugging Face (engine/tests/test_conversation.py checks it on held-out text; our
text is mostly lowercase Latin after folding, where the two agree exactly).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

import numpy as np

from engine.listener.rules import ASSETS, normalize, rules, scam_type

ROOT = Path(__file__).resolve().parents[2]
MODELS = ROOT / "models"
PREFIX = "query: "
MAX_CHARS = 1200
SEP = " | "
LEVELS = ["none", "watch", "warn", "scam"]


# ---------------------------------------------------------------------------------------------------- tokenizer
class Tokenizer:
    """multilingual-e5-small's tokenizer for our text: Metaspace + unigram Viterbi; <s> … </s>; keeps the newest tokens."""

    BOS, EOS, UNK = 0, 2, 3

    def __init__(self, path: Path = ASSETS / "e5_vocab.txt"):
        self.piece: dict[str, tuple[int, float]] = {}
        for ln in path.read_text(encoding="utf-8").split("\n")[:-1]:
            i, p, s = ln.split("\t")
            self.piece[p] = (int(i), float(s))
        self.longest = max(len(p) for p in self.piece)
        self.unk_score = min(s for _, s in self.piece.values()) - 10.0

    def word(self, w: str) -> list[int]:
        n = len(w)
        best = [-1e18] * (n + 1)
        back: list[tuple[int, int]] = [(0, -1)] * (n + 1)
        best[0] = 0.0
        for i in range(n):
            if best[i] <= -1e18:
                continue
            hit = False
            for j in range(i + 1, min(n, i + self.longest) + 1):
                e = self.piece.get(w[i:j])
                if e is None:
                    continue
                if j == i + 1:
                    hit = True
                s = best[i] + e[1]
                if s > best[j]:
                    best[j], back[j] = s, (i, e[0])
            if not hit:  # a character outside the vocabulary: one unknown token
                s = best[i] + self.unk_score
                if s > best[i + 1]:
                    best[i + 1], back[i + 1] = s, (i, self.UNK)
        out, j = [], n
        while j > 0:
            i, t = back[j]
            out.append(t)
            j = i
        return out[::-1]

    def encode(self, text: str, max_len: int = 320) -> list[int]:
        ids: list[int] = []
        # as e5's normalizer and Metaspace: NFKC, runs of spaces → one, every space → ▁, a ▁ in front, cut before each ▁
        s = "▁" + re.sub(" {2,}", " ", unicodedata.normalize("NFKC", text)).replace(" ", "▁")
        for w in re.findall("▁[^▁]*", s):
            ids.extend(self.word(w))
        ids = ids[-(max_len - 2) :]  # left truncation: the newest words are never cut
        return [self.BOS, *ids, self.EOS]


def write_vocab() -> None:
    """assets/e5_vocab.txt: every e5 piece with its id and score (special tokens and pieces with tabs or newlines left out)."""
    t = json.loads((MODELS / "hf" / "multilingual-e5-small" / "tokenizer.json").read_text(encoding="utf-8"))
    lines = [f"{i}\t{p}\t{s!r}" for i, (p, s) in enumerate(t["model"]["vocab"]) if i > 3 and not set(p) & set("\t\n\r")]
    (ASSETS / "e5_vocab.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {len(lines)} pieces")


@cache
def tokenizer() -> Tokenizer:
    return Tokenizer()


# ---------------------------------------------------------------------------------------------------- text
def segment_text(t: str) -> str:
    return " ".join(normalize(t))  # kept in its own script: e5 reads Devanagari Hindi natively


def window(segments: list[str]) -> str:
    """Same as ml.conv_data.window: the last MAX_CHARS characters of the call so far, cut at a segment boundary."""
    s = SEP.join(x for x in (segment_text(t) for t in segments) if x)
    if len(s) <= MAX_CHARS:
        return s
    cut = s[-MAX_CHARS:]
    i = cut.find(SEP)
    return cut[i + len(SEP) :] if 0 <= i < 200 else cut


# ---------------------------------------------------------------------------------------------------- models
class Encoder:
    """An e5 ONNX model: (input_ids, attention_mask) → p_scam (the conversation model) or an embedding (the matcher)."""

    def __init__(self, path: Path):
        import onnxruntime as ort

        so = ort.SessionOptions()
        so.intra_op_num_threads = 2
        self.s = ort.InferenceSession(str(path), so, providers=["CPUExecutionProvider"])
        self.out = self.s.get_outputs()[0].name

    def run(self, text: str, max_len: int = 320) -> np.ndarray:
        ids = np.array([tokenizer().encode(PREFIX + text, max_len)], dtype=np.int64)
        return self.s.run(None, {"input_ids": ids, "attention_mask": np.ones_like(ids)})[0][0]


@cache
def conv_model() -> Encoder:
    return Encoder(MODELS / "conv_model" / "conv.fp32.onnx")


@cache
def base_model() -> Encoder:
    return Encoder(MODELS / "conv_model" / "e5base.int8.onnx")


@dataclass(frozen=True)
class Move:
    id: str
    group: str
    category: str | None
    similarity: float


class Matcher:
    def __init__(self, path: Path = ASSETS / "moves.json"):
        d = json.loads(path.read_text(encoding="utf-8"))
        self.centre = np.array(d["centre"], dtype=np.float64)
        self.moves = d["moves"]
        self.index = {m["id"]: k for k, m in enumerate(self.moves)}
        self.vecs = np.array([x["vec"] for x in d["descriptions"]], dtype=np.float64)
        self.owner = np.array([self.index[x["move"]] for x in d["descriptions"]])

    def match(self, embedding: np.ndarray, guess: bool = False) -> Move | None:
        """The move this segment makes if it clears that move's threshold; with `guess`, the closest unsafe move anyway."""
        v = np.nan_to_num(np.asarray(embedding, dtype=np.float64)) - self.centre
        v = v / max(float(np.linalg.norm(v)), 1e-9)
        sims = np.einsum("ij,j->i", self.vecs, v)  # not @: numpy 2.2 on macOS raises false overflow warnings there
        best = np.full(len(self.moves), -2.0, dtype=np.float32)
        np.maximum.at(best, self.owner, sims)
        k = int(best.argmax())
        m = self.moves[k]
        if best[k] >= m["threshold"]:
            return Move(m["id"], m["group"], m["category"], float(best[k]))
        if not guess:
            return None
        unsafe = [i for i, x in enumerate(self.moves) if x["category"]]
        k = max(unsafe, key=lambda i: best[i])
        return Move(self.moves[k]["id"], self.moves[k]["group"], self.moves[k]["category"], float(best[k]))


@cache
def matcher() -> Matcher:
    return Matcher()


@cache
def config(path: Path = ASSETS / "conv.json") -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------------- the call
def higher(a: str, b: str) -> str:
    return a if LEVELS.index(a) >= LEVELS.index(b) else b


@dataclass
class Accumulator:
    """p for each segment → the call's level. Levels never go down.

    watch / warn: the mean p of the last `smooth` segments reaches t_watch / t_warn (one odd segment is not enough);
    scam: p ≥ t_scam on `scam_run` segments in a row. A known contact or a verified caller uses the stricter
    `trusted` thresholds. Context the phone saw counts as separate evidence: a failed caller check or a remote-control
    app opening reaches warn alone, and makes scam with the conversation at warn. The voice-clone check is one piece
    of evidence only: it lifts watch to warn, never makes scam.
    """

    cfg: dict = field(default_factory=config)
    ps: list[float] = field(default_factory=list)
    model_level: str = "none"
    level: str = "none"

    def feed(self, p: float, context: set[str] | frozenset[str] = frozenset()) -> str:
        self.ps.append(float(p))
        c = self.cfg
        th = c["trusted"] if set(context) & set(c["trusted_context"]) else c
        recent = self.ps[-c["smooth"] :]
        s = sum(recent) / len(recent)
        run = self.ps[-c["scam_run"] :]
        lvl = "none"
        if s >= th["t_watch"]:
            lvl = "watch"
        if s >= th["t_warn"]:
            lvl = "warn"
        if len(run) == c["scam_run"] and min(run) >= th["t_scam"]:
            lvl = "scam"
        self.model_level = higher(self.model_level, lvl)
        return self.judge(context)

    def judge(self, context: set[str] | frozenset[str] = frozenset()) -> str:
        c, ctx = self.cfg, set(context)
        lvl = self.model_level
        if ctx & set(c["warn_context"]):
            lvl = higher(lvl, "warn")
        if "synthetic_voice" in ctx and lvl == "watch":
            lvl = "warn"
        if ctx & set(c["scam_context"]) and LEVELS.index(self.model_level) >= LEVELS.index("warn"):
            lvl = "scam"  # two independent kinds of evidence: what was said, and what the phone saw
        self.level = higher(self.level, lvl)
        return self.level


@dataclass(frozen=True)
class CallState:
    level: str
    type: str
    p: float | None
    reasons: list[str]
    sources: list[str]


@dataclass
class Call:
    """Feed recognised segments one by one (the twin of Conversation.Call on the phone)."""

    p_of: object = None  # text → p (default: the conversation model, fp32 ONNX)
    embed: object = None  # text → embedding (default: the int8 base e5)
    segments: list[str] = field(default_factory=list)
    acc: Accumulator = field(default_factory=Accumulator)
    reasons: list[str] = field(default_factory=list)
    context: set[str] = field(default_factory=set)
    last_p: float | None = None

    def feed(self, segment: str) -> CallState:
        if segment_text(segment):
            self.segments.append(segment)
            p = float(self.p_of(window(self.segments)) if self.p_of else conv_model().run(window(self.segments)))
            rise = p - (self.last_p if self.last_p is not None else 0.0)
            self.last_p = p
            before = self.acc.model_level
            self.acc.feed(p, self.context)
            # name the move only when this segment made the risk rise (or the level went up); once the model has
            # reached amber with no reason named yet, its closest move is named even below the matcher's threshold
            warned = LEVELS.index(self.acc.model_level) >= LEVELS.index("warn")
            if rise >= self.acc.cfg["why_rise"] or self.acc.model_level != before or (warned and not self.reasons):
                t = segment_text(segment)
                v = self.embed(t) if self.embed else base_model().run(t, 64)
                m = matcher().match(np.asarray(v, dtype=np.float32), guess=warned and not self.reasons)
                if m and m.category and m.category not in self.reasons:
                    self.reasons.append(m.category)
        return self.state()

    def set_context(self, context: set[str]) -> CallState:
        self.context = set(context)
        self.acc.judge(self.context)
        return self.state()

    def state(self) -> CallState:
        lvl = self.acc.judge(self.context)
        why = list(self.reasons) + sorted(c for c in self.context if c in self.acc.cfg["shown_context"])
        kind = scam_type(set(self.reasons), rules()) if lvl != "none" else "unknown"
        if kind == "unknown" and "caller_check_failed" in self.context and lvl != "none":
            kind = "impersonation"
        sources = []
        if self.acc.model_level != "none":
            sources.append("phone_ai")
        if self.context & set(self.acc.cfg["warn_context"]) | (self.context & set(self.acc.cfg["scam_context"])):
            sources.append("context")
        if "synthetic_voice" in self.context:
            sources.append("voice")
        return CallState(lvl, kind, self.last_p, why, sorted(set(sources)))


def text_segments(text: str, max_words: int = 20) -> list[str]:
    """A whole transcript or message → segments as speech-to-text gives them: sentence ends, then ≤ max_words words."""
    out = []
    for s in re.split(r"[.!?।\n|]+", text):
        w = s.split()
        out.extend(" ".join(w[i : i + max_words]) for i in range(0, len(w), max_words))
    return [x for x in out if x.strip()]


def analyze(segments: list[str], context: set[str] | frozenset[str] = frozenset(), **kw) -> CallState:
    c = Call(**kw)
    c.context = set(context)
    st = c.state()
    for s in segments:
        st = c.feed(s)
    return st


def analyze_text(text: str, context: set[str] | frozenset[str] = frozenset(), **kw) -> CallState:
    """ "Check a recording or message" (Analyzer.text on the phone): the segments as a call, then the whole text once more."""
    segs = text_segments(text)
    st = analyze(segs, context, **kw)
    p_of = kw.get("p_of") or conv_model().run
    whole = float(p_of(window(segs))) if segs else 0.0
    if whole >= config()["t_scam"] and st.level in ("warn",):
        st = CallState("scam", st.type, st.p, st.reasons, st.sources)
    return st


def write_vectors() -> None:
    """Shared vectors for ConversationTest.kt and engine/tests/test_conversation.py (tokenizer ids from Hugging Face;
    the calls use the real ONNX models, recorded, so the phone's logic is checked without running them)."""
    import random

    import pandas as pd
    from transformers import AutoTokenizer

    from ml import listener_data

    hf = AutoTokenizer.from_pretrained(MODELS / "hf" / "multilingual-e5-small")
    hf.truncation_side = "left"
    rng = random.Random(5)
    texts = pd.read_parquet(ROOT / "data" / "conv" / "test_ours.parquet").sample(150, random_state=5)["text"].tolist()
    texts += ["मैं SBI से बोल रहा हूँ", "உங்கள் OTP சொல்லுங்கள்", "ＡＢＣ　full width", "emoji 🙂 here", "", "a" * 900 + " | end of call"]
    tok = [{"text": PREFIX + t, "ids": hf(PREFIX + t, max_length=320, truncation=True)["input_ids"]} for t in texts]
    rows = [r for r in listener_data.load() if r["source"] in ("team_calls", "adversarial")]
    team = {t["id"]: t["turns"] for t in json.loads(listener_data.TEAM.read_text(encoding="utf-8"))["transcripts"]}
    calls = []
    for i, r in enumerate(rows):
        segs = team[r["id"].split("/", 1)[1]] if r["source"] == "team_calls" else text_segments(r["text"])
        ctx = [["remote_app_opened"], ["caller_check_failed"], ["known_contact"], ["synthetic_voice"]][i % 4] if i % 3 == 0 else []
        p, emb = {}, {}

        def p_of(w: str, p: dict = p) -> float:
            p[w] = float(conv_model().run(w))
            return p[w]

        def embed(t: str, emb: dict = emb) -> np.ndarray:
            emb[t] = [round(float(x), 6) for x in base_model().run(t, 64)]
            return np.array(emb[t], dtype=np.float32)

        st = analyze(segs, set(ctx), p_of=p_of, embed=embed)
        calls.append(
            {"id": r["id"], "segments": segs, "context": ctx, "p": p, "emb": emb, "level": st.level, "type": st.type, "cues": st.reasons, "sources": st.sources}
        )
    acc = []
    for _ in range(40):
        ps = [round(rng.random() ** rng.choice([0.3, 1, 3]), 4) for _ in range(rng.randint(1, 12))]
        ctx = rng.choice([[], [], ["known_contact"], ["synthetic_voice"], ["remote_app_opened"], ["caller_check_failed"]])
        a = Accumulator()
        acc.append({"ps": ps, "context": ctx, "levels": [a.feed(x, set(ctx)) for x in ps]})
    segs = [
        {"text": t, "segments": text_segments(t)}
        for t in ["Hello. Are you there? Main police se bol raha hoon\nAapka parcel", " ".join(["word"] * 45), "", "OTP | batao | jaldi"]
    ]
    out = {
        "tokenizer": tok,
        "calls": calls,
        "accumulator": acc,
        "text_segments": segs,
        "windows": [{"segments": c["segments"], "window": window(c["segments"])} for c in calls],
    }
    path = ASSETS.parents[1] / "test" / "resources" / "conv_vectors.json"
    path.write_text(json.dumps(out, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(tok)} tokenizer, {len(calls)} call, {len(acc)} accumulator vectors to {path}")


if __name__ == "__main__":
    import sys

    write_vectors() if sys.argv[1:] == ["vectors"] else write_vocab()
