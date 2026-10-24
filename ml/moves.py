"""The scam-move matcher: which move a caller just made, by meaning, for the plain-words "why" and for the red-card rule.

    python -m ml.moves          # embeds the descriptions, sets each move's threshold, writes assets/moves.json
    python -m ml.moves export   # the base e5 as int8 ONNX for the phone (models/conv_model/e5base.int8.onnx)

A scam is a sequence of moves aimed at the listener (PreScam 2026, SCRIPTMIND 2026): a pretext (the bank, the police,
your son), pressure (a threat, a deadline), isolation (tell no one, stay on the line) and the ask (transfer money,
read the OTP, install this app). Each move here has a few written descriptions in English and Hinglish. A segment of
the call is embedded with the base multilingual-e5-small (no fine-tuning, so meaning is kept) and compared by cosine
with every description; a move counts when its best similarity clears that move's threshold.

Each segment makes at most one move (its best match), and only if the similarity clears that move's threshold: the
99.5th percentile over turns of genuine calls held out of training. The calibration sentences below (never the
descriptions) check that each move is recognised; "we will never ask for your OTP" is `reassure`, not `ask_otp`.
The matcher explains and gates (red needs an "ask" move); it never raises a call's risk on its own.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from engine.listener.rules import ASSETS
from ml.conv_data import turn_text

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "models" / "hf" / "multilingual-e5-small"
PREFIX = "query: "

# group: pretext | pressure | isolation | ask | safe; CATEGORY: the app's reason id for each move (scam_patterns.json
# categories, already worded for users in English and Hindi), so the screens and the scam-type table are unchanged
CATEGORY = {
    "claims_bank": "verification_pretext", "claims_police": "authority", "claims_courier": "parcel_customs", "claims_family": "family_emergency",
    "claims_boss": "boss_pretext", "lure_reward": "reward", "lure_job": "job_task", "lure_invest": "investment", "threat_legal": "threat",
    "threat_account": "sim_block", "urgency": "urgency", "isolation": "secrecy", "ask_money": "money_ask", "ask_otp": "credentials",
    "ask_app": "remote_access", "ask_details": "credentials", "reassure": None,
}  # fmt: skip
MOVES: dict[str, dict] = {
    "claims_bank": {
        "group": "pretext",
        "say": [
            "I am calling from your bank's customer care",
            "this is the fraud department of your bank",
            "main SBI bank se bol raha hoon",
            "hum aapke bank ke head office se call kar rahe hain",
        ],
    },
    "claims_police": {
        "group": "pretext",
        "say": [
            "I am an officer from the police / CBI / cyber crime",
            "this is the customs or narcotics department",
            "main Mumbai police se inspector bol raha hoon",
            "CBI officer bol raha hoon, aapke khilaf case hai",
            "this is a call from the court / TRAI / income tax department",
        ],
    },
    "claims_courier": {
        "group": "pretext",
        "say": ["your parcel has been held by customs", "a courier booked in your name contains illegal items", "aapka parcel FedEx mein pakda gaya hai"],
    },
    "claims_family": {
        "group": "pretext",
        "say": [
            "your son has had an accident and is in hospital",
            "your relative is in trouble and needs money urgently",
            "main aapke bete ka dost bol raha hoon, woh mushkil mein hai",
        ],
    },
    "claims_boss": {
        "group": "pretext",
        "say": [
            "this is your boss / MD speaking, I am in a meeting",
            "I am the CEO, I need you to handle something confidential",
            "main director bol raha hoon, meeting mein hoon",
        ],
    },
    "lure_reward": {
        "group": "pretext",
        "say": [
            "you have won a lottery prize",
            "your refund or cashback is ready to be credited",
            "aapka loan pre-approved hai, bas processing fee dena hai",
            "aapne inaam jeeta hai, claim karne ke liye fee bhariye",
        ],
    },
    "lure_job": {
        "group": "pretext",
        "say": [
            "you can earn money from home by doing simple tasks",
            "like videos and rate hotels to earn daily income",
            "part time job hai, pehle registration fee deni hogi",
        ],
    },
    "lure_invest": {
        "group": "pretext",
        "say": ["guaranteed high returns on this investment", "join our stock trading group for sure profit", "crypto mein paisa lagao, double ho jayega"],
    },
    "threat_legal": {
        "group": "pressure",
        "say": [
            "an arrest warrant has been issued in your name",
            "you will be arrested / face legal action",
            "you are under digital arrest",
            "aapke naam par FIR darj hai, aapko giraftar kiya jayega",
        ],
    },
    "threat_account": {
        "group": "pressure",
        "say": [
            "your account will be blocked today",
            "your SIM card will be deactivated in two hours",
            "aapka account band ho jayega agar abhi update nahi kiya",
        ],
    },
    "urgency": {
        "group": "pressure",
        "say": [
            "you must do this immediately, there is no time",
            "do it in the next ten minutes or it will be too late",
            "jaldi kijiye, abhi ke abhi karna padega",
        ],
    },
    "isolation": {
        "group": "isolation",
        "say": [
            "do not tell anyone about this call",
            "stay on the line, do not disconnect",
            "keep this confidential, not even your family",
            "kisi ko mat batana, phone mat kaatna",
            "move to a video call on WhatsApp / Skype",
        ],
    },
    "ask_money": {
        "group": "ask",
        "say": [
            "transfer the money to this account",
            "pay the fee by UPI now",
            "send the amount to the safe RBI account for verification",
            "paise is account mein bhej dijiye",
            "buy gift cards and send me the codes",
        ],
    },
    "ask_otp": {
        "group": "ask",
        "say": [
            "tell me the OTP you just received",
            "share your UPI PIN / card PIN / password",
            "read out the code sent to your phone",
            "jo OTP aaya hai woh bata dijiye",
        ],
    },
    "ask_app": {
        "group": "ask",
        "say": [
            "install AnyDesk / TeamViewer on your phone",
            "download this app and share your screen",
            "open the link I sent and enter your details",
            "yeh app download karke code bataiye",
        ],
    },
    "ask_details": {
        "group": "ask",
        "say": [
            "tell me your Aadhaar number and date of birth",
            "confirm your card number, expiry and CVV",
            "share your bank account number and KYC details",
            "apna PAN aur Aadhaar number bataiye",
        ],
    },
    "reassure": {
        "group": "safe",
        "say": [
            "we will never ask for your OTP or PIN",
            "please do not share your OTP with anyone",
            "you can visit the branch or use the official app",
            "no payment is needed on this call",
            "hum kabhi OTP nahi maangte",
        ],
    },
}

# calibration: different sentences, one per line, for setting thresholds (never used as descriptions)
CALIBRATE: dict[str, list[str]] = {
    "claims_bank": ["hello sir I'm from HDFC bank credit card department", "madam ICICI bank se call hai aapke account ke baare mein"],
    "claims_police": ["this is sub inspector verma from delhi crime branch", "main CBI headquarters se officer bol raha hoon"],
    "claims_courier": ["we found drugs in a package sent with your aadhaar", "DHL se bol rahe hain aapka parcel customs ne roka hai"],
    "claims_family": ["aunty rahul ka accident ho gaya hai hospital mein hai", "your nephew has been arrested and needs bail money"],
    "claims_boss": ["hi it's vikram your MD I can't talk I'm in a board meeting", "boss bol raha hoon ek confidential kaam hai"],
    "lure_reward": ["congratulations you won twenty five lakh in KBC", "your electricity refund of two thousand is pending, pay ten rupees to receive it"],
    "lure_job": ["aapko ghar baithe roz paanch hazaar kamane ka mauka hai", "complete these youtube tasks and get paid instantly"],
    "lure_invest": ["our IPO allotment gives forty percent returns in a month", "is app mein invest karo roz profit milega"],
    "threat_legal": ["the police will come to your house and arrest you today", "aap par money laundering ka case hai giraftari hogi"],
    "threat_account": ["your number will be disconnected by TRAI tonight", "aapka khata aaj raat block ho jayega"],
    "urgency": ["you have only five minutes to do this", "abhi turant karna hoga warna der ho jayegi"],
    "isolation": ["don't inform your family or your bank about this", "call mat kaatiye aur kisi ko kuch mat bataiye"],
    "ask_money": ["send fifty thousand to this account number now", "UPI se processing fee pay kar dijiye"],
    "ask_otp": ["please read the six digit code you received", "apna ATM pin bataiye verify karna hai"],
    "ask_app": ["install quick support app and give me the code", "maine link bheja hai usme details bhariye"],
    "ask_details": ["what is your aadhaar number please", "card ke peeche wala CVV number bataiye"],
    "reassure": ["remember the bank never asks for your PIN on a call", "OTP kisi ko bhi mat batana, hum nahi maangte"],
}
HARMLESS = [
    "hello mummy how are you, did you eat lunch",
    "I'm outside your building with the Amazon parcel",
    "your appointment with the doctor is at five tomorrow",
    "the meeting moved to three pm, please send the report",
    "bhaiya cab paanch minute mein pahunch rahi hai",
    "papa kal shaam ghar aa jaunga",
    "your card payment of twelve thousand was declined, if it was you please try again",
    "hum aapke loan ke documents ke liye branch aane ko keh rahe the",
    "school fees ki last date friday hai",
    "did you see the news about the fake police calls, be careful",
    "the electricity will be off tomorrow morning for repairs",
    "please collect your new debit card from the branch",
    "aapka order kal deliver ho jayega",
    "can you pick up vegetables on the way home",
    "the plumber will come at eleven",
    "happy birthday beta, kab aa rahe ho",
]


def load_encoder():
    import torch
    from transformers import AutoModel, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(BASE)
    model = AutoModel.from_pretrained(BASE).eval()

    def embed(texts: list[str]) -> np.ndarray:
        out = []
        for i in range(0, len(texts), 32):
            enc = tok([PREFIX + turn_text(t) for t in texts[i : i + 32]], max_length=128, truncation=True, padding=True, return_tensors="pt")
            with torch.no_grad():
                h = model(**enc).last_hidden_state
            m = enc["attention_mask"].unsqueeze(-1).float()
            v = (h * m).sum(1) / m.sum(1)
            out.append(torch.nn.functional.normalize(v, dim=-1).numpy())
        return np.concatenate(out)

    return embed


def genuine_turns(n: int) -> tuple[list[str], list[str]]:
    """Turns from ICFD conversations held out of training (ml.conv_data.part == "dev"): genuine calls, and scam calls."""
    import pandas as pd

    from ml.conv_data import ICFD, part

    cols = ["conversation_uid", "cumulative_transcript_json", "case_type"]
    df = pd.concat([pd.read_parquet(f, columns=cols) for f in sorted(ICFD.glob("train-*.parquet"))], ignore_index=True)
    df = df.drop_duplicates("conversation_uid", keep="last")
    df = df[df["conversation_uid"].map(part) == "dev"].sample(frac=1.0, random_state=1)
    good, bad = [], []
    for _, r in df.iterrows():
        side = good if "Normal" in r["case_type"] else bad
        side.extend(t["text"] for t in json.loads(r["cumulative_transcript_json"]))
    return good[:n], bad[:n]


def main() -> None:
    embed = load_encoder()
    names = list(MOVES)
    desc = [s for n in names for s in MOVES[n]["say"]]
    owner = np.array([n for n in names for _ in MOVES[n]["say"]])
    good, bad = genuine_turns(4000)
    G = embed(good)
    mu = G[:1000].mean(0)  # e5 puts every sentence in one narrow cone; removing its centre spreads the moves apart

    def centred(X: np.ndarray) -> np.ndarray:
        X = X - mu
        return X / np.linalg.norm(X, axis=1, keepdims=True)

    D = centred(embed(desc))

    def scores(X: np.ndarray) -> np.ndarray:
        S = centred(X) @ D.T
        return np.stack([S[:, owner == n].max(1) for n in names], 1)

    def fired(S: np.ndarray, thr: np.ndarray) -> np.ndarray:
        """A segment makes at most one move: its best-matching one, if that clears the move's threshold."""
        top = S.argmax(1)
        out = np.full(len(S), -1)
        ok = S[np.arange(len(S)), top] >= thr[top]
        out[ok] = top[ok]
        return out

    Sg = scores(G[1000:])  # genuine-call turns not used for the centre
    thr = np.quantile(Sg, 0.995, axis=0)
    cal = [(n, s) for n in names for s in CALIBRATE[n]]
    fc = fired(scores(embed([s for _, s in cal])), thr)
    fh = fired(scores(embed(HARMLESS)), thr)
    fg = fired(Sg, thr)
    fb = fired(scores(embed(bad)), thr)
    report = {
        "calibration_correct": round(float(np.mean([fc[i] == names.index(n) for i, (n, _) in enumerate(cal)])), 3),
        "harmless_sentences_any_move": round(float(np.mean(fh >= 0)), 3),
        "genuine_call_turns_any_move": round(float(np.mean(fg >= 0)), 3),
        "genuine_call_turns_ask_move": round(float(np.mean([f >= 0 and MOVES[names[f]]["group"] == "ask" for f in fg])), 4),
        "scam_call_turns_any_move": round(float(np.mean(fb >= 0)), 3),
        "scam_call_turns_ask_move": round(float(np.mean([f >= 0 and MOVES[names[f]]["group"] == "ask" for f in fb])), 4),
        "wrong_calibration": [(n, s, names[fc[i]] if fc[i] >= 0 else None) for i, (n, s) in enumerate(cal) if fc[i] != names.index(n)],
        "harmless_fired": [(s, names[f]) for s, f in zip(HARMLESS, fh, strict=True) if f >= 0],
    }
    out = {
        "version": 2,
        "about": "Scam moves for the matcher (ml/moves.py): descriptions embedded with multilingual-e5-small (query: prefix, mean pooled, L2), "
        "minus `centre`, L2 again; a segment makes its best move if the cosine clears that move's threshold "
        "(99.5th percentile on held-out genuine ICFD call turns).",
        "model": "intfloat/multilingual-e5-small",
        "centre": [round(float(x), 6) for x in mu],
        "moves": [{"id": n, "group": MOVES[n]["group"], "category": CATEGORY[n], "threshold": round(float(thr[i]), 4)} for i, n in enumerate(names)],
        "descriptions": [{"move": o, "text": t, "vec": [round(float(x), 5) for x in v]} for o, t, v in zip(owner.tolist(), desc, D, strict=True)],
        "report": report,
    }
    (ASSETS / "moves.json").write_text(json.dumps(out) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=1, ensure_ascii=False))


def export() -> None:
    """models/conv_model/e5base.int8.onnx: base e5 → mean-pooled, L2-normalised embedding, for the phone's matcher."""
    import onnxruntime as ort
    import torch
    from onnxruntime.quantization import QuantType, quantize_dynamic
    from transformers import AutoModel, AutoTokenizer

    class Pooled(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.enc = AutoModel.from_pretrained(BASE)

        def forward(self, input_ids, attention_mask):
            h = self.enc(input_ids=input_ids, attention_mask=attention_mask).last_hidden_state
            m = attention_mask.unsqueeze(-1).to(h.dtype)
            return torch.nn.functional.normalize((h * m).sum(1) / m.sum(1).clamp(min=1.0), dim=-1)

    out = ROOT / "models" / "conv_model"
    out.mkdir(parents=True, exist_ok=True)
    model = Pooled().eval()
    tok = AutoTokenizer.from_pretrained(BASE)
    enc = tok([PREFIX + "hello", PREFIX + "tell me the otp"], padding=True, return_tensors="pt")
    fp32, q = out / "e5base.fp32.onnx", out / "e5base.int8.onnx"
    torch.onnx.export(
        model, (enc["input_ids"], enc["attention_mask"]), str(fp32), input_names=["input_ids", "attention_mask"], output_names=["embedding"],
        dynamic_axes={"input_ids": {0: "b", 1: "n"}, "attention_mask": {0: "b", 1: "n"}, "embedding": {0: "b"}}, opset_version=17, dynamo=False,
    )  # fmt: skip
    quantize_dynamic(
        str(fp32), str(q), weight_type=QuantType.QInt8, op_types_to_quantize=["MatMul", "Gemm", "Gather"]
    )  # Gather: the 250k-word table, 3/4 of the model
    s = ort.InferenceSession(str(q), providers=["CPUExecutionProvider"])
    cos = []
    for t in [s for n in MOVES for s in CALIBRATE[n]] + HARMLESS:
        e = tok([PREFIX + turn_text(t)], return_tensors="pt")
        with torch.no_grad():
            ref = model(e["input_ids"], e["attention_mask"])[0].numpy()
        got = s.run(None, {"input_ids": e["input_ids"].numpy(), "attention_mask": e["attention_mask"].numpy()})[0][0]
        cos.append(float(ref @ got))
    print({"int8_vs_fp32_min_cosine": round(min(cos), 4), "int8_mb": round(q.stat().st_size / 1e6, 1)})
    assert min(cos) > 0.98, "int8 drifted from fp32"


if __name__ == "__main__":
    import sys

    export() if sys.argv[1:] == ["export"] else main()
