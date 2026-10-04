"""One-task loopback form transport without cookies, CORS or persistent access."""

import json
import math
import secrets
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from jinja2 import Environment, FileSystemLoader, select_autoescape


MAX_BODY_BYTES = 1024 * 1024
_TEMPLATES = Path(__file__).resolve().parents[2] / "templates" / "html"


class LoopbackRelay:
    """Stage one bounded answer through a same-origin task form, then close."""

    def __init__(
        self,
        request: dict,
        extractor: str,
        receive: Callable[[dict], dict],
        lifetime_seconds: float,
    ) -> None:
        if not math.isfinite(lifetime_seconds) or not 0 < lifetime_seconds <= 3600:
            raise ValueError("Relay lifetime must be positive and at most one hour")
        self._stop = threading.Event()
        self._closed = threading.Event()
        self._deadline = time.monotonic() + lifetime_seconds
        self._path = "/" + secrets.token_urlsafe(32) + "/"
        self._receive = receive
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(1)

            def log_message(self, format, *args):
                # Request paths are single-use capabilities; never log them or payloads.
                pass

            def _send(self, status: int, body: str) -> None:
                encoded = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(encoded)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("Referrer-Policy", "same-origin")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'")
                self.end_headers()
                self.wfile.write(encoded)

            def _authorized(self, submission: bool = False) -> bool:
                if self.headers.get_all("Host") != [owner.origin.removeprefix("http://")]:
                    self._send(403, "Invalid host")
                    return False
                if self.path != owner._path:
                    self._send(404, "Unknown task")
                    return False
                if submission and self.headers.get_all("Origin") != [owner.origin]:
                    self._send(403, "Invalid origin")
                    return False
                if owner._stop.is_set() or time.monotonic() >= owner._deadline:
                    self._send(410, "Task expired or closed")
                    return False
                return True

            def do_GET(self):
                if self._authorized():
                    self._send(200, owner._page)

            def do_POST(self):
                if not self._authorized(submission=True):
                    return
                lengths = self.headers.get_all("Content-Length", [])
                if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding"):
                    self._send(400, "Unsupported encoding")
                    return
                if len(lengths) != 1 or not lengths[0].isdigit():
                    self._send(400, "Invalid body length")
                    return
                size = int(lengths[0])
                if not 0 < size <= MAX_BODY_BYTES:
                    self._send(413, "Payload exceeds task transport limit")
                    return
                if self.headers.get("Content-Type", "").split(";")[0] != "application/x-www-form-urlencoded":
                    self._send(415, "Expected task form")
                    return
                try:
                    raw = self.rfile.read(size)
                    if len(raw) != size:
                        raise ValueError("Incomplete payload")
                    form = parse_qs(raw.decode("utf-8"), strict_parsing=True, max_num_fields=1)
                    if set(form) != {"payload"} or len(form["payload"]) != 1:
                        raise ValueError("Invalid form")
                    answer = json.loads(form["payload"][0])
                    if not isinstance(answer, dict):
                        raise ValueError("Expected object")
                    receipt = owner._receive(answer)
                    self._send(200, owner._render(status=receipt.get("status", "STAGED")))
                except (ValueError, UnicodeError):
                    self._send(400, "Invalid task answer")
                except Exception:
                    # A transport callback failure must not render exception payloads or locals.
                    self._send(500, "Task answer could not be staged")
                finally:
                    owner._stop.set()

        self._server = HTTPServer(("127.0.0.1", 0), Handler)
        self._server.timeout = 0.1
        self.origin = f"http://127.0.0.1:{self._server.server_port}"
        self.url = self.origin + self._path
        environment = Environment(loader=FileSystemLoader(_TEMPLATES), autoescape=select_autoescape(["html"]))
        self._template = environment.get_template("host_browser_relay.html")
        # Reuse vendored token bytes without its external font links on this capability page.
        self._theme_css = (_TEMPLATES / "_fino_theme.html").read_text().split("<style>", 1)[1].split("</style>", 1)[0]
        self._page = self._render(request=json.dumps(request, ensure_ascii=False), extractor=extractor)
        self._thread = threading.Thread(target=self._serve, name="ignis-task-relay", daemon=True)
        self._thread.start()

    def _render(self, **context) -> str:
        return self._template.render(theme_css=self._theme_css, **context)

    def _serve(self) -> None:
        try:
            while not self._stop.is_set() and time.monotonic() < self._deadline:
                self._server.handle_request()
        finally:
            self._server.server_close()
            self._closed.set()

    def close(self) -> None:
        self._stop.set()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=2)

    def wait_closed(self, timeout: float) -> bool:
        return self._closed.wait(timeout)
