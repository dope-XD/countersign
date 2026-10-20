"""Spike stand-in for the engine's /api/ingest/connect/start endpoint.

Verifies the Lambda's HMAC signature, logs the payload and prints (or, with --run,
starts at once) the kvs_dump command for that contact, so the pull begins while the
call is still live and the lag numbers mean something.

    set CONNECT_HMAC_SECRET=...      (same value as the Lambda's)
    python -m integrations.connect.receiver --run --profile countersign-kvs [--widget-page widget.html]
    ngrok http 8787                  (ENGINE_URL on the Lambda = the ngrok https URL)

--widget-page also serves the web-calling widget test page at / on the same tunnel.

Stdlib only. Not part of the engine; the real endpoint gets built at the venue.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import shlex
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from integrations.connect.kvs_dump import _safe_name
from integrations.connect.lambda_start import DEFAULT_PATH, SIGNATURE_HEADER, verify

log = logging.getLogger("receiver")
MAX_BODY = 64 * 1024


def check(body: bytes, header: str | None, secret: str) -> tuple[int, dict | None]:
    """HTTP status for a start notification, and its payload when the signature holds."""
    if not verify(body, header, secret):
        return 401, None
    payload = json.loads(body)
    if not payload.get("streamArn") or not payload.get("contactId"):
        return 400, payload
    return 202, payload


def dump_command(payload: dict, out_root: Path, profile: str | None = None) -> list[str]:
    contact = str(payload["contactId"])
    cmd = [sys.executable, "-m", "integrations.connect.kvs_dump", "--stream-arn", str(payload["streamArn"]), "--contact-id", contact]
    if payload.get("startFragment"):
        cmd += ["--start-fragment", str(payload["startFragment"])]
    cmd += ["--out", str(out_root / _safe_name(contact)), "--save-mkv"]
    if profile:
        cmd += ["--profile", profile]
    return cmd


def make_handler(secret: str, path: str, out_root: Path, profile: str | None, run: bool, widget_page: Path | None = None):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Optional test page holding the Connect web-calling widget snippet, served on the same tunnel.
            if widget_page is None or self.path not in ("/", "/index.html"):
                self._reply(404)
                return
            body = widget_page.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != path:
                self._reply(404)
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                self._reply(413)
                return
            status, payload = check(self.rfile.read(length), self.headers.get(SIGNATURE_HEADER), secret)
            self._reply(status)
            if status != 202:
                log.warning("rejected start notification: %d %s", status, payload)
                return
            log.info("contact %s attributes=%s", payload["contactId"], payload.get("attributes"))
            cmd = dump_command(payload, out_root, profile)
            log.info("kvs_dump: %s", shlex.join(cmd))
            if run:
                subprocess.Popen(cmd)

        def _reply(self, status: int):
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, fmt, *args):  # route http.server's access log through logging
            log.debug(fmt, *args)

    return Handler


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Receive the Connect Lambda's start notification and kick off kvs_dump.")
    p.add_argument("--port", type=int, default=8787)
    p.add_argument("--path", default=DEFAULT_PATH)
    p.add_argument("--out", type=Path, default=Path("data/runtime/connect"))
    p.add_argument("--profile", help="AWS profile passed on to kvs_dump")
    p.add_argument("--run", action="store_true", help="start kvs_dump immediately instead of only printing the command")
    p.add_argument("--widget-page", type=Path, help="HTML file with the communications widget snippet, served at /")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    secret = os.environ.get("CONNECT_HMAC_SECRET", "")
    if not secret:
        log.error("set CONNECT_HMAC_SECRET to the Lambda's shared secret")
        return 1
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(secret, args.path, args.out, args.profile, args.run, args.widget_page))
    log.info("listening on http://127.0.0.1:%d%s", args.port, args.path)
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
