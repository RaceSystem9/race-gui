from __future__ import annotations

from datetime import datetime
from typing import Dict, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.race_controller import RaceController
from ..core.race_state import RaceState


class MainWindow(QMainWindow):
    def __init__(self, controller: RaceController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Race Control Operator")
        self.resize(1700, 950)
        self._build_ui()
        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._refresh_clock)
        self._clock_timer.start()

        self.controller.state_changed.connect(self.refresh_from_state)
        self.controller.log_changed.connect(self._append_log)
        self.refresh_from_state(self.controller.state)

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        header = QHBoxLayout()
        self.current_team_label = QLabel("Current Team")
        self.current_team_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.next_team_label = QLabel("Next Team")
        self.next_team_label.setStyleSheet("font-size: 14px;")
        self.next_next_team_label = QLabel("Next Next Team")
        self.next_next_team_label.setStyleSheet("font-size: 14px;")
        self.clock_label = QLabel("--:--:--")
        self.clock_label.setStyleSheet("font-size: 18px; font-weight: bold;")
        header.addWidget(self.current_team_label)
        header.addStretch()
        header.addWidget(self.clock_label)
        layout.addLayout(header)

        team_row = QHBoxLayout()
        team_row.addWidget(self.next_team_label)
        team_row.addWidget(self.next_next_team_label)
        layout.addLayout(team_row)

        summary = QGridLayout()
        self.summary_labels: Dict[str, QLabel] = {}
        fields = [
            ("출전팀", "team"),
            ("경기상태", "status"),
            ("신호등", "light"),
            ("주행시간", "time"),
            ("랩", "lap"),
            ("최고기록", "best"),
            ("현재순위", "rank"),
        ]
        for row, (label_text, key) in enumerate(fields):
            label = QLabel(label_text)
            label.setStyleSheet("font-size: 16px; font-weight: bold;")
            value = QLabel("-")
            value.setStyleSheet("font-size: 16px;")
            summary.addWidget(label, row, 0)
            summary.addWidget(value, row, 1)
            self.summary_labels[key] = value
        layout.addLayout(summary)

        self.timer_display = QLabel("00.00")
        self.timer_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.timer_display.setStyleSheet("font-size: 72px; font-weight: bold; background: #111; color: #fff; padding: 20px;")
        layout.addWidget(self.timer_display)

        buttons = QHBoxLayout()
        button_specs = [
            ("START", self.controller.start),
            ("STOP", self.controller.stop),
            ("RESET", self.controller.reset),
            ("NEXT", self.controller.next_team),
            ("RETRY", self.controller.retry),
            ("PENALTY", self.controller.penalty),
            ("DISQUALIFY", self.controller.disqualify),
            ("EMERGENCY", self.controller.emergency),
        ]
        self.buttons = {}
        for text, callback in button_specs:
            button = QPushButton(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
            self.buttons[text] = button
        layout.addLayout(buttons)

        status = QGridLayout()
        self.status_labels: Dict[str, QLabel] = {}
        for index, label_text in enumerate(["신호등1", "신호등2", "통과감지장치", "WiFi", "ROS2", "WinGUI", "Broadcast", "Database"]):
            label = QLabel(label_text)
            label.setStyleSheet("font-size: 14px; padding: 6px;")
            status.addWidget(label, 0, index)
            value = QLabel("🟢 OK")
            self.status_labels[label_text] = value
            status.addWidget(value, 1, index)
        layout.addLayout(status)

        self.log_list = QListWidget()
        layout.addWidget(self.log_list)

    def refresh_from_state(self, state: RaceState) -> None:
        current = state.current_team or {}
        self.current_team_label.setText(
            f"현재팀 : {current.get('school', 'N/A')} / {current.get('team_name', 'N/A')} / {current.get('driver', 'N/A')}"
        )
        next_team = state.next_team or {}
        self.next_team_label.setText(f"(다음팀) {next_team.get('school', 'N/A')} / {next_team.get('team_name', 'N/A')}")
        next_next_team = state.next_next_team or {}
        self.next_next_team_label.setText(f"(다다음팀) {next_next_team.get('school', 'N/A')} / {next_next_team.get('team_name', 'N/A')}")
        self.summary_labels["team"].setText(f"#{current.get('number', 0)} {current.get('team_name', 'N/A')}")
        self.summary_labels["status"].setText(state.status)
        self.summary_labels["light"].setText(state.traffic_light)
        self.summary_labels["time"].setText(f"{state.elapsed_time:.2f}")
        self.summary_labels["lap"].setText(str(state.lap))
        self.summary_labels["best"].setText(f"{state.best_lap:.2f}" if state.best_lap is not None else "-")
        self.summary_labels["rank"].setText(str(state.rank) if state.rank is not None else "-")
        self.timer_display.setText(f"{state.elapsed_time:05.2f}")

        status_badges = self.controller.get_status_badges()
        for name, label in self.status_labels.items():
            key = {
                "신호등1": "traffic_light_1",
                "신호등2": "traffic_light_2",
                "통과감지장치": "gate",
                "WiFi": "wifi",
                "ROS2": "ros2",
                "WinGUI": "win_gui",
                "Broadcast": "broadcast",
                "Database": "database",
            }.get(name)
            if key:
                label.setText(status_badges.get(key, "🟢 OK"))

        self._refresh_clock()

    def _append_log(self, message: str) -> None:
        self.log_list.addItem(message)
        self.log_list.scrollToBottom()

    def _refresh_clock(self) -> None:
        self.clock_label.setText(datetime.now().strftime("%H:%M:%S"))
