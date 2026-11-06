from __future__ import annotations

import sys

from PySide6 import QtWidgets

from .settings import SettingsStore
from .ui.main_window import MainWindow
from .workflow import ImportWorkflow


def create_main_window(settings_store: SettingsStore | None = None) -> MainWindow:
    settings_store = settings_store or SettingsStore()
    return MainWindow(settings_store, ImportWorkflow(settings_store))


def main() -> int:
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    application.setApplicationName("Hospital Marketing MVP")
    window = create_main_window()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
