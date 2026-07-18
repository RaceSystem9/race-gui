from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class SQLiteManager:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or Path(__file__).resolve().parents[1] / "database" / "race_control.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS race_events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, message TEXT NOT NULL)"
        )
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS race_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                team_number INTEGER NOT NULL,
                team_name TEXT NOT NULL,
                school TEXT NOT NULL,
                elapsed_time REAL NOT NULL,
                mission_penalty_seconds REAL NOT NULL,
                manual_penalty_points INTEGER NOT NULL,
                final_time REAL,
                disqualified INTEGER NOT NULL,
                mission_scores_json TEXT NOT NULL
            )
            """
        )
        self.connection.commit()

    def append_event(self, message: str) -> int:
        timestamp = datetime.now().strftime("%H:%M:%S")
        cursor = self.connection.execute(
            "INSERT INTO race_events (created_at, message) VALUES (?, ?)",
            (timestamp, message),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def event_count(self) -> int:
        row = self.connection.execute("SELECT COUNT(*) FROM race_events").fetchone()
        return int(row[0]) if row else 0

    def status_text(self) -> str:
        return f"🟢 OK  Last Save {datetime.now().strftime('%H:%M:%S')}  Saved {self.event_count()}"

    def append_race_result(self, result: Dict[str, Any]) -> int:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        mission_scores_json = json.dumps(result.get("mission_scores", {}), ensure_ascii=False)
        cursor = self.connection.execute(
            """
            INSERT INTO race_results (
                created_at,
                team_number,
                team_name,
                school,
                elapsed_time,
                mission_penalty_seconds,
                manual_penalty_points,
                final_time,
                disqualified,
                mission_scores_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                int(result.get("team_number", 0)),
                str(result.get("team_name", "N/A")),
                str(result.get("school", "N/A")),
                float(result.get("elapsed_time", 0.0)),
                float(result.get("mission_penalty_seconds", 0.0)),
                int(result.get("manual_penalty_points", 0)),
                None if result.get("final_time") is None else float(result.get("final_time")),
                1 if result.get("disqualified", False) else 0,
                mission_scores_json,
            ),
        )
        self.connection.commit()

        archive_path = self.db_path.with_name("race_results.json")
        if archive_path.exists():
            with archive_path.open("r", encoding="utf-8") as handle:
                archive = json.load(handle)
            if not isinstance(archive, list):
                archive = []
        else:
            archive = []
        archive.append({"created_at": timestamp, **result})
        with archive_path.open("w", encoding="utf-8") as handle:
            json.dump(archive, handle, ensure_ascii=False, indent=2)

        return int(cursor.lastrowid)

    def rank_for_time(self, final_time: float) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) + 1
            FROM race_results
            WHERE disqualified = 0
              AND final_time IS NOT NULL
              AND final_time < ?
            """,
            (float(final_time),),
        ).fetchone()
        return int(row[0]) if row else 1

    def get_latest_result_for_team(self, team_number: int) -> Optional[Dict[str, Any]]:
        row = self.connection.execute(
            """
            SELECT id, created_at, team_number, team_name, school, elapsed_time,
                   mission_penalty_seconds, manual_penalty_points, final_time,
                   disqualified, mission_scores_json
            FROM race_results
            WHERE team_number = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(team_number),),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_result_dict(row)

    def get_leaderboard(self, limit: int = 22) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            """
            WITH latest AS (
                SELECT rr.*
                FROM race_results rr
                JOIN (
                    SELECT team_number, MAX(id) AS max_id
                    FROM race_results
                    GROUP BY team_number
                ) grouped
                ON rr.team_number = grouped.team_number AND rr.id = grouped.max_id
            )
            SELECT id, created_at, team_number, team_name, school, elapsed_time,
                   mission_penalty_seconds, manual_penalty_points, final_time,
                   disqualified, mission_scores_json
            FROM latest
            ORDER BY disqualified ASC, final_time ASC, team_number ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [self._row_to_result_dict(row) for row in rows]

    def _row_to_result_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        mission_scores_raw = row["mission_scores_json"] or "{}"
        try:
            mission_scores = json.loads(mission_scores_raw)
            if not isinstance(mission_scores, dict):
                mission_scores = {}
        except json.JSONDecodeError:
            mission_scores = {}

        final_time = row["final_time"]
        return {
            "id": int(row["id"]),
            "created_at": str(row["created_at"]),
            "team_number": int(row["team_number"]),
            "team_name": str(row["team_name"]),
            "school": str(row["school"]),
            "elapsed_time": float(row["elapsed_time"]),
            "mission_penalty_seconds": float(row["mission_penalty_seconds"]),
            "manual_penalty_points": int(row["manual_penalty_points"]),
            "final_time": None if final_time is None else float(final_time),
            "disqualified": bool(row["disqualified"]),
            "mission_scores": mission_scores,
        }

    def close(self) -> None:
        self.connection.close()
