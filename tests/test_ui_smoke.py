import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import keyring
from PySide6 import QtWidgets

from hospital_marketing.ai.registry import ProviderRegistry
from hospital_marketing.credentials import CredentialStore
from hospital_marketing.outputs.generate import OutputManifest
from hospital_marketing.report import ImportReport
from hospital_marketing.settings import AppSettings, SettingsStore
from hospital_marketing.ui.main_window import MainWindow
from hospital_marketing.ui.settings_dialog import SettingsDialog
from hospital_marketing.workflow import WorkflowResult


_APP = None


def _app():
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return _APP


class FakeWorkflow:
    def __init__(self, dashboard_path):
        self.calls = []
        self.extension_calls = []
        self.dashboard_path = dashboard_path

    def run(self, source_dir, target_dir, *, provider_id="mock", model_id="", mock_mode=True, enabled_extensions=None):
        self.calls.append((Path(source_dir), Path(target_dir), provider_id, model_id, mock_mode))
        self.extension_calls.append(tuple(enabled_extensions or ()))
        self.dashboard_path.parent.mkdir(parents=True, exist_ok=True)
        self.dashboard_path.write_text("<html></html>", encoding="utf-8")
        return WorkflowResult(
            ImportReport(inserted_count=2, updated_count=1, unchanged_count=3),
            OutputManifest([], self.dashboard_path, Path(target_dir) / "exports" / "marketing.xlsx"),
            classified_count=4,
            needs_review_count=0,
        )


def test_main_window_requires_paths_before_import(tmp_path):
    _app()
    workflow = FakeWorkflow(tmp_path / "target" / "dashboard" / "index.html")
    window = MainWindow(SettingsStore(tmp_path / "settings.json"), workflow)

    window.run_button.click()

    assert "source" in window.status_label.text().lower()
    assert workflow.calls == []


def test_main_window_persists_paths_runs_workflow_and_shows_counts(tmp_path):
    _app()
    source = tmp_path / "source"
    target = tmp_path / "target"
    dashboard = target / "dashboard" / "index.html"
    settings_store = SettingsStore(tmp_path / "settings.json")
    workflow = FakeWorkflow(dashboard)
    window = MainWindow(settings_store, workflow)
    window.source_path_edit.setText(str(source))
    window.target_path_edit.setText(str(target))

    window.run_button.click()

    assert workflow.calls == [(source, target, "mock", "", True)]
    assert settings_store.load().source_dir == source
    assert settings_store.load().target_dir == target
    assert "읽은 파일 0" in window.status_label.text()
    assert "읽을 파일이 없습니다" in window.status_label.text()
    assert "신규 2" in window.status_label.text()
    assert window.open_dashboard_button.isEnabled()


def test_open_dashboard_uses_injected_open_handler(tmp_path):
    _app()
    dashboard = tmp_path / "dashboard" / "index.html"
    dashboard.parent.mkdir(parents=True)
    dashboard.write_text("<html></html>", encoding="utf-8")
    opened = []
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(AppSettings(target_dir=tmp_path))
    window = MainWindow(settings_store, FakeWorkflow(dashboard), open_path=opened.append)

    window.open_dashboard_button.click()

    assert opened == [dashboard]


def test_settings_dialog_saves_provider_and_key_to_separate_stores(tmp_path, monkeypatch):
    _app()
    saved = {}
    monkeypatch.setattr(keyring, "set_password", lambda service, username, secret: saved.update({username: secret}))
    settings_store = SettingsStore(tmp_path / "settings.json")
    dialog = SettingsDialog(settings_store, CredentialStore(), ProviderRegistry())
    dialog.provider_combo.setCurrentText("anthropic")
    dialog.model_edit.setText("claude-test")
    dialog.api_key_edit.setText("secret-ui-key")
    dialog.mock_mode_checkbox.setChecked(False)

    dialog.save_button.click()

    assert settings_store.load().provider_id == "anthropic"
    assert settings_store.load().model_id == "claude-test"
    assert settings_store.load().mock_mode is False
    assert saved["anthropic"] == "secret-ui-key"
    assert "secret-ui-key" not in settings_store.path.read_text(encoding="utf-8")


def test_settings_dialog_preserves_enabled_extensions_when_saving(tmp_path):
    _app()
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(AppSettings(enabled_extensions=(".xlsx",)))
    dialog = SettingsDialog(settings_store, CredentialStore(), ProviderRegistry())

    dialog.save_button.click()

    assert settings_store.load().enabled_extensions == (".xlsx",)


def test_main_window_groups_paths_and_highlights_primary_action(tmp_path):
    _app()
    window = MainWindow(SettingsStore(tmp_path / "settings.json"), FakeWorkflow(tmp_path / "target" / "dashboard" / "index.html"))

    assert window.title_label.text() == "병원 마케팅 위키"
    assert window.paths_group.title() == "1. 폴더 설정"
    assert "#f3eee2" in window.centralWidget().styleSheet()
    assert window.run_button.objectName() == "run_import_button"
    assert window.run_button.text() == "선택 파일 읽고 위키 생성"
    style = window.centralWidget().styleSheet()
    assert "QGroupBox::title" in style and "color: #000000" in style
    window.close()


def test_main_window_persists_extension_checkboxes_and_black_folder_labels(tmp_path):
    from hospital_marketing.documents import SUPPORTED_EXTENSIONS

    _app()
    source = tmp_path / "source"
    target = tmp_path / "target"
    workflow = FakeWorkflow(target / "dashboard" / "index.html")
    settings_store = SettingsStore(tmp_path / "settings.json")
    window = MainWindow(settings_store, workflow)
    assert set(window.extension_checkboxes) == set(SUPPORTED_EXTENSIONS)
    assert all(box.isChecked() for box in window.extension_checkboxes.values())
    assert "QCheckBox { color: #000000; }" in window.centralWidget().styleSheet()
    assert "color: #000000" in window.source_label.styleSheet()
    assert "color: #000000" in window.target_label.styleSheet()

    for checkbox in window.extension_checkboxes.values():
        checkbox.setChecked(False)
    window.extension_checkboxes[".txt"].setChecked(True)
    window.source_path_edit.setText(str(source))
    window.target_path_edit.setText(str(target))
    window.run_button.click()

    assert workflow.extension_calls[-1] == (".txt",)
    assert settings_store.load().enabled_extensions == (".txt",)
    window.close()


def test_main_window_blocks_source_equal_to_or_nested_in_target(tmp_path, monkeypatch):
    _app()
    monkeypatch.setattr(os.path, "normcase", lambda value: value.casefold())
    warnings = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda _parent, _title, text: warnings.append(text),
    )
    paths = (
        (tmp_path / "same", tmp_path / "same"),
        (tmp_path / "data" / "source" / "20261102", tmp_path / "data"),
        (tmp_path / "DATA" / "source" / "20261102", tmp_path / "data"),
    )

    for index, (source, target) in enumerate(paths):
        workflow = FakeWorkflow(target / "dashboard" / "index.html")
        window = MainWindow(SettingsStore(tmp_path / f"settings-{index}.json"), workflow)
        window.source_path_edit.setText(str(source))
        window.target_path_edit.setText(str(target))

        window.run_button.click()

        assert workflow.calls == []
        assert "Target 폴더 안에 Source" in window.status_label.text()
        assert warnings[-1] == window.status_label.text()
        window.close()


def test_main_window_allows_target_inside_source_and_reports_empty_source(tmp_path, monkeypatch):
    _app()
    warnings = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda _parent, _title, text: warnings.append(text),
    )
    source = tmp_path / "source"
    target = source / "output"
    workflow = FakeWorkflow(target / "dashboard" / "index.html")
    window = MainWindow(SettingsStore(tmp_path / "settings.json"), workflow)
    window.source_path_edit.setText(str(source))
    window.target_path_edit.setText(str(target))

    window.run_button.click()

    assert len(workflow.calls) == 1
    assert "읽을 파일이 없습니다" in window.status_label.text()
    assert "선택 확장자 파일이 폴더 바로 아래" in window.status_label.text()
    assert warnings == []
    window.close()


def test_path_guide_button_explains_source_target_and_date_order(tmp_path, monkeypatch):
    _app()
    messages = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda _parent, title, text: messages.append((title, text)),
    )
    window = MainWindow(
        SettingsStore(tmp_path / "settings.json"),
        FakeWorkflow(tmp_path / "target" / "dashboard" / "index.html"),
    )

    window.path_guide_button.click()

    assert len(messages) == 1
    title, message = messages[0]
    assert "경로 안내" in title
    assert "바로 들어 있는" in message
    assert "하위 폴더는 읽지 않습니다" in message
    assert "20261102" in message and "20261103" in message and "20261106" in message
    assert "나쁜 예" in message
    window.close()


def test_run_error_never_displays_secret_from_exception(tmp_path):
    _app()

    class SecretFailingWorkflow:
        def run(self, *args, **kwargs):
            raise RuntimeError("provider failed with api_key=secret-test-value")

    window = MainWindow(SettingsStore(tmp_path / "settings.json"), SecretFailingWorkflow())
    window.source_path_edit.setText(str(tmp_path / "source"))
    window.target_path_edit.setText(str(tmp_path / "target"))

    window.run_button.click()

    assert "secret-test-value" not in window.status_label.text()
    assert window.status_label.text() == "처리에 실패했습니다. 입력 파일과 설정을 확인한 뒤 다시 시도해 주세요."
    window.close()


def test_settings_default_to_offline_mock_mode(tmp_path):
    _app()
    dialog = SettingsDialog(SettingsStore(tmp_path / "settings.json"), CredentialStore(), ProviderRegistry())

    assert dialog.mock_mode_checkbox.isChecked()
    assert dialog.provider_combo.currentText() == "mock"
