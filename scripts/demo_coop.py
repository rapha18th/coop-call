"""Create the public demo coop and connect it to real footage.

    python scripts/demo_coop.py --owner-uid <your Firebase uid> [--upload]

--upload puts the broiler-house clips (Pexels licence, free to use) into Firebase Storage.
The API's feed worker then reads frames from them like a camera, through the same
pipeline as a phone. Nothing here is simulated: every reading comes from the vision
model looking at real birds, and the flock is estimated from what it sees.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

from app import config, feed, store  # noqa: E402


def reset(coop_id: str) -> None:
    ref = store.coop_ref(coop_id)
    for name in ("obs", "hours", "alarms", "ledger", "calls", "push"):
        docs = list(ref.collection(name).list_documents())
        for i in range(0, len(docs), 400):
            batch = store.db().batch()
            for d in docs[i:i + 400]:
                batch.delete(d)
            batch.commit()


def upload(folder: Path) -> None:
    for clip in feed.DEMO_CLIPS:
        local = folder / Path(clip["path"]).name
        blob = store.bucket().blob(clip["path"], chunk_size=2 * 1024 * 1024)
        if blob.exists() and blob.size == local.stat().st_size:
            print("already there", clip["path"])
            continue
        blob.upload_from_filename(str(local), content_type="video/mp4", timeout=1800)
        print("uploaded", clip["path"])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--owner-uid", required=True)
    p.add_argument("--name", default="The Hen House")
    p.add_argument("--upload", type=Path, help="folder holding the pexels-*.mp4 clips")
    a = p.parse_args()
    if a.upload:
        upload(a.upload)
    reset(config.DEMO_COOP_ID)
    store.create_coop(a.owner_uid, a.name, "the owner", 0, 0, coop_id=config.DEMO_COOP_ID)
    store.coop_ref(config.DEMO_COOP_ID).update({"birds_expected": None})
    feed.connect(config.DEMO_COOP_ID)
    print(f"demo coop '{config.DEMO_COOP_ID}' reset and connected to the video feed")


if __name__ == "__main__":
    main()
