"""The relay: the only thing that runs off the phone. It passes messages between family phones and does no analysis.

    uvicorn engine.relay:app --port 8000          # locally
    docker build -f Dockerfile.relay -t countersign-relay .   # Hugging Face Spaces (port 7860) or Render

What goes through it (docs/agents/CONTRACT.md): sign-up and family links, call events and caller checks ("is this
really Rahul's phone?"), the scam alert and the family alarm (ids only: a scam type and cue ids, never words or
audio), "Not a scam" (family_alarm_cleared and one ids-only feedback record), the events socket, and the address of
the model pack the phone downloads once. Speech-to-text, the scam classifier and the voice-clone check all run on the
phone. No torch, no models.

State is in memory and SQLite on the host's disk; a free host may restart and lose it (docs/DEPLOY.md). Phones sign
up again and re-link in a minute.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from engine import auth, callcheck, cases, mobile
from engine.config import settings
from engine.db import db
from engine.hub import hub
from engine.mocks.world import world

log = logging.getLogger("countersign.relay")
STARTED = time.time()

# the model pack the phones download (ml/pack_models.py prints these); a GitHub release asset by default
PACK = {
    "name": os.environ.get("COUNTERSIGN_PACK_NAME", "countersign-pack-v1"),
    "size_mb": int(os.environ.get("COUNTERSIGN_PACK_MB", "0") or 0),
    "sha256": os.environ.get("COUNTERSIGN_PACK_SHA256", ""),
    "url": os.environ.get("COUNTERSIGN_PACK_URL", "https://github.com/dope-XD/countersign/releases/download/models-v1/countersign-pack-v1.zip"),
    "parts": ["asr-hi", "asr-en", "vad", "voice"],
}
_pack_file = settings.models_dir / "pack.json"
if _pack_file.exists():
    PACK |= {k: v for k, v in json.loads(_pack_file.read_text(encoding="utf-8")).items() if k in PACK and v}


async def _housekeeping() -> None:
    n = 0
    while True:
        await asyncio.sleep(5)
        callcheck.prune()
        n += 1
        if n % 120 == 0:
            cases.purge_expired()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    hub.loop = asyncio.get_running_loop()
    task = asyncio.create_task(_housekeeping())
    yield
    task.cancel()
    hub.loop = None


app = FastAPI(title="Countersign relay", lifespan=lifespan, docs_url=None, redoc_url=None)
app.include_router(mobile.router)
app.include_router(callcheck.router)
app.include_router(mobile.files)


@app.get("/health")
@app.get("/api/health")
async def health() -> JSONResponse:
    """Also asks the database, so a keep-alive pinging this keeps a free Postgres from pausing
    and a broken database shows up as 503 (docs/DEPLOY.md)."""
    try:
        db_ok = db.query("SELECT 1 AS ok")[0]["ok"] == 1
    except Exception as e:
        log.warning("health: database unreachable: %s", e)
        db_ok = False
    body = {
        "ok": db_ok,
        "role": "relay",
        "db": "postgres" if db.url else "sqlite",
        "uptime_s": round(time.time() - STARTED),
        "customers": len(world.customers),
        "analysis": "on the phone",
    }
    return JSONResponse(body, status_code=200 if db_ok else 503)


@app.get("/api/m/models")
async def models() -> list[dict]:
    return [PACK]


@app.get("/api/metrics")
async def metrics() -> dict:
    """The measured accuracy (models/metrics.json from ml.eval.run_all) and what happened on this relay since it started:
    scam alerts and false alarms users reported (ids only), for human review."""
    p = settings.models_dir / "metrics.json"
    fa = list(callcheck.false_alarms)
    alerts = db.query("SELECT COUNT(*) AS n FROM audit WHERE event = 'scam_call_alert'")[0]["n"]
    return {
        "report": json.loads(p.read_text(encoding="utf-8")) if p.exists() else None,
        "live": {
            "since": STARTED,
            "scam_alerts": alerts,
            "false_alarms_reported": len(fa),
            "false_alarms_by_reason": {r: sum(1 for x in fa if x["reason"] == r) for r in ("know_caller", "not_a_scam")},
            "false_alarms_by_level": {lv: sum(1 for x in fa if x["level"] == lv) for lv in ("watch", "warn", "scam")},
            "for_review": fa[-50:],
        },
    }


async def _send(ws: WebSocket, text: str) -> bool:
    try:
        await ws.send_text(text)
        return True
    except Exception:
        return False


@app.websocket("/ws/events")
async def ws_events(ws: WebSocket, topics: str = "") -> None:
    """A phone gets only the app events of the customer it's signed in as."""
    names = [t for t in topics.split(",") if t.startswith("app:") and auth.is_device(ws, t.split(":", 1)[1])][:4]
    await ws.accept()
    q = hub.subscribe(*names)
    customers = [t.split(":", 1)[1] for t in names]

    async def pump() -> None:
        while await _send(ws, await q.get()):
            pass

    pump_task = asyncio.create_task(pump())
    try:
        while True:
            await ws.receive_text()  # the phone's heartbeat: it's online
            for cid in customers:
                world.app_sessions[cid] = time.time()
    except WebSocketDisconnect:
        pass
    finally:
        pump_task.cancel()
        hub.unsubscribe(q)
