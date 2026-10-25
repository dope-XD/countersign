"""Cue scoring: which scam cue categories a call's words have shown so far (scam_patterns.json).

    s = CallScorer()
    s.feed("this is inspector sharma from mumbai police")
    s.feed("there is an arrest warrant in your name")
    s.result()   # categories ['authority', 'threat'], type 'digital_arrest'

Port of record for data/listen/ScamScorer.kt: keep the two identical (the shared transcripts check it).
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT / "android" / "app" / "src" / "main" / "assets"
MAX_TOKENS = 6000  # about 40 minutes of speech; older words are dropped


def normalize(text: str) -> list[str]:
    """Lower case; apostrophes dropped; anything but letters, marks, digits and "_" becomes a space."""
    t = unicodedata.normalize("NFC", text).lower().replace("'", "").replace("’", "")
    out = []
    for ch in t:
        out.append(ch if ch == "_" or unicodedata.category(ch)[0] in "LMN" else " ")
    return "".join(out).split()


def _allowed_edits(word: str) -> int:
    return 2 if len(word) >= 9 else 1 if len(word) >= 5 else 0


def _lev(a: str, b: str, limit: int) -> int:
    """Levenshtein distance, giving up (limit + 1) once it must exceed limit."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        best = cur[0]
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            best = min(best, cur[j])
        if best > limit:
            return limit + 1
        prev = cur
    return prev[-1]


def word_matches(phrase_word: str, token: str) -> bool:
    if phrase_word == token:
        return True
    k = _allowed_edits(phrase_word)
    return k > 0 and _lev(phrase_word, token, k) <= k


@dataclass(frozen=True)
class Rules:
    categories: dict[str, list[list[str]]]  # category -> phrases as word lists
    weak: frozenset[str]
    action: frozenset[str]
    negatable: frozenset[str]
    negations: frozenset[str]
    neg_before: int
    neg_after: int
    neg_exceptions: frozenset[tuple[str, ...]]  # word pairs that aren't negations ("nahi to" = otherwise)
    types: list[dict]
    order: list[str]  # category order in the file
    max_phrase: int


@cache
def rules(path: Path = ASSETS / "scam_patterns.json") -> Rules:
    d = json.loads(path.read_text(encoding="utf-8"))
    cats, weak, action, neg = {}, set(), set(), set()
    for name, c in d["categories"].items():
        phrases = [normalize(p) for p in c["phrases"]]
        cats[name] = [p for p in phrases if p]
        if c.get("weak"):
            weak.add(name)
        if c.get("action"):
            action.add(name)
        if c.get("negatable"):
            neg.add(name)
    w = d["negation_window"]
    return Rules(
        categories=cats,
        weak=frozenset(weak),
        action=frozenset(action),
        negatable=frozenset(neg),
        negations=frozenset(t for n in d["negations"] for t in normalize(n)),
        neg_before=int(w["before"]),
        neg_after=int(w["after"]),
        neg_exceptions=frozenset(tuple(normalize(n)) for n in d["negation_exceptions"]),
        types=d["types"],
        order=list(d["categories"]),
        max_phrase=max(len(p) for ps in cats.values() for p in ps),
    )


def find(phrase: list[str], tokens: list[str], start: int, stop: int) -> list[tuple[int, int]]:
    """Spans (first, last token index) where `phrase` starts in tokens[start:stop]; one extra word allowed between phrase words."""
    spans = []
    for i in range(start, min(stop, len(tokens))):
        if not word_matches(phrase[0], tokens[i]):
            continue
        pos, ok = i, True
        for w in phrase[1:]:
            if pos + 1 < len(tokens) and word_matches(w, tokens[pos + 1]):
                pos += 1
            elif pos + 2 < len(tokens) and word_matches(w, tokens[pos + 2]):
                pos += 2
            else:
                ok = False
                break
        if ok:
            spans.append((i, pos))
    return spans


def negated(span: tuple[int, int], tokens: list[str], r: Rules) -> bool:
    lo, hi = span
    for k in [*range(max(0, lo - r.neg_before), lo), *range(hi + 1, min(len(tokens), hi + 1 + r.neg_after))]:
        if tokens[k] in r.negations and tuple(tokens[k : k + 2]) not in r.neg_exceptions:
            return True
    return False


@dataclass
class Result:
    categories: list[str]
    type: str
    evidence: dict[str, str] = field(default_factory=dict)  # category -> the phrase that matched (eval and debugging only)

    @property
    def discussion(self) -> bool:
        return "discussion" in self.categories


def scam_type(cats: set[str], r: Rules) -> str:
    best, best_score = "unknown", 0
    for t in r.types:
        if not set(t["all"]) <= cats:
            continue
        if t["any"] and not (set(t["any"]) & cats):
            continue
        score = len(t["all"]) + len(set(t["any"]) & cats) + len(set(t["plus"]) & cats) + t.get("bonus", 0)
        if score > best_score:
            best, best_score = t["type"], score
    return best


class CallScorer:
    """Feed it the call's words as they arrive; it keeps what it has found. Words that can still be
    negated by what comes next stay provisional until enough words follow them."""

    def __init__(self, r: Rules | None = None):
        self.r = r or rules()
        self.tokens: list[str] = []
        self.found: dict[str, str] = {}  # committed: category -> phrase
        self._scanned = 0  # phrase starts before this index are committed

    def feed(self, text: str) -> Result:
        self.tokens += normalize(text)
        if len(self.tokens) > MAX_TOKENS:
            cut = len(self.tokens) - MAX_TOKENS
            self.tokens = self.tokens[cut:]
            self._scanned = max(0, self._scanned - cut)
        # a start is final once a whole phrase plus the negation window fits after it
        final_upto = max(self._scanned, len(self.tokens) - self.r.max_phrase * 2 - self.r.neg_after)
        self._commit(self._scan(self._scanned, final_upto))
        self._scanned = final_upto
        return self.result()

    def _scan(self, start: int, stop: int) -> dict[str, str]:
        hits: dict[str, str] = {}
        for cat, phrases in self.r.categories.items():
            if cat in self.found or cat in hits:
                continue
            for p in phrases:
                if any(not (cat in self.r.negatable and negated(s, self.tokens, self.r)) for s in find(p, self.tokens, start, stop)):
                    hits[cat] = " ".join(p)
                    break
        return hits

    def _commit(self, hits: dict[str, str]) -> None:
        for k, v in hits.items():
            self.found.setdefault(k, v)

    def result(self) -> Result:
        """Committed categories plus provisional ones from the words not yet final."""
        both = {**self._scan(self._scanned, len(self.tokens)), **self.found}
        cats = [c for c in self.r.order if c in both]
        return Result(cats, scam_type(set(cats) - {"discussion"}, self.r), {c: both[c] for c in cats})


def score_text(text: str) -> Result:
    s = CallScorer()
    s.feed(text)
    return s.result()


# number words a person reads an OTP or card number out with: English, Hinglish, Hindi (exact words only, no fuzzy match)
DIGIT_WORDS = frozenset(
    "zero one two three four five six seven eight nine "
    "shunya sunya ek do teen tin char chaar paanch panch chhe che chheh saat sat aath ath nau "
    "शून्य एक दो तीन चार पांच पाँच छह छः छे सात आठ नौ".split()
)
DIGITS_READ_OUT = (4, 8)  # an OTP is 4 to 8 digits; a 10-digit phone number is not one
HELPLINES = frozenset({"1930", "100", "112", "1800", "1600", "181", "1098", "14422", "155260"})  # said, not read out


def digit_runs(tokens: list[str]) -> list[int]:
    """Lengths of the runs of digits read out in a row: '4 5 2 1', '4521', 'char paanch do ek' are each 4."""
    runs, n = [], 0
    for t in tokens:
        if t.isascii() and t.isdigit() and t not in HELPLINES:
            n += len(t)
        elif t in DIGIT_WORDS:
            n += 1
        else:
            if n:
                runs.append(n)
            n = 0
    if n:
        runs.append(n)
    return runs


def digits_read_out(tokens: list[str]) -> bool:
    """Someone read out 4 to 8 digits in a row (on an unknown call: likely an OTP or a card's digits)."""
    lo, hi = DIGITS_READ_OUT
    return any(lo <= n <= hi for n in digit_runs(tokens))
