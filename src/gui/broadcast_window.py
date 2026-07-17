from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QMainWindow, QVBoxLayout, QWidget

from ..core.race_controller import RaceController
from ..core.race_state import RaceState


class BroadcastWindow(QMainWindow):
    def __init__(self, controller: RaceController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle("Race Control Broadcast")
        self.resize(1920, 1080)
        self.setStyleSheet("background: #0e1726; color: #f6f6f6;")
        self._build_ui()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._refresh_clock)
        self._clock_timer.start()

        self.controller.state_changed.connect(self.refresh_from_state)
        self.refresh_from_state(self.controller.state)

    def _build_ui(self) -> None:
        central = QWidget(self)
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.title_label = QLabel("2026년 제9회 국민대학교 자율주행 경진대회")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setFont(QFont("NanumGothic", 28, QFont.Weight.Bold))
        layout.addWidget(self.title_label)

        top = QWidget(self)
        top_layout = QVBoxLayout(top)
        self.team_label = QLabel("TEAM TENSOR")
        self.team_label.setFont(QFont("NanumGothic", 26, QFont.Weight.Bold))
        self.school_label = QLabel("충북대학교")
        self.school_label.setFont(QFont("NanumGothic", 18))
        self.time_label = QLabel("00.00")
        self.time_label.setFont(QFont("NanumGothic", 44, QFont.Weight.Bold))
        self.state_label = QLabel("RUNNING")
        self.state_label.setFont(QFont("NanumGothic", 30, QFont.Weight.Bold))
        top_layout.addWidget(self.team_label)
        top_layout.addWidget(self.school_label)
        top_layout.addWidget(self.time_label)
        top_layout.addWidget(self.state_label)
        layout.addWidget(top)

        self.info_label = QLabel("팀 소개 / 차량 사진 / 학교 로고 영역")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setFont(QFont("NanumGothic", 20))
        self.info_label.setStyleSheet("border: 1px solid #4d5d75; padding: 40px;")
        layout.addWidget(self.info_label)

        self.rank_label = QLabel("1. TEAM TENSOR  18.352")
        self.rank_label.setFont(QFont("NanumGothic", 18))
        layout.addWidget(self.rank_label)

    def refresh_from_state(self, state: RaceState) -> None:
        current = state.current_team or {}
        self.team_label.setText(current.get("team_name", "N/A"))
        self.school_label.setText(current.get("school", "N/A"))
        self.time_label.setText(f"{state.elapsed_time:05.2f}")
        self.state_label.setText(state.status)
        self.rank_label.setText(f"{state.rank or 1}. {current.get('team_name', 'N/A')}  {state.elapsed_time:05.2f}")

    def _refresh_clock(self) -> None:
        pass
