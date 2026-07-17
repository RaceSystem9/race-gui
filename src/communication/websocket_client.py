from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtCore import QObject, Signal


class WebSocketClient(QObject):
    connection_changed = Signal(bool)

    def __init__(self, host: str = "127.0.0.1", port: int = 8765, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self.host = host
        self.port = port
        self._connected = False

    def connect(self) -> None:
        self._connected = True
        self.connection_changed.emit(True)

    def disconnect(self) -> None:
        self._connected = False
        self.connection_changed.emit(False)

    def send_state(self, state: Dict[str, Any]) -> None:
        if not self._connected:
            return

    @property
    def is_connected(self) -> bool:
        return self._connected
