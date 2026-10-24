"""The LLM judge: a local model reads the call so far and says how likely it is a scam.

Runs on our own laptop through Ollama (free, nothing leaves the machine). Used by /ws/listen and
by the eval harness (ml/eval/listener.py). The judge only adds evidence: fusion.py decides the level,
and the judge alone can't make "scam" (it needs cue categories too).

    j = OllamaJudge("qwen2.5:7b")
    j.judge(["caller: this is mumbai police ...", "receiver: what?"])   # Judge(p_scam=0.93, type="digital_arrest")
"""

from __future__ import annotations

import json
import logging
import os
import re
import time

import httpx

from engine.listener.fusion import Judge

log = logging.getLogger(__name__)

OLLAMA = os.environ.get("COUNTERSIGN_OLLAMA", "http://127.0.0.1:11434")
TYPES = (
    "digital_arrest", "bank_kyc", "otp_upi", "remote_access", "family_emergency", "courier_customs",
    "trai_sim", "job_task", "investment", "reward", "impersonation", "unknown",
)  # fmt: skip

SYSTEM = """You protect people in India from phone scams. You read a phone call transcript, possibly cut off mid-call, possibly with speech-recognition errors, in English, Hindi or Hinglish. Decide how likely it is that the CALLER is running a scam on the person who received the call.

Indian scam patterns:
- digital_arrest: caller claims to be police, CBI, ED, customs, narcotics, TRAI, RBI or a court; says there is a case, warrant, drugs in a parcel or money laundering; demands the person stay on a video call, tell no one, and move money to a "safe" or "RBI" account.
- courier_customs: a parcel is held or contains illegal items; pay a fee or face a case.
- trai_sim: your number or SIM will be cut off in hours; press 9; connects to "police".
- bank_kyc: KYC, PAN or Aadhaar update, account will be blocked; asks for an OTP, PIN, card details, or to install an app or click a link.
- remote_access: asks to install AnyDesk, TeamViewer, QuickSupport, or to share the screen.
- otp_upi: asks for an OTP or UPI PIN, or to accept a collect request "to receive" money or a refund.
- family_emergency: claims to be a relative or their friend; accident, hospital, police station, new number or broken phone; needs money now; don't tell the others.
- job_task: part-time job, likes or ratings tasks, pay first to unlock earnings.
- investment: guaranteed returns, stock tips, trading apps, doubling money.
- reward: lottery, KBC, prize or cashback that needs a fee or an OTP first.

Usually NOT scams:
- delivery agents asking for the delivery OTP;
- a real bank's fraud alert that tells you not to share OTPs;
- a doctor's or hospital's appointment call;
- relatives talking normally about money;
- ordinary telemarketing that doesn't demand money, codes or apps;
- people discussing scams they saw in the news;
- real police asking someone to visit the station in person.

Real police, banks, RBI and courts never ask for money, OTPs or app installs on a call, and never put anyone under "digital arrest".

Answer with JSON only: {"p_scam": number from 0 to 1, "type": one of TYPES_LIST, "red_flags": [short phrases], "abstain": true if there is too little to judge yet}""".replace(
    "TYPES_LIST", ", ".join(TYPES)
)


def parse(text: str) -> Judge | None:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        p = float(d.get("p_scam", 0.0))
    except (ValueError, TypeError):
        return None
    t = d.get("type") if d.get("type") in TYPES else "unknown"
    return Judge(min(1.0, max(0.0, p)), t, bool(d.get("abstain", False)))


class OllamaJudge:
    def __init__(self, model: str = "qwen2.5:7b", timeout: float = 30.0, max_chars: int = 6000):
        self.model = model
        self.http = httpx.Client(base_url=OLLAMA, timeout=timeout)
        self.max_chars = max_chars
        self.last_ms = 0.0

    def judge(self, turns: list[str]) -> Judge | None:
        """None when the model is down or answers nonsense; fusion then goes on without it."""
        text = "\n".join(turns)[-self.max_chars :]  # the latest part of a long call matters most
        t0 = time.perf_counter()
        try:
            r = self.http.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": f"Transcript so far:\n{text}"}],
                    "format": "json",
                    "stream": False,
                    "keep_alive": "30m",
                    "options": {"temperature": 0, "num_ctx": 4096},
                },
            )
            r.raise_for_status()
            out = parse(r.json()["message"]["content"])
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("judge %s failed: %s", self.model, e)
            out = None
        self.last_ms = (time.perf_counter() - t0) * 1000
        return out
