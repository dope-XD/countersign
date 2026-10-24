"""Training data for the conversation model: "has the caller made a scam move yet?", judged on the call so far.

    python -m ml.conv_data          # data/conv/{train,dev}.parquet + data/conv/test_*.parquet

The main source is ICFD-31k (Ahuja et al., IJCAI 2026; huggingface.co/datasets/rishia2220/icfd-31k; released for
defensive research and education): 31k synthetic Indian bank-call conversations in English and Hinglish. Every 3 s it
gives the conversation so far and a verdict that turns YES at the first real policy violation (a request that breaches
security), with genuine calls ("Clear Normal", "Ambiguous but Ultimately Normal") as negatives. We add our own sets
(ml/listener_data.py: Hinglish call lines, BothBosu dialogues, Indian SMS, our hard-negative template calls) as
prefixes of the call.

Text is made the way the phone makes it: speaker names dropped (the phone can't tell who is talking), every turn
normalised (engine/listener/rules.normalize) but kept in its own script: e5 reads Devanagari Hindi natively, while
our rough Latin folding ("pulis", "fon") made Hindi transcripts unreadable to it. Turns joined with " | ", and only the
last ~1,200 characters kept. ICFD's validation and test splits hold only fraud calls, so 10% of its train
conversations (by id) go to dev and another 10% to a held-out test with genuine calls. ICFD's test, unseen-type and
held-out parts, and every held-out set of ml/listener_data.py, are never in train or dev.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path

import pandas as pd

from engine.listener.rules import normalize
from ml import listener_data
from ml.listener_clf import typos

ROOT = Path(__file__).resolve().parent.parent
ICFD = ROOT / "data" / "datasets" / "icfd" / "streaming_chunks"
HOLDOUT = 10  # ICFD's validation and test splits are fraud-only, so genuine calls are held out of its train split: 10% dev, 10% test
OUT = ROOT / "data" / "conv"
MAX_CHARS = 1200
SEP = " | "
SEED = 3


def turn_text(t: str) -> str:
    return " ".join(normalize(t))


def window(turns: list[str]) -> str:
    """The last MAX_CHARS characters of the call so far, cut at a turn boundary where possible."""
    s = SEP.join(x for x in (turn_text(t) for t in turns) if x)
    if len(s) <= MAX_CHARS:
        return s
    cut = s[-MAX_CHARS:]
    i = cut.find(SEP)
    return cut[i + len(SEP) :] if 0 <= i < 200 else cut


def icfd_turns(row) -> list[str]:
    try:
        return [t["text"] for t in json.loads(row["cumulative_transcript_json"])]
    except Exception:
        return [re.sub(r"^\w+:\s*", "", ln) for ln in str(row["cumulative_text"]).split("\n") if ln.strip()]


def part(uid: str) -> str:
    """Which part of ICFD's train split a conversation belongs to, fixed by its id: train, dev or test."""
    h = int(hashlib.sha256(uid.encode()).hexdigest(), 16) % 100
    return "dev" if h < HOLDOUT else "test" if h < 2 * HOLDOUT else "train"


def load_icfd(split: str, every: int, keep: str | None = None) -> pd.DataFrame:
    files = sorted(ICFD.glob(f"{split}-*.parquet"))
    cols = ["conversation_uid", "chunk_timestamp", "final_verdict", "cumulative_text", "cumulative_transcript_json", "case_type", "domain"]
    df = pd.concat([pd.read_parquet(f, columns=cols) for f in files], ignore_index=True)
    if keep:
        df = df[df["conversation_uid"].map(part) == keep]
    df["t"] = pd.to_numeric(df["chunk_timestamp"], errors="coerce").fillna(0).astype(int)
    df = df.sort_values(["conversation_uid", "t"])
    # every n-th chunk per call, and always the last one (the full call)
    df["k"] = df.groupby("conversation_uid").cumcount()
    last = df.groupby("conversation_uid")["k"].transform("max")
    df = df[(df["k"] % every == 0) | (df["k"] == last)]
    rows = [
        {"text": window(icfd_turns(r)), "label": int(r["final_verdict"] == "YES"), "source": "icfd", "group": r["conversation_uid"], "case_type": r["case_type"], "domain": r["domain"], "t": int(r["t"])}
        for _, r in df.iterrows()
    ]  # fmt: skip
    out = pd.DataFrame(rows)
    return out[out["text"].str.len() > 0]


def dialogue_turns(text: str) -> list[str]:
    parts = re.split(r"\b(?:caller|receiver|suspect|innocent|agent|customer)\s*:", text, flags=re.I)
    return [p.strip() for p in parts if p.strip()] or [text]


def ours(split: str) -> pd.DataFrame:
    """Our sets as calls in progress: the whole call, and (for multi-turn calls) the first two thirds of it."""
    rows = []
    for r in listener_data.load():
        if r["split"] != split or r["source"] in ("team_calls", "adversarial"):
            continue
        ts = dialogue_turns(r["text"])
        cuts = [len(ts)] + ([max(1, 2 * len(ts) // 3)] if len(ts) >= 4 else [])
        for c in cuts:
            rows.append(
                {"text": window(ts[:c]), "label": r["label"], "source": r["source"], "group": r["id"], "case_type": r["type"], "domain": r["lang"], "t": c}
            )
    return pd.DataFrame(rows)


def ours_test() -> pd.DataFrame:
    """Every held-out set of ml/listener_data.py as calls in progress: every prefix, in order (for measuring only)."""
    team = {t["id"]: t["turns"] for t in json.loads(listener_data.TEAM.read_text(encoding="utf-8"))["transcripts"]}
    rows = []
    for r in listener_data.load():
        if r["split"] not in ("test", "test_other_lang"):
            continue
        ts = team[r["id"].split("/", 1)[1]] if r["source"] == "team_calls" else dialogue_turns(r["text"])
        src = r["source"] if r["split"] == "test" else f"{r['source']}_other_lang"
        for c in range(1, len(ts) + 1):
            rows.append({"text": window(ts[:c]), "label": r["label"], "source": src, "group": r["id"], "case_type": r["type"], "domain": r["lang"], "t": c})
    return pd.DataFrame(rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    train = pd.concat([load_icfd("train", every=2, keep="train"), ours("train")], ignore_index=True)
    # recognition-style typos on 30% of training rows (the phone's speech-to-text is not perfect)
    noisy = train.sample(frac=0.3, random_state=SEED).copy()
    noisy["text"] = [typos(t, rng) for t in noisy["text"]]
    noisy["source"] = noisy["source"] + "+typos"
    train = pd.concat([train, noisy], ignore_index=True).sample(frac=1.0, random_state=SEED)
    dev = pd.concat([load_icfd("validation", every=3), load_icfd("train", every=3, keep="dev"), ours("dev")], ignore_index=True)
    train.to_parquet(OUT / "train.parquet")
    dev.to_parquet(OUT / "dev.parquet")
    load_icfd("test", every=1).to_parquet(OUT / "test_icfd.parquet")
    load_icfd("cross_domain", every=1).to_parquet(OUT / "test_icfd_unseen.parquet")
    ours_test().to_parquet(OUT / "test_ours.parquet")
    load_icfd("train", every=1, keep="test").to_parquet(OUT / "test_icfd_heldout.parquet")  # the only ICFD test with genuine calls
    for name, d in (("train", train), ("dev", dev)):
        print(name, len(d), d.groupby("source")["label"].agg(["count", "mean"]).round(3).to_dict("index"))


if __name__ == "__main__":
    main()
