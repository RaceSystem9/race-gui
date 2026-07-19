from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, QTimer, Signal, QUrl
from PySide6.QtNetwork import QAbstractSocket
from PySide6.QtWebSockets import QWebSocket


class WebSocketClient(QObject):
    connection_changed = Signal(bool)
    ack_status_changed = Signal(bool)
    message_received = Signal(dict)

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.host = str(host or os.getenv("RACE_WS_HOST", "127.0.0.1")).strip()
        self.port = int(port if port is not None else int(os.getenv("RACE_WS_PORT", "8765")))
        self._connected = False
        self._should_connect = False
        self._reconnect_interval_ms = 3000
        self._ack_timeout_ms = 2000
        self._ack_stale_seconds = 10.0
        self._last_ack_ok = False
        self._last_ack_timestamp = 0.0
        self._awaiting_ack = False
        self._ack_attempted = False
        self._socket = QWebSocket()
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.textMessageReceived.connect(self._on_text_message_received)
        self._socket.errorOccurred.connect(self._on_error)

        self._reconnect_timer = QTimer(self)
        self._reconnect_timer.setInterval(self._reconnect_interval_ms)
        self._reconnect_timer.timeout.connect(self._attempt_reconnect)

        self._ack_timeout_timer = QTimer(self)
        self._ack_timeout_timer.setSingleShot(True)
        self._ack_timeout_timer.setInterval(self._ack_timeout_ms)
        self._ack_timeout_timer.timeout.connect(self._on_ack_timeout)

    def connect(self) -> None:
        self._should_connect = True
        self._attempt_reconnect()

    def disconnect(self) -> None:
        self._should_connect = False
        self._reconnect_timer.stop()
        self._ack_timeout_timer.stop()
        self._socket.close()

    def send_state(self, state: Dict[str, Any]) -> None:
        if not self._connected:
            return
        payload = json.dumps({"type": "state_update", "payload": state}, ensure_ascii=False)
        self._socket.sendTextMessage(payload)

    def send_command(self, command: str, payload: Optional[Dict[str, Any]] = None) -> None:
        if not self._connected:
            return
        message = {"type": str(command), "payload": payload or {}}
        self._socket.sendTextMessage(json.dumps(message, ensure_ascii=False))
        if str(command) == "set_traffic_light":
            self._ack_attempted = True
            self._awaiting_ack = True
            self._last_ack_ok = False
            self._ack_timeout_timer.start()
            self.ack_status_changed.emit(False)

    def set_endpoint(self, host: str, port: int) -> None:
        self.host = host
        self.port = int(port)

    def _attempt_reconnect(self) -> None:
        if not self._should_connect:
            return
        if self._connected:
            return
        if self._socket.state() in (QAbstractSocket.SocketState.ConnectingState, QAbstractSocket.SocketState.ConnectedState):
            return
        url = QUrl(f"ws://{self.host}:{self.port}/race")
        self._socket.open(url)

    def _on_connected(self) -> None:
        self._connected = True
        self._reconnect_timer.stop()
        self.connection_changed.emit(True)

    def _on_disconnected(self) -> None:
        self._connected = False
        self._awaiting_ack = False
        self._ack_timeout_timer.stop()
        self.connection_changed.emit(False)
        self.ack_status_changed.emit(False)
        if self._should_connect and not self._reconnect_timer.isActive():
            self._reconnect_timer.start()

    def _on_text_message_received(self, message: str) -> None:
        try:
            data = json.loads(message)
            if isinstance(data, dict):
                if str(data.get("type", "")).lower() == "ack":
                    payload = data.get("payload", {})
                    if isinstance(payload, dict) and str(payload.get("status", "")).lower() == "ok":
                        self._awaiting_ack = False
                        self._last_ack_ok = True
                        self._last_ack_timestamp = time.time()
                        self._ack_timeout_timer.stop()
                        self.ack_status_changed.emit(True)
                self.message_received.emit(data)
        except json.JSONDecodeError:
            pass

    def _on_error(self, _error: object) -> None:
        self._connected = False
        self.connection_changed.emit(False)
        self.ack_status_changed.emit(False)
        if self._should_connect and not self._reconnect_timer.isActive():
            self._reconnect_timer.start()

    def _on_ack_timeout(self) -> None:
        if not self._awaiting_ack:
            return
        self._awaiting_ack = False
        self._last_ack_ok = False
        self.ack_status_changed.emit(False)

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def ack_state(self) -> str:
        if not self._connected:
            return "disconnected"
        if self._awaiting_ack:
            return "pending"
        if not self._ack_attempted:
            return "unknown"
        if self._last_ack_ok and (time.time() - self._last_ack_timestamp) <= self._ack_stale_seconds:
            return "ok"
        return "failed"

    @property
    def is_ack_healthy(self) -> bool:
        return self.ack_state == "ok"
