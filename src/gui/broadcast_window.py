from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QFile, QIODevice, QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QLabel, QMainWindow, QWidget

from ..core.race_controller import RaceController
from ..core.race_state import RaceState


class BroadcastWindow(QMainWindow):
    def __init__(self, controller: RaceController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.member_labels: Dict[int, QLabel] = {}
        self.mission_score_labels: Dict[str, QLabel] = {}
        self.rank_team_labels: Dict[int, QLabel] = {}
        self.rank_school_labels: Dict[int, QLabel] = {}
        self.rank_score_labels: Dict[int, QLabel] = {}
        self._load_ui()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._refresh_clock)
        self._clock_timer.start()

        self.controller.state_changed.connect(self.refresh_from_state)
        self.refresh_from_state(self.controller.state)

    def _load_ui(self) -> None:
        ui_path = Path(__file__).resolve().parent / "ui" / "broadcast_window.ui"
        loader = QUiLoader()
        ui_file = QFile(str(ui_path))
        if not ui_file.open(QIODevice.OpenModeFlag.ReadOnly):
            raise RuntimeError(f"Unable to open UI file: {ui_path}")
        try:
            loaded_window = loader.load(ui_file, self)
        finally:
            ui_file.close()

        if loaded_window is None:
            raise RuntimeError(f"Unable to load UI file: {ui_path}")

        self.setWindowTitle(loaded_window.windowTitle())
        self.resize(loaded_window.size())
        self.setStyleSheet(loaded_window.styleSheet())

        central_widget = loaded_window.findChild(QWidget, "centralwidget")
        if central_widget is None:
            raise RuntimeError("Loaded broadcast_window.ui has no centralwidget")
        self.setCentralWidget(central_widget)

        self.title_label = self._required_label("lblTitle")
        self.team_label = self._required_label("lblTeam")
        self.team_no_label = self._required_label("lblTeamNo")
        self.school_label = self._required_label("lblSchool")
        self.school_logo_label = self._required_label("lblSchoolLogo")
        self.time_label = self._required_label("lblTime")
        self.state_label = self._required_label("lblState")
        self.info_label = self._required_label("lblInfo")
        self.rank_label = self._required_label("lblRank")
        self.mission_total_label = self._required_label("lblMIssionScore")
        self.racing_score_label = self._required_label("lblRacingScore")
        self.total_score_label = self._required_label("lblTotalScore")

        self.member_labels = {
            1: self._required_label("lblMemberInfo1"),
            2: self._required_label("lblMemberInfo2"),
            3: self._required_label("lblMemberInfo3"),
            4: self._required_label("lblMemberInfo4"),
            5: self._required_label("lblMemberInfo5"),
        }
        self.mission_score_labels = {
            "lblMIssionScore1": self._required_label("lblMIssionScore1"),
            "lblMIssionScore2": self._required_label("lblMIssionScore2"),
            "lblMIssionScore3": self._required_label("lblMIssionScore3"),
            "lblMIssionScore4": self._required_label("lblMIssionScore4"),
            "lblMIssionScore5": self._required_label("lblMIssionScore5"),
        }
        self.rank_team_labels = {index: self._required_label(f"lblRankTeam{index}") for index in range(1, 23)}
        self.rank_school_labels = {index: self._required_label(f"lblRankSchool{index}") for index in range(1, 23)}
        self.rank_score_labels = {index: self._required_label(f"lblRankScore{index}") for index in range(1, 23)}

    def _required_label(self, object_name: str) -> QLabel:
        widget = self.findChild(QLabel, object_name)
        if widget is None:
            raise RuntimeError(f"Required QLabel not found: {object_name}")
        return widget

    def refresh_from_state(self, state: RaceState) -> None:
        current = state.current_team or {}
        team_number = int(current.get("number", 0) or 0)
        team_name = current.get("team_name", "N/A")
        school_name = current.get("school", "N/A")

        self.team_label.setText(current.get("team_name", "N/A"))
        self.team_no_label.setText(str(team_number))
        self.school_label.setText(school_name)
        self.time_label.setText(f"{state.elapsed_time:05.2f}")
        self.state_label.setText(state.status)
        self._refresh_school_logo(team_number)
        self._refresh_member_info(current)

        mission_total_seconds = self._refresh_mission_scores(state)
        self.mission_total_label.setText(f"{mission_total_seconds:.2f}")
        self.racing_score_label.setText(f"{state.elapsed_time:05.2f}")
        total_score = state.final_time if state.final_time is not None else round(state.elapsed_time + mission_total_seconds, 2)
        self.total_score_label.setText(f"{total_score:05.2f}")

        rank_text = str(state.rank) if state.rank is not None else "-"
        self.rank_label.setText(f"{rank_text}. {team_name}  {total_score:05.2f}")

        self._refresh_ranking_board()

    def _refresh_school_logo(self, team_number: int) -> None:
        config_dir = Path(__file__).resolve().parents[1] / "config"
        logo_path = config_dir / "team_logo" / f"{team_number}_logo.png"
        if not logo_path.exists():
            logo_path = None
        if logo_path is None:
            self.school_logo_label.clear()
            self.school_logo_label.setText("학교로고")
            return

        pixmap = QPixmap(str(logo_path))
        if pixmap.isNull():
            self.school_logo_label.clear()
            self.school_logo_label.setText("학교로고")
            return

        scaled = pixmap.scaled(
            self.school_logo_label.width(),
            self.school_logo_label.height(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.school_logo_label.setPixmap(scaled)
        self.school_logo_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def _refresh_member_info(self, current_team: Dict[str, object]) -> None:
        members = current_team.get("members", [])
        if not isinstance(members, list):
            members = []

        for index in range(1, 6):
            label = self.member_labels[index]
            if index <= len(members) and isinstance(members[index - 1], dict):
                member = members[index - 1]
                name = str(member.get("name", ""))
                school = str(member.get("school", ""))
                department = str(member.get("department", ""))
                grade = str(member.get("grade", ""))
                label.setText(f"{name} {school} {department} {grade}".strip())
            else:
                label.setText("-")

    def _refresh_mission_scores(self, state: RaceState) -> float:
        mission_scores = state.mission_scores or {}
        total_seconds = 0.0
        for mission_key, label in self.mission_score_labels.items():
            count = int(mission_scores.get(mission_key, 0) or 0)
            seconds = float(count) * float(self.controller.MISSION_SECONDS.get(mission_key, 0))
            total_seconds += seconds
            label.setText(str(int(seconds) if seconds.is_integer() else round(seconds, 2)))
        return total_seconds

    def _refresh_ranking_board(self) -> None:
        rows = self.controller.database.get_leaderboard(limit=22)
        for rank in range(1, 23):
            team_label = self.rank_team_labels[rank]
            school_label = self.rank_school_labels[rank]
            score_label = self.rank_score_labels[rank]

            if rank <= len(rows):
                row = rows[rank - 1]
                team_label.setText(str(row.get("team_name", "-")))
                school_label.setText(str(row.get("school", "-")))
                final_time = row.get("final_time")
                disqualified = bool(row.get("disqualified", False))
                score_label.setText("DQ" if disqualified or final_time is None else f"{float(final_time):05.2f}")
            else:
                team_label.setText("-")
                school_label.setText("-")
                score_label.setText("-")

    def _refresh_clock(self) -> None:
        pass
