from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from PySide6.QtCore import QObject, QTimer, Signal

from ..communication.websocket_client import WebSocketClient
from ..database.sqlite_manager import SQLiteManager
from .race_state import RaceState


class RaceController(QObject):
    state_changed = Signal(object)
    log_changed = Signal(str)
    MISSION_SECONDS = {
        "lblMIssionScore1": 5,
        "lblMIssionScore2": 5,
        "lblMIssionScore3": 5,
        "lblMIssionScore4": 5,
        "lblMIssionScore5": 5,
    }

    def __init__(self, config_path: Optional[Path] = None, database: Optional[SQLiteManager] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.state = RaceState()
        self.database = database or SQLiteManager()
        self.websocket_client = WebSocketClient()
        self.websocket_client.connect()

        config_dir = Path(__file__).resolve().parents[1] / "config"
        default_config = config_dir / "team_info.json"
        if not default_config.exists():
            default_config = config_dir / "teams.json"
        self.config_path = config_path or default_config
        self.teams: List[Dict[str, Any]] = self._load_teams()
        self.team_index = 0
        self.state.mission_scores = self._default_mission_scores()
        self._run_finalized = False
        self._assign_teams()

        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)

        self.countdown_timer = QTimer(self)
        self.countdown_timer.setInterval(1000)
        self.countdown_timer.timeout.connect(self._countdown_tick)

        self._record("System ready")
        self._emit_state()

    def _load_teams(self) -> List[Dict[str, Any]]:
        with self.config_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)

        if isinstance(data, dict):
            raw_teams = data.get("teams", [])
        elif isinstance(data, list):
            raw_teams = data
        else:
            raw_teams = []

        return [self._normalize_team(team) for team in raw_teams if isinstance(team, dict)]

    def _normalize_team(self, team: Dict[str, Any]) -> Dict[str, Any]:
        # Support both legacy teams.json and team_info.json fields.
        number = team.get("number", team.get("team_no", 0))
        driver = team.get("driver")
        if not driver:
            members = team.get("members", [])
            if isinstance(members, list) and members:
                first_member = members[0]
                if isinstance(first_member, dict):
                    driver = first_member.get("name")

        return {
            "number": number,
            "team_name": team.get("team_name", "N/A"),
            "school": team.get("school", "N/A"),
            "driver": driver or "N/A",
            "car_name": team.get("car_name", "N/A"),
            "num_of_members": team.get("num_of_members", 0),
            "members": team.get("members", []),
        }

    def _assign_teams(self) -> None:
        if not self.teams:
            self.state.current_team = {"number": 0, "team_name": "No Team", "school": "N/A", "driver": "N/A"}
            self.state.next_team = dict(self.state.current_team)
            self.state.next_next_team = dict(self.state.current_team)
            return

        self.state.current_team = dict(self.teams[self.team_index % len(self.teams)])
        next_index = (self.team_index + 1) % len(self.teams)
        self.state.next_team = dict(self.teams[next_index])
        next_next_index = (self.team_index + 2) % len(self.teams)
        self.state.next_next_team = dict(self.teams[next_next_index])

    def start(self) -> None:
        self.countdown_timer.stop()
        self.timer.stop()
        self.state.status = "COUNTDOWN"
        self.state.traffic_light = "YELLOW"
        self.state.countdown = 3
        self.state.timer_running = False
        self.state.elapsed_time = 0.0
        self.state.lap = 1
        self.state.mission_scores = self._default_mission_scores()
        self.state.mission_penalty_seconds = 0.0
        self.state.final_time = None
        self.state.disqualified = False
        self._run_finalized = False
        self._record("START button pressed")
        self.countdown_timer.start()
        self._emit_state()

    def _countdown_tick(self) -> None:
        if self.state.countdown <= 1:
            self.countdown_timer.stop()
            self.state.status = "RUNNING"
            self.state.traffic_light = "GREEN"
            self.state.timer_running = True
            self.state.last_update = time.time()
            self._record("Countdown finished")
            self.timer.start()
        else:
            self.state.countdown -= 1
            self._record(f"Countdown {self.state.countdown}")
        self._emit_state()

    def stop(self, mission_scores: Optional[Dict[str, int]] = None) -> None:
        self.timer.stop()
        self.countdown_timer.stop()
        self.state.timer_running = False
        self.state.status = "FINISHED"
        self.state.traffic_light = "YELLOW"
        if mission_scores is not None:
            self.set_mission_scores(mission_scores)
        self._finalize_current_run()
        self._record("STOP button pressed")
        self._emit_state()

    def reset(self) -> None:
        self.timer.stop()
        self.countdown_timer.stop()
        self.state.timer_running = False
        self.state.elapsed_time = 0.0
        self.state.lap = 0
        self.state.status = "IDLE"
        self.state.traffic_light = "RED"
        self.state.best_lap = None
        self.state.rank = None
        self.state.penalty_points = 0
        self.state.mission_scores = self._default_mission_scores()
        self.state.mission_penalty_seconds = 0.0
        self.state.final_time = None
        self.state.disqualified = False
        self._run_finalized = False
        self._record("RESET button pressed")
        self._emit_state()

    def next_team(self) -> None:
        self.timer.stop()
        self.countdown_timer.stop()
        self.team_index = (self.team_index + 1) % max(1, len(self.teams))
        self._assign_teams()
        self.state.status = "READY"
        self.state.traffic_light = "RED"
        self.state.elapsed_time = 0.0
        self.state.lap = 0
        self.state.best_lap = None
        self.state.rank = None
        self.state.penalty_points = 0
        self.state.mission_scores = self._default_mission_scores()
        self.state.mission_penalty_seconds = 0.0
        self.state.final_time = None
        self.state.disqualified = False
        self._run_finalized = False
        self._record("NEXT team requested")
        self._emit_state()

    def retry(self) -> None:
        self.timer.stop()
        self.countdown_timer.stop()
        self.state.elapsed_time = 0.0
        self.state.lap = 0
        self.state.status = "READY"
        self.state.traffic_light = "RED"
        self.state.timer_running = False
        self.state.best_lap = None
        self.state.rank = None
        self.state.penalty_points = 0
        self.state.mission_scores = self._default_mission_scores()
        self.state.mission_penalty_seconds = 0.0
        self.state.final_time = None
        self.state.disqualified = False
        self._run_finalized = False
        self._record("RETRY button pressed")
        self._emit_state()

    def penalty(self) -> None:
        self.state.penalty_points += 1
        self._record(f"Penalty applied: {self.state.penalty_points}")
        self._emit_state()

    def disqualify(self) -> None:
        self.state.disqualified = True
        self.state.status = "FINISHED"
        self._finalize_current_run()
        self._record("DISQUALIFY button pressed")
        self._emit_state()

    def emergency(self) -> None:
        self.timer.stop()
        self.countdown_timer.stop()
        self.state.timer_running = False
        self.state.status = "EMERGENCY"
        self.state.traffic_light = "RED"
        self._record("EMERGENCY button pressed")
        self._emit_state()

    def _tick(self) -> None:
        if self.state.timer_running:
            self.state.elapsed_time = round(self.state.elapsed_time + 0.1, 2)
            self._emit_state()

    def _record(self, message: str) -> None:
        self.state.append_log(message)
        self.database.append_event(message)
        self.log_changed.emit(message)
        self.websocket_client.send_state(self.state.snapshot())

    def _emit_state(self) -> None:
        self.state.last_update = time.time()
        self.state_changed.emit(self.state)

    def get_status_badges(self) -> Dict[str, str]:
        return {
            "traffic_light_1": "🟢 OK" if self.websocket_client.is_connected else "🔴 OFF",
            "traffic_light_2": "🟢 OK" if self.websocket_client.is_connected else "🔴 OFF",
            "gate": "🟢 OK" if self.websocket_client.is_connected else "🔴 OFF",
            "wifi": "🟢 OK" if self.websocket_client.is_connected else "🔴 OFF",
            "ros2": "🟢 OK" if self.websocket_client.is_connected else "🔴 OFF",
            "win_gui": "🟢 OK",
            "broadcast": "🟢 OK",
            "database": self.database.status_text(),
        }

    def _default_mission_scores(self) -> Dict[str, int]:
        return {name: 0 for name in self.MISSION_SECONDS}

    def set_mission_scores(self, mission_scores: Dict[str, int]) -> None:
        cleaned = self._default_mission_scores()
        for name, value in mission_scores.items():
            if name in cleaned:
                cleaned[name] = max(0, int(value))
        self.state.mission_scores = cleaned

    def _mission_penalty_seconds(self) -> float:
        total = 0.0
        for name, score in self.state.mission_scores.items():
            total += float(score) * float(self.MISSION_SECONDS.get(name, 0))
        return total

    def _finalize_current_run(self) -> None:
        if self._run_finalized:
            return

        self.state.mission_penalty_seconds = self._mission_penalty_seconds()
        if self.state.disqualified:
            self.state.final_time = None
            self.state.rank = None
        else:
            self.state.final_time = round(self.state.elapsed_time + self.state.mission_penalty_seconds, 2)

        current = self.state.current_team or {}
        result = {
            "team_number": int(current.get("number", 0) or 0),
            "team_name": str(current.get("team_name", "N/A")),
            "school": str(current.get("school", "N/A")),
            "elapsed_time": float(self.state.elapsed_time),
            "mission_penalty_seconds": float(self.state.mission_penalty_seconds),
            "manual_penalty_points": int(self.state.penalty_points),
            "final_time": self.state.final_time,
            "disqualified": bool(self.state.disqualified),
            "mission_scores": dict(self.state.mission_scores),
        }

        self.database.append_race_result(result)
        if self.state.final_time is not None:
            self.state.rank = self.database.rank_for_time(self.state.final_time)
        self._run_finalized = True
