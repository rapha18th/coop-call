"""When the coop needs its owner: rules, the alarm ladder, and the ring."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from google.cloud import firestore
from pywebpush import WebPushException, webpush

from . import config, store, timeline

log = logging.getLogger("coop.alarms")

RING_EVERY = timedelta(minutes=3)
MAX_RINGS = 4
QUIET_AFTER_RESOLVE = timedelta(minutes=30)

MESSAGES = {
    "drinker_empty": "The drinker is empty.",
    "feeder_empty": "The feeder is empty.",
    "huddled": "The birds are huddled together. The brooder may have gone cold.",
    "heat": "The birds are panting and keeping to the edges. The house may be too hot.",
    "unusual": "Something unusual in the coop.",
    "node_silent": "The coop phone has gone quiet.",
}


def _alarms(coop_id: str):
    return store.coop_ref(coop_id).collection("alarms")


def open_alarms(coop_id: str) -> list[dict]:
    q = _alarms(coop_id).where(filter=firestore.FieldFilter("status", "in", ["ringing", "answered"]))
    out = [{"id": d.id, **d.to_dict()} for d in q.stream()]
    return sorted(out, key=lambda a: a["ts"], reverse=True)


def get_alarm(coop_id: str, alarm_id: str) -> dict | None:
    snap = _alarms(coop_id).document(alarm_id).get()
    return {"id": snap.id, **snap.to_dict()} if snap.exists else None


def _recently(coop_id: str, kind: str) -> bool:
    for a in open_alarms(coop_id):
        if a["kind"] == kind:
            return True
    q = (_alarms(coop_id).where(filter=firestore.FieldFilter("kind", "==", kind))
         .where(filter=firestore.FieldFilter("status", "==", "resolved")))
    cutoff = store.now() - QUIET_AFTER_RESOLVE
    return any((d.to_dict().get("resolved_at") or cutoff) > cutoff for d in q.stream())


def raise_alarm(coop_id: str, kind: str, detail: str = "", frame: str | None = None) -> dict | None:
    if _recently(coop_id, kind):
        return None
    ts = store.now()
    message = MESSAGES.get(kind, "The coop needs you.")
    if detail:
        message = f"{message} {detail}".strip()
    data = {"ts": ts, "kind": kind, "message": message, "frame": frame,
            "status": "ringing", "rings": 0, "last_ring": None}
    ref = _alarms(coop_id).document()
    ref.set(data)
    alarm = {"id": ref.id, **data}
    ring(coop_id, alarm)
    return alarm


def resolve(coop_id: str, kind: str, by: str | None = None) -> None:
    for a in open_alarms(coop_id):
        if a["kind"] == kind:
            _alarms(coop_id).document(a["id"]).update(
                {"status": "resolved", "resolved_at": store.now(), "resolved_by": by or "auto"})


def set_status(coop_id: str, alarm_id: str, status: str, by: str | None = None) -> None:
    update: dict = {"status": status}
    if status == "answered":
        update.update({"answered_at": store.now(), "answered_by": by})
    if status == "resolved":
        update.update({"resolved_at": store.now(), "resolved_by": by})
    _alarms(coop_id).document(alarm_id).update(update)


# ------------------------------------------------------------------ rules


def evaluate(coop_id: str) -> None:
    """Run after each camera reading. Two readings in a row avoid one-frame false alarms."""
    last = timeline.recent(coop_id, 3)
    if not last:
        return
    newest = last[0]
    two = last[:2] if len(last) >= 2 else []

    if newest.get("unusual"):
        raise_alarm(coop_id, "unusual", newest["unusual"], newest.get("frame"))
    elif len(two) == 2 and not any(o.get("unusual") for o in two):
        # Two clear pictures in a row: whatever it was has gone.
        resolve(coop_id, "unusual", by="camera")

    def both(pred) -> bool:
        return len(two) == 2 and all(pred(o) for o in two)

    for kind, pred in (
        ("drinker_empty", lambda o: o.get("drinker") == "empty"),
        ("feeder_empty", lambda o: o.get("feeder") == "empty"),
        ("huddled", lambda o: o.get("spread") == "huddled"),
        ("heat", lambda o: o.get("panting") and o.get("spread") in ("clustered_edges", "avoiding_area", "even")),
    ):
        if both(pred):
            since = timeline.clock(two[-1]["ts"])
            raise_alarm(coop_id, kind, f"Since about {since}.", newest.get("frame"))
        elif not pred(newest):
            resolve(coop_id, kind)


def check_heartbeat(coop: dict) -> None:
    seen: datetime | None = coop.get("last_seen")
    if seen is None:
        return
    if store.now() - seen > timedelta(seconds=config.NODE_SILENT_AFTER_S):
        raise_alarm(coop["id"], "node_silent", f"Last heard at {timeline.clock(seen)}.")
    else:
        resolve(coop["id"], "node_silent")


def re_ring(coop_id: str) -> None:
    for a in open_alarms(coop_id):
        if a["status"] != "ringing" or a.get("rings", 0) >= MAX_RINGS:
            continue
        last = a.get("last_ring")
        if last is None or store.now() - last >= RING_EVERY:
            ring(coop_id, a)


# ------------------------------------------------------------------ the ring


def _subs(coop_id: str):
    return store.coop_ref(coop_id).collection("push")


def subscribe(coop_id: str, sub: dict, uid: str | None) -> None:
    _subs(coop_id).document(store.hash_key(sub["endpoint"])[:32]).set(
        {"sub": sub, "uid": uid, "ts": store.now()})


def _ladder(coop_id: str, ring_no: int) -> set[str] | None:
    """Rings one and two reach the owner. From ring three, the whole team. None means everyone."""
    if ring_no >= 2:
        return None
    coop = store.get_coop(coop_id) or {}
    return {uid for uid, m in coop.get("members", {}).items() if m.get("role") == "owner"} or {coop.get("owner_uid")}


def ring(coop_id: str, alarm: dict) -> int:
    """Web push styled as an incoming call. Tapping it opens the call with the alarm loaded."""
    ring_no = alarm.get("rings", 0)
    _alarms(coop_id).document(alarm["id"]).update(
        {"rings": firestore.Increment(1), "last_ring": store.now()})
    reach = _ladder(coop_id, ring_no)
    if not config.VAPID_PRIVATE_KEY:
        log.warning("no VAPID key, cannot ring")
        return 0
    payload = json.dumps({
        "title": "Your coop is calling",
        "body": alarm["message"],
        "url": f"/call?coop={coop_id}&alarm={alarm['id']}",
        "tag": f"alarm-{alarm['id']}",
    })
    sent = 0
    for doc in _subs(coop_id).stream():
        if reach is not None and doc.to_dict().get("uid") not in reach:
            continue
        try:
            webpush(subscription_info=doc.to_dict()["sub"], data=payload,
                    vapid_private_key=config.VAPID_PRIVATE_KEY,
                    vapid_claims={"sub": config.VAPID_SUBJECT}, ttl=300,
                    headers={"Urgency": "high"})
            sent += 1
        except WebPushException as exc:
            status = getattr(exc.response, "status_code", None)
            if status in (404, 410):
                doc.reference.delete()
            log.warning("push failed: %s", exc)
    return sent
