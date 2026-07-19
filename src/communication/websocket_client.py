from __future__ import annotations

import json
from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtWebSockets import QWebSocket


class WebSocketClient(QObject):
    connection_changed = Signal(bool)
    message_received = Signal(dict)

    def __init__(self, host: str = "192.168.4.1", port: int = 8765, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.host = host
        self.port = port
        self._connected = False
        self._socket = QWebSocket()
        self._socket.connected.connect(self._on_connected)
        self._socket.disconnected.connect(self._on_disconnected)
        self._socket.textMessageReceived.connect(self._on_text_message_received)
        self._socket.errorOccurred.connect(self._on_error)

    def connect(self) -> None:
        url = QUrl(f"ws://{self.host}:{self.port}/race")
        self._socket.open(url)

    def disconnect(self) -> None:
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

    def set_endpoint(self, host: str, port: int) -> None:
        self.host = host
        self.port = int(port)

    def _on_connected(self) -> None:
        self._connected = True
        self.connection_changed.emit(True)

    def _on_disconnected(self) -> None:
        self._connected = False
        self.connection_changed.emit(False)

    def _on_text_message_received(self, message: str) -> None:
        try:
            data = json.loads(message)
            if isinstance(data, dict):
                self.message_received.emit(data)
        except json.JSONDecodeError:
            pass

    def _on_error(self, _error: object) -> None:
        self._connected = False
        self.connection_changed.emit(False)

    @property
    def is_connected(self) -> bool:
        return self._connected
