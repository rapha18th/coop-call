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


def coops_for(uid: str) -> list[dict]:
    q = db().collection("coops").where(filter=firestore.FieldFilter("owner_uid", "==", uid))
    return [{"id": s.id, **s.to_dict()} for s in q.stream()]


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def create_coop(uid: str, name: str, owner_name: str, birds: int, age_days: int,
                coop_id: str | None = None) -> tuple[dict, str]:
    node_key = secrets.token_urlsafe(24)
    ref = coop_ref(coop_id) if coop_id else db().collection("coops").document()
    data = {
        "name": name,
        "owner_uid": uid,
        "owner_name": owner_name,
        "birds_expected": birds,
        "age_days_at_start": age_days,
        "created": now(),
        "node_key_hash": hash_key(node_key),
        "last_seen": None,
    }
    ref.set(data)
    return {"id": ref.id, **data}, node_key


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
