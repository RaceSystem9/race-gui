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
                round_no INTEGER NOT NULL DEFAULT 1,
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
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS final_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._ensure_race_results_schema()
        self.connection.commit()

    def _ensure_race_results_schema(self) -> None:
        columns = self.connection.execute("PRAGMA table_info(race_results)").fetchall()
        column_names = {str(row[1]) for row in columns}
        if "round_no" not in column_names:
            self.connection.execute("ALTER TABLE race_results ADD COLUMN round_no INTEGER NOT NULL DEFAULT 1")

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
        round_no = int(result.get("round_no", 1) or 1)
        team_number = int(result.get("team_number", 0))

        update_cursor = self.connection.execute(
            """
            UPDATE race_results
            SET created_at = ?,
                team_name = ?,
                school = ?,
                elapsed_time = ?,
                mission_penalty_seconds = ?,
                manual_penalty_points = ?,
                final_time = ?,
                disqualified = ?,
                mission_scores_json = ?
            WHERE team_number = ? AND round_no = ?
            """,
            (
                timestamp,
                str(result.get("team_name", "N/A")),
                str(result.get("school", "N/A")),
                float(result.get("elapsed_time", 0.0)),
                float(result.get("mission_penalty_seconds", 0.0)),
                int(result.get("manual_penalty_points", 0)),
                None if result.get("final_time") is None else float(result.get("final_time")),
                1 if result.get("disqualified", False) else 0,
                mission_scores_json,
                team_number,
                round_no,
            ),
        )

        if update_cursor.rowcount and int(update_cursor.rowcount) > 0:
            row = self.connection.execute(
                "SELECT id FROM race_results WHERE team_number = ? AND round_no = ? LIMIT 1",
                (team_number, round_no),
            ).fetchone()
            saved_id = int(row["id"]) if row else 0
        else:
            cursor = self.connection.execute(
                """
                INSERT INTO race_results (
                    created_at,
                    round_no,
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
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    timestamp,
                    round_no,
                    team_number,
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
            saved_id = int(cursor.lastrowid)
        self.connection.commit()

        archive_path = self.db_path.with_name("race_results.json")
        if archive_path.exists():
            with archive_path.open("r", encoding="utf-8") as handle:
                archive = json.load(handle)
            if not isinstance(archive, list):
                archive = []
        else:
            archive = []
        updated = False
        for item in archive:
            item_team = int(item.get("team_number", 0) or 0)
            item_round = int(item.get("round_no", 1) or 1)
            if item_team == team_number and item_round == round_no:
                item.clear()
                item.update({"created_at": timestamp, **result, "round_no": round_no})
                updated = True
                break
        if not updated:
            archive.append({"created_at": timestamp, **result, "round_no": round_no})
        with archive_path.open("w", encoding="utf-8") as handle:
            json.dump(archive, handle, ensure_ascii=False, indent=2)

        return saved_id

    def rank_for_time(self, final_time: float, round_no: Optional[int] = None) -> int:
        if round_no is None:
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
        else:
            row = self.connection.execute(
                """
                SELECT COUNT(*) + 1
                FROM race_results
                WHERE disqualified = 0
                  AND final_time IS NOT NULL
                  AND round_no = ?
                  AND final_time < ?
                """,
                (int(round_no), float(final_time)),
            ).fetchone()
        return int(row[0]) if row else 1

    def get_latest_result_for_team(self, team_number: int, round_no: Optional[int] = None) -> Optional[Dict[str, Any]]:
        if round_no is None:
            row = self.connection.execute(
                """
                SELECT id, created_at, round_no, team_number, team_name, school, elapsed_time,
                       mission_penalty_seconds, manual_penalty_points, final_time,
                       disqualified, mission_scores_json
                FROM race_results
                WHERE team_number = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(team_number),),
            ).fetchone()
        else:
            row = self.connection.execute(
                """
                SELECT id, created_at, round_no, team_number, team_name, school, elapsed_time,
                       mission_penalty_seconds, manual_penalty_points, final_time,
                       disqualified, mission_scores_json
                FROM race_results
                WHERE team_number = ? AND round_no = ?
                ORDER BY id DESC
                LIMIT 1
                """,
                (int(team_number), int(round_no)),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_result_dict(row)

    def get_leaderboard(self, limit: int = 22, round_no: Optional[int] = None) -> List[Dict[str, Any]]:
        if round_no is None:
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
                SELECT id, created_at, round_no, team_number, team_name, school, elapsed_time,
                       mission_penalty_seconds, manual_penalty_points, final_time,
                       disqualified, mission_scores_json
                FROM latest
                ORDER BY disqualified ASC, final_time ASC, team_number ASC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        else:
            rows = self.connection.execute(
                """
                WITH latest AS (
                    SELECT rr.*
                    FROM race_results rr
                    JOIN (
                        SELECT team_number, round_no, MAX(id) AS max_id
                        FROM race_results
                        WHERE round_no = ?
                        GROUP BY team_number, round_no
                    ) grouped
                    ON rr.team_number = grouped.team_number
                    AND rr.round_no = grouped.round_no
                    AND rr.id = grouped.max_id
                )
                SELECT id, created_at, round_no, team_number, team_name, school, elapsed_time,
                       mission_penalty_seconds, manual_penalty_points, final_time,
                       disqualified, mission_scores_json
                FROM latest
                ORDER BY disqualified ASC, final_time ASC, team_number ASC
                LIMIT ?
                """,
                (int(round_no), int(limit)),
            ).fetchall()
        return [self._row_to_result_dict(row) for row in rows]

    def get_final_leaderboard_best_of_two(self, limit: int = 22) -> List[Dict[str, Any]]:
        rows = self.connection.execute(
            """
            WITH best AS (
                SELECT
                    team_number,
                    MIN(final_time) AS best_final_time
                FROM race_results
                WHERE disqualified = 0
                  AND final_time IS NOT NULL
                GROUP BY team_number
            )
            SELECT rr.id, rr.created_at, rr.round_no, rr.team_number, rr.team_name, rr.school,
                   rr.elapsed_time, rr.mission_penalty_seconds, rr.manual_penalty_points,
                   rr.final_time, rr.disqualified, rr.mission_scores_json
            FROM race_results rr
            JOIN best b
              ON rr.team_number = b.team_number
             AND rr.final_time = b.best_final_time
            ORDER BY rr.final_time ASC, rr.team_number ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()
        return [self._row_to_result_dict(row) for row in rows]

    def save_final_snapshot(self, rows: List[Dict[str, Any]]) -> int:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        payload_json = json.dumps(rows, ensure_ascii=False)
        cursor = self.connection.execute(
            "INSERT INTO final_snapshots (created_at, payload_json) VALUES (?, ?)",
            (timestamp, payload_json),
        )
        self.connection.commit()
        return int(cursor.lastrowid)

    def get_latest_final_snapshot(self) -> Optional[Dict[str, Any]]:
        row = self.connection.execute(
            "SELECT id, created_at, payload_json FROM final_snapshots ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return self._row_to_snapshot_dict(row)

    def get_final_snapshot(self, snapshot_id: int) -> Optional[Dict[str, Any]]:
        row = self.connection.execute(
            "SELECT id, created_at, payload_json FROM final_snapshots WHERE id = ? LIMIT 1",
            (int(snapshot_id),),
        ).fetchone()
        if row is None:
            return None
        return self._row_to_snapshot_dict(row)

    def get_team_progress_map(self) -> Dict[int, Dict[str, bool]]:
        rows = self.connection.execute(
            """
            SELECT
                team_number,
                MAX(CASE WHEN round_no = 1 THEN 1 ELSE 0 END) AS round1_done,
                MAX(CASE WHEN round_no = 2 THEN 1 ELSE 0 END) AS round2_done
            FROM race_results
            GROUP BY team_number
            """
        ).fetchall()

        progress: Dict[int, Dict[str, bool]] = {}
        for row in rows:
            team_no = int(row["team_number"])
            progress[team_no] = {
                "round1_done": bool(row["round1_done"]),
                "round2_done": bool(row["round2_done"]),
                "final_confirmed": False,
            }

        latest_snapshot = self.get_latest_final_snapshot()
        if latest_snapshot:
            snapshot_rows = latest_snapshot.get("rows", [])
            if isinstance(snapshot_rows, list):
                for item in snapshot_rows:
                    if not isinstance(item, dict):
                        continue
                    team_no = int(item.get("team_number", 0) or 0)
                    if team_no <= 0:
                        continue
                    if team_no not in progress:
                        progress[team_no] = {
                            "round1_done": False,
                            "round2_done": False,
                            "final_confirmed": True,
                        }
                    else:
                        progress[team_no]["final_confirmed"] = True

        return progress

    def _row_to_snapshot_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        payload_raw = row["payload_json"] or "[]"
        try:
            payload = json.loads(payload_raw)
            if not isinstance(payload, list):
                payload = []
        except json.JSONDecodeError:
            payload = []

        return {
            "id": int(row["id"]),
            "created_at": str(row["created_at"]),
            "rows": payload,
        }

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
            "round_no": int(row["round_no"]) if row["round_no"] is not None else 1,
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
