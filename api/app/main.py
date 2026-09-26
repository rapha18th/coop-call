"""Ziso API: the coop phone writes in, the owner's call reads out."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import alarms, config, store, timeline, vision, voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("coop")

app = FastAPI(title="Ziso API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.WEB_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

_last_vision: dict[str, float] = {}
_demo_calls: dict[str, deque] = defaultdict(deque)


# ------------------------------------------------------------------ access


def user(authorization: str | None = Header(default=None)) -> dict | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return store.verify_id_token(authorization.removeprefix("Bearer ").strip())
    except Exception:
        raise HTTPException(401, "sign in again")


def coop_for(coop_id: str, who: dict | None, write: bool = False) -> dict:
    coop = store.get_coop(coop_id)
    if not coop:
        raise HTTPException(404, "no such coop")
    if who and who["uid"] == coop["owner_uid"]:
        return coop
    if coop_id == config.DEMO_COOP_ID and not write:
        return coop
    raise HTTPException(403, "not your coop")


def node_coop(coop_id: str, x_node_key: str | None) -> dict:
    coop = store.coop_for_node_key(coop_id, x_node_key or "")
    if not coop:
        raise HTTPException(403, "this phone is not paired with the coop")
    return coop


def demo_rate_limit(request: Request) -> None:
    ip = request.headers.get("x-forwarded-for", request.client.host if request.client else "?").split(",")[0]
    q = _demo_calls[ip]
    now = time.time()
    while q and now - q[0] > 3600:
        q.popleft()
    if len(q) >= config.DEMO_CALLS_PER_HOUR:
        raise HTTPException(429, "the demo coop has taken enough calls from you this hour")
    q.append(now)


# ------------------------------------------------------------------ basics


@app.get("/")
@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "service": "ziso", "demo_coop": config.DEMO_COOP_ID}


@app.get("/api/push/key")
def push_key() -> dict:
    return {"key": config.VAPID_PUBLIC_KEY}


# ------------------------------------------------------------------ coops


class NewCoop(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    birds: int = Field(ge=0, le=100000)
    age_days: int = Field(default=0, ge=0, le=1000)


@app.get("/api/coops")
def my_coops(who: dict | None = Depends(user)) -> list[dict]:
    if not who:
        raise HTTPException(401, "sign in")
    return [_public(c) for c in store.coops_for(who["uid"])]


@app.post("/api/coops")
def new_coop(body: NewCoop, who: dict | None = Depends(user)) -> dict:
    if not who:
        raise HTTPException(401, "sign in")
    coop, key = store.create_coop(who["uid"], body.name, who.get("name", ""), body.birds, body.age_days)
    return {"coop": _public(coop), "node_key": key}


@app.post("/api/coops/{coop_id}/node-key")
def rotate_key(coop_id: str, who: dict | None = Depends(user)) -> dict:
    coop_for(coop_id, who, write=True)
    return {"node_key": store.rotate_node_key(coop_id)}


def _public(coop: dict) -> dict:
    return {k: v for k, v in coop.items() if k != "node_key_hash"}


@app.get("/api/coops/{coop_id}/state")
def state(coop_id: str, who: dict | None = Depends(user)) -> dict:
    coop = coop_for(coop_id, who)
    now = store.now()
    hours = timeline.hours_between(coop_id, now - timedelta(hours=23), now)
    strip = [{
        "hour": h["hour"],
        "nv": h.get("nv", 0),
        "birds": round(h["birds_sum"] / h["nv"]) if h.get("nv") else None,
        "huddled": timeline._frac(h, "huddled"),
        "drinker_low": timeline._frac(h, "drinker_low"),
        "agitated": timeline._frac(h, "agitated"),
        "sound": timeline._mean(h, "sound_db"),
        "notes": len(h.get("notes", [])),
        "simulated": bool(h.get("simulated")),
    } for h in hours]
    return {
        "coop": _public(coop),
        "now": timeline.answer_now(coop_id),
        "alarms": [_alarm_view(a) for a in alarms.open_alarms(coop_id)],
        "strip": strip,
        "owner": bool(who and who["uid"] == coop["owner_uid"]),
    }


def _alarm_view(a: dict) -> dict:
    return {"id": a["id"], "kind": a["kind"], "message": a["message"], "status": a["status"],
            "time": timeline.clock(a["ts"]), "frame_url": store.frame_url(a.get("frame"))}


# ------------------------------------------------------------------ the coop phone


def _num(v) -> float | None:
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def _sensor_obs(sensors: dict, ts, simulated: bool = False) -> dict:
    return {
        "ts": ts, "source": "sensor", "simulated": simulated,
        "brightness": _num(sensors.get("brightness")),
        "sound_db": _num(sensors.get("sound_db")),
        "motion": _num(sensors.get("motion")),
        "battery": _num(sensors.get("battery")),
        "charging": bool(sensors.get("charging")),
    }


class Beat(BaseModel):
    brightness: float | None = None
    sound_db: float | None = None
    motion: float | None = None
    battery: float | None = None
    charging: bool | None = None


@app.post("/api/node/{coop_id}/beat")
def beat(coop_id: str, body: Beat, x_node_key: str | None = Header(default=None)) -> dict:
    node_coop(coop_id, x_node_key)
    timeline.record(coop_id, _sensor_obs(body.model_dump(), store.now()))
    return {"ok": True}


@app.post("/api/node/{coop_id}/frame")
def frame(coop_id: str, image: UploadFile = File(...), sensors: str = Form("{}"),
          x_node_key: str | None = Header(default=None)) -> dict:
    node_coop(coop_id, x_node_key)
    ts = store.now()
    readings = json.loads(sensors or "{}")
    timeline.record(coop_id, _sensor_obs(readings, ts))

    since = time.time() - _last_vision.get(coop_id, 0)
    if since < config.MIN_VISION_INTERVAL_S:
        return {"analysed": False, "wait_s": round(config.MIN_VISION_INTERVAL_S - since)}
    _last_vision[coop_id] = time.time()

    jpeg = image.file.read()
    if len(jpeg) > 2_500_000:
        raise HTTPException(413, "frame too large")
    path = store.save_frame(coop_id, ts, jpeg)
    try:
        seen = vision.read_frame(jpeg)
    except Exception as exc:
        log.exception("vision failed")
        return {"analysed": False, "error": str(exc)[:200]}
    obs = {"ts": ts, "source": "vision", "simulated": False, "frame": path, **seen}
    timeline.record(coop_id, obs)
    alarms.evaluate(coop_id)
    return {"analysed": True, "seen": seen}


# ------------------------------------------------------------------ the call


class CallRequest(BaseModel):
    alarm_id: str | None = None


@app.post("/api/coops/{coop_id}/call")
def call(coop_id: str, body: CallRequest, request: Request, who: dict | None = Depends(user)) -> dict:
    coop = coop_for(coop_id, who)
    if not (who and who["uid"] == coop["owner_uid"]):
        demo_rate_limit(request)
    if not config.ASSEMBLYAI_API_KEY:
        raise HTTPException(503, "voice is not configured")
    return {"token": voice.mint_token(), "session": voice.session(coop, body.alarm_id)}


@app.post("/api/coops/{coop_id}/tools/{name}")
def tool(coop_id: str, name: str, args: dict, who: dict | None = Depends(user)) -> dict:
    coop = coop_for(coop_id, who)
    try:
        if name == "coop_now":
            return timeline.answer_now(coop_id)
        if name == "coop_period":
            return timeline.answer_period(coop_id, timeline.parse_local(args["start"]),
                                          timeline.parse_local(args["end"]))
        if name == "coop_vs_normal":
            return timeline.answer_vs_normal(coop_id)
        if name == "show_picture":
            return timeline.answer_frame(coop_id, timeline.parse_local(args.get("time")))
        if name == "coop_alarms":
            found = alarms.open_alarms(coop_id)
            return {"alarms": [{"id": a["id"], "message": a["message"], "since": timeline.clock(a["ts"]),
                                "status": a["status"]} for a in found] or "No open alarms."}
        if name == "resolve_alarm":
            if not (who and who["uid"] == coop["owner_uid"]) and coop_id != config.DEMO_COOP_ID:
                raise HTTPException(403, "not your coop")
            alarms.set_status(coop_id, args["alarm_id"], "resolved")
            return {"ok": True}
    except (KeyError, ValueError) as exc:
        return {"error": f"bad arguments: {exc}"}
    raise HTTPException(404, "no such tool")


# ------------------------------------------------------------------ the ring


@app.post("/api/coops/{coop_id}/push/subscribe")
def subscribe(coop_id: str, sub: dict, who: dict | None = Depends(user)) -> dict:
    coop_for(coop_id, who)
    if "endpoint" not in sub:
        raise HTTPException(400, "not a push subscription")
    alarms.subscribe(coop_id, sub)
    return {"ok": True}


class TestAlarm(BaseModel):
    kind: str = "drinker_empty"


@app.post("/api/coops/{coop_id}/alarms/test")
def test_alarm(coop_id: str, body: TestAlarm, who: dict | None = Depends(user)) -> dict:
    coop_for(coop_id, who, write=True)
    alarms.resolve(coop_id, body.kind)
    latest = timeline.latest(coop_id, "vision")
    alarm = alarms.raise_alarm(coop_id, body.kind, "(test)", latest.get("frame") if latest else None)
    return {"alarm": _alarm_view(alarm) if alarm else None}


@app.post("/api/coops/{coop_id}/alarms/{alarm_id}/resolve")
def resolve_alarm(coop_id: str, alarm_id: str, who: dict | None = Depends(user)) -> dict:
    coop_for(coop_id, who, write=True)
    alarms.set_status(coop_id, alarm_id, "resolved")
    return {"ok": True}


# ------------------------------------------------------------------ the watch


async def watch() -> None:
    """Every minute: is each coop phone still alive, and does any alarm need another ring."""
    while True:
        try:
            coops = await asyncio.to_thread(lambda: [
                {"id": s.id, **s.to_dict()} for s in store.db().collection("coops").stream()])
            for coop in coops:
                await asyncio.to_thread(alarms.check_heartbeat, coop)
                await asyncio.to_thread(alarms.re_ring, coop["id"])
        except Exception:
            log.exception("watch loop")
        await asyncio.sleep(60)


@app.on_event("startup")
async def start_watch() -> None:
    if config.service_account() or config.FIREBASE_PROJECT:
        asyncio.create_task(watch())
