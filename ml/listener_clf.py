"""Train our scam classifier (engine/listener/classifier.py) and fit its fusion thresholds, on train/dev only.

    python -m ml.listener_clf                 # train, export to the app's assets, fit fusion.json, write models/listener_clf.json
    python -m ml.listener_clf --exclude bothbosu --out data/runs/lodo   # leave one dataset out (ml.eval.run_all does this)

What it does:
  1. Rows from ml.listener_data (train split), plus two kinds of extra copies of each training text, so the model
     copes with the phone's speech-to-text: one with ~5% character typos (deletions, swaps, doubled letters) and,
     for long calls, the first 40 and 90 words (a call the classifier hears only the start of).
  2. Logistic regression on the hashed n-grams; C is picked on dev by log loss.
  3. fusion.json's classifier thresholds (warn/scam clf_p and how many cue categories each needs) are picked on dev:
     the most scams at warn with at most 5% of harmless dev texts at warn and at most 1% at scam.
  4. The test splits are never read here. ml.eval.run_all records the git hash of these files before it tests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import subprocess
import time
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss, roc_auc_score

from engine.listener import fusion as fusion_mod
from engine.listener.classifier import Classifier, vectorize
from engine.listener.rules import ASSETS, normalize, score_text
from ml import listener_data

ROOT = Path(__file__).resolve().parent.parent
DIM = 1 << 18
NGRAM = (2, 5)
MIN_WORDS_CALL = 25  # a live call: the classifier stays quiet until it has heard this many words
MIN_WORDS_TEXT = 5  # "Check a message": an SMS is short
REPORT = ROOT / "models" / "listener_clf.json"


def typos(text: str, rng: random.Random, rate: float = 0.05) -> str:
    out = []
    for ch in text:
        r = rng.random()
        if not ch.isalpha() or r > rate:
            out.append(ch)
        elif r < rate / 3:
            continue  # dropped
        elif r < 2 * rate / 3:
            out.append(ch + ch)  # doubled
        else:
            out.append(rng.choice("aeiouhnrst"))  # misheard
    return "".join(out)


def augment(rows: list[dict], seed: int) -> list[dict]:
    rng = random.Random(seed)
    out = list(rows)
    for r in rows:
        out.append(r | {"text": typos(r["text"], rng), "aug": "typos"})
        words = r["text"].split()
        for n in (40, 90):
            if len(words) > n * 1.5:
                out.append(r | {"text": " ".join(words[:n]), "aug": f"first{n}"})
    return out


def matrix(texts: list[str]) -> csr_matrix:
    data, ind, ptr = [], [], [0]
    for t in texts:
        v = vectorize(t, DIM, *NGRAM)
        ind.extend(v.keys())
        data.extend(v.values())
        ptr.append(len(ind))
    return csr_matrix((np.array(data, dtype=np.float32), np.array(ind, dtype=np.int32), np.array(ptr)), shape=(len(texts), DIM))


def git_hash() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return "unknown"


def train(rows: list[dict], seed: int = listener_data.SEED, exclude: str | None = None) -> tuple[Classifier, dict]:
    tr = [r for r in rows if r["split"] == "train" and r["source"] != exclude]
    dev = [r for r in rows if r["split"] == "dev" and r["source"] != exclude]
    tr_aug = augment(tr, seed)
    X, y = matrix([r["text"] for r in tr_aug]), np.array([r["label"] for r in tr_aug])
    Xd, yd = matrix([r["text"] for r in dev]), np.array([r["label"] for r in dev])
    best = None
    for C in (1.0, 4.0, 16.0, 64.0):
        m = LogisticRegression(C=C, class_weight="balanced", solver="liblinear", max_iter=2000, random_state=seed).fit(X, y)
        p = m.predict_proba(Xd)[:, 1]
        loss = log_loss(yd, p, labels=[0, 1])
        if best is None or loss < best[0]:
            best = (loss, C, m, p)
    loss, C, m, p = best
    w = m.coef_[0].astype(np.float32)
    meta = {
        "version": 1,
        "about": "Our scam classifier (engine/listener/classifier.py, data/listen/ScamClassifier.kt): hashed char 2-5 + word 1-2 grams, logistic regression. Trained by ml/listener_clf.py.",
        "dim": DIM,
        "ngram_min": NGRAM[0],
        "ngram_max": NGRAM[1],
        "bias": float(m.intercept_[0]),
        "min_words_call": MIN_WORDS_CALL,
        "min_words_text": MIN_WORDS_TEXT,
        "C": C,
        "trained_on": sorted({r["source"] for r in tr}),
        "train_rows": len(tr),
        "train_rows_with_copies": len(tr_aug),
        "seed": seed,
    }
    clf = Classifier(w, meta["bias"], DIM, NGRAM[0], NGRAM[1], meta)
    report = {"C": C, "dev_log_loss": round(loss, 4), "dev_auc": round(roc_auc_score(yd, p), 4), "dev_rows": len(dev)}
    return clf, report


def _fuse_with(cues, judge, f: dict, context) -> str:
    return fusion_mod.fuse(cues, set(context), judge=judge, cfg=f).level


def fit_fusion(rows: list[dict], clf: Classifier, exclude: str | None = None) -> tuple[dict, dict]:
    """Pick the classifier's fusion thresholds on dev. Everything else in fusion.json (the cue rules) stays as it is."""
    base = json.loads((ASSETS / "fusion.json").read_text(encoding="utf-8"))
    dev = [r for r in rows if r["split"] == "dev" and r["source"] != exclude]
    pre = [(r, score_text(r["text"]), clf.p_scam(r["text"]), len(normalize(r["text"]))) for r in dev]
    best = None
    grid = [
        (wp, wc, ve, sp, sc)
        for wp in (0.5, 0.6, 0.7, 0.8, 0.9)
        for wc in (0, 1)
        for ve in (0.0, 0.05, 0.1, 0.2, 0.3)
        for sp in (0.9, 0.95, 0.98)
        for sc in (1, 2, 3)
    ]
    for wp, wc, ve, sp, sc in grid:
        if sp < wp or ve >= wp:
            continue
        f = json.loads(json.dumps(base))
        f["warn"]["clf_p"], f["warn"]["clf_min_categories"], f["warn"]["clf_veto_below"] = wp, wc, ve
        f["scam"]["clf_p"], f["scam"]["clf_min_categories"] = sp, sc
        lv = []
        for r, cues, p, n in pre:
            j = fusion_mod.Judge(0.0, abstain=True) if n < MIN_WORDS_TEXT else fusion_mod.Judge(p)
            lv.append((r["label"], _fuse_with(cues, j, f, frozenset())))
        pos = [x for y, x in lv if y == 1]
        neg = [x for y, x in lv if y == 0]
        rec_w = sum(x in ("warn", "scam") for x in pos) / len(pos)
        rec_s = sum(x == "scam" for x in pos) / len(pos)
        fp_w = sum(x in ("warn", "scam") for x in neg) / len(neg)
        fp_s = sum(x == "scam" for x in neg) / len(neg)
        ok = fp_w <= 0.05 and fp_s <= 0.01
        key = (ok, rec_w if ok else -fp_w, rec_s, -fp_w, -wp)
        if best is None or key > best[0]:
            best = (key, f, {"warn_clf_p": wp, "warn_clf_min_categories": wc, "warn_clf_veto_below": ve, "scam_clf_p": sp, "scam_clf_min_categories": sc,
                                         "dev_recall_warn": round(rec_w, 4), "dev_recall_scam": round(rec_s, 4), "dev_fp_warn": round(fp_w, 4), "dev_fp_scam": round(fp_s, 4),
                                         "met_dev_budget": ok})  # fmt: skip
    return best[1], best[2]


def export(clf: Classifier, f: dict, folder: Path) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    clf.weights.astype("<f4").tofile(folder / "scam_clf.bin")
    clf.meta["sha256"] = hashlib.sha256((folder / "scam_clf.bin").read_bytes()).hexdigest()
    (folder / "scam_clf.json").write_text(json.dumps(clf.meta, indent=2) + "\n", encoding="utf-8")
    (folder / "fusion.json").write_text(json.dumps(f, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--exclude", help="leave this source out of train and dev")
    ap.add_argument("--out", type=Path, default=ASSETS)
    a = ap.parse_args()
    t0 = time.time()
    rows = listener_data.load()
    clf, rep = train(rows, exclude=a.exclude)
    f, frep = fit_fusion(rows, clf, exclude=a.exclude)
    export(clf, f, a.out)
    rep |= {"fusion": frep, "git": git_hash(), "seconds": round(time.time() - t0, 1), "exclude": a.exclude, "trained_on": clf.meta["trained_on"]}
    if a.out == ASSETS:
        REPORT.write_text(json.dumps(rep, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rep, indent=2))
    nz = int(np.count_nonzero(clf.weights))
    print(f"weights: {nz}/{DIM} non-zero, {math.ceil(DIM * 4 / 1024)} KB")


if __name__ == "__main__":
    main()
