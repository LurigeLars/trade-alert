"""Bounded loopback receiver for silent Chrome-to-Windows post transfer.

The extension POSTs one validated public status. We write it atomically into
the existing Chrome inbox, preserving the same account validation, timestamp
filter, dedupe, alert history and Windows notifier as the old Downloads route.
Nothing listens on the LAN, no browser tokens/cookies are accepted or stored.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .chrome_feed import MAX_FILE_BYTES, browser_feed_path
from .truth_direct import DirectUnavailable, parse_statuses

BIND_HOST = "127.0.0.1"
BIND_PORT = 18761
INGEST_PATH = "/chrome-post"
BRIDGE_HEADER = "X-Trade-Alert-Bridge"
BRIDGE_VALUE = "1"
EXTENSION_ORIGIN = re.compile(r"^chrome-extension://[a-p]{32}$")
MAX_REQUEST_BYTES = MAX_FILE_BYTES


class _LoopbackHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


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

        def do_OPTIONS(self):
            if self.path != INGEST_PATH or not self._origin():
                self._reply(403, {"status": "DENIED"})
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin",
                             self._origin().replace("\r", "").replace("\n", ""))
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers",
                             "Content-Type, X-Trade-Alert-Bridge")
            self.send_header("Access-Control-Max-Age", "600")
            self.send_header("Content-Length", "0")
            self.send_header("Vary", "Origin")
            self.end_headers()

        def do_POST(self):
            if (self.path != INGEST_PATH or not self._origin() or
                    self.headers.get(BRIDGE_HEADER) != BRIDGE_VALUE or
                    self.headers.get("Content-Type", "").split(";")[0].strip().lower()
                    != "application/json"):
                self._reply(403, {"status": "DENIED"})
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
) -> tuple[ThreadingHTTPServer, threading.Thread]:
    """Start local-only intake; caller owns shutdown/server_close."""
    destination = directory if directory is not None else browser_feed_path()
    server = _LoopbackHTTPServer((BIND_HOST, port), _handler(destination))
    thread = threading.Thread(
        target=server.serve_forever,
        name="trade-alert-chrome-loopback",
        daemon=True,
    )
    thread.start()
    logging.info("Chrome loopback inbox listening at %s:%s", BIND_HOST, server.server_port)
    return server, thread
