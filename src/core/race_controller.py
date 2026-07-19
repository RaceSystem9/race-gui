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
    leaderboard_changed = Signal()
    MISSION_SECONDS = {
        "lblMIssionScore1": 5,
        "lblMIssionScore2": 5,
        "lblMIssionScore3": 5,
        "lblMIssionScore4": 5,
        "lblMIssionScore5": 5,
    }
    VIEW_MODE_ROUND1 = "ROUND1"
    VIEW_MODE_ROUND2 = "ROUND2"
    VIEW_MODE_FINAL = "FINAL"

    def __init__(self, config_path: Optional[Path] = None, database: Optional[SQLiteManager] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.state = RaceState()
        self.database = database or SQLiteManager()
        self.websocket_client = WebSocketClient()
        self.websocket_client.connection_changed.connect(self._on_connection_changed)
        self.websocket_client.ack_status_changed.connect(self._on_ack_status_changed)
        self.websocket_client.connect()
        self._last_sent_traffic_light: Optional[str] = None

        config_dir = Path(__file__).resolve().parents[1] / "config"
        default_config = config_dir / "team_info.json"
        if not default_config.exists():
            default_config = config_dir / "teams.json"
        self.config_path = config_path or default_config
        self.teams: List[Dict[str, Any]] = self._load_teams()
        self.team_index = 0
        self.state.mission_scores = self._default_mission_scores()
        self.current_round = 1
        self.view_mode = self.VIEW_MODE_ROUND1
        latest_snapshot = self.database.get_latest_final_snapshot()
        self.final_snapshot_id = int(latest_snapshot["id"]) if latest_snapshot else None
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
        # Emit leaderboard update immediately after persistence.
        self.leaderboard_changed.emit()
        self._emit_state()
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

    def penalty(self, mission_scores: Optional[Dict[str, int]] = None) -> None:
        if mission_scores is not None:
            self.set_mission_scores(mission_scores)
        self.state.penalty_points += 1
        if self.state.status == "FINISHED" or self._run_finalized:
            self._finalize_current_run(force_update=True)
            self.leaderboard_changed.emit()
            self._emit_state()
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

    def _emit_state(self) -> None:
        self.state.last_update = time.time()
        self.websocket_client.send_state(self.state.snapshot())
        self._sync_traffic_light_command()
        self.state_changed.emit(self.state)

    def _sync_traffic_light_command(self) -> None:
        current_light = str(self.state.traffic_light).upper()
        if current_light == self._last_sent_traffic_light:
            return
        self.websocket_client.send_command("set_traffic_light", {"color": current_light})
        self._last_sent_traffic_light = current_light

    def _on_connection_changed(self, connected: bool) -> None:
        if connected:
            # Force light command resend after reconnect.
            self._last_sent_traffic_light = None
            self.websocket_client.send_state(self.state.snapshot())
            self._sync_traffic_light_command()
        self.state_changed.emit(self.state)

    def _on_ack_status_changed(self, _ok: bool) -> None:
        self.state_changed.emit(self.state)

    def get_status_badges(self) -> Dict[str, str]:
        connected = self.websocket_client.is_connected
        ack_state = self.websocket_client.ack_state

        if not connected:
            wifi_badge = "🔴 OFF"
            ros2_badge = "🔴 OFF"
        elif ack_state == "ok":
            wifi_badge = "🟢 OK"
            ros2_badge = "🟢 OK"
        elif ack_state == "pending":
            wifi_badge = "🟡 WAIT"
            ros2_badge = "🟡 WAIT"
        elif ack_state == "failed":
            wifi_badge = "🟡 WARN"
            ros2_badge = "🔴 OFF"
        else:
            wifi_badge = "🟢 OK"
            ros2_badge = "🟡 READY"

        return {
            "traffic_light_1": "🟢 OK" if connected else "🔴 OFF",
            "traffic_light_2": "🟢 OK" if connected else "🔴 OFF",
            "gate": "🟢 OK" if connected else "🔴 OFF",
            "wifi": wifi_badge,
            "ros2": ros2_badge,
            "win_gui": "🟢 OK",
            "broadcast": "🟢 OK",
            "database": self.database.status_text(),
        }

    def get_round_leaderboard(self, limit: int = 22) -> List[Dict[str, Any]]:
        return self.database.get_leaderboard(limit=limit, round_no=self.current_round)

    def get_final_leaderboard(self, limit: int = 22) -> List[Dict[str, Any]]:
        return self.database.get_final_leaderboard_best_of_two(limit=limit)

    def get_active_leaderboard(self, limit: int = 22) -> List[Dict[str, Any]]:
        if self.view_mode == self.VIEW_MODE_ROUND1:
            return self.database.get_leaderboard(limit=limit, round_no=1)
        if self.view_mode == self.VIEW_MODE_ROUND2:
            return self.database.get_leaderboard(limit=limit, round_no=2)
        if self.final_snapshot_id is not None:
            snapshot = self.database.get_final_snapshot(self.final_snapshot_id)
            if snapshot:
                rows = snapshot.get("rows", [])
                if isinstance(rows, list):
                    return [row for row in rows if isinstance(row, dict)][: int(limit)]
        return self.database.get_final_leaderboard_best_of_two(limit=limit)

    def set_view_mode(self, view_mode: str) -> None:
        allowed = {self.VIEW_MODE_ROUND1, self.VIEW_MODE_ROUND2, self.VIEW_MODE_FINAL}
        normalized = str(view_mode).upper().strip()
        self.view_mode = normalized if normalized in allowed else self.VIEW_MODE_ROUND1
        if self.view_mode == self.VIEW_MODE_ROUND1:
            self.current_round = 1
        elif self.view_mode == self.VIEW_MODE_ROUND2:
            self.current_round = 2
        self.leaderboard_changed.emit()
        self._emit_state()

    def get_view_mode_title(self) -> str:
        if self.view_mode == self.VIEW_MODE_ROUND2:
            return "2차"
        if self.view_mode == self.VIEW_MODE_FINAL:
            return "최종"
        return "1차"

    def publish_final_snapshot(self) -> int:
        limit = max(22, len(self.teams))
        rows = self.database.get_final_leaderboard_best_of_two(limit=limit)
        snapshot_id = self.database.save_final_snapshot(rows)
        self.final_snapshot_id = snapshot_id
        self._record(f"FINAL snapshot saved: #{snapshot_id}")
        self._emit_state()
        return snapshot_id

    def get_team_progress_map(self) -> Dict[int, Dict[str, bool]]:
        return self.database.get_team_progress_map()

    def get_team_progress_text(self, team_number: int) -> str:
        team_no = int(team_number or 0)
        info = self.get_team_progress_map().get(
            team_no,
            {"round1_done": False, "round2_done": False, "final_confirmed": False},
        )
        return (
            f"1차 {'완료' if info.get('round1_done') else '미완료'} | "
            f"2차 {'완료' if info.get('round2_done') else '미완료'} | "
            f"최종 {'확정' if info.get('final_confirmed') else '미확정'}"
        )

    def get_team_progress_short(self, team_number: int) -> str:
        team_no = int(team_number or 0)
        info = self.get_team_progress_map().get(
            team_no,
            {"round1_done": False, "round2_done": False, "final_confirmed": False},
        )
        return (
            f"1{'O' if info.get('round1_done') else 'X'}/"
            f"2{'O' if info.get('round2_done') else 'X'}/"
            f"F{'O' if info.get('final_confirmed') else 'X'}"
        )

    def _default_mission_scores(self) -> Dict[str, int]:
        return {name: 0 for name in self.MISSION_SECONDS}

    def set_mission_scores(self, mission_scores: Dict[str, int]) -> None:
        cleaned = self._default_mission_scores()
        for name, value in mission_scores.items():
            if name in cleaned:
                cleaned[name] = max(0, int(value))
        self.state.mission_scores = cleaned

    def set_round(self, round_no: int) -> None:
        self.current_round = 1 if int(round_no) <= 1 else 2
        self.view_mode = self.VIEW_MODE_ROUND1 if self.current_round == 1 else self.VIEW_MODE_ROUND2
        self._record(f"ROUND changed to {self.current_round}")
        self.leaderboard_changed.emit()
        self._emit_state()

    def _mission_penalty_seconds(self) -> float:
        total = 0.0
        for name, score in self.state.mission_scores.items():
            total += float(score) * float(self.MISSION_SECONDS.get(name, 0))
        return total

    def _finalize_current_run(self, force_update: bool = False) -> None:
        if self._run_finalized and not force_update:
            return

        self.state.mission_penalty_seconds = self._mission_penalty_seconds()
        if self.state.disqualified:
            self.state.final_time = None
            self.state.rank = None
        else:
            self.state.final_time = round(self.state.elapsed_time + self.state.mission_penalty_seconds, 2)

        current = self.state.current_team or {}
        result = {
            "round_no": int(self.current_round),
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
            self.state.rank = self.database.rank_for_time(self.state.final_time, round_no=self.current_round)
        self._run_finalized = True
