"""IndiaCall: our consented test set. Fixed recording script shared by the recorder page,
the clone generators and the call simulator.

Only teammates who signed the consent form record. Clone outputs are labelled synthetic
and deleted after the event.
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path

from engine.config import settings
from engine.signals.s3_liveness import Challenge

ROOT = settings.data_dir / "indiacall"
REC = ROOT / "recordings"

OPENINGS = [
    ("O01", "en", "Hi, I lost my phone yesterday. Can you please change my registered mobile number to my new number? It's a bit urgent."),
    ("O02", "en", "Hello, I want to add a new payee to my account today. I need to send money to my landlord before evening."),
    ("O03", "hi", "नमस्ते, मेरा फ़ोन कल खो गया। कृपया मेरा रजिस्टर्ड मोबाइल नंबर बदल दीजिए, बहुत ज़रूरी है।"),
    ("O04", "hi", "हेलो, मुझे अपने खाते में एक नया पेयी जोड़ना है। आज ही पैसे भेजने हैं।"),
    ("O05", "hinglish", "Hello, mera phone kho gaya hai. Please mera registered mobile number change kar dijiye, urgent hai."),
    ("O06", "hinglish", "Hi, mujhe ek naya payee add karna hai aur transfer limit bhi badhani hai, aaj hi."),
]

_DIGITS = ["4729", "8153", "3961", "5284", "7316", "9142", "2678", "6835", "1497", "5923", "8261", "3574"]
_PHRASES = [
    ("neela tota", "नीला तोता", "blue parrot", "47"),
    ("hara aam", "हरा आम", "green mango", "18"),
    ("peela ghoda", "पीला घोड़ा", "yellow horse", "36"),
    ("laal kitaab", "लाल किताब", "red book", "52"),
    ("kaala chaand", "काला चांद", "black moon", "29"),
    ("neela aam", "नीला आम", "blue mango", "64"),
    ("hara tota", "हरा तोता", "green parrot", "73"),
    ("laal ghoda", "लाल घोड़ा", "red horse", "85"),
    ("peela chaand", "पीला चांद", "yellow moon", "91"),
    ("kaala tota", "काला तोता", "black parrot", "12"),
    ("neela ghoda", "नीला घोड़ा", "blue horse", "58"),
    ("hara kitaab", "हरा किताब", "green book", "37"),
]


def challenges() -> dict[str, Challenge]:
    out = {}
    for i, d in enumerate(_DIGITS, 1):
        cid = f"C{i:02d}"
        out[cid] = Challenge(cid, "digits", f"Please repeat these numbers quickly: {' '.join(d)}", expect_digits=d)
    for j, (r, dev, en, num) in enumerate(_PHRASES, len(_DIGITS) + 1):
        cid = f"C{j:02d}"
        out[cid] = Challenge(cid, "phrase", f'Please say: "{r} {num}"', expect_digits=num, variants=[r, dev, en])
    return out


PASSAGES = [
    (
        "P01",
        "en",
        "The bank called me this morning about my card. I told them I would visit the branch on Saturday, because I prefer to sort these things out in person. My mother keeps reminding me to check every message twice before I pay anyone.",
    ),
    ("P02", "hi", "आज सुबह मैंने बाज़ार से सब्ज़ियाँ खरीदीं और फिर दफ़्तर गया। शाम को माँ से फ़ोन पर बात हुई, उन्होंने पूछा कि खाना ठीक से खा रहा हूँ या नहीं।"),
    (
        "P03",
        "hinglish",
        "Kal weekend pe hum dosto ke saath movie dekhne gaye the. Wapas aate hue traffic bahut tha, toh ghar pahunchne mein late ho gaya. Mummy ne phone karke poocha kahan ho.",
    ),
    ("P04", "any", "Talk freely for about 40 seconds about your day, in whichever language you like."),
]

VOICE_NOTES = [
    ("V01", "hinglish", "Mummy, accident ho gaya hai. Abhi pachaas hazaar bhejo, isi UPI ID pe. Papa ko mat batana, please jaldi karo."),
    ("V02", "hinglish", "Mummy, main theek hoon, bas dosto ke saath bahar hoon. Raat ko phone karta hoon."),
]


def items() -> list[dict]:
    out = [{"id": i, "kind": "opening", "lang": lang, "text": t} for i, lang, t in OPENINGS]
    out += [{"id": c.id, "kind": "challenge", "lang": "any", "text": c.say.split(": ", 1)[1].strip('"')} for c in challenges().values()]
    out += [{"id": i, "kind": "passage", "lang": lang, "text": t} for i, lang, t in PASSAGES]
    out += [{"id": i, "kind": "voice_note", "lang": lang, "text": t} for i, lang, t in VOICE_NOTES]
    return out


def _safe(s: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "", s.lower())[:32]


def save_recording(speaker: str, item_id: str, data: bytes, ext: str) -> dict:
    speaker = _safe(speaker)
    if not speaker or not (ROOT / "consent" / f"{speaker}.json").exists():
        raise PermissionError("No consent on file for this speaker. Sign the consent form first.")
    if item_id not in {i["id"] for i in items()}:
        raise ValueError("unknown item")
    d = REC / speaker
    d.mkdir(parents=True, exist_ok=True)
    raw = d / f"{item_id}.{_safe(ext) or 'webm'}"
    raw.write_bytes(data)
    wav = d / f"{item_id}.wav"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(raw), "-ac", "1", "-ar", "16000", str(wav)], check=True, timeout=60)
    raw.unlink()
    return {"speaker": speaker, "item": item_id, "path": str(wav.relative_to(settings.data_dir))}


def record_consent(speaker: str, full_name: str, languages: list[str], clone: bool = False, age_band: str | None = None, gender: str | None = None) -> dict:
    speaker = _safe(speaker)
    (ROOT / "consent").mkdir(parents=True, exist_ok=True)
    terms = "Recordings used only for Countersign's IndiaCall test set at RAKSHAM 2026 and deleted after the event."
    terms += (
        " Clones of this voice may be made; they are labelled synthetic and never released."
        if clone
        else " Genuine recordings only: this voice is never cloned or used as a source for voice conversion."
    )
    entry = {
        "speaker": speaker,
        "name": full_name,
        "languages": languages,
        "clone": clone,
        "age_band": age_band,
        "gender": gender,
        "agreed_at": time.time(),
        "terms": terms,
    }
    (ROOT / "consent" / f"{speaker}.json").write_text(json.dumps(entry, indent=2, ensure_ascii=False), encoding="utf-8")
    return entry


def progress(speaker: str) -> list[str]:
    d = REC / _safe(speaker)
    return sorted(p.stem for p in d.glob("*.wav")) if d.exists() else []


def recording_path(speaker: str, item_id: str) -> Path:
    return REC / _safe(speaker) / f"{item_id}.wav"
