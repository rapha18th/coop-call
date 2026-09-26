"""Generate the Web Push key pair that lets the coop ring the owner's phone.

Writes VAPID_PUBLIC_KEY and VAPID_PRIVATE_KEY into the repo's .env if they are missing.
"""

import base64
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

ENV = Path(__file__).resolve().parents[1] / ".env"


def b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def main() -> None:
    text = ENV.read_text(encoding="utf-8") if ENV.exists() else ""
    if "VAPID_PRIVATE_KEY=" in text and not any(
        line.strip() == "VAPID_PRIVATE_KEY=" for line in text.splitlines()
    ):
        print("VAPID keys already set")
        return
    key = ec.generate_private_key(ec.SECP256R1())
    private = b64(key.private_numbers().private_value.to_bytes(32, "big"))
    public = b64(key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint))
    lines = [l for l in text.splitlines() if not l.startswith(("VAPID_PRIVATE_KEY=", "VAPID_PUBLIC_KEY="))]
    lines += [f"VAPID_PUBLIC_KEY={public}", f"VAPID_PRIVATE_KEY={private}"]
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("wrote VAPID keys to .env")


if __name__ == "__main__":
    main()
