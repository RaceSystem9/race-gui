from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


class SQLiteManager:
    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or Path(__file__).resolve().parents[1] / "database" / "race_control.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path)
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS race_events (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at TEXT NOT NULL, message TEXT NOT NULL)"
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

    def close(self) -> None:
        self.connection.close()
