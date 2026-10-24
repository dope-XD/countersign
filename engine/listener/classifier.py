"""Our scam classifier: hashed character and word n-grams → logistic regression → p_scam for a transcript or message.

    clf = classifier()
    clf.p_scam("inspector sharma bol raha hoon, aapke naam pe arrest warrant hai")   # 0.97
    clf.judge("...", min_words=25)   # fusion's Judge, abstaining under min_words

Port of record for data/listen/ScamClassifier.kt: keep the two identical (ScamClassifierTest checks
the shared vectors in android/app/src/test/resources/clf_vectors.json against this file).
Trained by ml/listener_clf.py; weights in assets/scam_clf.bin (float32, little-endian), settings in scam_clf.json.

Features, in this order, for every token of normalize(text) after fold() (Devanagari → rough Latin, so
"पुलिस" and "pulis" share n-grams):
  - character n-grams of " token " for n in [ngram_min, ngram_max] ("c" + gram),
  - the word itself ("w" + token) and each pair of neighbouring words ("b" + a + " " + b).
Each feature string is hashed with 32-bit FNV-1a over its UTF-8 bytes, modulo `dim`. A feature's value is
1 + ln(count); the vector is then scaled to unit length. p_scam = sigmoid(w · x + bias).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np

from engine.listener.fusion import Judge
from engine.listener.rules import ASSETS, normalize

# ---- Devanagari → Latin, roughly as Hinglish is typed ("खाता" → "khata", "पुलिस" → "pulis")
_CONS = dict(
    zip(
        "क ख ग घ ङ च छ ज झ ञ ट ठ ड ढ ण त थ द ध न प फ ब भ म य र ल व श ष स ह ळ".split(),
        "k kh g gh n ch chh j jh n t th d dh n t th d dh n p ph b bh m y r l v sh sh s h l".split(),
        strict=True,
    )
)
_VOWELS = dict(zip("अ आ इ ई उ ऊ ऋ ए ऐ ओ औ ऍ ऑ".split(), "a a i i u u ri e ai o au e o".split(), strict=True))
_MATRAS = dict(zip("ा ि ी ु ू ृ े ै ो ौ ॅ ॉ".split(), "a i i u u ri e ai o au e o".split(), strict=True))
_NASAL = {"ं": "n", "ँ": "n"}
_VIRAMA, _NUKTA, _VISARGA = "्", "़", "ः"
_NUKTA_CONS = {"क": "q", "ख": "kh", "ग": "g", "ज": "z", "ड": "d", "ढ": "dh", "फ": "f"}


def fold(token: str) -> str:
    """One token, Devanagari letters → Latin; everything else unchanged. Word-final inherent 'a' is dropped."""
    if not any("ऀ" <= ch <= "ॿ" for ch in token):
        return token
    out: list[str] = []
    pending_a = False  # the last consonant still carries its inherent 'a'
    chars = list(token)
    i = 0
    while i < len(chars):
        ch = chars[i]
        nxt = chars[i + 1] if i + 1 < len(chars) else ""
        if ch in _CONS:
            if pending_a:
                out.append("a")
            if nxt == _NUKTA:
                out.append(_NUKTA_CONS.get(ch, _CONS[ch]))
                i += 1
            else:
                out.append(_CONS[ch])
            pending_a = True
        elif ch in _MATRAS:
            out.append(_MATRAS[ch])
            pending_a = False
        elif ch == _VIRAMA:
            pending_a = False
        elif ch in _VOWELS:
            if pending_a:
                out.append("a")
            out.append(_VOWELS[ch])
            pending_a = False
        elif ch in _NASAL:
            if pending_a:
                out.append("a")
            out.append(_NASAL[ch])
            pending_a = False
        elif ch in (_NUKTA, _VISARGA):
            pass
        elif "०" <= ch <= "९":  # Devanagari digits
            if pending_a:
                out.append("a")
            out.append(str(ord(ch) - 0x966))
            pending_a = False
        else:
            if pending_a:
                out.append("a")
            out.append(ch)
            pending_a = False
        i += 1
    # a pending inherent 'a' at the end of the word is silent in Hindi ("pulis", not "pulisa")
    return "".join(out)


def fnv1a(s: str) -> int:
    h = 0x811C9DC5
    for b in s.encode("utf-8"):
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


def tokens(text: str) -> list[str]:
    return [fold(t) for t in normalize(text)]


def feature_strings(toks: list[str], nmin: int, nmax: int) -> list[str]:
    out = []
    for t in toks:
        w = f" {t} "
        for n in range(nmin, nmax + 1):
            out.extend("c" + w[i : i + n] for i in range(len(w) - n + 1))
        out.append("w" + t)
    out.extend(f"b{a} {b}" for a, b in zip(toks, toks[1:], strict=False))
    return out


def vectorize(text: str, dim: int, nmin: int, nmax: int) -> dict[int, float]:
    """Sparse feature vector: hashed index → value, unit length."""
    counts: dict[int, int] = {}
    for f in feature_strings(tokens(text), nmin, nmax):
        k = fnv1a(f) % dim
        counts[k] = counts.get(k, 0) + 1
    vec = {k: 1.0 + math.log(c) for k, c in counts.items()}
    norm = math.sqrt(sum(v * v for v in vec.values()))
    return {k: v / norm for k, v in vec.items()} if norm > 0 else {}


@dataclass
class Classifier:
    weights: np.ndarray  # float32[dim]
    bias: float
    dim: int
    ngram_min: int
    ngram_max: int
    meta: dict

    def logit(self, text: str) -> float:
        v = vectorize(text, self.dim, self.ngram_min, self.ngram_max)
        return self.bias + sum(float(self.weights[k]) * x for k, x in v.items())

    def p_scam(self, text: str) -> float:
        z = self.logit(text)
        return 1.0 / (1.0 + math.exp(-z)) if z > -500 else 0.0

    def judge(self, text: str, min_words: int | None = None) -> Judge:
        """Fusion's judge slot. Abstains while there are fewer than min_words words (default: scam_clf.json)."""
        need = self.meta["min_words_call"] if min_words is None else min_words
        if len(normalize(text)) < need:
            return Judge(0.0, abstain=True)
        return Judge(self.p_scam(text))

    @classmethod
    def load(cls, folder: Path = ASSETS, name: str = "scam_clf") -> Classifier:
        meta = json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))
        w = np.fromfile(folder / f"{name}.bin", dtype="<f4")
        assert len(w) == meta["dim"], "scam_clf.bin and scam_clf.json don't match"
        return cls(w, float(meta["bias"]), int(meta["dim"]), int(meta["ngram_min"]), int(meta["ngram_max"]), meta)


@cache
def classifier() -> Classifier:
    return Classifier.load()


VECTORS = ASSETS.parents[1] / "test" / "resources" / "clf_vectors.json"
_VECTOR_TEXTS = [
    "",
    "Hello, how are you?",
    "This is inspector Sharma from Mumbai police. Your Aadhaar is linked to a money laundering case. Do not tell anyone.",
    "मैं दिल्ली पुलिस से बोल रहा हूँ, आपका गिरफ़्तारी वारंट निकला है। किसी को मत बताइए।",
    "क्षमा कीजिए, ज़रा फ़ोन दीजिए। ऋषि को २५ रुपये दो।",
    "Madam मैं CBI से officer बोल रहा हूँ. आपके Aadhaar से parcel भेजा गया है",
    "Bhaiya Flipkart delivery, main darwaze pe hoon. OTP bata dijiye.",
    "naïve café — what's the OTP?? 4521!!",
    "aapke acount mein kyc pending hai aaj band ho jayega, otpi bata dijiye",
]


def write_vectors() -> None:
    """Shared vectors for ScamClassifierTest: tokens, a fold of each token, the hashed features and p_scam."""
    from ml import listener_data  # only for the vector texts; never needed at runtime

    clf = Classifier.load()
    extra = [r["text"] for r in listener_data.load() if r["source"] in ("adversarial", "team_calls")][:20]
    out = []
    for t in _VECTOR_TEXTS + extra:
        v = vectorize(t, clf.dim, clf.ngram_min, clf.ngram_max)
        out.append(
            {"text": t, "tokens": tokens(t), "features": {str(k): round(x, 9) for k, x in sorted(v.items())}, "logit": clf.logit(t), "p_scam": clf.p_scam(t)}
        )
    out.append({"fnv1a": {s: fnv1a(s) for s in ["", "a", "cpol", "w पुलिस", "b otp bata"]}})
    VECTORS.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {len(out)} vectors to {VECTORS}")


if __name__ == "__main__":
    write_vectors()
