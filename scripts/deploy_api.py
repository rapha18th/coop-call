"""Push api/ to the Hugging Face Space and set its secrets from the repo's .env."""

import json
import os
import sys
from pathlib import Path

from huggingface_hub import HfApi

ROOT = Path(__file__).resolve().parents[1]
SPACE = os.environ.get("HF_SPACE", "rairo/ziso-api")
SECRETS = [
    "ASSEMBLYAI_API_KEY", "GEMINI_API_KEY", "VAPID_PUBLIC_KEY", "VAPID_PRIVATE_KEY",
    "WEB_ORIGINS", "WEB_URL", "DEMO_COOP_ID", "VISION_MODEL",
]


def env() -> dict:
    out = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            if v.strip():
                out[k.strip()] = v.strip()
    return out


def main() -> None:
    values = env()
    api = HfApi()
    api.create_repo(SPACE, repo_type="space", space_sdk="docker", exist_ok=True)
    for name in SECRETS:
        if values.get(name):
            api.add_space_secret(SPACE, name, values[name])
    sa = values.get("FIREBASE_SERVICE_ACCOUNT", "")
    if sa and Path(sa).exists():
        api.add_space_secret(SPACE, "FIREBASE_SERVICE_ACCOUNT",
                             json.dumps(json.loads(Path(sa).read_text(encoding="utf-8"))))
    elif not sa:
        print("warning: FIREBASE_SERVICE_ACCOUNT not set, the Space cannot reach Firebase", file=sys.stderr)
    api.upload_folder(
        folder_path=str(ROOT / "api"), repo_id=SPACE, repo_type="space",
        ignore_patterns=[".venv/*", "**/__pycache__/*", "*.pyc"],
        commit_message="Deploy Ziso API",
    )
    print(f"deployed https://huggingface.co/spaces/{SPACE}")


if __name__ == "__main__":
    main()
