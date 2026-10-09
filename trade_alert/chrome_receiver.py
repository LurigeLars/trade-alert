"""Bounded loopback receiver for silent Chrome-to-Windows post transfer.

The paired Chrome extension POSTs one validated public status with a
256-bit bearer token. A manually entered, single-use code pins its extension
origin. Writes use the existing inbox and downstream validator. No LAN bind,
browser cookies or account credentials. This does not protect against a
compromised same-user Windows account.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .chrome_feed import MAX_FILE_BYTES, browser_feed_path
from .chrome_pairing import PairingStore
from .truth_direct import DirectUnavailable, parse_statuses

BIND_HOST = "127.0.0.1"
BIND_PORT = 18761
INGEST_PATH = "/chrome-post"
PAIR_PATH = "/chrome-pair"
TOKEN_HEADER = "X-Trade-Alert-Token"
BRIDGE_HEADER = "X-Trade-Alert-Bridge"
BRIDGE_VALUE = "1"
EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")
MAX_REQUEST_BYTES = MAX_FILE_BYTES


class _LoopbackHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, *, pairing: PairingStore):
        self.pairing = pairing
        self._limit_lock = threading.Lock()
        self._limits: dict[tuple[str, str], list[float]] = {}
        self._slots = threading.BoundedSemaphore(8)
        super().__init__(address, handler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(3)
        return connection, address

    def process_request(self, request, client_address):
        if not self._slots.acquire(blocking=False):
            request.close()
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._slots.release()

    def limited(self, category: str, key: str, max_hits: int, window: int) -> bool:
        now = time.monotonic()
        with self._limit_lock:
            # Bounded state: only a handful of local origins are expected.
            if len(self._limits) > 64:
                self._limits.clear()
            k = (category, key)
            hits = [t for t in self._limits.get(k, []) if t > now - window]
            if len(hits) >= max_hits:
                self._limits[k] = hits
                return True
            hits.append(now)
            self._limits[k] = hits
            return False


def _is_extension_origin(value: str | None) -> bool:
    return isinstance(value, str) and EXTENSION_ORIGIN.fullmatch(value) is not None


def _persist_post(data: bytes, *, folder: Path) -> str:
    if not 1 <= len(data) <= MAX_REQUEST_BYTES:
        raise ValueError("bad payload length")
    raw = json.loads(data)
    if not isinstance(raw, dict):
        raise ValueError("post must be an object")
    # Shared canonical validation, independent of untrusted extension claims.
    parsed = parse_statuses(
        json.dumps([raw], ensure_ascii=False).encode("utf-8"),
        fetched_at=0.0,
    )
    if len(parsed.posts) != 1 or str(raw.get("id")) != parsed.posts[0].post_id:
        raise ValueError("unverified public status")
    post_id = parsed.posts[0].post_id
    folder.mkdir(parents=True, exist_ok=True)
    # Atomic rename prevents the independent one-second scanner from seeing
    # a partial JSON file. This directory is an untrusted local inbox.
    fd, temp = tempfile.mkstemp(prefix=".incoming-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temp, folder / f"post-{post_id}.json")
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return post_id


def _handler(folder: Path):
    class Handler(BaseHTTPRequestHandler):
        server_version = "TradeAlertLoopback/1"

        def log_message(self, fmt, *args):
            # No raw post contents, cookies or URL arguments in logs.
            logging.debug("Chrome bridge local request %s", self.command)

        def _origin(self) -> str | None:
            origin = self.headers.get("Origin")
            return origin if _is_extension_origin(origin) else None

        def _reply(self, status: int, body: dict) -> None:
            payload = json.dumps(body, separators=(",", ":")).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            origin = self._origin()
            if origin:
                self.send_header("Access-Control-Allow-Origin",
                                 origin.replace("\r", "").replace("\n", ""))
                self.send_header("Vary", "Origin")
            self.end_headers()
            self.wfile.write(payload)

        def _allowed_origin(self):
            origin = self._origin()
            if not origin:
                return None
            bound_origin = self.server.pairing.paired_origin()
            if self.path == INGEST_PATH and bound_origin and origin != bound_origin:
                return None
            return origin

        def do_OPTIONS(self):
            origin = self._allowed_origin()
            if self.path not in (INGEST_PATH, PAIR_PATH) or origin is None:
                self._reply(403, {"status": "DENIED"})
                return
            if self.server.limited("preflight", origin, 120, 60):
                self._reply(429, {"status": "RATE_LIMITED"})
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin",
                             origin.replace("\r", "").replace("\n", ""))
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, X-Trade-Alert-Bridge, X-Trade-Alert-Token")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.send_header("Vary", "Origin")
            self.end_headers()

        def do_POST(self):
            origin = self._allowed_origin()
            if (self.path not in (INGEST_PATH, PAIR_PATH) or
                    origin is None or
                    self.headers.get(BRIDGE_HEADER) != BRIDGE_VALUE or
                    self.headers.get("Content-Type", "").split(";")[0].strip().lower()
                    != "application/json"):
                self._reply(403, {"status": "DENIED"})
                return
            if self.server.limited("requests", origin, 180, 60):
                self._reply(429, {"status": "RATE_LIMITED"})
                return
            if self.path == PAIR_PATH and self.server.limited("pair", "all", 5, 600):
                self._reply(429, {"status": "PAIR_LIMITED"})
                return
            if self.path == INGEST_PATH:
                token = self.headers.get(TOKEN_HEADER)
                if not self.server.pairing.authenticated(origin, token):
                    # Block brute force even though bearer tokens have 256 bits.
                    if self.server.limited("unauthorized", "all", 12, 60):
                        self._reply(429, {"status": "RATE_LIMITED"})
                    else:
                        self._reply(401, {"status": "PAIR_REQUIRED"})
                    return
            try:
                size = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                size = 0
            if not 1 <= size <= MAX_REQUEST_BYTES:
                self._reply(413, {"status": "INVALID_SIZE"})
                return
            data = self.rfile.read(size)
            if len(data) != size:
                self._reply(400, {"status": "INCOMPLETE"})
                return
            if self.path == PAIR_PATH:
                try:
                    payload = json.loads(data)
                    code = payload.get("code") if isinstance(payload, dict) else None
                    token = self.server.pairing.pair(origin, code)
                except (ValueError, UnicodeError):
                    token = None
                if not token:
                    self._reply(403, {"status": "INVALID_PAIRING_CODE"})
                    return
                self._reply(200, {"status": "PAIRED", "token": token})
                return
            try:
                post_id = _persist_post(data, folder=folder)
            except (ValueError, UnicodeError, json.JSONDecodeError,
                    DirectUnavailable, OSError) as error:
                logging.warning("Chrome loopback transfer rejected: %s",
                                type(error).__name__)
                self._reply(400, {"status": "INVALID"})
                return
            self._reply(200, {"status": "QUEUED", "id": post_id})

    return Handler


def start_chrome_receiver(
    *, port: int = BIND_PORT, directory: Path | None = None,
    auth_directory: Path | None = None,
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start local-only authenticated intake; caller owns shutdown."""
    destination = directory if directory is not None else browser_feed_path()
    server = _LoopbackHTTPServer(
        (BIND_HOST, port), _handler(destination),
        pairing=PairingStore(auth_directory),
    )
    thread = threading.Thread(
        target=server.serve_forever,
        name="trade-alert-chrome-loopback",
        daemon=True,
    )
    thread.start()
    logging.info("Chrome loopback inbox listening at %s:%s", BIND_HOST, server.server_port)
    return server, thread
