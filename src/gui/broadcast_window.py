from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QFile, QIODevice, QTimer
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QLabel, QMainWindow, QWidget

from ..core.race_controller import RaceController
from ..core.race_state import RaceState


class BroadcastWindow(QMainWindow):
    def __init__(self, controller: RaceController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
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
        self.school_label = self._required_label("lblSchool")
        self.time_label = self._required_label("lblTime")
        self.state_label = self._required_label("lblState")
        self.info_label = self._required_label("lblInfo")
        self.rank_label = self._required_label("lblRank")

    def _required_label(self, object_name: str) -> QLabel:
        widget = self.findChild(QLabel, object_name)
        if widget is None:
            raise RuntimeError(f"Required QLabel not found: {object_name}")
        return widget

    def refresh_from_state(self, state: RaceState) -> None:
        current = state.current_team or {}
        self.team_label.setText(current.get("team_name", "N/A"))
        self.school_label.setText(current.get("school", "N/A"))
        self.time_label.setText(f"{state.elapsed_time:05.2f}")
        self.state_label.setText(state.status)
        self.rank_label.setText(f"{state.rank or 1}. {current.get('team_name', 'N/A')}  {state.elapsed_time:05.2f}")

    def _refresh_clock(self) -> None:
        pass
