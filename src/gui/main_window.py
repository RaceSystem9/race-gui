from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import QEvent, QFile, QIODevice, QSettings, QTimer, Qt
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import (
    QComboBox,
    QInputDialog,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QToolBar,
    QWidget,
)

from ..core.race_controller import RaceController
from ..core.race_state import RaceState


class MainWindow(QMainWindow):
    WS_SETTINGS_GROUP = "network"
    WS_HOST_KEY = "race_ws_host"
    WS_PORT_KEY = "race_ws_port"

    def __init__(self, controller: RaceController, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.settings = QSettings()
        self.summary_labels: Dict[str, QLabel] = {}
        self.status_labels: Dict[str, QLabel] = {}
        self.mission_score_labels: Dict[str, QLabel] = {}
        self._load_ui()
        self._init_round_selector()
        self._wire_actions()
        self._restore_server_endpoint_from_settings()

        self._clock_timer = QTimer(self)
        self._clock_timer.setInterval(1000)
        self._clock_timer.timeout.connect(self._refresh_clock)
        self._clock_timer.start()

        self.controller.state_changed.connect(self.refresh_from_state)
        self.controller.log_changed.connect(self._append_log)
        self.refresh_from_state(self.controller.state)

    def _load_ui(self) -> None:
        ui_path = Path(__file__).resolve().parent / "ui" / "main_window.ui"
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
        central_widget = loaded_window.findChild(QWidget, "centralwidget")
        if central_widget is None:
            raise RuntimeError("Loaded main_window.ui has no centralwidget")
        self.setCentralWidget(central_widget)

        self.current_team_label = self._required_label("lblCurrentTeam")
        self.next_team_label = self._required_label("lblNextTeam")
        self.next_next_team_label = self._required_label("lblNextNextTeam")
        self.clock_label = self._required_label("lblClock")
        self.timer_display = self._required_label("lblTimerDisplay")
        self.log_list = self._required_list("listLog")

        self.summary_labels = {
            "team": self._required_label("valTeam"),
            "status": self._required_label("valStatus"),
            "light": self._required_label("valLight"),
            "time": self._required_label("valTime"),
            "lap": self._required_label("valLap"),
            "best": self._required_label("valBest"),
            "rank": self._required_label("valRank"),
        }

        self.status_labels = {
            "traffic_light_1": self._required_label("statusTrafficLight1"),
            "traffic_light_2": self._required_label("statusTrafficLight2"),
            "gate": self._required_label("statusGate"),
            "wifi": self._required_label("statusWifi"),
            "ros2": self._required_label("statusRos2"),
            "win_gui": self._required_label("statusWinGui"),
            "broadcast": self._required_label("statusBroadcast"),
            "database": self._required_label("statusDatabase"),
        }

        self.mission_score_labels = {
            "lblMIssionScore1": self._required_label("lblMIssionScore1"),
            "lblMIssionScore2": self._required_label("lblMIssionScore2"),
            "lblMIssionScore3": self._required_label("lblMIssionScore3"),
            "lblMIssionScore4": self._required_label("lblMIssionScore4"),
            "lblMIssionScore5": self._required_label("lblMIssionScore5"),
        }
        for label in self.mission_score_labels.values():
            label.setCursor(Qt.CursorShape.PointingHandCursor)
            label.setToolTip("더블클릭해서 감점 횟수를 입력하세요")
            label.installEventFilter(self)

    def _wire_actions(self) -> None:
        button_specs = {
            "btnStart": self.controller.start,
            "btnReset": self.controller.reset,
            "btnNext": self.controller.next_team,
            "btnRetry": self.controller.retry,
            "btnDisqualify": self.controller.disqualify,
            "btnEmergency": self.controller.emergency,
        }
        for object_name, callback in button_specs.items():
            self._required_button(object_name).clicked.connect(callback)
        self._required_button("btnStop").clicked.connect(self._on_stop_clicked)
        self._required_button("btnPenalty").clicked.connect(self._on_penalty_clicked)

    def _init_round_selector(self) -> None:
        self.round_toolbar = QToolBar("Round", self)
        self.round_toolbar.setObjectName("roundToolbar")
        self.round_toolbar.setMovable(False)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.round_toolbar)

        round_label = QLabel("라운드:", self)
        self.round_toolbar.addWidget(round_label)

        self.round_selector = QComboBox(self)
        self.round_selector.addItem("1차", 1)
        self.round_selector.addItem("2차", 2)
        self.round_selector.setCurrentIndex(0 if self.controller.current_round == 1 else 1)
        self.round_selector.currentIndexChanged.connect(self._on_round_changed)
        self.round_toolbar.addWidget(self.round_selector)

        self.round_toolbar.addSeparator()
        view_mode_label = QLabel("보기:", self)
        self.round_toolbar.addWidget(view_mode_label)

        self.view_mode_selector = QComboBox(self)
        self.view_mode_selector.addItem("1차", self.controller.VIEW_MODE_ROUND1)
        self.view_mode_selector.addItem("2차", self.controller.VIEW_MODE_ROUND2)
        self.view_mode_selector.addItem("최종", self.controller.VIEW_MODE_FINAL)
        self.view_mode_selector.currentIndexChanged.connect(self._on_view_mode_changed)
        self.round_toolbar.addWidget(self.view_mode_selector)

        self.round_toolbar.addSeparator()
        self.publish_final_button = QPushButton("최종 발표 확정", self)
        self.publish_final_button.clicked.connect(self._on_publish_final_clicked)
        self.round_toolbar.addWidget(self.publish_final_button)

        self.round_toolbar.addSeparator()
        self.progress_label = QLabel("진행: -", self)
        self.round_toolbar.addWidget(self.progress_label)

        self.round_toolbar.addSeparator()
        self.server_button = QPushButton(self._server_button_text(), self)
        self.server_button.clicked.connect(self._on_server_button_clicked)
        self.round_toolbar.addWidget(self.server_button)

        self._sync_view_mode_selector()

    def _on_round_changed(self, index: int) -> None:
        round_no = int(self.round_selector.itemData(index) or 1)
        self.controller.set_round(round_no)

    def _on_view_mode_changed(self, index: int) -> None:
        view_mode = str(self.view_mode_selector.itemData(index) or self.controller.VIEW_MODE_ROUND1)
        self.controller.set_view_mode(view_mode)

    def _sync_view_mode_selector(self) -> None:
        target_mode = self.controller.view_mode
        for i in range(self.view_mode_selector.count()):
            if str(self.view_mode_selector.itemData(i)) == target_mode:
                self.view_mode_selector.blockSignals(True)
                self.view_mode_selector.setCurrentIndex(i)
                self.view_mode_selector.blockSignals(False)
                return

    def _server_button_text(self) -> str:
        host, port = self.controller.get_ws_endpoint()
        return f"서버: {host}:{port}"

    def _on_server_button_clicked(self) -> None:
        current_host, current_port = self.controller.get_ws_endpoint()
        host, ok = QInputDialog.getText(
            self,
            "서버 주소 설정",
            "라즈베리파이 IP 또는 호스트:",
            text=current_host,
        )
        if not ok:
            return
        target_host = host.strip()
        if not target_host:
            QMessageBox.warning(self, "입력 오류", "서버 주소를 입력하세요.")
            return

        port, ok = QInputDialog.getInt(
            self,
            "서버 포트 설정",
            "WebSocket 포트:",
            value=int(current_port),
            minValue=1,
            maxValue=65535,
        )
        if not ok:
            return

        try:
            self.controller.reconnect_websocket(target_host, int(port))
        except ValueError as error:
            QMessageBox.warning(self, "설정 오류", str(error))
            return

        self._save_server_endpoint_to_settings(target_host, int(port))
        self.server_button.setText(self._server_button_text())
        QMessageBox.information(self, "서버 연결", f"서버를 {target_host}:{port} 로 변경했습니다.")

    def _restore_server_endpoint_from_settings(self) -> None:
        self.settings.beginGroup(self.WS_SETTINGS_GROUP)
        try:
            saved_host = str(self.settings.value(self.WS_HOST_KEY, "") or "").strip()
            saved_port_raw = self.settings.value(self.WS_PORT_KEY, 0)
        finally:
            self.settings.endGroup()

        try:
            saved_port = int(saved_port_raw)
        except (TypeError, ValueError):
            return

        if not saved_host or saved_port < 1 or saved_port > 65535:
            return

        current_host, current_port = self.controller.get_ws_endpoint()
        if saved_host == current_host and int(saved_port) == int(current_port):
            return

        try:
            self.controller.reconnect_websocket(saved_host, saved_port)
        except ValueError:
            return

        self.server_button.setText(self._server_button_text())

    def _save_server_endpoint_to_settings(self, host: str, port: int) -> None:
        self.settings.beginGroup(self.WS_SETTINGS_GROUP)
        try:
            self.settings.setValue(self.WS_HOST_KEY, str(host).strip())
            self.settings.setValue(self.WS_PORT_KEY, int(port))
        finally:
            self.settings.endGroup()
        self.settings.sync()

    def closeEvent(self, event: QEvent) -> None:  # noqa: N802
        host, port = self.controller.get_ws_endpoint()
        self._save_server_endpoint_to_settings(host, int(port))
        super().closeEvent(event)

    def _on_publish_final_clicked(self) -> None:
        preview_text = self._build_final_top3_preview_text()
        reply = QMessageBox.question(
            self,
            "최종 발표 확인",
            (
                "현재 최종 순위를 확정하시겠습니까?\n"
                "확정 후에는 해당 시점 순위가 스냅샷으로 저장됩니다.\n\n"
                f"{preview_text}"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        snapshot_id = self.controller.publish_final_snapshot()
        QMessageBox.information(self, "최종 발표", f"최종 순위 스냅샷 저장 완료: #{snapshot_id}")

    def _build_final_top3_preview_text(self) -> str:
        rows = self.controller.get_final_leaderboard(limit=3)
        if not rows:
            return "상위 3팀 미리보기: 집계된 최종 기록이 없습니다."

        lines = ["상위 3팀 미리보기"]
        for index, row in enumerate(rows, start=1):
            team_name = str(row.get("team_name", "-"))
            final_time = row.get("final_time")
            score_text = "DQ" if final_time is None else f"{float(final_time):05.2f}"
            lines.append(f"{index}. {team_name}  {score_text}")
        return "\n".join(lines)

    def _required_label(self, object_name: str) -> QLabel:
        widget = self.findChild(QLabel, object_name)
        if widget is None:
            raise RuntimeError(f"Required QLabel not found: {object_name}")
        return widget

    def _required_button(self, object_name: str) -> QPushButton:
        widget = self.findChild(QPushButton, object_name)
        if widget is None:
            raise RuntimeError(f"Required QPushButton not found: {object_name}")
        return widget

    def _required_list(self, object_name: str) -> QListWidget:
        widget = self.findChild(QListWidget, object_name)
        if widget is None:
            raise RuntimeError(f"Required QListWidget not found: {object_name}")
        return widget

    def refresh_from_state(self, state: RaceState) -> None:
        current = state.current_team or {}
        self.round_selector.blockSignals(True)
        self.round_selector.setCurrentIndex(0 if self.controller.current_round == 1 else 1)
        self.round_selector.blockSignals(False)
        self._sync_view_mode_selector()

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
        summary_time = state.final_time if state.final_time is not None else state.elapsed_time
        self.summary_labels["time"].setText(f"{summary_time:.2f}")
        self.summary_labels["lap"].setText(str(state.lap))
        self.summary_labels["best"].setText(f"{state.best_lap:.2f}" if state.best_lap is not None else "-")
        self.summary_labels["rank"].setText(str(state.rank) if state.rank is not None else "-")
        self.timer_display.setText(f"{summary_time:05.2f}")

        team_number = int(current.get("number", 0) or 0)
        self.progress_label.setText(f"진행: {self.controller.get_team_progress_text(team_number)}")
        self.server_button.setText(self._server_button_text())

        mission_scores = state.mission_scores or {}
        for name, label in self.mission_score_labels.items():
            label.setText(str(int(mission_scores.get(name, self._safe_int(label.text())))))

        status_badges = self.controller.get_status_badges()
        for key, label in self.status_labels.items():
            label.setText(status_badges.get(key, "🟢 OK"))

        self._refresh_clock()

    def _append_log(self, message: str) -> None:
        self.log_list.addItem(message)
        self.log_list.scrollToBottom()

    def _refresh_clock(self) -> None:
        self.clock_label.setText(datetime.now().strftime("%H:%M:%S"))

    def _on_stop_clicked(self) -> None:
        self.controller.stop(self._collect_mission_scores())

    def _on_penalty_clicked(self) -> None:
        self.controller.penalty(self._collect_mission_scores())

    def _collect_mission_scores(self) -> Dict[str, int]:
        scores: Dict[str, int] = {}
        for name, label in self.mission_score_labels.items():
            scores[name] = self._safe_int(label.text())
        return scores

    def eventFilter(self, watched: object, event: QEvent) -> bool:  # noqa: N802
        if isinstance(watched, QLabel) and watched.objectName() in self.mission_score_labels:
            if event.type() == QEvent.Type.MouseButtonDblClick:
                self._edit_mission_score(watched)
                return True
        return super().eventFilter(watched, event)

    def _edit_mission_score(self, label: QLabel) -> None:
        current_value = self._safe_int(label.text())
        value, accepted = QInputDialog.getInt(
            self,
            "미션 감점 횟수 입력",
            f"{label.objectName()} 감점 횟수:",
            current_value,
            0,
            999,
            1,
        )
        if accepted:
            label.setText(str(value))

    def _safe_int(self, value: str) -> int:
        try:
            return max(0, int(value.strip()))
        except (TypeError, ValueError, AttributeError):
            return 0
