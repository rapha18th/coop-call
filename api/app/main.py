"""Ziso API: the coop phone writes in, the owner's call reads out."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import defaultdict, deque
from datetime import timedelta
from typing import Literal

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import firestore
from pydantic import BaseModel, Field

import os

from . import alarms, batchcal, config, device, feed, flock, metrics, pipeline, store, timeline, today, vision, voice

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("coop")

app = FastAPI(title="Ziso API", version="0.2.0")
app.add_middleware(CORSMiddleware, allow_origins=config.WEB_ORIGINS, allow_methods=["*"], allow_headers=["*"])

_demo_calls: dict[str, deque] = defaultdict(deque)
_touched: dict[str, tuple[float, dict]] = {}

Role = Literal["owner", "keeper", "viewer"]
RANK = {"public": 0, "viewer": 1, "keeper": 2, "owner": 3, "admin": 4}


# ------------------------------------------------------------------ who is asking


def user(authorization: str | None = Header(default=None)) -> dict | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        claims = store.verify_id_token(authorization.removeprefix("Bearer ").strip())
    except Exception:
        raise HTTPException(401, "sign in again")
    uid = claims["uid"]
    cached = _touched.get(uid)
    if not cached or time.time() - cached[0] > 600:
        cached = (time.time(), store.touch_user(claims))
        _touched[uid] = cached
    if cached[1].get("blocked"):
        raise HTTPException(403, "this account is paused. Contact the Coop Call team.")
    claims["admin"] = bool(claims.get("email_verified")) and (claims.get("email") or "").lower() in config.ADMIN_EMAILS
    return claims


def signed_in(who: dict | None = Depends(user)) -> dict:
    if not who:
        raise HTTPException(401, "sign in")
    return who


def admin(who: dict = Depends(signed_in)) -> dict:
    if not who["admin"]:
        raise HTTPException(403, "admins only")
    return who


def role_of(coop: dict, who: dict | None) -> str:
    if who and who.get("admin"):
        return "admin"
    if who:
        if who["uid"] == coop.get("owner_uid"):
            return "owner"
        member = coop.get("members", {}).get(who["uid"])
        if member:
            return member["role"]
    return "public" if coop["id"] == config.DEMO_COOP_ID else "none"


def access(coop_id: str, who: dict | None, need: str = "viewer") -> tuple[dict, str]:
    coop = store.get_coop(coop_id)
    if not coop:
        raise HTTPException(404, "no such coop")
    role = role_of(coop, who)
    if role == "none":
        raise HTTPException(403, "not your coop")
    need_rank = 0 if (need == "viewer" and role == "public") else RANK[need]
    if RANK[role] < need_rank:
        raise HTTPException(403, f"needs a {need}")
    return coop, role


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


@app.get("/api/me")
def me(who: dict = Depends(signed_in)) -> dict:
    return {"uid": who["uid"], "email": who.get("email"), "name": who.get("name"), "admin": who["admin"]}


# ------------------------------------------------------------------ coops


def _public(coop: dict) -> dict:
    return {k: v for k, v in coop.items() if k not in ("node_key_hash", "invites", "invite_emails", "member_uids")}


def _card(coop: dict, role: str) -> dict:
    v = timeline.latest(coop["id"], "vision")
    return {
        **_public(coop),
        "role": role,
        "open_alarms": len(alarms.open_alarms(coop["id"])),
        "latest": {
            "time": timeline.clock(v["ts"]), "ago": timeline.ago(v["ts"]), "birds": v.get("birds"),
            "spread": v.get("spread"), "drinker": v.get("drinker"), "feeder": v.get("feeder"),
            "frame_url": store.frame_url(v.get("frame")), "simulated": bool(v.get("simulated")),
        } if v else None,
    }


class Prices(BaseModel):
    chick: float | None = Field(default=None, ge=0, le=20)
    feed_per_kg: float | None = Field(default=None, ge=0, le=10)
    sell_per_kg: float | None = Field(default=None, ge=0, le=50)
    other_per_bird: float | None = Field(default=None, ge=0, le=20)


class FlockSetup(BaseModel):
    birds: int = Field(ge=1, le=100000)
    age_days: int = Field(default=0, ge=0, le=70)
    breed: str = "Cobb 500"
    prices: Prices = Prices()
    sell_day: int = Field(default=35, ge=28, le=56)


class NewCoop(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    birds: int = Field(ge=0, le=100000)
    age_days: int = Field(default=0, ge=0, le=1000)
    breed: str = "Cobb 500"
    prices: Prices = Prices()
    sell_day: int = Field(default=35, ge=28, le=56)


@app.get("/api/coops")
def my_coops(who: dict = Depends(signed_in)) -> list[dict]:
    coops = [store.backfill_owner(c, who) for c in store.coops_for(who["uid"], who.get("email", ""), who.get("name", ""))]
    return [_card(c, role_of(c, who)) for c in coops]


@app.post("/api/coops")
def new_coop(body: NewCoop, who: dict = Depends(signed_in)) -> dict:
    coop, key = store.create_coop(who["uid"], body.name, who.get("name", ""), body.birds, body.age_days,
                                  owner_email=(who.get("email") or "").lower())
    if body.birds:
        flock.setup(coop["id"], body.birds, min(body.age_days, 70), body.breed,
                    body.prices.model_dump(), body.sell_day)
    return {"coop": _public(coop), "node_key": key}


@app.put("/api/coops/{coop_id}/flock")
def setup_flock(coop_id: str, body: FlockSetup, who: dict = Depends(signed_in)) -> dict:
    access(coop_id, who, "owner")
    return flock.setup(coop_id, body.birds, body.age_days, body.breed, body.prices.model_dump(), body.sell_day)


class PriceEdit(BaseModel):
    prices: Prices = Prices()
    sell_day: int | None = Field(default=None, ge=28, le=56)


@app.patch("/api/coops/{coop_id}/flock")
def edit_flock(coop_id: str, body: PriceEdit, who: dict = Depends(signed_in)) -> dict:
    coop, _ = access(coop_id, who, "owner")
    if not coop.get("flock"):
        raise HTTPException(400, "set up the flock first")
    update = {f"flock.prices.{k}": v for k, v in body.prices.model_dump().items() if v is not None}
    if body.sell_day:
        update["flock.sell_day"] = body.sell_day
    if update:
        store.coop_ref(coop_id).update(update)
    return {"ok": True}


class Record(BaseModel):
    kind: str
    quantity: float | None = Field(default=None, ge=0, le=1_000_000)
    amount_usd: float | None = Field(default=None, ge=0, le=10_000_000)
    unit: str = ""
    note: str = ""


@app.get("/api/coops/{coop_id}/ledger")
def get_ledger(coop_id: str, who: dict | None = Depends(user)) -> list[dict]:
    coop, _ = access(coop_id, who)
    if not coop.get("flock"):
        return []
    rows = flock.ledger(coop_id, coop["flock"]["batch"])
    return [{**r, "ts": store.local(r["ts"]).strftime("%a %d %b %H:%M")} for r in reversed(rows)]


@app.post("/api/coops/{coop_id}/ledger")
def post_ledger(coop_id: str, body: Record, who: dict | None = Depends(user)) -> dict:
    coop, role = access(coop_id, who, "keeper" if coop_id != config.DEMO_COOP_ID else "viewer")
    if not coop.get("flock"):
        raise HTTPException(400, "set up the flock first")
    try:
        row = flock.add_record(coop_id, coop["flock"]["batch"], body.kind, body.quantity, body.amount_usd,
                               body.note, who["uid"] if who else None, body.unit)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return {"ok": True, "id": row["id"]}


@app.delete("/api/coops/{coop_id}/ledger/{row_id}")
def delete_ledger(coop_id: str, row_id: str, who: dict = Depends(signed_in)) -> dict:
    access(coop_id, who, "keeper")
    store.coop_ref(coop_id).collection("ledger").document(row_id).delete()
    return {"ok": True}


class CoopEdit(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    birds: int | None = Field(default=None, ge=0, le=100000)
    age_days: int | None = Field(default=None, ge=0, le=1000)


@app.patch("/api/coops/{coop_id}")
def edit_coop(coop_id: str, body: CoopEdit, who: dict = Depends(signed_in)) -> dict:
    access(coop_id, who, "owner")
    update = {k: v for k, v in {"name": body.name, "birds_expected": body.birds}.items() if v is not None}
    if body.age_days is not None:
        update.update({"age_days_at_start": body.age_days, "created": store.now()})
    if update:
        store.coop_ref(coop_id).update(update)
    return {"ok": True}


@app.post("/api/coops/{coop_id}/node-key")
def rotate_key(coop_id: str, who: dict = Depends(signed_in)) -> dict:
    access(coop_id, who, "owner")
    key = store.rotate_node_key(coop_id)
    store.coop_ref(coop_id).update({"source": {"type": "pairing", "label": "Waiting for a phone",
                                               "connected_at": store.now()}, "device": {}})
    return {"node_key": key}


@app.get("/api/coops/{coop_id}/state")
def state(coop_id: str, who: dict | None = Depends(user)) -> dict:
    coop, role = access(coop_id, who)
    now = store.now()
    hours = timeline.hours_between(coop_id, now - timedelta(hours=23), now)
    strip = [{
        "hour": h["hour"], "nv": h.get("nv", 0),
        "birds": round(h["birds_sum"] / h["nv"]) if h.get("nv") else None,
        "huddled": timeline._frac(h, "huddled"), "drinker_low": timeline._frac(h, "drinker_low"),
        "agitated": timeline._frac(h, "agitated"), "sound": timeline._mean(h, "sound_db"),
        "notes": len(h.get("notes", [])), "simulated": bool(h.get("simulated")),
    } for h in hours]
    st = flock.state(coop)
    dev = device.health(coop)
    open_alarms = alarms.open_alarms(coop_id)
    acts = today.actions(coop, st, dev, open_alarms)
    care = today._care_today(coop)
    return {
        "coop": _public(coop),
        "role": role,
        "device": dev,
        "source": {k: v for k, v in (coop.get("source") or {"type": "none"}).items() if k != "clips"},
        "flock": st,
        "today": {"headline": today.headline(coop, st, care, dev, acts, open_alarms), "actions": acts, "care": care},
        "now": timeline.answer_now(coop_id),
        "alarms": [_alarm_view(a) for a in open_alarms],
        "strip": strip,
        "owner": role in ("owner", "admin"),
    }


@app.get("/api/coops/{coop_id}/calendar")
def coop_calendar(coop_id: str, who: dict | None = Depends(user)) -> dict:
    coop, _ = access(coop_id, who)
    return batchcal.month(coop)


@app.get("/api/coops/{coop_id}/span")
def coop_span(coop_id: str, first: str, last: str, who: dict | None = Depends(user)) -> dict:
    coop, _ = access(coop_id, who)
    from datetime import date as _date
    try:
        return batchcal.span(coop, _date.fromisoformat(first), _date.fromisoformat(last))
    except ValueError:
        raise HTTPException(400, "dates must look like 2026-09-27")


@app.get("/api/coops/{coop_id}/metrics")
def coop_metrics(coop_id: str, days: int = 7, who: dict | None = Depends(user)) -> dict:
    coop, _ = access(coop_id, who)
    return metrics.week(coop, max(1, min(days, 14)))


def _alarm_view(a: dict) -> dict:
    return {"id": a["id"], "kind": a["kind"], "message": a["message"], "status": a["status"],
            "time": timeline.clock(a["ts"]), "frame_url": store.frame_url(a.get("frame"))}


# ------------------------------------------------------------------ the team


class Invite(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    role: Literal["keeper", "viewer"] = "keeper"


@app.get("/api/coops/{coop_id}/team")
def team(coop_id: str, who: dict = Depends(signed_in)) -> dict:
    coop, role = access(coop_id, who)
    coop = store.backfill_owner(coop, who)
    members = sorted(({"uid": uid, **m} for uid, m in coop.get("members", {}).items()),
                     key=lambda m: m.get("order", 99))
    invites = list(coop.get("invites", {}).values()) if RANK[role] >= RANK["owner"] else []
    return {"members": members, "invites": invites, "can_manage": RANK[role] >= RANK["owner"]}


@app.post("/api/coops/{coop_id}/team")
def invite(coop_id: str, body: Invite, who: dict = Depends(signed_in)) -> dict:
    access(coop_id, who, "owner")
    if "@" not in body.email:
        raise HTTPException(400, "that is not an email address")
    store.invite(coop_id, body.email, body.role, who["uid"])
    return {"ok": True}


class MemberChange(BaseModel):
    role: Literal["keeper", "viewer"] | None = None


@app.patch("/api/coops/{coop_id}/team/{uid}")
def change_member(coop_id: str, uid: str, body: MemberChange, who: dict = Depends(signed_in)) -> dict:
    coop, _ = access(coop_id, who, "owner")
    if uid == coop["owner_uid"]:
        raise HTTPException(400, "the owner stays the owner")
    store.set_member(coop_id, uid, body.role)
    return {"ok": True}


@app.delete("/api/coops/{coop_id}/team/{uid}")
def remove_member(coop_id: str, uid: str, who: dict = Depends(signed_in)) -> dict:
    coop, _ = access(coop_id, who, "owner")
    if uid == coop["owner_uid"]:
        raise HTTPException(400, "the owner stays the owner")
    store.set_member(coop_id, uid, None)
    return {"ok": True}


@app.delete("/api/coops/{coop_id}/invites/{email}")
def cancel_invite(coop_id: str, email: str, who: dict = Depends(signed_in)) -> dict:
    access(coop_id, who, "owner")
    store.cancel_invite(coop_id, email)
    return {"ok": True}


# ------------------------------------------------------------------ the coop phone


def node_coop(coop_id: str, x_node_key: str | None) -> dict:
    coop = store.coop_for_node_key(coop_id, x_node_key or "")
    if not coop:
        raise HTTPException(403, "this phone is not paired with the coop")
    return coop


class Beat(BaseModel):
    brightness: float | None = None
    sound_db: float | None = None
    motion: float | None = None
    battery: float | None = None
    charging: bool | None = None
    network: str | None = None
    sharpness: float | None = None
    width: int | None = None
    height: int | None = None
    version: str | None = None
    camera: str | None = None
    temperature_c: float | None = None
    humidity_pct: float | None = None
    ammonia_ppm: float | None = None


@app.post("/api/node/{coop_id}/beat")
def beat(coop_id: str, body: Beat, x_node_key: str | None = Header(default=None)) -> dict:
    coop = node_coop(coop_id, x_node_key)
    data = body.model_dump()
    _mark_source(coop, data.get("camera"))
    pipeline.ingest(coop_id, None, data)
    return {"ok": True}


@app.post("/api/node/{coop_id}/frame")
def frame(coop_id: str, image: UploadFile = File(...), sensors: str = Form("{}"),
          x_node_key: str | None = Header(default=None)) -> dict:
    coop = node_coop(coop_id, x_node_key)
    readings = json.loads(sensors or "{}")
    _mark_source(coop, readings.get("camera"))
    jpeg = image.file.read()
    if len(jpeg) > 2_500_000:
        raise HTTPException(413, "frame too large")
    return pipeline.ingest(coop_id, jpeg, readings)


@app.post("/api/node/{coop_id}/disconnect")
def node_disconnect(coop_id: str, x_node_key: str | None = Header(default=None)) -> dict:
    """The coop phone lets go: its key stops working and the coop shows nothing connected."""
    node_coop(coop_id, x_node_key)
    _disconnect(coop_id)
    return {"ok": True}


def _mark_source(coop: dict, camera: str | None) -> None:
    """The first reading after pairing says what kind of eyes the coop has."""
    kind, label = ("camera", "IP camera through the Ziso bridge") if camera == "rtsp" else ("phone", "Coop phone")
    if (coop.get("source") or {}).get("type") != kind:
        store.coop_ref(coop["id"]).update({"source": {"type": kind, "label": label, "connected_at": store.now()}})


def _disconnect(coop_id: str) -> None:
    store.rotate_node_key(coop_id)
    store.coop_ref(coop_id).update({"source": {"type": "none", "disconnected_at": store.now()}, "device": {}})


@app.post("/api/coops/{coop_id}/source/video")
def connect_video(coop_id: str, body: dict | None = Body(default=None), who: dict = Depends(signed_in)) -> dict:
    access(coop_id, who, "owner")
    store.rotate_node_key(coop_id)
    src = feed.connect(coop_id, (body or {}).get("feed", "demo"))
    return {"ok": True, "label": src["label"]}


@app.delete("/api/coops/{coop_id}/source")
def disconnect(coop_id: str, who: dict = Depends(signed_in)) -> dict:
    access(coop_id, who, "owner")
    _disconnect(coop_id)
    return {"ok": True}


# ------------------------------------------------------------------ the call


class CallRequest(BaseModel):
    alarm_id: str | None = None


@app.post("/api/coops/{coop_id}/call")
def call(coop_id: str, body: CallRequest, request: Request, who: dict | None = Depends(user)) -> dict:
    coop, role = access(coop_id, who)
    if role == "public":
        demo_rate_limit(request)
    if not config.ASSEMBLYAI_API_KEY:
        raise HTTPException(503, "voice is not configured")
    token = voice.mint_token()
    session = voice.session(coop, body.alarm_id, who["uid"] if who else None,
                            flock.briefing(flock.state(coop)), device.spoken(device.health(coop)))
    ref = store.coop_ref(coop_id).collection("calls").document()
    ref.set({"ts": store.now(), "uid": who["uid"] if who else None,
             "name": (who or {}).get("name") or ("Demo caller" if role == "public" else ""),
             "role": role, "alarm_id": body.alarm_id, "status": "live"})
    return {"token": token, "session": session, "call_id": ref.id}


class CallEnd(BaseModel):
    duration_s: float = Field(ge=0, le=36000)
    transcript: list[dict] = Field(default_factory=list, max_length=400)
    tools: list[str] = Field(default_factory=list, max_length=200)
    evidence: int = 0


@app.post("/api/coops/{coop_id}/calls/{call_id}/end")
def call_end(coop_id: str, call_id: str, body: CallEnd, who: dict | None = Depends(user)) -> dict:
    access(coop_id, who)
    ref = store.coop_ref(coop_id).collection("calls").document(call_id)
    snap = ref.get()
    if not snap.exists or snap.to_dict().get("status") != "live":
        raise HTTPException(409, "that call is already closed")
    lines = [{"who": str(l.get("who"))[:8], "text": str(l.get("text"))[:600]} for l in body.transcript]
    ref.update({"status": "ended", "ended_at": store.now(), "duration_s": round(body.duration_s),
                "transcript": lines, "tools": body.tools[:200], "evidence": body.evidence})
    store.bump_usage(calls=1, call_seconds=round(body.duration_s))
    return {"ok": True}


@app.get("/api/coops/{coop_id}/calls")
def calls(coop_id: str, limit: int = 30, who: dict | None = Depends(user)) -> list[dict]:
    access(coop_id, who)
    q = (store.coop_ref(coop_id).collection("calls")
         .order_by("ts", direction=firestore.Query.DESCENDING).limit(max(1, min(limit, 100))))
    out = []
    for d in q.stream():
        c = d.to_dict()
        out.append({"id": d.id, "when": store.local(c["ts"]).strftime("%a %d %b %H:%M"),
                    "name": c.get("name") or "", "role": c.get("role"), "alarm_id": c.get("alarm_id"),
                    "duration_s": c.get("duration_s"), "status": c.get("status"),
                    "tools": c.get("tools", []), "evidence": c.get("evidence", 0),
                    "transcript": c.get("transcript", [])})
    return out


@app.post("/api/coops/{coop_id}/tools/{name}")
def tool(coop_id: str, name: str, args: dict, who: dict | None = Depends(user)) -> dict:
    coop, role = access(coop_id, who)
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
        if name == "coop_week":
            w = metrics.week(coop, 7)
            return {"today": w["today"], "insights": [i["text"] for i in w["insights"]],
                    "flock": w["flock"], "alarms": w["alarms"]}
        if name == "flock_status":
            st = flock.state(coop)
            if not st:
                return {"note": "The flock has not been set up yet."}
            out = {k: st[k] for k in ("age_days", "week", "phase", "phase_ends_in", "next_phase", "birds",
                                      "water_l_today")}
            out["growth"] = {k: v for k, v in st["growth"].items() if k not in ("curve", "weighs")}
            out["feed"] = {k: v for k, v in st["feed"].items() if k != "weekly"}
            out["feed_by_week"] = [{"week": w["week"], "bags": w["bags"], "usd": w["usd"]}
                                   for w in st["feed"]["weekly"]]
            out["money"] = {k: v for k, v in st["money"].items() if k != "plan"}
            return out
        if name == "sell_plan":
            st = flock.state(coop)
            if not st:
                return {"note": "The flock has not been set up yet."}
            plan = st["money"]["plan"]
            wanted = {st["money"]["best_day"], args.get("day"), 32, 35, 38, 42}
            return {"best_day": st["money"]["best_day"], "growth_basis": st["growth"]["factor_source"],
                    "options": [r for r in plan if r["day"] in wanted], "prices": st["money"]["prices"]}
        if name == "today_tasks":
            st = flock.state(coop)
            if not st:
                return {"note": "No flock set up."}
            return {"tasks": [t["text"] + " (" + t["when"] + ")" for t in st["tasks"]]}
        if name == "device_status":
            return device.health(coop)
        if name == "log_record":
            if RANK[role] < RANK["keeper"] and role != "public":
                raise HTTPException(403, "needs a keeper")
            if not coop.get("flock"):
                return {"error": "Set up the flock first."}
            row = flock.add_record(coop_id, coop["flock"]["batch"], args["kind"], args.get("quantity"),
                                   args.get("amount_usd"), args.get("note", ""), who["uid"] if who else "voice",
                                   args.get("unit", ""))
            return {"saved": True, "id": row["id"], "kind": row["kind"]}
        if name == "resolve_alarm":
            if RANK[role] < RANK["keeper"] and role != "public":
                raise HTTPException(403, "needs a keeper")
            alarms.set_status(coop_id, args["alarm_id"], "resolved", who["uid"] if who else None)
            return {"ok": True}
    except (KeyError, ValueError) as exc:
        return {"error": f"bad arguments: {exc}"}
    raise HTTPException(404, "no such tool")


# ------------------------------------------------------------------ the ring


@app.post("/api/coops/{coop_id}/push/subscribe")
def subscribe(coop_id: str, sub: dict, who: dict | None = Depends(user)) -> dict:
    access(coop_id, who)
    if "endpoint" not in sub:
        raise HTTPException(400, "not a push subscription")
    alarms.subscribe(coop_id, sub, who["uid"] if who else None)
    return {"ok": True}


class TestAlarm(BaseModel):
    kind: str = "drinker_empty"


@app.post("/api/coops/{coop_id}/alarms/test")
def test_alarm(coop_id: str, body: TestAlarm, who: dict = Depends(signed_in)) -> dict:
    access(coop_id, who, "keeper")
    alarms.resolve(coop_id, body.kind)
    latest = timeline.latest(coop_id, "vision")
    alarm = alarms.raise_alarm(coop_id, body.kind, "(test)", latest.get("frame") if latest else None)
    return {"alarm": _alarm_view(alarm) if alarm else None}


@app.post("/api/coops/{coop_id}/alarms/{alarm_id}/resolve")
def resolve_alarm(coop_id: str, alarm_id: str, who: dict = Depends(signed_in)) -> dict:
    access(coop_id, who, "keeper")
    alarms.set_status(coop_id, alarm_id, "resolved", who["uid"])
    return {"ok": True}


# ------------------------------------------------------------------ admin


@app.get("/api/admin/overview")
def admin_overview(who: dict = Depends(admin)) -> dict:
    coops = [{"id": s.id, **s.to_dict()} for s in store.db().collection("coops").stream()]
    users = store.all_users()
    by_uid = {u["uid"]: u for u in users}
    since = store.now() - timedelta(days=7)
    coop_rows = []
    for c in coops:
        calls_7d = store.coop_ref(c["id"]).collection("calls").where(
            filter=firestore.FieldFilter("ts", ">=", since)).count().get()[0][0].value
        owner = by_uid.get(c.get("owner_uid"), {})
        coop_rows.append({
            "id": c["id"], "name": c.get("name"), "owner": owner.get("email") or c.get("owner_uid"),
            "members": len(c.get("members", {})), "invites": len(c.get("invite_emails", [])),
            "birds": c.get("birds_expected"),
            "last_seen": timeline.ago(c["last_seen"]) if c.get("last_seen") else "never",
            "open_alarms": len(alarms.open_alarms(c["id"])), "calls_7d": calls_7d,
        })
    member_counts: dict[str, int] = defaultdict(int)
    for c in coops:
        for uid in c.get("members", {}):
            member_counts[uid] += 1
    user_rows = sorted(({
        "uid": u["uid"], "email": u.get("email"), "name": u.get("name"),
        "coops": member_counts.get(u["uid"], 0), "blocked": bool(u.get("blocked")),
        "admin": (u.get("email") or "") in config.ADMIN_EMAILS,
        "first_seen": store.local(u["first_seen"]).strftime("%d %b %Y") if u.get("first_seen") else "",
        "last_seen": timeline.ago(u["last_seen"]) if u.get("last_seen") else "",
    } for u in users), key=lambda r: r["email"] or "")
    days = []
    for d in store.db().collection("usage").order_by("day", direction=firestore.Query.DESCENDING).limit(14).stream():
        u = d.to_dict()
        frames, secs = u.get("frames", 0), u.get("call_seconds", 0)
        days.append({"day": u["day"], "frames": frames, "calls": u.get("calls", 0),
                     "call_minutes": round(secs / 60, 1),
                     "cost_usd": round(frames * config.GEMINI_USD_PER_FRAME
                                       + secs / 3600 * config.ASSEMBLYAI_USD_PER_HOUR, 2)})
    return {"coops": coop_rows, "users": user_rows, "usage": days[::-1]}


class Block(BaseModel):
    blocked: bool


@app.post("/api/admin/users/{uid}/block")
def admin_block(uid: str, body: Block, who: dict = Depends(admin)) -> dict:
    if uid == who["uid"]:
        raise HTTPException(400, "you cannot pause yourself")
    store.set_blocked(uid, body.blocked)
    _touched.pop(uid, None)
    return {"ok": True}


# ------------------------------------------------------------------ the watch


FEED_WORKER = os.environ.get("FEED_WORKER", "0") == "1"


async def watch() -> None:
    """Every minute: is each coop phone still alive, and does any alarm need another ring."""
    while True:
        try:
            coops = await asyncio.to_thread(lambda: [
                {"id": s.id, **s.to_dict()} for s in store.db().collection("coops").stream()])
            for coop in coops:
                if FEED_WORKER:
                    await asyncio.to_thread(feed.tick, coop)
                if (coop.get("source") or {}).get("type") in ("phone", "camera", "video"):
                    await asyncio.to_thread(alarms.check_heartbeat, coop)
                await asyncio.to_thread(alarms.re_ring, coop["id"])
        except Exception:
            log.exception("watch loop")
        await asyncio.sleep(30)


@app.on_event("startup")
async def start_watch() -> None:
    asyncio.create_task(watch())
