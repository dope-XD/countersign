"""Countersign engine: one FastAPI process serving the API, websockets and the web app.

Run:  .venv/Scripts/python -m uvicorn engine.app:app --host 0.0.0.0 --port 8000

Every handler that touches call, request, approval or case state is `async`, so they all
run on the event loop one at a time, alongside the audio pipeline. Blocking work (models,
ffmpeg) goes to threads with asyncio.to_thread.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse

from engine import approvals, auth, callcheck, cases, indiacall, mobile, policy, schemas
from engine.config import settings
from engine.db import db
from engine.fingerprint import replay_index
from engine.hub import hub
from engine.ingest import connect as connect_ingest
from engine.mocks.world import world
from engine.session import LINE, CallSession, calls
from engine.signals import s3_liveness
from engine.signals.s1_synth import detector
from engine.signals.s2_drift import embedder
from engine.stepup import devicekeys

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("countersign")

MODEL_STATE = {"s1": "loading", "s2": "loading", "asr": "loading"}


def _load_models() -> None:
    import torch

    torch.set_num_threads(1)  # Silero VAD's per-chunk CPU calls must not fight the GPU worker for cores
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
    n = 0
    while True:
        await asyncio.sleep(5)
        callcheck.prune()
        n += 1
        if n % 120 == 0:
            cases.purge_expired()
            calls.prune()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    hub.loop = asyncio.get_running_loop()
    log.warning("Staff PIN for agent console, fraud desk and demo panel: %s", auth.staff_pin())
    threading.Thread(target=_load_models, daemon=True).start()
    task = asyncio.create_task(_housekeeping())
    yield
    task.cancel()
    hub.loop = None


app = FastAPI(title="Countersign", lifespan=lifespan)
staff = APIRouter(dependencies=[Depends(auth.require_staff)])
public = APIRouter()


@app.exception_handler(policy.PolicyError)
async def _policy_err(_r, e):
    return JSONResponse({"error": str(e)}, status_code=404 if str(e).startswith("no such") else 409)


@app.exception_handler(devicekeys.StepUpError)
async def _stepup_err(_r, e):
    return JSONResponse({"error": str(e)}, status_code=404 if str(e).startswith("no such") else 400)


@app.exception_handler(cases.CaseError)
async def _case_err(_r, e):
    return JSONResponse({"error": str(e)}, status_code=404 if str(e).startswith("no such") else 409)


def _host(conn: Request | WebSocket) -> str | None:
    return conn.headers.get("x-forwarded-host") or conn.headers.get("host")


def _customer(cid: str):
    c = world.customer(cid)
    if c is None:
        raise HTTPException(404, "no such customer")
    return c


def _call(call_id: str) -> CallSession:
    cs = calls.get(call_id)
    if cs is None:
        raise HTTPException(404, "no such call")
    return cs


def _publish_call(call_id: str | None) -> None:
    cs = calls.get(call_id) if call_id else None
    if cs:
        hub.publish(f"call:{cs.id}", {"type": "state", "call": cs.public()})


async def _send(ws: WebSocket | None, text: str | None = None, data: bytes | None = None) -> bool:
    """Best-effort websocket send; False if the peer has gone."""
    if ws is None:
        return False
    try:
        if data is not None:
            await ws.send_bytes(data)
        else:
            await ws.send_text(text)
        return True
    except Exception:
        return False


# ============================================================== health & staff login
@public.get("/api/health")
async def health():
    return {
        "ok": True,
        "models": MODEL_STATE,
        "s1_version": detector.version,
        "p95_ms": detector.p95_ms(),
        "public_url": settings.public_url,
        "live_calls": sum(1 for c in calls.calls.values() if c.status != "ended"),
    }


@public.post("/api/staff/login")
async def staff_login(body: schemas.StaffLogin, request: Request, response: Response):
    client = auth.client_key(request)
    if not auth.pin_ok(body.pin, client):
        await asyncio.sleep(1.0)  # slow down guessing (the lockout in auth.py is the real limit)
        if auth.pin_locked(client):
            raise HTTPException(429, "Too many wrong PINs. PIN sign-in is locked for a few minutes.")
        raise HTTPException(401, "wrong PIN")
    response.set_cookie(auth.COOKIE, auth.make_cookie(), max_age=auth.TTL, httponly=True, samesite="lax", secure=_secure(request))
    return {"staff": True}


def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


@public.get("/api/staff/me")
async def staff_me(request: Request):
    return {"staff": auth.is_staff(request)}


# ============================================================== caller softphone (public)
@app.websocket("/ws/caller")
async def ws_caller(ws: WebSocket, cli: str = "", lang: str = "unknown"):
    """A caller's phone line (the browser softphone), answered by a human agent on /agent. The calling number is whatever the caller claims, as on a
    real line: an attacker can spoof it, which is why nothing risky rests on it."""
    await ws.accept()
    if calls.live_count() >= settings.max_live_calls:
        await _send(ws, json.dumps({"type": "busy", "message": "All our lines are busy. Please try again in a few minutes."}))
        await ws.close(code=1013)  # try again later
        return
    lang = lang if lang in ("en", "hi", "hinglish") else "unknown"
    cli = cli.strip()
    if cli and cli[0].isdigit():
        cli = "+" + cli  # a raw "+" in a query string arrives as a space
    cs = calls.create(cli or "+910000000000", lang, source="softphone")
    cs.caller_ws = ws
    await _send(ws, json.dumps({"type": "call", "id": cs.id}))

    async def pinger():
        while not cs.ended and await _send(ws, json.dumps({"type": "ping", "t": time.time()})):
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
                    if not await _send(a, data=msg["bytes"]):
                        cs.agent_wss.discard(a)
            elif msg.get("text"):
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "pong" and isinstance(data.get("t"), int | float):
                    rtt = max(0.0, time.time() - float(data["t"]))
                    cs.caller_rtt = 0.8 * cs.caller_rtt + 0.2 * rtt if cs.caller_rtt else rtt
                elif data.get("type") == "hangup":
                    break
    except WebSocketDisconnect:
        pass
    finally:
        ping_task.cancel()
        cs.end()


# ============================================================== agent console (staff)
@app.websocket("/ws/agent/{call_id}")
async def ws_agent(ws: WebSocket, call_id: str):
    if not auth.is_staff(ws):
        await ws.close(code=4401)
        return
    cs = calls.get(call_id)
    await ws.accept()
    if cs is None:
        await _send(ws, json.dumps({"type": "error", "error": "no such call"}))
        await ws.close()
        return
    cs.agent_wss.add(ws)
    q = hub.subscribe(f"call:{call_id}")
    await _send(ws, json.dumps({"type": "state", "call": cs.public()}))

    async def pump():
        while await _send(ws, await q.get()):
            pass

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None and cs.source != "connect":  # a Connect agent talks in the CCP; that leg comes from KVS
                await cs.on_agent_audio(msg["bytes"])
                if cs.status == "live":
                    await _send(cs.caller_ws, data=msg["bytes"])
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        hub.unsubscribe(q)
        cs.agent_wss.discard(ws)


@staff.get("/api/calls")
async def list_calls():
    return calls.live()


@staff.get("/api/calls/{call_id}")
async def get_call(call_id: str):
    return _call(call_id).public()


@staff.post("/api/calls/{call_id}/answer")
async def answer(call_id: str):
    cs = _call(call_id)
    if cs.status == "ringing":
        cs.answer()
        await _send(cs.caller_ws, json.dumps({"type": "answered"}))
    return cs.public()


@staff.post("/api/calls/{call_id}/identify")
async def identify(call_id: str, body: schemas.CustomerRef):
    cs = _call(call_id)
    _customer(body.customer_id)
    if cs.customer_id != body.customer_id:
        cs.customer_id = body.customer_id
        world.calls_by_customer.setdefault(body.customer_id, []).append(time.time())
    db.audit("agent", "customer_identified", call_id, customer=body.customer_id)
    if cs.case_id:
        cs.ensure_case("customer_identified")
    cs.recompute()
    return cs.public()


@staff.post("/api/calls/{call_id}/request")
async def new_request(call_id: str, body: schemas.NewRequest):
    cs = _call(call_id)
    if not cs.customer_id:
        raise HTTPException(400, "identify the customer first")
    if cs.ended:
        raise HTTPException(409, "the call has ended")
    tier = cs.tier or "GREEN"
    r = policy.create_request(cs.customer_id, "contact_centre", body.action, body.details, tier, call_id)
    cs.request_ids.append(r["id"])
    if tier == "RED":
        cs.ensure_case("risky_request_on_red")
    cs.recompute()
    _publish_call(call_id)
    return r


@staff.post("/api/calls/{call_id}/challenge")
async def challenge(call_id: str, force: str | None = None):
    cs = _call(call_id)
    if cs.status != "live":
        raise HTTPException(409, "the call is not live")
    fixed = None
    if force:
        # Only the IndiaCall simulator may pick the challenge, so recorded replies exist for it.
        if not settings.eval_mode:
            raise HTTPException(403, "fixed challenges are only allowed in eval mode")
        fixed = indiacall.challenges().get(force)
        if fixed is None:
            raise HTTPException(404, "no such challenge")
    c = cs.issue_challenge(fixed)
    asyncio.create_task(cs.challenge_timeout(c))
    _publish_call(call_id)
    return {"id": c.ch.id, "say": c.ch.say, "kind": c.ch.kind}


@staff.post("/api/calls/{call_id}/code")
async def ask_code(call_id: str):
    """Liveness by a fresh code shown in the identified customer's CS Bank app. The agent never sees it."""
    cs = _call(call_id)
    if cs.status != "live":
        raise HTTPException(409, "the call is not live")
    if not cs.customer_id:
        raise HTTPException(400, "identify the customer first")
    c = cs.issue_code()
    asyncio.create_task(cs.challenge_timeout(c, seconds=20))
    _publish_call(call_id)
    return {"id": c.ch.id, "say": policy.SCRIPT["liveness"], "kind": "code"}


@staff.post("/api/calls/{call_id}/challenge/done-reading")
async def done_reading(call_id: str):
    _call(call_id).agent_done_reading()
    return {"ok": True}


@staff.post("/api/calls/{call_id}/transfer")
async def transfer(call_id: str):
    cs = _call(call_id)
    case_id = cs.ensure_case("transferred_to_fraud_desk")
    if cs.tier == "RED":
        cs.attach_evidence()
    db.audit("agent", "transferred_to_fraud_desk", call_id, case=case_id)
    _publish_call(call_id)
    return {"case_id": case_id}


@staff.post("/api/calls/{call_id}/hangup")
async def hangup(call_id: str):
    cs = _call(call_id)
    await _send(cs.caller_ws, json.dumps({"type": "ended"}))
    cs.end()
    return {"ok": True}


# ============================================================== requests (policy, staff)
def _request_out(r: dict) -> dict:
    return {**r, "missing": policy.missing(r)}


@staff.get("/api/requests/{rid}")
async def get_request(rid: str):
    return _request_out(policy.get(rid))


@staff.post("/api/requests/{rid}/send-approval")
async def send_approval(rid: str):
    r = policy.get(rid)
    if "app_approval" not in r["policy"]["reqs"]:
        raise HTTPException(400, "this request doesn't need an app approval")
    return approvals.send_app_approval(rid)


@staff.post("/api/requests/{rid}/standard-checks")
async def standard_checks(rid: str, body: schemas.StandardChecks):
    r = policy.mark(rid, "standard_checks", "met" if body.passed else "failed", by="agent")
    _publish_call(r["call_id"])
    return _request_out(r)


@staff.post("/api/requests/{rid}/override")
async def override(rid: str, body: schemas.Override):
    r = policy.override(rid, body.requirement, body.agent, body.reason)
    _publish_call(r["call_id"])
    return _request_out(r)


@staff.post("/api/requests/{rid}/decline-voice-check")
async def decline_voice(rid: str):
    r = policy.decline_voice_check(rid, "agent")
    _publish_call(r["call_id"])
    return _request_out(r)


@staff.post("/api/requests/{rid}/execute")
async def execute(rid: str):
    r = policy.execute(rid, "agent")
    _publish_call(r["call_id"])
    return _request_out(r)


# ============================================================== approvals evidence (staff)
@staff.get("/api/approvals/{aid}/evidence")
async def approval_evidence(aid: str):
    return devicekeys.binding_evidence(aid)


# ============================================================== fraud desk (staff)
@staff.get("/api/cases")
async def list_cases():
    return db.query("SELECT * FROM cases ORDER BY opened_at DESC LIMIT 100")


@staff.get("/api/cases/{case_id}")
async def get_case(case_id: str):
    c = db.get("cases", case_id)
    if not c:
        raise HTTPException(404, "no such case")
    refs = [case_id, c.get("call_id") or "", c.get("request_id") or ""]
    c["audit"] = db.query("SELECT * FROM audit WHERE ref IN (?,?,?) ORDER BY ts", refs)
    c["request"] = db.get("requests", c["request_id"]) if c.get("request_id") else None
    c["reports"] = db.query("SELECT * FROM reports WHERE case_id=?", [case_id])
    c["has_clip"] = bool(c.pop("clip_path", None))
    return c


@staff.get("/api/cases/{case_id}/clip")
async def case_clip(case_id: str, analyst: str = "analyst"):
    try:
        return Response(cases.read_clip(case_id, analyst[:64]), media_type="audio/wav")
    except FileNotFoundError as e:
        raise HTTPException(404, "no clip") from e


@staff.post("/api/cases/{case_id}/resolve")
async def case_resolve(case_id: str, body: schemas.Resolve):
    c = cases.resolve(case_id, body.outcome, body.analyst, body.note)
    rid = c.get("request_id")
    r = db.get("requests", rid) if rid else None
    if r and r["status"] == "open" and "fraud_desk" in r["policy"]["reqs"]:
        if body.outcome == "fraud_confirmed":
            policy.mark(rid, "fraud_desk", "failed", by=body.analyst)
            policy.cancel(rid, body.analyst, "fraud confirmed")
        elif body.outcome == "false_alarm":
            policy.mark(rid, "fraud_desk", "met", by=body.analyst)
        _publish_call(r["call_id"])
    return c


# ============================================================== demo operator panel (staff)
@staff.get("/api/demo/world")
async def demo_world():
    return world.public()


@staff.post("/api/demo/reset")
async def demo_reset():
    world.reset()
    callcheck.reset()
    for c in list(calls.calls.values()):
        await _send(c.caller_ws, json.dumps({"type": "ended"}))
        c.end()
    calls.calls.clear()
    db.wipe_world()
    replay_index.clear()
    for f in cases.EVIDENCE_DIR.glob("*.bin"):
        f.unlink()
    hub.publish("calls", {"type": "calls"})
    hub.publish("desk", {"type": "reset"})
    return {"ok": True}


@staff.post("/api/demo/sim-swap")
async def demo_sim_swap(body: schemas.SimSwap):
    cust = _customer(body.customer_id)
    if body.on:
        world.sim_swaps[cust.registered_mobile] = time.time() - 3600 * body.hours_ago
    else:
        world.sim_swaps.pop(cust.registered_mobile, None)
    return world.public()


@staff.post("/api/demo/fri")
async def demo_fri(body: schemas.Fri):
    if body.rating:
        world.fri[body.number] = body.rating
    else:
        world.fri.pop(body.number, None)
    return world.public()


@staff.post("/api/demo/recent-call")
async def demo_recent_call(body: schemas.RecentCall):
    _customer(body.customer_id)
    if body.on:
        world.recent_calls[body.customer_id] = time.time() - 60 * body.minutes_ago
    else:
        world.recent_calls.pop(body.customer_id, None)
        world.on_call.pop(body.customer_id, None)
    return world.public()


@staff.post("/api/demo/clear-call-history")
async def demo_clear_calls(body: schemas.CustomerRef):
    world.calls_by_customer.pop(body.customer_id, None)
    return {"ok": True}


@staff.get("/api/demo/stored")
async def demo_stored():
    """Privacy inspector: exactly what Countersign holds right now."""
    live = [c for c in calls.calls.values() if not c.ended]
    return {
        "voiceprints": 0,
        "calls_with_speaker_embeddings_in_memory": sum(1 for c in live if c.drift.history),
        "audio_files_on_disk": [{"file": f.name, "bytes": f.stat().st_size, "encrypted": True} for f in cases.EVIDENCE_DIR.glob("*.bin")],
        "live_audio_seconds_in_memory": {c.id: c.audio_seconds_in_memory() for c in live},
        "line_rate_hz": LINE,
        "case_rows": db.query("SELECT id, tier, reasons, status, outcome FROM cases"),
        "audit_events": db.query("SELECT COUNT(*) AS n FROM audit")[0]["n"],
        "transcripts_stored": 0,
    }


# ============================================================== metrics (public: the numbers are for judges too)
@public.get("/api/metrics")
async def metrics():
    p = settings.models_dir / "metrics.json"
    lat = sorted(detector.latencies_ms)
    return {
        "report": json.loads(p.read_text(encoding="utf-8")) if p.exists() else None,
        "live": {
            "s1_backend": detector.backend,
            "s1_version": detector.version,
            "windows_scored": len(lat),
            "p50_ms": float(lat[len(lat) // 2]) if lat else None,
            "p95_ms": detector.p95_ms(),
        },
    }


# ============================================================== IndiaCall recorder (staff: teammates)
@staff.get("/api/indiacall/items")
async def ic_items():
    return indiacall.items()


@staff.post("/api/indiacall/consent")
async def ic_consent(body: schemas.Consent):
    if not body.agree:
        raise HTTPException(400, "consent required")
    return indiacall.record_consent(body.speaker, body.name, body.languages, body.clone, body.age_band, body.gender)


@staff.get("/api/indiacall/progress/{speaker}")
async def ic_progress(speaker: str):
    return {"done": indiacall.progress(speaker)}


@staff.post("/api/indiacall/upload")
async def ic_upload(speaker: str = Form(...), item: str = Form(...), file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, "file too large")
    ext = (file.filename or "rec.webm").rsplit(".", 1)[-1]
    try:
        return await asyncio.to_thread(indiacall.save_recording, speaker, item, data, ext)
    except PermissionError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


# ============================================================== event stream for UIs
def _event_topics(conn: Request | WebSocket, topics: str) -> list[str]:
    """Staff get what they ask for; a phone only gets the app events of the customer it is logged in as."""
    names = [t for t in topics.split(",") if t][:10]
    if auth.is_staff(conn):
        return names
    return [t for t in names if t.startswith("app:") and auth.is_device(conn, t.split(":", 1)[1])]


@app.websocket("/ws/listen")
async def ws_listen(ws: WebSocket, call_id: str = "", lang: str = "en", token: str = ""):
    """The call listener's stronger check (docs/agents/CONTRACT.md, "Call listener"). Audio is kept in memory only."""
    from engine.listener.judge import OllamaJudge
    from engine.listener.live import ListenSession

    cid = auth.device_customer(ws) or auth.token_customer(token)
    me = world.customer(cid) if cid else None
    await ws.accept()
    if me is None or not call_id or len(call_id) > 64:
        await ws.close(code=4401)
        return
    if not me.stronger_check:
        await ws.close(code=4403)
        return
    if len(_listens) >= settings.max_listens:
        await _send(ws, json.dumps({"type": "busy"}))
        await ws.close(code=1013)
        return
    judge = None if settings.listen_judge == "off" else OllamaJudge(settings.listen_judge, timeout=20)

    async def send(msg: dict) -> bool:
        return await _send(ws, json.dumps(msg))

    def on_scam(v):
        callcheck.raise_alert(me, call_id, v.type, v.cues, sorted(set(v.sources) | {"server"}))

    sess = ListenSession(
        me.id,
        call_id,
        lang if lang in ("en", "hi", "hinglish") else "en",
        lambda audio, language: s3_liveness.asr.transcribe(audio, language=language),
        judge.judge if judge else None,
        send,
        on_scam,
    )
    _listens.add(sess)
    db.audit(me.id, "listen_started", call_id)
    try:
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes"):
                await sess.on_audio(msg["bytes"])
            elif msg.get("text"):
                try:
                    data = json.loads(msg["text"])
                except json.JSONDecodeError:
                    continue
                if data.get("type") == "context":
                    await sess.on_context(list(data.get("signals") or [])[:20], data.get("caller_check"))
    except WebSocketDisconnect:
        pass
    finally:
        _listens.discard(sess)
        await sess.close()
        db.audit(me.id, "listen_ended", call_id, level=sess.verdict.level)


_listens: set = set()


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket, topics: str = "calls"):
    names = _event_topics(ws, topics)
    await ws.accept()
    q = hub.subscribe(*names)
    app_customers = [t.split(":", 1)[1] for t in names if t.startswith("app:")]

    async def pump():
        while await _send(ws, await q.get()):
            pass

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


app.include_router(public)
app.include_router(connect_ingest.router)
app.include_router(mobile.router)
app.include_router(callcheck.router)
app.include_router(mobile.files)
app.include_router(staff)


# ============================================================== static web app
WEB_ROOT = settings.web_dist.resolve()


@app.get("/{path:path}", include_in_schema=False)
async def spa(path: str):
    if path.startswith(("api/", "ws/")):
        raise HTTPException(404, "not found")
    index = WEB_ROOT / "index.html"
    if not index.exists():
        raise HTTPException(503, "web app not built (cd web; npm run build)")
    f = (WEB_ROOT / path).resolve()
    # never serve anything outside web/dist (e.g. /..%2F..%2Fdata/runtime/kms.key)
    if path and f.is_file() and f.is_relative_to(WEB_ROOT):
        return FileResponse(f)
    return FileResponse(index, headers={"Cache-Control": "no-store"})
