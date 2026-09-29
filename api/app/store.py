"""Firebase: Firestore for the timeline, Storage for frames, Auth for owners."""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import firebase_admin
from firebase_admin import auth as fb_auth
from firebase_admin import credentials, storage
from google.cloud import firestore

from . import config


@lru_cache
def app() -> firebase_admin.App:
    info = config.service_account()
    cred = credentials.Certificate(info) if info else credentials.ApplicationDefault()
    return firebase_admin.initialize_app(
        cred, {"projectId": config.FIREBASE_PROJECT, "storageBucket": config.STORAGE_BUCKET}
    )


@lru_cache
def db() -> firestore.Client:
    cred = app().credential.get_credential()
    return firestore.Client(
        project=config.FIREBASE_PROJECT, credentials=cred, database=config.FIRESTORE_DATABASE
    )


def bucket():
    return storage.bucket(app=app())


def verify_id_token(token: str) -> dict:
    return fb_auth.verify_id_token(token, app=app())


# ------------------------------------------------------------------ coops


def coop_ref(coop_id: str):
    return db().collection("coops").document(coop_id)


def get_coop(coop_id: str) -> dict | None:
    snap = coop_ref(coop_id).get()
    return {"id": snap.id, **snap.to_dict()} if snap.exists else None


def coops_for(uid: str, email: str = "", name: str = "") -> list[dict]:
    """Coops this person owns or belongs to. Pending email invites are claimed here."""
    col = db().collection("coops")
    found = {s.id: {"id": s.id, **s.to_dict()} for s in
             col.where(filter=firestore.FieldFilter("member_uids", "array_contains", uid)).stream()}
    for s in col.where(filter=firestore.FieldFilter("owner_uid", "==", uid)).stream():
        found.setdefault(s.id, {"id": s.id, **s.to_dict()})
    email = email.lower()
    if email:
        for s in col.where(filter=firestore.FieldFilter("invite_emails", "array_contains", email)).stream():
            coop = {"id": s.id, **s.to_dict()}
            invite = coop.get("invites", {}).get(_email_key(email), {})
            claim_invite(s.id, uid, email, invite.get("role", "viewer"), name)
            found[s.id] = get_coop(s.id)
    return list(found.values())


def backfill_owner(coop: dict, claims: dict) -> dict:
    """Coops made before teams existed get their owner written in as the first member."""
    if coop.get("members") or claims.get("uid") != coop.get("owner_uid"):
        return coop
    member = {"role": "owner", "name": claims.get("name", ""), "email": (claims.get("email") or "").lower(), "order": 0}
    coop_ref(coop["id"]).update({"members": {claims["uid"]: member}, "member_uids": [claims["uid"]],
                                 "invites": {}, "invite_emails": []})
    return {**coop, "members": {claims["uid"]: member}, "member_uids": [claims["uid"]]}


def _email_key(email: str) -> str:
    return "e" + hashlib.sha256(email.lower().encode()).hexdigest()[:16]


def invite(coop_id: str, email: str, role: str, by: str) -> None:
    email = email.lower()
    coop_ref(coop_id).update({
        f"invites.{_email_key(email)}": {"email": email, "role": role, "by": by, "ts": now()},
        "invite_emails": firestore.ArrayUnion([email]),
    })


def claim_invite(coop_id: str, uid: str, email: str, role: str, name: str) -> None:
    coop = get_coop(coop_id) or {}
    order = len(coop.get("members", {}))
    coop_ref(coop_id).update({
        f"members.{uid}": {"role": role, "name": name, "email": email, "order": order},
        "member_uids": firestore.ArrayUnion([uid]),
        f"invites.{_email_key(email)}": firestore.DELETE_FIELD,
        "invite_emails": firestore.ArrayRemove([email]),
    })


def set_member(coop_id: str, uid: str, role: str | None) -> None:
    if role is None:
        coop_ref(coop_id).update({f"members.{uid}": firestore.DELETE_FIELD,
                                  "member_uids": firestore.ArrayRemove([uid])})
    else:
        coop_ref(coop_id).update({f"members.{uid}.role": role})


def cancel_invite(coop_id: str, email: str) -> None:
    email = email.lower()
    coop_ref(coop_id).update({f"invites.{_email_key(email)}": firestore.DELETE_FIELD,
                              "invite_emails": firestore.ArrayRemove([email])})


# ------------------------------------------------------------------ people


def touch_user(claims: dict) -> dict:
    ref = db().collection("users").document(claims["uid"])
    snap = ref.get()
    data = snap.to_dict() if snap.exists else {"first_seen": now(), "blocked": False}
    data.update({"email": (claims.get("email") or "").lower(), "name": claims.get("name", ""),
                 "photo": claims.get("picture", ""), "last_seen": now()})
    ref.set(data)
    return data


def get_user(uid: str) -> dict | None:
    snap = db().collection("users").document(uid).get()
    return snap.to_dict() if snap.exists else None


def all_users() -> list[dict]:
    return [{"uid": s.id, **s.to_dict()} for s in db().collection("users").stream()]


def set_blocked(uid: str, blocked: bool) -> None:
    db().collection("users").document(uid).set({"blocked": blocked}, merge=True)


def bump_usage(**counts: float) -> None:
    day = local(now()).strftime("%Y%m%d")
    db().collection("usage").document(day).set(
        {"day": day, **{k: firestore.Increment(v) for k, v in counts.items()}}, merge=True)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_coop(uid: str, name: str, owner_name: str, birds: int | None, age_days: int | None,
                coop_id: str | None = None, owner_email: str = "") -> tuple[dict, str]:
    node_key = secrets.token_urlsafe(24)
    ref = coop_ref(coop_id) if coop_id else db().collection("coops").document()
    data = {
        "name": name,
        "owner_uid": uid,
        "owner_name": owner_name,
        "member_uids": [uid],
        "members": {uid: {"role": "owner", "name": owner_name, "email": owner_email, "order": 0}},
        "invites": {},
        "invite_emails": [],
        "birds_expected": birds,
        "age_days_at_start": age_days,
        "created": now(),
        "node_key_hash": hash_key(node_key),
        "last_seen": None,
    }
    ref.set(data)
    return {"id": ref.id, **data}, node_key


def delete_coop(coop_id: str) -> dict:
    """Every document under the coop, then every picture it stored."""
    frames = 0
    for blob in bucket().list_blobs(prefix=f"coop-call/{coop_id}/"):
        blob.delete()
        frames += 1
    db().recursive_delete(coop_ref(coop_id))
    return {"frames": frames}


def rotate_node_key(coop_id: str) -> str:
    node_key = secrets.token_urlsafe(24)
    coop_ref(coop_id).update({"node_key_hash": hash_key(node_key)})
    return node_key


def coop_for_node_key(coop_id: str, node_key: str) -> dict | None:
    coop = get_coop(coop_id)
    if coop and secrets.compare_digest(coop.get("node_key_hash", ""), hash_key(node_key)):
        return coop
    return None


# ------------------------------------------------------------------ time


def now() -> datetime:
    return datetime.now(timezone.utc)


def local(ts: datetime) -> datetime:
    return ts.astimezone(config.TZ)


def hour_key(ts: datetime) -> str:
    return local(ts).strftime("%Y%m%d%H")


# ------------------------------------------------------------------ frames


def save_frame(coop_id: str, ts: datetime, jpeg: bytes) -> str:
    path = f"coop-call/{coop_id}/frames/{local(ts).strftime('%Y%m%d')}/{ts.strftime('%H%M%S%f')}.jpg"
    blob = bucket().blob(path)
    blob.upload_from_string(jpeg, content_type="image/jpeg")
    return path


def frame_url(path: str | None, minutes: int = 60) -> str | None:
    if not path:
        return None
    blob = bucket().blob(path)
    return blob.generate_signed_url(expiration=timedelta(minutes=minutes), version="v4")
