"""A video feed as a coop camera: real footage, read frame by frame like a phone would send it.

The demo coop plays freely licensed broiler-house footage (Pexels licence: free to use,
modify and use commercially, attribution optional). Frames are pulled at the same pace a
phone sends them and go through the same pipeline.
"""

from __future__ import annotations

import logging
import os
import random
import tempfile
import time

from . import pipeline, store

log = logging.getLogger("coop.feed")

DEMO_CLIPS = [
    {"path": "coop-call/feeds/pexels-34381836.mp4", "title": "Broiler Chickens Feeding in Farm Pen", "pexels": 34381836},
    {"path": "coop-call/feeds/pexels-34381954.mp4", "title": "Broiler Chickens Feeding in Farm Enclosure", "pexels": 34381954},
    {"path": "coop-call/feeds/pexels-39703635.mp4", "title": "Crowded Chicken Farm in Indoor Poultry Barn", "pexels": 39703635},
]
INTERVAL_S = int(os.environ.get("FEED_INTERVAL_S", "120"))
CACHE = os.path.join(tempfile.gettempdir(), "ziso-feeds")
_last: dict[str, float] = {}


def _local(path: str) -> str:
    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, os.path.basename(path))
    if not os.path.exists(out):
        store.bucket().blob(path).download_to_filename(out)
    return out


def grab(clip: dict) -> tuple[bytes, dict]:
    import cv2

    cap = cv2.VideoCapture(_local(clip["path"]))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    cap.set(cv2.CAP_PROP_POS_FRAMES, random.randint(0, max(0, n - 2)))
    ok, frame = cap.read()
    cap.release()
    if not ok:
        raise RuntimeError(f"could not read {clip['path']}")
    frame = cv2.resize(frame, (800, int(800 * frame.shape[0] / frame.shape[1])))
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(gray, (64, 48))
    readings = {
        "brightness": float(small.mean()),
        "sharpness": float(abs(small[:, 1:].astype(int) - small[:, :-1].astype(int)).mean()),
        "width": frame.shape[1], "height": frame.shape[0],
        "camera": "video", "network": "video feed", "version": "feed",
    }
    ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 75])
    return jpg.tobytes(), readings


def tick(coop: dict) -> bool:
    src = coop.get("source") or {}
    if src.get("type") != "video":
        return False
    if time.time() - _last.get(coop["id"], 0) < src.get("interval_s", INTERVAL_S):
        return False
    _last[coop["id"]] = time.time()
    clips = src.get("clips") or DEMO_CLIPS
    try:
        jpeg, readings = grab(random.choice(clips))
        pipeline.ingest(coop["id"], jpeg, readings, force=True)
        return True
    except Exception:
        log.exception("feed tick failed for %s", coop["id"])
        return False


def connect(coop_id: str, interval_s: int = INTERVAL_S) -> dict:
    src = {"type": "video", "clips": DEMO_CLIPS, "interval_s": interval_s, "label": "Broiler house footage (Pexels)",
           "connected_at": store.now()}
    store.coop_ref(coop_id).update({"source": src})
    _last.pop(coop_id, None)
    return src
