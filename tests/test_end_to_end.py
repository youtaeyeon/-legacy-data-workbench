import os
from importlib.metadata import version

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from hospital_marketing.app import create_main_window
from hospital_marketing.settings import SettingsStore
from hospital_marketing.ui.main_window import MainWindow


def test_application_factory_builds_first_run_window_without_api_key(tmp_path):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    window = create_main_window(SettingsStore(tmp_path / "settings.json"))

    assert isinstance(window, MainWindow)
    assert window.windowTitle() == f"병원 마케팅 대시보드 · v{version('hospital-marketing-mvp')}"
    assert not window.open_dashboard_button.isEnabled()
    assert window.source_path_edit.text() == ""
    assert window.target_path_edit.text() == ""
    window.close()
    app.quit()
