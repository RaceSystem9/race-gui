from __future__ import annotations

import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse

STATIC_DIR = Path(__file__).resolve().parent / "static"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


def _guess_content_type(path: Path) -> str:
    return _CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


class _BroadcastRequestHandler(BaseHTTPRequestHandler):
    # `server` is the ThreadingHTTPServer instance below; it carries the
    # snapshot_provider callback set up by BroadcastWebServer.
    server: "_Server"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        pass  # keep the GUI's console output clean

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/state":
            self._send_json(self.server.snapshot_provider())
            return
        self._send_static(path)

    def _send_json(self, payload: Dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        relative = path.lstrip("/") or "index.html"
        file_path = (STATIC_DIR / relative).resolve()
        # Reject any path that escapes the static directory (e.g. via "..").
        if STATIC_DIR not in file_path.parents and file_path != STATIC_DIR:
            self.send_error(403, "Forbidden")
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_error(404, "Not Found")
            return
        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _guess_content_type(file_path))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    snapshot_provider: Callable[[], Dict[str, Any]]


class BroadcastWebServer:
    """Serves the broadcast web pages plus a JSON /api/state endpoint.

    Runs in a background thread so it does not block the Qt event loop.
    """

    def __init__(
        self,
        snapshot_provider: Callable[[], Dict[str, Any]],
        host: str = "0.0.0.0",
        port: int = 8080,
    ) -> None:
        self._httpd = _Server((host, port), _BroadcastRequestHandler)
        self._httpd.snapshot_provider = snapshot_provider
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._httpd.serve_forever, name="BroadcastWebServer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
            self._thread = None

    @property
    def port(self) -> int:
        return int(self._httpd.server_address[1])

    @staticmethod
    def discover_local_ip() -> str:
        # Best-effort LAN IP discovery so the operator can tell the broadcast
        # team which address to open, without requiring outbound connectivity.
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
                probe.connect(("8.8.8.8", 80))
                return str(probe.getsockname()[0])
        except OSError:
            return "127.0.0.1"
