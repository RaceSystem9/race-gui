from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .core.race_controller import RaceController
from .database.sqlite_manager import SQLiteManager
from .gui.broadcast_window import BroadcastWindow
from .gui.main_window import MainWindow


def build_app(headless: bool = False, ws_host: str | None = None, ws_port: int | None = None):
    app = QApplication(sys.argv)
    app.setApplicationName("RaceControl")
    app.setOrganizationName("RaceManager")

    config_dir = Path(__file__).resolve().parent / "config"
    team_config_path = config_dir / "team_info.json"
    if not team_config_path.exists():
        team_config_path = config_dir / "teams.json"

    db_manager = SQLiteManager(config_dir / "race_control.db")
    controller = RaceController(
        config_path=team_config_path,
        database=db_manager,
        ws_host=ws_host,
        ws_port=ws_port,
    )

    operator_window = MainWindow(controller)
    broadcast_window = BroadcastWindow(controller)

    if not headless:
        screens = app.screens()
        if len(screens) > 1:
            broadcast_window.setGeometry(screens[1].geometry())
            operator_window.setGeometry(screens[0].geometry())
        else:
            broadcast_window.resize(1600, 1000)

        operator_window.show()
        broadcast_window.show()

    return app, operator_window, broadcast_window, controller, db_manager


def main() -> None:
    parser = argparse.ArgumentParser(description="RaceControl PySide6 GUI")
    parser.add_argument("--headless", action="store_true", help="Create the UI without showing windows")
    parser.add_argument("--ws-host", default=None, help="Race WebSocket server host (e.g. Raspberry Pi IP)")
    parser.add_argument("--ws-port", default=None, type=int, help="Race WebSocket server port")
    args = parser.parse_args()

    app, *_ = build_app(headless=args.headless, ws_host=args.ws_host, ws_port=args.ws_port)

    if args.headless:
        app.processEvents()
        app.quit()
    else:
        sys.exit(app.exec())


if __name__ == "__main__":
    main()
