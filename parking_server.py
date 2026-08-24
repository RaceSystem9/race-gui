from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "src" / "web" / "static"
PARKING_CONFIG_PATH = ROOT_DIR / "src" / "config" / "parking_team_info.json"

CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".ico": "image/x-icon",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
}


class ParkingRequestHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        pass

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/parking-teams":
            self._send_parking_teams()
            return
        self._send_static(path)

    def _send_parking_teams(self) -> None:
        try:
            teams = json.loads(PARKING_CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(teams, list):
                raise ValueError("parking team config must be a list")
        except (OSError, ValueError, json.JSONDecodeError):
            self.send_error(500, "Parking team config unavailable")
            return
        self._send_json(teams)

    def _send_json(self, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static(self, path: str) -> None:
        if path in ("", "/"):
            path = "/parking_admin.html"
        file_path = (STATIC_DIR / path.lstrip("/")).resolve()
        if STATIC_DIR not in file_path.parents or not file_path.is_file():
            self.send_error(404, "Not Found")
            return

        body = file_path.read_bytes()
        self.send_response(200)
        self.send_header(
            "Content-Type",
            CONTENT_TYPES.get(file_path.suffix.lower(), "application/octet-stream"),
        )
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", 8080), ParkingRequestHandler)
    print("Parking web server running: http://127.0.0.1:8080/parking_admin.html")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
