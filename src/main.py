from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .core.race_controller import RaceController
from .database.sqlite_manager import SQLiteManager
from .gui.broadcast_window import BroadcastWindow
from .gui.main_window import MainWindow


def build_app(headless: bool = False):
    app = QApplication(sys.argv)
    app.setApplicationName("RaceControl")
    app.setOrganizationName("RaceManager")

    config_dir = Path(__file__).resolve().parent / "config"
    team_config_path = config_dir / "team_info.json"
    if not team_config_path.exists():
        team_config_path = config_dir / "teams.json"

    db_manager = SQLiteManager(config_dir / "race_control.db")
    controller = RaceController(config_path=team_config_path, database=db_manager)

    operator_window = MainWindow(controller)
    broadcast_window = BroadcastWindow(controller)

    if not headless:
        screens = app.screens()
        if len(screens) > 1:
            broadcast_window.setGeometry(screens[1].geometry())
            operator_window.setGeometry(screens[0].geometry())
        else:
            broadcast_window.setGeometry(0, 0, 1920, 1080)

        operator_window.show()
        broadcast_window.show()

    return app, operator_window, broadcast_window, controller, db_manager


def main() -> None:
    parser = argparse.ArgumentParser(description="RaceControl PySide6 GUI")
    parser.add_argument("--headless", action="store_true", help="Create the UI without showing windows")
    args = parser.parse_args()

    app, *_ = build_app(headless=args.headless)

    if args.headless:
        app.processEvents()
        app.quit()
    else:
        sys.exit(app.exec())


if __name__ == "__main__":
    main()
