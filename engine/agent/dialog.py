"""CS Bank's virtual assistant: answers calls from the CS Bank app like a contact-centre agent.

It greets the caller (and says it's automated), finds the account by the calling number,
understands what they want (engine/agent/llm.py), and works the request through the same
policy engine a human agent uses: card digits for standard checks, a code shown in the account
holder's app for liveness, the app approval, then the change. Everything the caller hears about
their account is filled in from the bank's own data, and every step-up line is word for word
from policy.yaml, so the assistant can't be talked into anything and can't be used to tune a clone.

Turn-taking is half duplex: while the assistant speaks, the caller's phone sends silence and
the engine ignores caller speech, so the assistant's own voice is never scored or transcribed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable

from engine import approvals, guard, policy
from engine.agent import llm, voice
from engine.audio.codec import upsample_8k_to_16k
from engine.db import db
from engine.hub import hub
from engine.mocks.world import world
from engine.session import LINE, CallSession
from engine.signals import s3_liveness

log = logging.getLogger(__name__)

SendJson = Callable[[dict], Awaitable[object]]
SendBytes = Callable[[bytes], Awaitable[object]]

GREETING = (
    "Namaste, and thank you for calling CS Bank. I'm Asha, the bank's automated assistant. "
    "I can check your balance, block your card, or help with changes to your account. How can I help you today?"
)
HELP = "I can check your balance, block your card, turn on your kill switch, change your registered mobile number, add a payee, or raise your limit."
ANYTHING_ELSE = "Is there anything else I can help you with?"
LABEL = {"change_mobile": "change your registered mobile number", "add_payee": "add a new payee", "raise_limit": "raise your transfer limit"}
END_OF_TURN_S = 0.7  # silence after the caller stops that ends their turn
LISTEN_S = 20.0
CALL_LIMIT_S = 300.0
LIVENESS_WAIT_S = 20.0
DECISION_WAIT_S = 180.0
BLOCKERS = {"cooloff_24h", "fraud_desk", "alert_customer"}  # requirements the caller can't meet on the call
STT_LANG = {"en": "en", "hi": "hi"}


def upi_in(text: str) -> str | None:
    """A UPI ID as people say it: "rakesh at okaxis", "rakesh at the rate okaxis", "rakesh@okaxis"."""
    t = re.sub(r"\s+(at the rate( of)?|at)\s+", "@", text.lower().strip(" .,"))
    m = re.search(r"([a-z0-9._-]{2,64})\s*@\s*([a-z0-9-]{2,32})", t)
    return f"{m.group(1)}@{m.group(2)}" if m else None


def speech_seconds(text: str) -> float:
    """How long the caller's phone takes to read a line aloud when the bank sends text only."""
    return 0.4 + len(text.split()) * 0.38


class Agent:
    def __init__(self, cs: CallSession, send_json: SendJson, send_bytes: SendBytes):
        self.cs = cs
        self.send_json = send_json
        self.send_bytes = send_bytes
        self.turns: asyncio.Queue[str] = asyncio.Queue()
        self.history: list[tuple[str, str]] = []
        self.speaking_until = 0.0
        self._utt_start: int | None = None
        self._utt_end: int | None = None
        self._end_timer: asyncio.TimerHandle | None = None
        self.transferred = False
        self.last_text = ""
        cs.vad_listeners.append(self._on_vad)
        cs.typed_turns = self.turns

    # ------------------------------------------------------------------ ears
    def _on_vad(self, kind: str, pos: int) -> None:
        cs = self.cs
        in_challenge = cs.challenge is not None and not cs.challenge.done
        if kind == "onset":
            if in_challenge or cs.caller.wall_at(pos) < self.speaking_until:
                return  # the code reply goes to the liveness judge; speech over the assistant is ignored
            if self._end_timer:
                self._end_timer.cancel()
                self._end_timer = None
            if self._utt_start is None:
                self._utt_start = pos
        elif kind == "offset" and self._utt_start is not None:
            self._utt_end = pos
            if self._end_timer:
                self._end_timer.cancel()
            self._end_timer = asyncio.get_running_loop().call_later(END_OF_TURN_S, self._end_turn)

    def _end_turn(self) -> None:
        start, end = self._utt_start, self._utt_end
        self._utt_start = self._utt_end = self._end_timer = None
        if start is None or end is None or self.cs.ended:
            return
        audio8 = self.cs.caller.ring.span(max(0, start - int(0.2 * LINE)), end)
        asyncio.create_task(self._transcribe(audio8))

    async def _transcribe(self, audio8) -> None:
        text = await voice.transcribe(upsample_8k_to_16k(audio8), STT_LANG.get(self.cs.language))
        if text and re.search(r"\w", text):
            await self.turns.put(text)

    async def hear(self, timeout: float = LISTEN_S) -> str | None:
        try:
            text = await asyncio.wait_for(self.turns.get(), timeout)
        except TimeoutError:
            return None
        self.history.append(("caller", text))
        self.last_text = text
        await self.send_json({"type": "caller", "said": text})
        return text

    def _drain(self) -> None:
        while not self.turns.empty():
            self.turns.get_nowait()

    # ------------------------------------------------------------------ mouth
    async def say(self, text: str, challenge: bool = False) -> None:
        cs = self.cs
        self.history.append(("agent", text))
        extra = {"challenge": text} if challenge else {}
        if voice.tts_available():
            try:
                await self.send_json({"type": "agent", "say": text, "audio": True, **extra})
                t_next = time.time()
                async for frame in voice.speak(text):
                    if cs.ended:
                        return
                    await self.send_bytes(frame)
                    await cs.on_agent_audio(frame)
                    self.speaking_until = time.time() + 0.6
                    t_next += 0.02
                    await asyncio.sleep(max(0.0, t_next - time.time()))
                self.speaking_until = time.time() + 0.6  # the phone's jitter buffer is still playing
                await asyncio.sleep(0.15)
                if challenge:
                    cs.agent_done_reading()
                return
            except Exception as e:
                log.warning("TTS failed on %s, the phone will read the line: %s", cs.id, e)
        # text only: the caller's phone reads it, mutes its mic meanwhile, and sends read_done after a challenge
        secs = speech_seconds(text)
        self.speaking_until = time.time() + secs + 0.6
        await self.send_json({"type": "agent", "say": text, "audio": False, **extra})
        await asyncio.sleep(secs)

    # ------------------------------------------------------------------ the call
    async def run(self) -> None:
        cs = self.cs
        await asyncio.sleep(0.8)
        cs.answer()
        await self.send_json({"type": "answered"})
        db.audit("virtual_agent", "call_answered", cs.id, customer=cs.customer_id)
        await self.say(GREETING)
        silent = 0
        t0 = time.time()
        while not cs.ended and time.time() - t0 < CALL_LIMIT_S:
            text = await self.hear()
            if cs.ended:
                return
            if text is None:
                silent += 1
                if silent >= 2:
                    await self.say("I can't hear anything, so I'll end this call. Please call again when you're ready.")
                    break
                await self.say("Sorry, I didn't catch that. How can I help you?")
                continue
            silent = 0
            u = await llm.understand(text, self._context(), self.history)
            if await self.handle(u):
                break
        if not self.transferred:
            await self.hangup()

    def _context(self, asking: str = "") -> str:
        cust = world.customer(self.cs.customer_id) if self.cs.customer_id else None
        return f"caller {'identified as an account holder' if cust else 'not identified yet'}; {asking or 'waiting for what the caller wants'}"

    async def handle(self, u: llm.Understanding) -> bool:
        """One caller request. True ends the call."""
        if u.intent == "goodbye":
            await self.say("Thank you for calling CS Bank. Take care, and goodbye.")
            return True
        if u.intent == "human":
            return await self.transfer()
        if u.intent in ("balance", "block_card", "kill_switch", "change_mobile", "add_payee", "raise_limit"):
            if not await self.identify():
                return False
            if u.intent == "balance":
                await self.balance()
            elif u.intent == "block_card":
                await self.block_card()
            elif u.intent == "kill_switch":
                await self.kill_switch()
            else:
                await self.risky(u.intent, u.slots)
            self._drain()
            if not self.cs.ended:
                await self.say(ANYTHING_ELSE)
            return False
        await self.say(u.reply if u.source != "rules" and u.reply else f"I'm sorry, I didn't quite get that. {HELP}")
        return False

    async def hangup(self) -> None:
        if not self.cs.ended:
            await asyncio.sleep(1.0)
            await self.send_json({"type": "ended"})
            self.cs.end()

    async def ask(self, question: str, asking: str) -> llm.Understanding | None:
        """Ask, and understand the answer. Digits are read from the words too ("four four one seven")."""
        await self.say(question)
        text = await self.hear()
        if text is None:
            return None
        u = await llm.understand(text, self._context(asking), self.history)
        spoken = s3_liveness.digits_in(text)
        if len(spoken) > len(str(u.slots.get("digits") or "")):
            u.slots["digits"] = spoken
        return u

    # ------------------------------------------------------------------ steps
    async def identify(self) -> bool:
        """The account comes from the calling number, as an IVR does; else the caller says it."""
        cs = self.cs
        if cs.customer_id:
            return True
        u = await self.ask(
            "I couldn't find an account for the number you're calling from. What's your registered mobile number?", "asked for the registered mobile number"
        )
        digits = re.sub(r"\D", "", str(u.slots.get("digits") or u.slots.get("new_mobile") or "") if u else "")[-10:]
        cust = world.by_mobile("+91" + digits) if len(digits) == 10 else None
        if cust is None:
            await self.say("I'm sorry, I couldn't find an account with that number.")
            return False
        cs.customer_id = cust.id
        world.calls_by_customer.setdefault(cust.id, []).append(time.time())
        cs.recompute()
        approvals.publish_call(cs.id)
        return True

    def _request(self, action: str, details: dict) -> dict:
        cs = self.cs
        r = policy.create_request(cs.customer_id, "contact_centre", action, details, cs.tier or "GREEN", cs.id)
        cs.request_ids.append(r["id"])
        if cs.tier == "RED" and policy.ACTIONS[action]["risk"] != "low":
            cs.ensure_case("risky_request_on_red")
        cs.recompute()
        approvals.publish_call(cs.id)
        return r

    async def balance(self) -> None:
        r = self._request("balance", {})
        policy.execute(r["id"], "virtual agent")
        if r["policy"]["no_sensitive_details"]:
            await self.say("For your security, I can't read out account details on this call. You can see your balance in the CS Bank app.")
        else:
            await self.say(f"Your available balance is {guard.inr(world.customer(self.cs.customer_id).balance)}.")

    async def block_card(self) -> None:
        r = self._request("block_card", {})
        policy.execute(r["id"], "virtual agent")
        card = world.customer(self.cs.customer_id).card_last4
        await self.say(f"Done. I've blocked your debit card ending in {' '.join(card)}. You can order a new one from the app.")

    async def kill_switch(self) -> None:
        guard.kill_switch_on(self.cs.customer_id, by="virtual agent")
        await self.say("I've turned on your kill switch. All payments and account changes are blocked until you turn it off in the CS Bank app.")

    async def risky(self, action: str, slots: dict) -> None:
        details = await self._details(action, slots)
        if details is None:
            await self.say("I'm sorry, I didn't get that, so I haven't made any change.")
            return
        try:
            r = self._request(action, details)
        except policy.PolicyError as e:
            await self.say(str(e))
            return
        await self.say(f"Sure. I've logged a request to {LABEL[action]}.")
        await self.work(r["id"])
        await self.finish(r["id"])

    async def _details(self, action: str, slots: dict) -> dict | None:
        for attempt in range(2):
            if action == "change_mobile":
                d = re.sub(r"\D", "", str(slots.get("new_mobile") or slots.get("digits") or ""))[-10:]
                if len(d) == 10 and d[0] in "6789":
                    return {"new_mobile": "+91" + d}
                q = "What's the new mobile number you'd like to register?"
            elif action == "add_payee":
                p = upi_in(str(slots.get("payee") or "")) or upi_in(self.last_text)
                if p:
                    return {"payee": p}
                q = "What's the UPI ID of the person you'd like to add?"
            else:
                d = re.sub(r"\D", "", str(slots.get("limit") or slots.get("digits") or ""))
                if d and int(d) > 0:
                    return {"limit": int(d)}
                q = "What should your new daily limit be, in rupees?"
            if attempt == 1:
                return None
            u = await self.ask(q, f"asked for the {action.replace('_', ' ')} details")
            if u is None:
                return None
            slots = u.slots
        return None

    async def work(self, rid: str) -> None:
        """One requirement at a time, until the request is executed, declined or blocked."""
        cs = self.cs
        asked_checks = asked_code = sent_approval = False
        t0 = time.time()
        while not cs.ended and time.time() - t0 < DECISION_WAIT_S:
            r = policy.get(rid)
            if r["status"] != "open":
                return
            reqs = r["policy"]["reqs"]
            miss = policy.missing(r)
            if not miss:
                policy.execute(rid, "virtual agent")
                return
            if any(v.get("status") == "failed" for v in reqs.values()):
                return  # a failed check can't be retried on this call
            if "standard_checks" in miss and not asked_checks:
                asked_checks = True
                await self.standard_checks(rid)
            elif "liveness" in miss and not asked_code:
                asked_code = True
                await self.code_check()
            elif "app_approval" in miss and not sent_approval and reqs.get("app_approval", {}).get("status") == "pending":
                sent_approval = True
                try:
                    approvals.send_app_approval(rid)
                except policy.PolicyError as e:
                    await self.say(str(e))
                    return
                cs.recompute()
                await self.say(policy.SCRIPT["app_approval"] + " Please answer it on that phone.")
            else:
                waiting = reqs.get("app_approval", {}).get("status") == "sent"
                if not waiting and set(miss) <= BLOCKERS:
                    return  # blocked: nothing more the caller can do on this call
            await asyncio.sleep(0.5)

    async def standard_checks(self, rid: str) -> None:
        card = world.customer(self.cs.customer_id).card_last4
        for attempt in range(2):
            u = await self.ask(
                policy.SCRIPT["standard_checks"] if attempt == 0 else "Sorry, could you say the last four digits of your debit card again?",
                "asked for the last four digits of the debit card",
            )
            got = re.sub(r"\D", "", str(u.slots.get("digits") or "") if u else "")
            if got.endswith(card):
                policy.mark(rid, "standard_checks", "met", by="virtual agent", note="card last four digits")
                await self.say("Thank you.")
                return
        policy.mark(rid, "standard_checks", "failed", by="virtual agent", note="card digits didn't match")
        await self.say("Those details don't match our records.")

    async def code_check(self) -> None:
        cs = self.cs
        c = cs.issue_code()
        if c is None:
            return
        approvals.publish_call(cs.id)
        asyncio.create_task(cs.challenge_timeout(c, seconds=LIVENESS_WAIT_S))
        await self.say(policy.SCRIPT["liveness"], challenge=True)
        while not c.done and not cs.ended:
            await asyncio.sleep(0.25)
        self._drain()
        passed = bool(cs.liveness and cs.liveness.get("passed"))
        await self.say("Thank you, that's correct." if passed else "That didn't match the code in the app.")

    async def finish(self, rid: str) -> None:
        cs = self.cs
        r = policy.get(rid)
        miss = policy.missing(r)
        reqs = r["policy"]["reqs"]
        if r["status"] == "executed":
            outcome, line = "executed", "Done. The change has been made."
            if r["action"] == "change_mobile":
                line = f"Done. Your registered mobile number is now {' '.join(r['details']['new_mobile'][-10:])}."
        elif r["status"] == "declined":
            outcome, line = "declined", "The account holder said no in the app, so nothing was changed. Our fraud team has the case."
        elif "cooloff_24h" in miss or "fraud_desk" in miss:
            outcome, line = "held", "For your security, this change is on hold for 24 hours, and our fraud team will call your registered number."
        elif reqs.get("liveness", {}).get("status") == "failed" or reqs.get("standard_checks", {}).get("status") == "failed":
            outcome, line = "held", "I can't make this change on a call. Please visit a branch or use video KYC."
        else:
            outcome, line = "unfinished", "I couldn't complete this on the call, so nothing was changed."
        await self.send_json({"type": "result", "outcome": outcome, "request": {**r, "missing": miss}, "tier": cs.tier})
        await self.say(line)

    async def transfer(self) -> bool:
        if hub.has_subscribers("calls"):  # someone has the agent console open
            await self.say("Of course. I'm transferring you to a colleague. Please hold.")
            self.cs.timeline.append({"t": self.cs._elapsed(), "event": "transferred_to_human"})
            hub.publish("calls", {"type": "calls"})
            self.transferred = True
            return True  # the assistant steps back; the call stays open for the human agent
        await self.say("All our colleagues are busy right now. I've noted that you'd like a call back on your registered number. " + ANYTHING_ELSE)
        return False


def start_virtual_agent(cs: CallSession, send_json: SendJson, send_bytes: SendBytes) -> asyncio.Task:
    """Run the virtual agent for this call, and stream the live verdict to the caller's app."""

    async def main() -> None:
        q = hub.subscribe(f"call:{cs.id}")

        async def pump() -> None:
            while True:
                msg = json.loads(await q.get())
                if msg.get("type") in ("state", "window", "liveness"):
                    await send_json({"type": "verdict", "event": msg})

        pump_task = asyncio.create_task(pump())
        try:
            agent = Agent(cs, send_json, send_bytes)
            await agent.run()
            while agent.transferred and not cs.ended:  # keep the caller's verdict live while a human talks
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("virtual agent failed on %s", cs.id)
            await send_json({"type": "agent", "say": "Sorry, something went wrong on our side. Please call again.", "audio": False})
        finally:
            pump_task.cancel()
            hub.unsubscribe(q)

    return asyncio.create_task(main())
