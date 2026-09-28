"""Ziso bridge: turn any IP camera into a coop camera.

Runs on a small computer beside the camera (a Raspberry Pi Zero 2 W is enough). It reads
the camera's RTSP stream, decides on the spot what is worth sending, the same way the coop
phone does, adds readings from optional sensors, and posts to Ziso with the coop's pairing
key. The backend needs no camera-specific code.

    python ziso_bridge.py --pair "https://<site>/node/<coop>#<key>" --camera "rtsp://user:pass@192.168.1.20:554/stream1"

Every option can also come from the environment (ZISO_PAIR, ZISO_CAMERA, ...), which suits
a systemd service with an env file.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shlex
import signal
import subprocess
import sys
import time
from urllib.parse import urlparse

import cv2
import numpy as np
import requests

VERSION = "bridge-0.1"
DEFAULT_API = "https://rairo-ziso-api.hf.space"
SENSOR_KEYS = ("temperature_c", "humidity_pct", "ammonia_ppm")

log = logging.getLogger("ziso-bridge")


class NotPaired(Exception):
    pass


# ------------------------------------------------------------------ settings


def settings() -> argparse.Namespace:
    env = os.environ.get
    p = argparse.ArgumentParser(description="Turn an IP camera into a Ziso coop camera.")
    p.add_argument("--pair", default=env("ZISO_PAIR"),
                   help="the pairing link from the coop's Camera sheet: https://<site>/node/<coop>#<key>")
    p.add_argument("--coop", default=env("ZISO_COOP"), help="coop id, if not using --pair")
    p.add_argument("--key", default=env("ZISO_KEY"), help="pairing key, if not using --pair")
    p.add_argument("--api", default=env("ZISO_API", DEFAULT_API), help="Ziso API base URL")
    p.add_argument("--camera", default=env("ZISO_CAMERA"),
                   help="RTSP URL, a local webcam index such as 0, or a video file for testing")
    p.add_argument("--sample", type=float, default=float(env("ZISO_SAMPLE_S", "5")), help="seconds between looks")
    p.add_argument("--frame-every", type=float, default=float(env("ZISO_FRAME_S", "60")),
                   help="send a picture at least this often, in seconds")
    p.add_argument("--beat-every", type=float, default=float(env("ZISO_BEAT_S", "30")),
                   help="send a heartbeat at least this often, in seconds")
    p.add_argument("--motion", type=float, default=float(env("ZISO_MOTION", "7")),
                   help="motion score that triggers an early picture")
    p.add_argument("--sensor-cmd", default=env("ZISO_SENSOR_CMD"),
                   help='command printing JSON such as {"temperature_c": 29.5, "humidity_pct": 61, "ammonia_ppm": 12}')
    p.add_argument("--once", action="store_true", help="send one picture and exit, to test a setup")
    p.add_argument("--disconnect", action="store_true", help="unpair this bridge from the coop and exit")
    a = p.parse_args()
    if a.pair:
        u = urlparse(a.pair)
        parts = [x for x in u.path.split("/") if x]
        if len(parts) < 2 or parts[0] != "node" or not u.fragment:
            p.error("--pair must look like https://<site>/node/<coop>#<key>")
        a.coop, a.key = parts[1], u.fragment
    if not (a.coop and a.key):
        p.error("give --pair, or both --coop and --key")
    if not a.camera and not a.disconnect:
        p.error("give --camera")
    a.api = a.api.rstrip("/")
    return a


# ------------------------------------------------------------------ the camera


class Camera:
    """Keeps an RTSP stream open, reconnecting with backoff, and hands out the latest frame."""

    def __init__(self, source: str):
        self.source = int(source) if source.isdigit() else source
        self.cap: cv2.VideoCapture | None = None
        self.backoff = 2.0
        self.is_file = isinstance(self.source, str) and os.path.exists(self.source)

    def _open(self) -> bool:
        if isinstance(self.source, str) and self.source.startswith("rtsp"):
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")
        self.cap = cv2.VideoCapture(self.source)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if self.cap.isOpened():
            log.info("camera open")
            self.backoff = 2.0
            return True
        log.warning("camera not reachable, retrying in %.0f s", self.backoff)
        time.sleep(self.backoff)
        self.backoff = min(self.backoff * 2, 120)
        return False

    def latest(self) -> np.ndarray | None:
        if self.cap is None or not self.cap.isOpened():
            if not self._open():
                return None
        if self.is_file:
            ok, frame = self.cap.read()
            if not ok:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, frame = self.cap.read()
            if ok:
                # Step through a test file faster than real time.
                pos = self.cap.get(cv2.CAP_PROP_POS_FRAMES)
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, pos + int(self.cap.get(cv2.CAP_PROP_FPS) or 25) * 2)
            return frame if ok else None
        # A live stream buffers; drop the backlog so the picture is current.
        for _ in range(4):
            self.cap.grab()
        ok, frame = self.cap.retrieve()
        if not ok:
            log.warning("stream dropped, reconnecting")
            self.cap.release()
            self.cap = None
            return None
        return frame

    def close(self) -> None:
        if self.cap is not None:
            self.cap.release()


# ------------------------------------------------------------------ what the phone would notice


def look(frame: np.ndarray, prev: np.ndarray | None) -> tuple[dict, np.ndarray]:
    small = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (64, 48)).astype(np.int16)
    readings = {
        "brightness": float(small.mean()),
        "sharpness": float(np.abs(small[:, 1:] - small[:, :-1]).mean()),
        "motion": float(np.abs(small - prev).mean()) if prev is not None else 0.0,
        "width": int(frame.shape[1]),
        "height": int(frame.shape[0]),
        "camera": "rtsp",
        "network": "bridge",
        "version": VERSION,
    }
    return readings, small


def sensors(cmd: str | None) -> dict:
    if not cmd:
        return {}
    try:
        out = subprocess.run(shlex.split(cmd), capture_output=True, text=True, timeout=15, check=True).stdout
        data = json.loads(out.strip().splitlines()[-1])
        return {k: float(data[k]) for k in SENSOR_KEYS if data.get(k) is not None}
    except Exception as exc:
        log.warning("sensor read failed: %s", exc)
        return {}


def jpeg(frame: np.ndarray) -> bytes:
    h = int(800 * frame.shape[0] / frame.shape[1])
    ok, buf = cv2.imencode(".jpg", cv2.resize(frame, (800, h)), [cv2.IMWRITE_JPEG_QUALITY, 72])
    return buf.tobytes()


# ------------------------------------------------------------------ talking to Ziso


class Ziso:
    def __init__(self, api: str, coop: str, key: str):
        self.base = f"{api}/api/node/{coop}"
        self.http = requests.Session()
        self.http.headers["X-Node-Key"] = key

    def _check(self, r: requests.Response) -> dict:
        if r.status_code == 403:
            raise NotPaired("this bridge is not paired with the coop; get a new link from the Camera sheet")
        r.raise_for_status()
        return r.json()

    def beat(self, readings: dict) -> dict:
        return self._check(self.http.post(f"{self.base}/beat", json=readings, timeout=30))

    def frame(self, image: bytes, readings: dict) -> dict:
        files = {"image": ("frame.jpg", image, "image/jpeg")}
        return self._check(self.http.post(f"{self.base}/frame", files=files,
                                          data={"sensors": json.dumps(readings)}, timeout=90))

    def disconnect(self) -> dict:
        return self._check(self.http.post(f"{self.base}/disconnect", timeout=30))


# ------------------------------------------------------------------ the loop


def run(a: argparse.Namespace) -> int:
    ziso = Ziso(a.api, a.coop, a.key)
    if a.disconnect:
        ziso.disconnect()
        log.info("disconnected; pair again from the coop's Camera sheet")
        return 0

    cam = Camera(a.camera)
    stop = {"now": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(now=True))
    signal.signal(signal.SIGTERM, lambda *_: stop.update(now=True))

    prev = None
    motion_since = 0.0
    last_frame = last_beat = 0.0
    try:
        while not stop["now"]:
            started = time.time()
            frame = cam.latest()
            if frame is None:
                continue
            readings, prev = look(frame, prev)
            motion_since = max(motion_since, readings["motion"])
            now = time.time()
            want_frame = (a.once or now - last_frame >= a.frame_every
                          or (motion_since >= a.motion and now - last_frame >= 15))
            try:
                if want_frame:
                    readings.update(sensors(a.sensor_cmd))
                    readings["motion"] = motion_since
                    out = ziso.frame(jpeg(frame), readings)
                    last_frame = last_beat = now
                    motion_since = 0.0
                    seen = out.get("seen") or {}
                    log.info("picture sent%s", f": {seen.get('summary')}" if seen else f" ({out})")
                    if a.once:
                        return 0
                elif now - last_beat >= a.beat_every:
                    readings.update(sensors(a.sensor_cmd))
                    ziso.beat(readings)
                    last_beat = now
                    log.debug("heartbeat sent")
            except NotPaired:
                raise
            except requests.RequestException as exc:
                log.warning("Ziso unreachable, still watching: %s", exc)
            time.sleep(max(0.0, a.sample - (time.time() - started)))
    except NotPaired as exc:
        log.error("%s", exc)
        return 2
    finally:
        cam.close()
    return 0


def main() -> None:
    logging.basicConfig(level=os.environ.get("ZISO_LOG", "INFO"), format="%(asctime)s %(message)s")
    sys.exit(run(settings()))


if __name__ == "__main__":
    main()
