from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List


def _row_to_result(row: sqlite3.Row) -> Dict[str, Any]:
    mission_scores_raw = row["mission_scores_json"] or "{}"
    try:
        mission_scores = json.loads(mission_scores_raw)
        if not isinstance(mission_scores, dict):
            mission_scores = {}
    except json.JSONDecodeError:
        mission_scores = {}

    final_time = row["final_time"]
    return {
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


def sync_db_to_json(db_path: Path, json_path: Path, backup: bool = True) -> int:
    if not db_path.exists():
        raise FileNotFoundError(f"DB file not found: {db_path}")

    if backup and json_path.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = json_path.with_name(f"{json_path.stem}.backup_{timestamp}{json_path.suffix}")
        shutil.copy2(json_path, backup_path)
        print(f"Backup created: {backup_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT created_at, round_no, team_number, team_name, school,
                   elapsed_time, mission_penalty_seconds, manual_penalty_points,
                   final_time, disqualified, mission_scores_json
            FROM race_results
            ORDER BY id ASC
            """
        ).fetchall()
    finally:
        conn.close()

    results: List[Dict[str, Any]] = [_row_to_result(row) for row in rows]
    with json_path.open("w", encoding="utf-8") as handle:
        json.dump(results, handle, ensure_ascii=False, indent=2)

    return len(results)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync race_results.json from race_control.db")
    parser.add_argument(
        "--db",
        type=Path,
        default=Path(__file__).resolve().parent / "race_control.db",
        help="Path to race_control.db",
    )
    parser.add_argument(
        "--json",
        type=Path,
        default=Path(__file__).resolve().parent / "race_results.json",
        help="Path to race_results.json",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Do not create backup of existing JSON before overwrite",
    )

    args = parser.parse_args()
    count = sync_db_to_json(args.db, args.json, backup=not args.no_backup)
    print(f"Synced {count} rows from DB to JSON")
    print(f"DB   : {args.db}")
    print(f"JSON : {args.json}")


if __name__ == "__main__":
    main()
