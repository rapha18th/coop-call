"""A video feed as a coop camera: real footage, read frame by frame like a phone would send it.

The demo coop plays freely licensed broiler-house footage (Pexels licence: free to use,
modify and use commercially, attribution optional). Frames are pulled at the same pace a
phone sends them and go through the same pipeline.

The red-flag feed is a tape that plays in order and loops: a bird down among the flock for
four pictures, then the house clear for the rest. A coop connected to it rings its owner
on the first picture, and the alarm closes itself once the camera sees the house clear.
One picture a minute makes a 40-minute cycle, so the bird returns well after the
30-minute quiet that follows an alarm, and every loop rings once. The frames come from
"Broilerihalli Isossakyrössä" by Oikeutta eläimille (Animal Rights Finland), CC BY 3.0,
via Wikimedia Commons, resized, without sound.
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
RED_FLAG_CLIPS = [
    {"path": "coop-call/feeds/ziso-red-flag.mp4", "title": "Broiler house, a bird down, then clear",
     "credit": "Oikeutta eläimille, CC BY 3.0, Wikimedia Commons", "sequence": True},
]
FEEDS = {
    "demo": {"clips": DEMO_CLIPS, "label": "Broiler house footage (Pexels)"},
    "red_flag": {"clips": RED_FLAG_CLIPS, "interval_s": 60,
                 "label": "Test tape: a bird down, then clear (Oikeutta eläimille, CC BY 3.0)"},
}
INTERVAL_S = int(os.environ.get("FEED_INTERVAL_S", "120"))
CACHE = os.path.join(tempfile.gettempdir(), "ziso-feeds")
_last: dict[str, float] = {}


def _local(path: str) -> str:
    os.makedirs(CACHE, exist_ok=True)
    out = os.path.join(CACHE, os.path.basename(path))
    if not os.path.exists(out):
        store.bucket().blob(path).download_to_filename(out)
    return out


def grab(clip: dict, step: int | None = None) -> tuple[bytes, dict]:
    """A random moment of a clip, or with step, the step-th frame of a tape, looping."""
    import cv2

    cap = cv2.VideoCapture(_local(clip["path"]))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    cap.set(cv2.CAP_PROP_POS_FRAMES, step % n if step is not None else random.randint(0, max(0, n - 2)))
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
        clip = random.choice(clips)
        step = None
        if clip.get("sequence"):
            # The tape keeps time from when it was connected, so a restart does not rewind it.
            since = src.get("connected_at")
            elapsed = time.time() - since.timestamp() if since else 0
            step = int(elapsed // src.get("interval_s", INTERVAL_S))
        jpeg, readings = grab(clip, step)
        pipeline.ingest(coop["id"], jpeg, readings, force=True)
        return True
    except Exception:
        log.exception("feed tick failed for %s", coop["id"])
        return False


def connect(coop_id: str, feed: str = "demo", interval_s: int = INTERVAL_S) -> dict:
    chosen = FEEDS.get(feed, FEEDS["demo"])
    src = {"type": "video", "feed": feed if feed in FEEDS else "demo", "clips": chosen["clips"],
           "interval_s": chosen.get("interval_s", interval_s), "label": chosen["label"],
           "connected_at": store.now()}
    store.coop_ref(coop_id).update({"source": src})
    _last.pop(coop_id, None)
    return src
