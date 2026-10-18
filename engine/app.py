"""Countersign engine: one FastAPI process serving the API, websockets and the web app.

Run:  .venv/Scripts/python -m uvicorn engine.app:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from engine import cases, guard, indiacall, policy, voicenote
from engine.config import settings
from engine.db import db
from engine.hub import hub
from engine.mocks.world import world
from engine.session import calls
from engine.signals import s3_liveness
from engine.signals.s1_synth import detector
from engine.signals.s2_drift import embedder
from engine.stepup import passkeys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("countersign")

MODEL_STATE = {"s1": "loading", "s2": "loading", "asr": "loading"}


def _load_models() -> None:
    try:
        detector.load()
        MODEL_STATE["s1"] = detector.backend
    except Exception as e:
        log.exception("S1 load failed")
        MODEL_STATE["s1"] = f"error: {e}"
    embedder.load()
    MODEL_STATE["s2"] = "ecapa" if embedder.available else "off"
    s3_liveness.asr.load()
    MODEL_STATE["asr"] = settings.asr_model if s3_liveness.asr.model is not None else "off"
    log.info("models ready: %s", MODEL_STATE)


async def _housekeeping() -> None:
    while True:
        await asyncio.sleep(600)
        cases.purge_expired()
        calls.prune()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    hub.loop = asyncio.get_running_loop()
    threading.Thread(target=_load_models, daemon=True).start()
    task = asyncio.create_task(_housekeeping())
    yield
    task.cancel()


app = FastAPI(title="Countersign", lifespan=lifespan)


@app.exception_handler(policy.PolicyError)
async def _policy_err(_r, e):
    return JSONResponse({"error": str(e)}, status_code=409)


@app.exception_handler(passkeys.StepUpError)
async def _stepup_err(_r, e):
    return JSONResponse({"error": str(e)}, status_code=400)


def _host(req: Request) -> str | None:
    return req.headers.get("x-forwarded-host") or req.headers.get("host")


def _origin(req: Request) -> str | None:
    return req.headers.get("origin")


# ============================================================== health
@app.get("/api/health")
def health():
    return {"ok": True, "models": MODEL_STATE, "s1_version": detector.version, "p95_ms": detector.p95_ms(),
            "live_calls": len(calls.live()), "rp_id": settings.rp_id}


# ============================================================== caller softphone
@app.websocket("/ws/caller")
async def ws_caller(ws: WebSocket, cli: str = "", lang: str = "unknown"):
    await ws.accept()
    cli = cli.strip()
    if cli and cli[0].isdigit():
        cli = "+" + cli  # a raw "+" in a query string arrives as a space
    cs = calls.create(cli or "+910000000000", lang)
    cs.caller_ws = ws
    await ws.send_text(json.dumps({"type": "call", "id": cs.id}))

    async def pinger():
        while cs.status != "ended":
            try:
                await ws.send_text(json.dumps({"type": "ping", "t": time.time()}))
            except Exception:
                return
            await asyncio.sleep(2)

    ping_task = asyncio.create_task(pinger())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                await cs.on_caller_audio(msg["bytes"])
                for a in list(cs.agent_wss):
                    try:
                        await a.send_bytes(msg["bytes"])
                    except Exception:
                        cs.agent_wss.discard(a)
            elif msg.get("text"):
                data = json.loads(msg["text"])
                if data.get("type") == "pong":
                    rtt = time.time() - float(data["t"])
                    cs.caller_rtt = 0.8 * cs.caller_rtt + 0.2 * rtt if cs.caller_rtt else rtt
                elif data.get("type") == "hangup":
                    break
    except WebSocketDisconnect:
        pass
    finally:
        ping_task.cancel()
        cs.end()


# ============================================================== agent console
@app.websocket("/ws/agent/{call_id}")
async def ws_agent(ws: WebSocket, call_id: str):
    cs = calls.get(call_id)
    await ws.accept()
    if cs is None:
        await ws.send_text(json.dumps({"type": "error", "error": "no such call"}))
        await ws.close()
        return
    cs.agent_wss.add(ws)
    q = hub.subscribe(f"call:{call_id}")
    await ws.send_text(json.dumps({"type": "state", "call": cs.public()}))

    async def pump():
        while True:
            await ws.send_text(await q.get())

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                await cs.on_agent_audio(msg["bytes"])
                cw = getattr(cs, "caller_ws", None)
                if cw is not None and cs.status == "live":
                    try:
                        await cw.send_bytes(msg["bytes"])
                    except Exception:
                        pass
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        hub.unsubscribe(q)
        cs.agent_wss.discard(ws)


def _call(call_id: str):
    cs = calls.get(call_id)
    if cs is None:
        raise HTTPException(404, "no such call")
    return cs


@app.get("/api/calls")
def list_calls():
    return calls.live()


@app.get("/api/calls/{call_id}")
def get_call(call_id: str):
    return _call(call_id).public()


@app.post("/api/calls/{call_id}/answer")
async def answer(call_id: str):
    cs = _call(call_id)
    cs.answer()
    cust = world.by_mobile(cs.caller_cli)
    if cust:
        cs.customer_id = cust.id  # IVR matched the caller ID; the agent can change it
        world.calls_by_customer.setdefault(cust.id, []).append(time.time())
    cw = getattr(cs, "caller_ws", None)
    if cw:
        await cw.send_text(json.dumps({"type": "answered"}))
    return cs.public()


@app.post("/api/calls/{call_id}/identify")
def identify(call_id: str, body: dict = Body(...)):
    cs = _call(call_id)
    cid = body.get("customer_id")
    if world.customer(cid) is None:
        raise HTTPException(404, "no such customer")
    if cs.customer_id != cid:
        cs.customer_id = cid
        world.calls_by_customer.setdefault(cid, []).append(time.time())
    db.audit("agent", "customer_identified", call_id, customer=cid)
    if cs.case_id:
        cs.ensure_case("customer_identified")
    cs.recompute()
    return cs.public()


@app.post("/api/calls/{call_id}/request")
def new_request(call_id: str, body: dict = Body(...)):
    cs = _call(call_id)
    if not cs.customer_id:
        raise HTTPException(400, "identify the customer first")
    tier = cs.tier or "GREEN"
    r = policy.create_request(cs.customer_id, "contact_centre", body["action"], body.get("details") or {}, tier, call_id)
    cs.request_ids.append(r["id"])
    if cs.case_id is None and tier == "RED":
        cs.ensure_case("risky_request_on_red")
    cs.recompute()
    return r


@app.post("/api/calls/{call_id}/challenge")
async def challenge(call_id: str, force: str | None = None):
    cs = _call(call_id)
    fixed = None
    if force:
        # Only the IndiaCall simulator may pick the challenge, so recorded replies exist for it.
        if os.environ.get("COUNTERSIGN_EVAL") != "1":
            raise HTTPException(403, "fixed challenges are only allowed in eval mode")
        fixed = indiacall.challenges().get(force)
    ch = cs.issue_challenge(fixed)
    asyncio.create_task(cs.check_challenge_timeout(10.0))
    hub.publish(f"call:{call_id}", {"type": "state", "call": cs.public()})
    return ch


@app.post("/api/calls/{call_id}/challenge/done-reading")
def done_reading(call_id: str):
    _call(call_id).agent_done_reading()
    return {"ok": True}


@app.post("/api/calls/{call_id}/transfer")
def transfer(call_id: str):
    cs = _call(call_id)
    case_id = cs.ensure_case("transferred_to_fraud_desk")
    if cs.tier == "RED" and cs.caller.ring.total:
        cases.attach_clip(case_id, cs.caller.ring.last(int(settings.evidence_seconds * 16000)))
    db.audit("agent", "transferred_to_fraud_desk", call_id, case=case_id)
    return {"case_id": case_id}


@app.post("/api/calls/{call_id}/hangup")
async def hangup(call_id: str):
    cs = _call(call_id)
    cw = getattr(cs, "caller_ws", None)
    if cw:
        try:
            await cw.send_text(json.dumps({"type": "ended"}))
        except Exception:
            pass
    cs.end()
    return {"ok": True}


# ============================================================== requests (policy)
def _publish_request(rid: str) -> None:
    r = policy.get(rid)
    if r.get("call_id"):
        cs = calls.get(r["call_id"])
        if cs:
            hub.publish(f"call:{cs.id}", {"type": "state", "call": cs.public()})


@app.get("/api/requests/{rid}")
def get_request(rid: str):
    r = policy.get(rid)
    return {**r, "missing": policy.missing(r)}


@app.post("/api/requests/{rid}/send-approval")
def send_approval(rid: str):
    r = policy.get(rid)
    if "app_approval" not in r["policy"]["reqs"]:
        raise HTTPException(400, "this request doesn't need an app approval")
    if not passkeys.credentials(r["customer_id"]):
        raise HTTPException(409, "No passkey on this account. The customer must approve at a branch or by video-KYC.")
    cust = world.customer(r["customer_id"])
    label = policy.ACTIONS[r["action"]]["label"]
    d = r["details"] or {}
    detail = ", ".join(f"{k.replace('_', ' ')}: {v}" for k, v in d.items()) or ""
    summary = {"question": f"Did you ask us to: {label}?", "detail": detail, "action": r["action"],
               "channel": "phone call to the bank", "customer": cust.name}
    a = passkeys.request_approval(rid, r["customer_id"], "app_approval", summary)
    pol = r["policy"]
    pol["reqs"]["app_approval"] = {"status": "sent", "approval_id": a["id"], "at": time.time()}
    db.update("requests", rid, {"policy": pol})
    _publish_request(rid)
    return a


@app.post("/api/requests/{rid}/standard-checks")
def standard_checks(rid: str, body: dict = Body(...)):
    r = policy.mark(rid, "standard_checks", "met" if body.get("passed") else "failed", by="agent")
    _publish_request(rid)
    return r


@app.post("/api/requests/{rid}/override")
def override(rid: str, body: dict = Body(...)):
    r = policy.override(rid, body["requirement"], body.get("agent", "agent"), body.get("reason", ""))
    _publish_request(rid)
    return r


@app.post("/api/requests/{rid}/decline-voice-check")
def decline_voice(rid: str):
    r = policy.decline_voice_check(rid, "agent")
    _publish_request(rid)
    return r


@app.post("/api/requests/{rid}/execute")
def execute(rid: str):
    r = policy.execute(rid, "agent")
    _publish_request(rid)
    return r


def _record_human_lag(call_id: str | None) -> None:
    """A passkey-approved request means the caller was the real customer, so their
    liveness reply delay is a genuine human sample for the IndiaCall simulator."""
    cs = calls.get(call_id) if call_id else None
    if not cs or not cs.liveness or cs.liveness.get("lag_s") is None or os.environ.get("COUNTERSIGN_EVAL") == "1":
        return
    p = indiacall.ROOT / "human_lags.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    lags = json.loads(p.read_text()) if p.exists() else []
    lags.append(cs.liveness["lag_s"])
    p.write_text(json.dumps(lags))


# ============================================================== passkeys & approvals
@app.post("/api/app/{cid}/passkey/options")
def passkey_options(cid: str, req: Request):
    return Response(passkeys.registration_options(cid, _host(req)), media_type="application/json")


@app.post("/api/app/{cid}/passkey/verify")
def passkey_verify(cid: str, req: Request, body: dict = Body(...)):
    return passkeys.verify_registration(cid, body["credential"], body.get("device", "phone"), _host(req), _origin(req))


@app.delete("/api/app/{cid}/passkeys")
def passkey_remove(cid: str):
    passkeys.remove_credentials(cid)
    return {"ok": True}


@app.get("/api/approvals/{aid}")
def approval(aid: str):
    return passkeys.public_approval(aid)


@app.post("/api/approvals/{aid}/options")
def approval_options(aid: str, req: Request):
    return Response(passkeys.assertion_options(aid, _host(req)), media_type="application/json")


@app.post("/api/approvals/{aid}/decide")
def approval_decide(aid: str, req: Request, body: dict = Body(...)):
    a = passkeys.decide(aid, body["decision"], body.get("credential"), _host(req), _origin(req))
    if a["kind"] == "app_approval":
        rid = a["request_id"]
        if a["status"] == "approved":
            policy.mark(rid, "app_approval", "met", by=a["target_customer"], approval_id=aid)
            _record_human_lag(policy.get(rid).get("call_id"))
        else:
            policy.mark(rid, "app_approval", "failed", by=a["target_customer"], approval_id=aid)
            r = policy.get(rid)
            cs = calls.get(r["call_id"]) if r.get("call_id") else None
            if cs:
                cs.ensure_case("customer_declined_in_app")
            else:
                cases.open_case(channel="contact_centre", customer_id=r["customer_id"], request_id=rid, tier=r["tier"], event="customer_declined_in_app")
            hub.publish(f"app:{a['target_customer']}", {"type": "alert", "title": "Thanks. Nothing was changed.",
                                                        "body": "Our fraud team has the case. You can call us on the number on your card."})
        _publish_request(rid)
    else:
        guard.on_family_decision(a)
    return a


# ============================================================== bank app (Entry B)
@app.get("/api/app/{cid}/home")
def app_home(cid: str):
    cust = world.customer(cid)
    if cust is None:
        raise HTTPException(404, "no such customer")
    world.app_sessions[cid] = time.time()
    pays = db.query("SELECT id, details, status, created_at FROM requests WHERE customer_id=? AND channel='app' ORDER BY created_at DESC LIMIT 10", [cid])
    return {
        "customer": cust.__dict__, "passkeys": passkeys.credentials(cid), "pending": passkeys.pending_for(cid),
        "payments": pays, "family": [world.customer(f).__dict__ for f in cust.family_circle if world.customer(f)],
    }


@app.post("/api/app/{cid}/pay")
def app_pay(cid: str, body: dict = Body(...)):
    return guard.start_payment(cid, body["payee"].strip(), float(body["amount"]), body.get("note", ""))


@app.post("/api/payments/{pid}/ask-family")
def pay_ask_family(pid: str, body: dict = Body(...)):
    try:
        return guard.ask_family(pid, body["family_id"])
    except PermissionError as e:
        raise HTTPException(403, str(e))


@app.post("/api/payments/{pid}/continue")
def pay_continue(pid: str):
    return guard.continue_anyway(pid)


@app.post("/api/payments/{pid}/cancel")
def pay_cancel(pid: str):
    return guard.cancel(pid)


@app.post("/api/payments/{pid}/report")
def pay_report(pid: str):
    return guard.prefill_1930(pid)


@app.post("/api/voice-note")
async def voice_note(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "file too large")
    res = await asyncio.to_thread(voicenote.check, data)
    db.audit("app", "voice_note_checked", None, verdict=res["verdict"], seconds=res.get("seconds"))
    return res


# ============================================================== fraud desk
@app.get("/api/cases")
def list_cases():
    return db.query("SELECT * FROM cases ORDER BY opened_at DESC LIMIT 100")


@app.get("/api/cases/{case_id}")
def get_case(case_id: str):
    c = db.get("cases", case_id)
    if not c:
        raise HTTPException(404)
    c["audit"] = db.query("SELECT * FROM audit WHERE ref IN (?,?,?) ORDER BY ts", [case_id, c.get("call_id") or "", c.get("request_id") or ""])
    c["request"] = db.get("requests", c["request_id"]) if c.get("request_id") else None
    c["reports"] = db.query("SELECT * FROM reports WHERE case_id=?", [case_id])
    c["has_clip"] = bool(c.get("clip_path"))
    c.pop("clip_path", None)
    return c


@app.get("/api/cases/{case_id}/clip")
def case_clip(case_id: str, analyst: str = "analyst"):
    try:
        return Response(cases.read_clip(case_id, analyst), media_type="audio/wav")
    except FileNotFoundError:
        raise HTTPException(404, "no clip")


@app.post("/api/cases/{case_id}/resolve")
def case_resolve(case_id: str, body: dict = Body(...)):
    outcome = body["outcome"]
    analyst = body.get("analyst", "analyst")
    c = cases.resolve(case_id, outcome, analyst, body.get("note", ""))
    rid = c.get("request_id")
    if rid:
        r = db.get("requests", rid)
        if r and r["status"] == "open" and "fraud_desk" in r["policy"]["reqs"]:
            if outcome == "fraud_confirmed":
                policy.mark(rid, "fraud_desk", "failed", by=analyst)
                policy.cancel(rid, analyst, "fraud confirmed")
            elif outcome == "false_alarm":
                policy.mark(rid, "fraud_desk", "met", by=analyst)
            _publish_request(rid)
    return c


# ============================================================== demo operator panel
@app.get("/api/demo/world")
def demo_world():
    return world.public()


@app.post("/api/demo/reset")
def demo_reset():
    world.reset()
    db.wipe_world()
    for c in list(calls.calls.values()):
        c.end()
    calls.calls.clear()
    for f in cases.EVIDENCE_DIR.glob("*.bin"):
        f.unlink()
    hub.publish("calls", {"type": "calls"})
    hub.publish("desk", {"type": "reset"})
    return {"ok": True}


@app.post("/api/demo/sim-swap")
def demo_sim_swap(body: dict = Body(...)):
    cust = world.customer(body["customer_id"])
    if body.get("on", True):
        world.sim_swaps[cust.registered_mobile] = time.time() - 3600 * float(body.get("hours_ago", 5))
    else:
        world.sim_swaps.pop(cust.registered_mobile, None)
    return world.public()


@app.post("/api/demo/fri")
def demo_fri(body: dict = Body(...)):
    if body.get("rating"):
        world.fri[body["number"]] = body["rating"]
    else:
        world.fri.pop(body["number"], None)
    return world.public()


@app.post("/api/demo/recent-call")
def demo_recent_call(body: dict = Body(...)):
    if body.get("on", True):
        world.recent_calls[body["customer_id"]] = time.time() - 60 * float(body.get("minutes_ago", 2))
    else:
        world.recent_calls.pop(body["customer_id"], None)
    return world.public()


@app.post("/api/demo/clear-call-history")
def demo_clear_calls(body: dict = Body(...)):
    world.calls_by_customer.pop(body["customer_id"], None)
    return {"ok": True}


@app.get("/api/demo/stored")
def demo_stored():
    """Privacy inspector: exactly what Countersign holds right now."""
    clips = [{"file": f.name, "bytes": f.stat().st_size, "encrypted": True} for f in cases.EVIDENCE_DIR.glob("*.bin")]
    live_audio = {c.id: round(c.caller.ring.total / 16000, 1) if c.status != "ended" else 0 for c in calls.calls.values()}
    return {
        "voiceprints": 0,
        "speaker_embeddings_in_memory": sum(len(c.drift.history) and 1 for c in calls.calls.values() if c.status != "ended"),
        "audio_files_on_disk": clips,
        "live_audio_seconds_in_memory": live_audio,
        "case_rows": db.query("SELECT id, tier, reasons, status, outcome FROM cases"),
        "audit_events": len(db.query("SELECT id FROM audit")),
        "transcripts_stored": 0,
    }


@app.get("/api/demo/audit")
def demo_audit(limit: int = 200):
    return db.query("SELECT * FROM audit ORDER BY id DESC LIMIT ?", [limit])


# ============================================================== metrics
@app.get("/api/metrics")
def metrics():
    p = settings.models_dir / "metrics.json"
    report = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    lat = detector.latencies_ms
    return {
        "report": report,
        "live": {
            "s1_backend": detector.backend, "s1_version": detector.version,
            "windows_scored": len(lat), "p50_ms": float(sorted(lat)[len(lat) // 2]) if lat else None,
            "p95_ms": detector.p95_ms(),
        },
    }


# ============================================================== IndiaCall recorder
@app.get("/api/indiacall/items")
def ic_items():
    return indiacall.items()


@app.post("/api/indiacall/consent")
def ic_consent(body: dict = Body(...)):
    if not body.get("agree"):
        raise HTTPException(400, "consent required")
    return indiacall.record_consent(body["speaker"], body["name"], body.get("languages", []))


@app.get("/api/indiacall/progress/{speaker}")
def ic_progress(speaker: str):
    return {"done": indiacall.progress(speaker)}


@app.post("/api/indiacall/upload")
async def ic_upload(speaker: str = Form(...), item: str = Form(...), file: UploadFile = File(...)):
    data = await file.read()
    ext = (file.filename or "rec.webm").rsplit(".", 1)[-1]
    try:
        return await asyncio.to_thread(indiacall.save_recording, speaker, item, data, ext)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ============================================================== event stream for UIs
@app.websocket("/ws/events")
async def ws_events(ws: WebSocket, topics: str = "calls"):
    await ws.accept()
    names = [t for t in topics.split(",") if t]
    q = hub.subscribe(*names)
    app_customers = [t.split(":", 1)[1] for t in names if t.startswith("app:")]

    async def pump():
        while True:
            await ws.send_text(await q.get())

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            await ws.receive_text()  # heartbeat from the client
            for cid in app_customers:
                world.app_sessions[cid] = time.time()
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        hub.unsubscribe(q)


# ============================================================== static web app
if settings.web_dist.exists():
    app.mount("/assets", StaticFiles(directory=settings.web_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        f = settings.web_dist / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(settings.web_dist / "index.html", headers={"Cache-Control": "no-store"})
