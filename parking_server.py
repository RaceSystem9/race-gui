from __future__ import annotations

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT_DIR = Path(__file__).resolve().parent
STATIC_DIR = ROOT_DIR / "src" / "parking_web" / "static"
PARKING_CONFIG_PATH = ROOT_DIR / "src" / "parking_web" / "static" / "parking_team_info" / "parking_team_info.json"
PARKING_RESULT_DB_PATH = STATIC_DIR / "parking_result.db"
PARKING_RESULT_JSON_PATH = STATIC_DIR / "parking_result.json"
PARKING_RESULT_LOCK = threading.Lock()
PARKING_START_SCORE = 500
PARKING_PENALTIES = {
    "cone_touch": 10,
    "cone_move": 20,
    "wall_touch": 30,
    "wall_move": 50,
    "start_fail": 20,
    "time_over": 50,
    "disqualified": 1000,
}

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
        if path == "/api/parking-results":
            self._send_parking_results()
            return
        self._send_static(path)

    def do_PUT(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/parking-results":
            self.send_error(404, "Not Found")
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length > 1_000_000:
                raise ValueError("request body is too large")
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            data = _normalize_parking_data(payload)
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            self.send_error(400, "Invalid parking result data")
            return

        try:
            _save_parking_results(data)
        except OSError:
            self.send_error(500, "Unable to save parking result data")
            return
        self._send_json(data)

    def _send_parking_teams(self) -> None:
        try:
            teams = json.loads(PARKING_CONFIG_PATH.read_text(encoding="utf-8"))
            if not isinstance(teams, list):
                raise ValueError("parking team config must be a list")
        except (OSError, ValueError, json.JSONDecodeError):
            self.send_error(500, "Parking team config unavailable")
            return
        self._send_json(teams)

    def _send_parking_results(self) -> None:
        try:
            self._send_json(_load_parking_results())
        except (OSError, sqlite3.Error):
            self.send_error(500, "Parking result data unavailable")

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


def _normalize_parking_data(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise ValueError("parking result data must be an object")
    teams = payload.get("teams", [])
    scores = payload.get("scores", {})
    if not isinstance(teams, list) or not isinstance(scores, dict):
        raise ValueError("invalid parking result fields")
    final_scores = {
        str(team.get("id")): _calculate_final_score(scores.get(str(team.get("id")), {}))
        for team in teams
        if isinstance(team, dict) and team.get("id") is not None
    }
    return {"teams": teams, "scores": scores, "final_scores": final_scores}


def _calculate_final_score(score: object) -> int:
    if not isinstance(score, dict):
        return PARKING_START_SCORE

    deduction = sum(
        (int(score.get(key, 0) or 0) * penalty)
        for key, penalty in PARKING_PENALTIES.items()
        if key not in {"start_fail", "time_over", "disqualified"}
    )
    deduction += 10 if int(score.get("protrude", 0) or 0) == 1 else 20 if int(score.get("protrude", 0) or 0) >= 2 else 0
    deduction += 100 if int(score.get("park_fail", 0) or 0) == 1 else 200 if int(score.get("park_fail", 0) or 0) >= 2 else 0
    deduction += sum(
        penalty for key, penalty in PARKING_PENALTIES.items()
        if key in {"start_fail", "time_over", "disqualified"} and score.get(key)
    )
    return PARKING_START_SCORE - deduction


def _connect_result_db() -> sqlite3.Connection:
    connection = sqlite3.connect(PARKING_RESULT_DB_PATH)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS parking_results (id INTEGER PRIMARY KEY CHECK (id = 1), data_json TEXT NOT NULL)"
    )
    return connection


def _load_parking_results() -> dict[str, object]:
    with PARKING_RESULT_LOCK, _connect_result_db() as connection:
        row = connection.execute("SELECT data_json FROM parking_results WHERE id = 1").fetchone()
    if row is None:
        return {"teams": [], "scores": {}}
    return _normalize_parking_data(json.loads(row[0]))


def _save_parking_results(data: dict[str, object]) -> None:
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with PARKING_RESULT_LOCK, _connect_result_db() as connection:
        connection.execute(
            "INSERT INTO parking_results (id, data_json) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET data_json = excluded.data_json",
            (encoded,),
        )
        PARKING_RESULT_JSON_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )


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
