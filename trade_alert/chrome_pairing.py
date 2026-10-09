"""User-approved local pairing for Trade Alert's Chrome -> Windows bridge.

The pairing code is valid for ten minutes and one successful exchange.
The service stores *hashes* of the long-lived token and temporary code,
not plaintext credentials. The token is returned only once to the Chrome
extension that supplies the one-time code. A local same-user compromise or
a malicious privileged extension is outside this pairing protocol's guarantees.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time

from .config import app_dir

PAIR_CODE_RE = re.compile(r"[A-F0-9]{20}\Z")
TOKEN_RE = re.compile(r"[a-f0-9]{64}\Z")
CHROME_ORIGIN_RE = re.compile(r"chrome-extension://[a-p]{32}\Z")
PAIR_TTL_SECONDS = 600
_LOCK = threading.RLock()


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _atomic_private_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".trade-alert-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            os.chmod(tmp, 0o600)
            json.dump(payload, handle, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        os.chmod(path, 0o600)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


class PairingStore:
    def __init__(self, directory: Path | None = None) -> None:
        root = directory if directory is not None else app_dir()
        self.auth_path = root / "chrome-bridge-auth.json"
        self.pending_path = root / "chrome-bridge-pairing.json"

    def issue_code(self, now: float | None = None) -> str:
        now = time.time() if now is None else now
        code = secrets.token_hex(10).upper()  # 80 bits, manual copy/paste
        with _LOCK:
            _atomic_private_json(self.pending_path, {
                "code_hash": _hash(code),
                "expires_at": now + PAIR_TTL_SECONDS,
            })
        return code

    def pair(self, origin: str | None, code: str, now: float | None = None) -> str | None:
        now = time.time() if now is None else now
        if (not isinstance(origin, str) or not CHROME_ORIGIN_RE.fullmatch(origin)
                or not isinstance(code, str) or not PAIR_CODE_RE.fullmatch(code)):
            return None
        with _LOCK:
            pending = _read_json(self.pending_path)
            code_hash = pending.get("code_hash")
            if (not isinstance(code_hash, str) or
                    not hmac.compare_digest(_hash(code), code_hash) or
                    not isinstance(pending.get("expires_at"), (int, float)) or
                    now > pending["expires_at"]):
                return None
            token = secrets.token_hex(32)  # 256-bit bearer credential
            # The paired extension ID is pinned; all older tokens are revoked.
            _atomic_private_json(self.auth_path, {
                "extension_origin": origin,
                "token_hash": _hash(token),
                "paired_at": now,
            })
            try:
                self.pending_path.unlink(missing_ok=True)
            except OSError:
                # A missing delete must not cause replay: expire the code.
                _atomic_private_json(self.pending_path, {"expires_at": 0})
            return token

    def authenticated(self, origin: str | None, token: str | None) -> bool:
        if (not isinstance(origin, str) or not CHROME_ORIGIN_RE.fullmatch(origin)
                or not isinstance(token, str) or not TOKEN_RE.fullmatch(token)):
            return False
        credentials = _read_json(self.auth_path)
        stored_origin = credentials.get("extension_origin")
        stored_hash = credentials.get("token_hash")
        return (isinstance(stored_origin, str) and origin == stored_origin
                and isinstance(stored_hash, str)
                and hmac.compare_digest(_hash(token), stored_hash))

    def paired_origin(self) -> str | None:
        origin = _read_json(self.auth_path).get("extension_origin")
        return origin if isinstance(origin, str) and CHROME_ORIGIN_RE.fullmatch(origin) else None


def main() -> None:
    cli = argparse.ArgumentParser(
        description="Generate a one-time Chrome pairing code for local Trade Alert"
    )
    cli.add_argument("command", choices=["pair"])
    args = cli.parse_args()
    if args.command == "pair":
        code = PairingStore().issue_code()
        print("Trade Alert - one-time Chrome pairing code (expires in 10 minutes):")
        print(code)
        print("Enter this code in the Trump Monitor extension popup.")
        print("Do not paste the permanent bridge token into chat, logs or GitHub.")


if __name__ == "__main__":
    main()
