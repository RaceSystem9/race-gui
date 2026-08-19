from __future__ import annotations

import json
import threading
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
        "lblMIssionScore1": 10,
        "lblMIssionScore2": 3,
        "lblMIssionScore3": 5,
        "lblMIssionScore4": 10,
        "lblMIssionScore5": 10,
    }
    VIEW_MODE_ROUND1 = "ROUND1"
    VIEW_MODE_ROUND2 = "ROUND2"
    VIEW_MODE_FINAL = "FINAL"
    MAX_LAPS = 3
    MIN_LAP_INTERVAL_SECONDS = 10.0
    PI_STATUS_STALE_SECONDS = 15.0

    def __init__(
        self,
        config_path: Optional[Path] = None,
        database: Optional[SQLiteManager] = None,
        ws_host: Optional[str] = None,
        ws_port: Optional[int] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.state = RaceState()
        self.database = database or SQLiteManager()
        self.websocket_client = WebSocketClient(host=ws_host, port=ws_port)
        self.websocket_client.connection_changed.connect(self._on_connection_changed)
        self.websocket_client.ack_status_changed.connect(self._on_ack_status_changed)
        self.websocket_client.message_received.connect(self._on_websocket_message)
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
        self._loaded_lap_durations: Optional[Dict[str, Optional[float]]] = None
        self._official_timer_base_ms: Optional[float] = None
        # Serializes SQLite access between the Qt main thread and the web broadcast
        # server's background thread (the connection is shared, not per-thread).
        self.db_lock = threading.Lock()
        self._pi_status_available = False
        self._pi_connected_count = 0
        self._pi_devices: List[Dict[str, Any]] = []
        self._pi_status_last_received_at = 0.0
        self._assign_teams()
        self._load_existing_result_for_current_team()

        self.timer = QTimer(self)
        self.timer.setInterval(10)
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
            "giveup": bool(int(team.get("giveup", 0) or 0)),
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

    def _load_existing_result_for_current_team(self) -> None:
        # Restore a previously saved result so admins can revisit/correct an earlier team's
        # mission scores without recomputing lap times from a freshly-reset (zeroed) state.
        current = self.state.current_team or {}
        team_number = int(current.get("number", 0) or 0)
        existing = self.database.get_latest_result_for_team(team_number, round_no=self.current_round)
        if not existing:
            return

        self.state.status = "FINISHED"
        self.state.elapsed_time = float(existing.get("elapsed_time", 0.0))
        self.state.official_elapsed_time = self.state.elapsed_time
        self.state.lap = self.MAX_LAPS
        self.state.mission_scores = dict(existing.get("mission_scores") or self._default_mission_scores())
        self.state.mission_penalty_seconds = float(existing.get("mission_penalty_seconds", 0.0))
        self.state.penalty_points = int(existing.get("manual_penalty_points", 0))
        self.state.final_time = existing.get("final_time")
        self.state.disqualified = bool(existing.get("disqualified", False))
        self.state.rank = (
            self.database.rank_for_time(self.state.final_time, round_no=self.current_round)
            if self.state.final_time is not None
            else None
        )
        self._loaded_lap_durations = {
            "lap1_time": existing.get("lap1_time"),
            "lap2_time": existing.get("lap2_time"),
            "lap3_time": existing.get("lap3_time"),
        }
        self._run_finalized = True
        self._record(f"Loaded existing result for team {team_number} (round {self.current_round})")

    @property
    def has_finalized_run(self) -> bool:
        # True once the current team/round has a saved result that Start/Reset would wipe.
        return self._run_finalized

    def start(self) -> None:
        self.countdown_timer.stop()
        self.timer.stop()
        self.state.status = "COUNTDOWN"
        self.state.traffic_light = "RED"
        self.state.countdown = 5
        self.state.timer_running = False
        self.state.elapsed_time = 0.0
        self.state.official_elapsed_time = None
        self._official_timer_base_ms = None
        self.state.lap = 0
        self.state.lap1_time = None
        self.state.lap2_time = None
        self.state.lap3_time = None
        self.state.mission_scores = self._default_mission_scores()
        self.state.mission_penalty_seconds = 0.0
        self.state.final_time = None
        self.state.disqualified = False
        self._run_finalized = False
        self._loaded_lap_durations = None
        self._record("START button pressed")
        self.countdown_timer.start()
        self._emit_state()

    def _countdown_tick(self) -> None:
        # Displays 5-4-3-2-1 (stops before 0) then starts the race.
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
        self.state.traffic_light = "RED"
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
        self.state.official_elapsed_time = None
        self._official_timer_base_ms = None
        self.state.lap = 0
        self.state.lap1_time = None
        self.state.lap2_time = None
        self.state.lap3_time = None
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
        self._loaded_lap_durations = None
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
        self.state.official_elapsed_time = None
        self._official_timer_base_ms = None
        self.state.lap = 0
        self.state.lap1_time = None
        self.state.lap2_time = None
        self.state.lap3_time = None
        self.state.best_lap = None
        self.state.rank = None
        self.state.penalty_points = 0
        self.state.mission_scores = self._default_mission_scores()
        self.state.mission_penalty_seconds = 0.0
        self.state.final_time = None
        self.state.disqualified = False
        self._run_finalized = False
        self._loaded_lap_durations = None
        self._record("NEXT team requested")
        self._load_existing_result_for_current_team()
        self._emit_state()

    def prev_team(self) -> None:
        self.timer.stop()
        self.countdown_timer.stop()
        self.team_index = (self.team_index - 1) % max(1, len(self.teams))
        self._assign_teams()
        self.state.status = "READY"
        self.state.traffic_light = "RED"
        self.state.elapsed_time = 0.0
        self.state.official_elapsed_time = None
        self._official_timer_base_ms = None
        self.state.lap = 0
        self.state.lap1_time = None
        self.state.lap2_time = None
        self.state.lap3_time = None
        self.state.best_lap = None
        self.state.rank = None
        self.state.penalty_points = 0
        self.state.mission_scores = self._default_mission_scores()
        self.state.mission_penalty_seconds = 0.0
        self.state.final_time = None
        self.state.disqualified = False
        self._run_finalized = False
        self._loaded_lap_durations = None
        self._record("PREV team requested")
        self._load_existing_result_for_current_team()
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
            self.state.elapsed_time = round(self.state.elapsed_time + 0.01, 2)
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
            self.request_pi_status()
        self.state_changed.emit(self.state)

    def _on_ack_status_changed(self, _ok: bool) -> None:
        self.state_changed.emit(self.state)

    def _on_websocket_message(self, message: Dict[str, Any]) -> None:
        message_type = str(message.get("type", "")).lower()
        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            return

        if message_type == "status_response":
            self._apply_pi_status_payload(payload)
            self.state_changed.emit(self.state)
            return

        changed = self._try_apply_authoritative_elapsed(payload)

        if message_type == "gate_trigger":
            # Gate trigger timestamps come from Raspberry Pi/ROS device timing.
            detected = bool(payload.get("detected", False))
            timestamp_ms = payload.get("timestamp")
            if detected and self.state.status == "RUNNING" and self.state.timer_running:
                lap_index_raw = payload.get("lap_index")
                lap_elapsed_raw = payload.get("lap_elapsed_time")

                if lap_index_raw is not None and lap_elapsed_raw is not None:
                    try:
                        lap_index = int(lap_index_raw)
                        lap_elapsed = round(float(lap_elapsed_raw), 2)
                    except (TypeError, ValueError):
                        lap_index = 0
                        lap_elapsed = 0.0

                    if 1 <= lap_index <= self.MAX_LAPS:
                        if not self._is_lap_interval_valid(lap_elapsed):
                            return
                        self.state.lap = lap_index
                        self.state.official_elapsed_time = lap_elapsed
                        changed = True
                        if lap_index == 1:
                            self.state.lap1_time = lap_elapsed
                        elif lap_index == 2:
                            self.state.lap2_time = lap_elapsed
                        elif lap_index == 3:
                            self.state.lap3_time = lap_elapsed
                else:
                    # Fallback when server is old and does not send lap metadata.
                    if timestamp_ms is not None:
                        changed = self._set_official_elapsed_from_gate_timestamp(timestamp_ms) or changed

                    race_elapsed = self.state.official_elapsed_time
                    if race_elapsed is None:
                        race_elapsed = self.state.elapsed_time
                    race_elapsed = round(float(race_elapsed), 2)

                    if not self._is_lap_interval_valid(race_elapsed):
                        return

                    self.state.lap = min(self.MAX_LAPS, int(self.state.lap) + 1)
                    changed = True

                    if self.state.lap == 1:
                        self.state.lap1_time = race_elapsed
                    elif self.state.lap == 2:
                        self.state.lap2_time = race_elapsed
                    elif self.state.lap == 3:
                        self.state.lap3_time = race_elapsed

                if self.state.lap >= self.MAX_LAPS:
                    self._auto_stop_after_last_lap()
                    return

        if changed and (self.state.timer_running or self.state.status == "FINISHED"):
            self.state_changed.emit(self.state)

    def _is_lap_interval_valid(self, candidate_elapsed: float) -> bool:
        previous_lap_time = self.state.lap2_time if self.state.lap2_time is not None else self.state.lap1_time
        if previous_lap_time is None:
            return True
        return (float(candidate_elapsed) - float(previous_lap_time)) >= self.MIN_LAP_INTERVAL_SECONDS

    def _auto_stop_after_last_lap(self) -> None:
        self.timer.stop()
        self.countdown_timer.stop()
        self.state.timer_running = False
        self.state.status = "FINISHED"
        self.state.traffic_light = "RED"
        self._finalize_current_run()
        self.leaderboard_changed.emit()
        self._record("AUTO STOP: reached 3rd trigger")
        self._emit_state()

    def _try_apply_authoritative_elapsed(self, payload: Dict[str, Any]) -> bool:
        # Support multiple payload schemas to stay compatible with server-side evolution.
        keys_seconds = ("official_elapsed_time", "elapsed_time", "race_time", "timer_seconds")
        for key in keys_seconds:
            value = payload.get(key)
            if value is None:
                continue
            try:
                seconds = round(float(value), 2)
            except (TypeError, ValueError):
                continue
            if seconds < 0:
                continue
            if self.state.official_elapsed_time != seconds:
                self.state.official_elapsed_time = seconds
                return True
            return False

        keys_millis = ("official_elapsed_ms", "elapsed_ms", "timer_ms")
        for key in keys_millis:
            value = payload.get(key)
            if value is None:
                continue
            return self._set_official_elapsed_from_ms(value)

        return False

    def _set_official_elapsed_from_ms(self, value: Any) -> bool:
        try:
            seconds = round(float(value) / 1000.0, 2)
        except (TypeError, ValueError):
            return False
        if seconds < 0:
            return False
        if self.state.official_elapsed_time == seconds:
            return False
        self.state.official_elapsed_time = seconds
        return True

    def _set_official_elapsed_from_gate_timestamp(self, value: Any) -> bool:
        try:
            timestamp_ms = float(value)
        except (TypeError, ValueError):
            return False

        if timestamp_ms < 0:
            return False

        if self._official_timer_base_ms is None:
            self._official_timer_base_ms = timestamp_ms
            elapsed_seconds = 0.0
        else:
            elapsed_seconds = max(0.0, (timestamp_ms - self._official_timer_base_ms) / 1000.0)

        elapsed_seconds = round(elapsed_seconds, 2)
        if self.state.official_elapsed_time == elapsed_seconds:
            return False
        self.state.official_elapsed_time = elapsed_seconds
        return True

    def get_ws_endpoint(self) -> tuple[str, int]:
        return self.websocket_client.host, int(self.websocket_client.port)

    def request_pi_status(self) -> None:
        self.websocket_client.send_command("status_request", {})

    def reconnect_websocket(self, host: str, port: int) -> None:
        target_host = str(host).strip()
        target_port = int(port)
        if not target_host:
            raise ValueError("WebSocket host cannot be empty")
        if target_port < 1 or target_port > 65535:
            raise ValueError("WebSocket port must be between 1 and 65535")

        self.websocket_client.disconnect()
        self.websocket_client.set_endpoint(target_host, target_port)
        self.websocket_client.connect()
        self._last_sent_traffic_light = None
        self._record(f"WebSocket endpoint changed to {target_host}:{target_port}")
        self._emit_state()

    def get_status_badges(self) -> Dict[str, str]:
        connected = self.websocket_client.is_connected
        ack_state = self.websocket_client.ack_state
        device_healthy = connected and ack_state == "ok"
        pi_status_fresh = self._pi_status_available and (
            (time.time() - self._pi_status_last_received_at) <= self.PI_STATUS_STALE_SECONDS
        )

        tl1_connected = False
        tl2_connected = False
        gate1_connected = False
        gate2_connected = False
        if self._pi_status_available:
            tl1_connected = any(
                int(d.get("device_id", 0)) >= 200
                and int(d.get("sensor_id", 0)) == 1
                and bool(d.get("connected", False))
                for d in self._pi_devices
            )
            tl2_connected = any(
                int(d.get("device_id", 0)) >= 200
                and int(d.get("sensor_id", 0)) == 2
                and bool(d.get("connected", False))
                for d in self._pi_devices
            )
            gate1_connected = any(
                100 <= int(d.get("device_id", 0)) < 200
                and int(d.get("sensor_id", 0)) == 1
                and bool(d.get("connected", False))
                for d in self._pi_devices
            )
            gate2_connected = any(
                100 <= int(d.get("device_id", 0)) < 200
                and int(d.get("sensor_id", 0)) == 2
                and bool(d.get("connected", False))
                for d in self._pi_devices
            )
        else:
            tl1_connected = device_healthy
            tl2_connected = device_healthy
            gate1_connected = device_healthy
            gate2_connected = device_healthy

        if not connected:
            wifi_badge = "🔴 OFF"
            ros2_badge = "🔴 OFF"
        elif pi_status_fresh:
            wifi_badge = "🟢 OK"
            ros2_badge = "🟢 OK"
        elif ack_state == "pending":
            wifi_badge = "🟡 WAIT"
            ros2_badge = "🟡 WAIT"
        elif self._pi_status_available:
            # Status responses have arrived before, but are currently stale.
            wifi_badge = "🟡 WARN"
            ros2_badge = "🟡 WAIT"
        else:
            wifi_badge = "🟢 OK"
            ros2_badge = "🟡 READY"

        return {
            "traffic_light_1": "🟢 OK" if tl1_connected else "🔴 OFF",
            "traffic_light_2": "🟢 OK" if tl2_connected else "🔴 OFF",
            "gate1": "🟢 OK" if gate1_connected else "🔴 OFF",
            "gate2": "🟢 OK" if gate2_connected else "🔴 OFF",
            "ros2": ros2_badge,
            "win_gui": "🟢 OK",
            "broadcast": "🟢 OK",
            "database": self.database.status_text(),
        }

    def _apply_pi_status_payload(self, payload: Dict[str, Any]) -> None:
        devices = payload.get("devices", [])
        if not isinstance(devices, list):
            devices = []
        self._pi_devices = [d for d in devices if isinstance(d, dict)]
        self._pi_connected_count = int(payload.get("connected_count", 0) or 0)
        self._pi_status_available = True
        self._pi_status_last_received_at = time.time()

    def get_round_leaderboard(self, limit: int = 22) -> List[Dict[str, Any]]:
        return self.database.get_leaderboard(limit=limit, round_no=self.current_round)

    def get_final_leaderboard(self, limit: int = 22) -> List[Dict[str, Any]]:
        return self.database.get_final_leaderboard_best_of_two(limit=limit)

    def get_leaderboard_for_view(self, view_mode: str, limit: int = 22) -> List[Dict[str, Any]]:
        normalized = str(view_mode).upper().strip()
        if normalized == self.VIEW_MODE_ROUND1:
            return self.database.get_leaderboard(limit=limit, round_no=1)
        if normalized == self.VIEW_MODE_ROUND2:
            return self.database.get_leaderboard(limit=limit, round_no=2)
        if self.final_snapshot_id is not None:
            snapshot = self.database.get_final_snapshot(self.final_snapshot_id)
            if snapshot:
                rows = snapshot.get("rows", [])
                if isinstance(rows, list):
                    return [row for row in rows if isinstance(row, dict)][: int(limit)]
        return self.database.get_final_leaderboard_best_of_two(limit=limit)

    def get_active_leaderboard(self, limit: int = 22) -> List[Dict[str, Any]]:
        return self.get_leaderboard_for_view(self.view_mode, limit=limit)

    def get_giveup_teams(self) -> List[Dict[str, Any]]:
        giveup_teams = [team for team in self.teams if team.get("giveup")]
        return sorted(giveup_teams, key=lambda team: int(team.get("number", 0) or 0))

    def get_ranking_board_rows(self, max_rows: int = 22, view_mode: Optional[str] = None) -> List[Optional[Dict[str, Any]]]:
        # Shared by BroadcastWindow and the web broadcast server so both show the
        # exact same ranking (give-up teams always pinned to the bottom-most rows).
        raced_rows = self.get_leaderboard_for_view(view_mode or self.view_mode, limit=max_rows)
        raced_team_numbers = {int(row.get("team_number", 0) or 0) for row in raced_rows}
        giveup_rows = [
            {
                "team_name": team.get("team_name", "-"),
                "school": team.get("school", "-"),
                "final_time": 999,
                "giveup": True,
            }
            for team in self.get_giveup_teams()
            if int(team.get("number", 0) or 0) not in raced_team_numbers
        ][:max_rows]

        board_rows: List[Optional[Dict[str, Any]]] = [None] * max_rows
        for index, row in enumerate(raced_rows[: max_rows - len(giveup_rows)]):
            board_rows[index] = row
        for offset, row in enumerate(giveup_rows):
            board_rows[max_rows - len(giveup_rows) + offset] = row
        return board_rows

    def get_broadcast_snapshot(self) -> Dict[str, Any]:
        # Called from the web broadcast server's background thread, so all SQLite
        # access here must go through db_lock (the connection is shared with the Qt
        # main thread, which does not itself take the lock for its own DB calls).
        with self.db_lock:
            board_rows = self.get_ranking_board_rows(max_rows=22)
            leaderboards = {
                "ROUND1": self.get_ranking_board_rows(max_rows=22, view_mode=self.VIEW_MODE_ROUND1),
                "ROUND2": self.get_ranking_board_rows(max_rows=22, view_mode=self.VIEW_MODE_ROUND2),
                "FINAL": self.get_ranking_board_rows(max_rows=22, view_mode=self.VIEW_MODE_FINAL),
            }
            progress_map = self.get_team_progress_map()

        state = self.state
        current = state.current_team or {}
        lap_durations = self.get_live_lap_durations()
        teams = [
            {
                "number": int(team.get("number", 0) or 0),
                "team_name": team.get("team_name", "-"),
                "school": team.get("school", "-"),
                "giveup": bool(team.get("giveup", False)),
            }
            for team in self.teams
        ]

        return {
            "generated_at": time.time(),
            "current_round": self.current_round,
            "view_mode": self.view_mode,
            "view_mode_title": self.get_view_mode_title(),
            "team": {
                "number": int(current.get("number", 0) or 0),
                "name": current.get("team_name", "N/A"),
                "school": current.get("school", "N/A"),
            },
            "status": state.status,
            "traffic_light": state.traffic_light,
            "countdown": int(state.countdown or 0),
            "elapsed_time": state.elapsed_time,
            "official_elapsed_time": state.official_elapsed_time,
            "final_time": state.final_time,
            "rank": state.rank,
            "lap": state.lap,
            "lap_times": lap_durations,
            "mission_scores": dict(state.mission_scores),
            "mission_penalty_seconds": state.mission_penalty_seconds,
            "leaderboard": [
                row if row is not None else {"team_name": "-", "school": "-", "final_time": None}
                for row in board_rows
            ],
            "leaderboards": {
                mode: [
                    row if row is not None else {"team_name": "-", "school": "-", "final_time": None}
                    for row in rows
                ]
                for mode, rows in leaderboards.items()
            },
            "team_progress": {str(team_no): info for team_no, info in progress_map.items()},
            "teams": teams,
        }

    def set_view_mode(self, view_mode: str) -> None:
        allowed = {self.VIEW_MODE_ROUND1, self.VIEW_MODE_ROUND2, self.VIEW_MODE_FINAL}
        normalized = str(view_mode).upper().strip()
        self.view_mode = normalized if normalized in allowed else self.VIEW_MODE_ROUND1
        previous_round = self.current_round
        if self.view_mode == self.VIEW_MODE_ROUND1:
            self.current_round = 1
        elif self.view_mode == self.VIEW_MODE_ROUND2:
            self.current_round = 2

        if self.view_mode in (self.VIEW_MODE_ROUND1, self.VIEW_MODE_ROUND2) and self.current_round != previous_round:
            # Reload the currently displayed team's saved result for the newly
            # selected round instead of leaving the other round's data on screen.
            self.timer.stop()
            self.countdown_timer.stop()
            self.state.status = "READY"
            self.state.traffic_light = "RED"
            self.state.timer_running = False
            self.state.elapsed_time = 0.0
            self.state.official_elapsed_time = None
            self._official_timer_base_ms = None
            self.state.lap = 0
            self.state.lap1_time = None
            self.state.lap2_time = None
            self.state.lap3_time = None
            self.state.best_lap = None
            self.state.rank = None
            self.state.penalty_points = 0
            self.state.mission_scores = self._default_mission_scores()
            self.state.mission_penalty_seconds = 0.0
            self.state.final_time = None
            self.state.disqualified = False
            self._run_finalized = False
            self._loaded_lap_durations = None
            self._record(f"VIEW MODE changed to round {self.current_round}")
            self._load_existing_result_for_current_team()

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

    def clear_mission_scores(self) -> None:
        self.state.mission_scores = self._default_mission_scores()
        self._record("Mission scores cleared")
        self._emit_state()

    def save_mission_scores(self, mission_scores: Dict[str, int]) -> None:
        self.set_mission_scores(mission_scores)
        self._finalize_current_run(force_update=True)
        self.leaderboard_changed.emit()
        self._record("Mission scores saved")
        self._emit_state()


    def _mission_penalty_seconds(self) -> float:
        total = 0.0
        for name, score in self.state.mission_scores.items():
            total += float(score) * float(self.MISSION_SECONDS.get(name, 0))
        return total

    def _lap_durations(self, race_elapsed: float) -> Dict[str, Optional[float]]:
        durations = self.get_live_lap_durations()
        # Fallback: last lap wasn't triggered by a gate, derive it from the finish time.
        if durations["lap3_time"] is None and self.state.lap2_time is not None and self.state.lap3_time is None:
            durations["lap3_time"] = round(race_elapsed - self.state.lap2_time, 2)
        return durations

    def get_live_lap_durations(self) -> Dict[str, Optional[float]]:
        # When viewing a previously saved result, use the DB's per-lap durations directly
        # instead of the (unset) live state, which was cleared when this team was loaded.
        if self._loaded_lap_durations is not None:
            return dict(self._loaded_lap_durations)

        # state.lapN_time holds cumulative split times; convert to individual per-lap durations.
        lap1 = self.state.lap1_time
        lap2 = self.state.lap2_time
        lap3 = self.state.lap3_time

        lap1_duration = round(lap1, 2) if lap1 is not None else None
        lap2_duration = round(lap2 - lap1, 2) if lap2 is not None and lap1 is not None else None
        lap3_duration = round(lap3 - lap2, 2) if lap3 is not None and lap2 is not None else None

        return {"lap1_time": lap1_duration, "lap2_time": lap2_duration, "lap3_time": lap3_duration}

    def _finalize_current_run(self, force_update: bool = False) -> None:
        if self._run_finalized and not force_update:
            return

        race_elapsed = self.state.official_elapsed_time
        if race_elapsed is None:
            race_elapsed = self.state.elapsed_time

        # A 0.00s "finish" only happens when Stop is pressed without an actual run
        # (e.g. right after Reset). Treat it as a full reset for this team/round:
        # wipe any previously saved result so it looks like the team never raced.
        if not self.state.disqualified and race_elapsed <= 0:
            current = self.state.current_team or {}
            team_number = int(current.get("number", 0) or 0)
            self.database.delete_race_result(team_number, self.current_round)
            self.state.final_time = None
            self.state.rank = None
            self._record(f"STOP ignored: no elapsed race time (0.00s) for team {team_number}, cleared as not raced")
            return

        self.state.mission_penalty_seconds = self._mission_penalty_seconds()
        if self.state.disqualified:
            self.state.final_time = None
            self.state.rank = None
        else:
            self.state.final_time = round(race_elapsed + self.state.mission_penalty_seconds, 2)

        current = self.state.current_team or {}
        result = {
            "round_no": int(self.current_round),
            "team_number": int(current.get("number", 0) or 0),
            "team_name": str(current.get("team_name", "N/A")),
            "school": str(current.get("school", "N/A")),
            "elapsed_time": float(race_elapsed),
            "mission_penalty_seconds": float(self.state.mission_penalty_seconds),
            "manual_penalty_points": int(self.state.penalty_points),
            "final_time": self.state.final_time,
            "disqualified": bool(self.state.disqualified),
            "mission_scores": dict(self.state.mission_scores),
        }
        # Reuse lap durations loaded from a prior saved result (editing an earlier team)
        # instead of recomputing from cumulative split fields that were never re-populated.
        result.update(self._loaded_lap_durations or self._lap_durations(race_elapsed))

        self.database.append_race_result(result)
        if self.state.final_time is not None:
            self.state.rank = self.database.rank_for_time(self.state.final_time, round_no=self.current_round)
        self._run_finalized = True
