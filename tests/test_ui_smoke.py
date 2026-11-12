import os

from threading import Event
from pathlib import Path
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import keyring
import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from hospital_marketing.ai.registry import ProviderRegistry
from hospital_marketing.credentials import CredentialStore
from hospital_marketing.outputs.generate import OutputManifest
from hospital_marketing.providers import ProviderRequestError
from hospital_marketing.report import ImportReport
from hospital_marketing.settings import AppSettings, SettingsStore
from hospital_marketing.ui.main_window import MainWindow
from hospital_marketing.ui.product_keywords_dialog import ProductKeywordsDialog
from hospital_marketing.ui.settings_dialog import SettingsDialog
from hospital_marketing.workflow import ImportWorkflow, WorkflowResult


_APP = None


@pytest.fixture(autouse=True)
def _mock_cli_status_checks(monkeypatch):
    from hospital_marketing.ai.cli_status import CLIStatus

    monkeypatch.setattr(
        "hospital_marketing.ui.settings_dialog.cli_status.check_all_cli_statuses",
        lambda: {cli: CLIStatus(True, f"/mock/{cli}", "1.0", None) for cli in ("claude", "codex", "gemini")},
    )
    monkeypatch.setattr(
        "hospital_marketing.ui.settings_dialog.cli_status.check_node_tool_status",
        lambda: {"node": None, "npm": None},
    )
    yield
    assert QtCore.QThreadPool.globalInstance().waitForDone(5_000)
    app = QtWidgets.QApplication.instance()
    if app is not None:
        app.processEvents()


def _app():
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return _APP


def _wait_for_import(window, timeout_ms=5_000):
    deadline = QtCore.QDeadlineTimer(timeout_ms)
    while window._import_thread is not None and window._import_thread.isRunning() and not deadline.hasExpired():
        _app().processEvents()
        QtCore.QThread.msleep(5)
    _app().processEvents()
    assert window._import_thread is None or not window._import_thread.isRunning()


class FakeWorkflow:
    def __init__(self, dashboard_path):
        self.calls = []
        self.extension_calls = []
        self.dashboard_path = dashboard_path

    def run(self, source_dir, target_dir, *, provider_id="mock", model_id="", mock_mode=True, enabled_extensions=None):
        self.calls.append((Path(source_dir), Path(target_dir), provider_id, model_id, mock_mode))
        self.extension_calls.append(tuple(enabled_extensions or ()))
        source_dir = Path(source_dir)
        source_files = sorted(path.name for path in source_dir.iterdir()) if source_dir.is_dir() else []
        self.dashboard_path.parent.mkdir(parents=True, exist_ok=True)
        self.dashboard_path.write_text("<html></html>", encoding="utf-8")
        return WorkflowResult(
            ImportReport(source_dir=str(source_dir), source_files=source_files, inserted_count=2, updated_count=1, unchanged_count=3),
            OutputManifest([], self.dashboard_path, Path(target_dir) / "exports" / "marketing.xlsx"),
            classified_count=4,
            needs_review_count=0,
        )


def test_main_window_requires_paths_before_import(tmp_path):
    _app()
    workflow = FakeWorkflow(tmp_path / "target" / "dashboard" / "index.html")
    window = MainWindow(SettingsStore(tmp_path / "settings.json"), workflow)

    window.run_button.click()
    _wait_for_import(window)

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
    _wait_for_import(window)

    assert workflow.calls == [(source, target, "local-cli", "claude", False)]
    assert settings_store.load().source_dir == source
    assert settings_store.load().target_dir == target
    assert "읽은 파일 0" in window.status_label.text()
    assert "읽을 파일이 없습니다" in window.status_label.text()
    assert "신규 2" in window.status_label.text()
    assert window.open_dashboard_button.isEnabled()
    assert not hasattr(window, "export_dashboard_button")


def test_main_window_no_longer_shows_channel_candidate_button(tmp_path):
    _app()
    window = MainWindow(SettingsStore(tmp_path / "settings.json"), FakeWorkflow(tmp_path / "dashboard.html"))
    assert not hasattr(window, "channel_candidates_button")
    window.close()


def test_import_does_not_prompt_to_start_channel_search(tmp_path, monkeypatch):
    _app()
    target = tmp_path / "target"
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(AppSettings(target_dir=target, provider_id="local-cli", model_id="claude"))

    prompts = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda _p, _t, text, *_a: prompts.append(text) or QtWidgets.QMessageBox.StandardButton.Yes)
    window = MainWindow(settings_store, FakeWorkflow(target / "dashboard" / "index.html"))
    window.source_path_edit.setText(str(tmp_path / "source"))
    window.target_path_edit.setText(str(target))
    window.run_button.click()
    _wait_for_import(window)
    assert prompts == []
    window.close()


def test_main_window_status_redacts_masked_provider_key(tmp_path):
    _app()
    masked_token = "sk-proj-" + "*" * 3 + "abcd"

    class FailingWorkflow:
        def run(self, *_args, **_kwargs):
            raise ProviderRequestError(f"HTTP 401 Incorrect API key provided: {masked_token}")

    window = MainWindow(SettingsStore(tmp_path / "settings.json"), cast(ImportWorkflow, FailingWorkflow()))
    window.source_path_edit.setText(str(tmp_path / "source"))
    window.target_path_edit.setText(str(tmp_path / "target"))

    window.run_button.click()
    _wait_for_import(window)

    status = window.status_label.text()
    assert "[REDACTED]" in status
    assert "sk-proj-" not in status
    assert "abcd" not in status
    window.close()


def test_open_dashboard_uses_injected_open_handler(tmp_path):
    from hospital_marketing.version import APP_VERSION

    _app()
    dashboard = tmp_path / "dashboard" / "index.html"
    dashboard.parent.mkdir(parents=True)
    dashboard.write_text(f'<meta name="generator" content="hospital-marketing {APP_VERSION}">', encoding="utf-8")
    opened = []
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(AppSettings(target_dir=tmp_path))
    window = MainWindow(settings_store, FakeWorkflow(dashboard), open_path=opened.append)

    window.open_dashboard_button.click()

    assert opened == [dashboard]


@pytest.mark.parametrize("html", ["<html></html>", '<meta name="generator" content="hospital-marketing 0.0.0">'])
def test_open_dashboard_warns_for_legacy_or_different_version(tmp_path, monkeypatch, html):
    _app()
    dashboard = tmp_path / "dashboard" / "index.html"
    dashboard.parent.mkdir(parents=True)
    dashboard.write_text(html, encoding="utf-8")
    opened, messages = [], []
    monkeypatch.setattr(QtWidgets.QMessageBox, "information", lambda _parent, title, text: messages.append((title, text)))
    settings = SettingsStore(tmp_path / "settings.json")
    settings.save(AppSettings(target_dir=tmp_path))
    window = MainWindow(settings, FakeWorkflow(dashboard), open_path=opened.append)

    window.open_dashboard_button.click()

    assert opened == [dashboard]
    assert messages == [("이전 버전 대시보드", "이전 버전에서 만든 대시보드입니다. 위키를 다시 생성하면 새 화면으로 바뀝니다.")]
    window.close()


def test_settings_dialog_saves_provider_and_key_to_separate_stores(tmp_path, monkeypatch):
    _app()
    saved = {}
    monkeypatch.setattr(keyring, "set_password", lambda service, username, secret: saved.update({username: secret}))
    settings_store = SettingsStore(tmp_path / "settings.json")
    dialog = SettingsDialog(settings_store, CredentialStore(), ProviderRegistry())
    dialog.provider_combo.setCurrentText("anthropic")
    dialog.model_combo.setCurrentText("claude-test")
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


def test_settings_dialog_preserves_product_keywords_when_saving(tmp_path):
    from hospital_marketing.settings import ProductKeyword

    _app()
    settings_store = SettingsStore(tmp_path / "settings.json")
    keywords = (ProductKeyword("제품 A", False), ProductKeyword("제품 B", True))
    settings_store.save(AppSettings(product_keywords=keywords))
    dialog = SettingsDialog(settings_store, CredentialStore(), ProviderRegistry())

    dialog.save_button.click()

    assert settings_store.load().product_keywords == keywords


def test_product_keywords_dialog_adds_trimmed_keyword_and_rejects_duplicates(tmp_path, monkeypatch):
    from hospital_marketing.settings import ProductKeyword

    _app()
    dialog = ProductKeywordsDialog((ProductKeyword("피아모 노빌리티"),))
    answers = iter((("  새 제품  ", True), (" 피아모   노빌리티 ", True)))
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *_args, **_kwargs: next(answers))
    warnings = []
    monkeypatch.setattr(QtWidgets.QMessageBox, "warning", lambda _parent, title, text: warnings.append((title, text)))

    dialog.add_button.click()
    dialog.add_button.click()

    assert dialog.keywords() == (ProductKeyword("피아모 노빌리티"), ProductKeyword("새 제품"))
    assert len(warnings) == 1
    assert "이미" in warnings[0][1]


def test_product_keywords_dialog_edits_removes_restores_defaults_and_cancel_does_not_save(tmp_path, monkeypatch):
    from hospital_marketing.settings import DEFAULT_PRODUCTS, ProductKeyword

    _app()
    settings_store = SettingsStore(tmp_path / "settings.json")
    original = (ProductKeyword("사용자 제품", False),)
    settings_store.save(AppSettings(product_keywords=original))
    dialog = ProductKeywordsDialog(original)
    dialog.keyword_list.setCurrentRow(0)
    monkeypatch.setattr(QtWidgets.QInputDialog, "getText", lambda *_args, **_kwargs: ("수정 제품", True))

    dialog.edit_button.click()
    assert dialog.keywords() == (ProductKeyword("수정 제품", False),)
    dialog.remove_button.click()
    assert dialog.keywords() == ()
    dialog.restore_button.click()
    assert dialog.keywords() == tuple(ProductKeyword(term) for term in DEFAULT_PRODUCTS)
    dialog.reject()

    assert settings_store.load().product_keywords == original


def test_main_window_does_not_run_when_no_product_keyword_is_enabled(tmp_path, monkeypatch):
    from hospital_marketing.settings import ProductKeyword

    _app()
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(AppSettings(product_keywords=(ProductKeyword("제품 A", False),)))
    workflow = FakeWorkflow(tmp_path / "target" / "dashboard" / "index.html")
    window = MainWindow(settings_store, workflow)
    window.source_path_edit.setText(str(tmp_path / "source"))
    window.target_path_edit.setText(str(tmp_path / "target"))

    window.run_button.click()
    _wait_for_import(window)

    assert workflow.calls == []
    assert "검색 단어" in window.status_label.text()


def test_main_window_keyword_dialog_saves_changes_and_import_preserves_them(tmp_path, monkeypatch):
    from hospital_marketing.settings import ProductKeyword
    import hospital_marketing.ui.main_window as main_window_module

    _app()
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(AppSettings(product_keywords=(ProductKeyword("제품 A", True),)))
    updated_keywords = (ProductKeyword("제품 A", False), ProductKeyword("제품 B", True))

    class AcceptedDialog:
        def __init__(self, *_args):
            pass

        def exec(self):
            return QtWidgets.QDialog.DialogCode.Accepted

        def keywords(self):
            return updated_keywords

    monkeypatch.setattr(main_window_module, "ProductKeywordsDialog", AcceptedDialog)
    target = tmp_path / "target"
    workflow = FakeWorkflow(target / "dashboard" / "index.html")
    window = MainWindow(settings_store, workflow)
    window.product_keywords_button.click()

    assert settings_store.load().product_keywords == updated_keywords
    window.source_path_edit.setText(str(tmp_path / "source"))
    window.target_path_edit.setText(str(target))
    window.run_button.click()
    _wait_for_import(window)

    assert settings_store.load().product_keywords == updated_keywords


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
    _wait_for_import(window)

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
        _wait_for_import(window)

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
    _wait_for_import(window)

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


def test_path_guide_is_small_circled_question_icon_at_group_top_right(tmp_path):
    _app()
    window = MainWindow(
        SettingsStore(tmp_path / "settings.json"),
        FakeWorkflow(tmp_path / "target" / "dashboard" / "index.html"),
    )
    window.show()
    QtWidgets.QApplication.processEvents()

    button = window.path_guide_button
    group = window.paths_group
    assert isinstance(button, QtWidgets.QToolButton)
    assert button.parent() is group
    assert button.text() == "?"
    assert button.accessibleName() == "경로 안내"
    assert "사용법" in button.toolTip()
    assert button.width() <= 24 and button.height() <= 24
    assert button.width() == button.height()
    assert button.y() <= 4
    assert group.width() - button.geometry().right() <= 24
    assert not any(
        b.text() == "경로 안내" for b in window.findChildren(QtWidgets.QPushButton)
    )

    window.resize(window.width() + 300, window.height())
    QtWidgets.QApplication.processEvents()
    assert group.width() - button.geometry().right() <= 24
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
    _wait_for_import(window)

    assert "secret-test-value" not in window.status_label.text()
    assert window.status_label.text() == "처리에 실패했습니다. 입력 파일과 설정을 확인한 뒤 다시 시도해 주세요."
    window.close()


def test_provider_error_disables_open_dashboard_when_previous_dashboard_exists(tmp_path):
    _app()
    source = tmp_path / "source"
    target = tmp_path / "target"
    dashboard = target / "dashboard" / "index.html"
    dashboard.parent.mkdir(parents=True)
    dashboard.write_text("<html></html>", encoding="utf-8")
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(AppSettings(source_dir=source, target_dir=target))

    class ProviderFailingWorkflow:
        def run(self, *args, **kwargs):
            raise ProviderRequestError("provider request failed")

    window = MainWindow(settings_store, cast(ImportWorkflow, ProviderFailingWorkflow()))

    window.run_button.click()
    _wait_for_import(window)

    assert not window.open_dashboard_button.isEnabled()
    window.close()


def test_provider_error_shows_cause_and_mock_mode_fallback(tmp_path):
    _app()

    class ProviderFailingWorkflow:
        def run(self, *args, **kwargs):
            raise ProviderRequestError("AI 모델을 찾을 수 없습니다. 모델 ID를 확인해 주세요.")

    window = MainWindow(
        SettingsStore(tmp_path / "settings.json"),
        cast(ImportWorkflow, ProviderFailingWorkflow()),
    )
    window.source_path_edit.setText(str(tmp_path / "source"))
    window.target_path_edit.setText(str(tmp_path / "target"))

    window.run_button.click()
    _wait_for_import(window)

    assert "AI 모델을 찾을 수 없습니다" in window.status_label.text()
    assert "목업 모드로 다시 실행" in window.status_label.text()
    window.close()


def test_settings_default_to_subscription_cli(tmp_path):
    _app()
    dialog = SettingsDialog(SettingsStore(tmp_path / "settings.json"), CredentialStore(), ProviderRegistry())

    assert not dialog.mock_mode_checkbox.isChecked()
    assert dialog.provider_combo.currentText() == "local-cli"
    assert dialog.model_combo.currentText() == "claude"


def test_disabled_primary_buttons_use_disabled_colors_and_restore_enabled_styles(tmp_path):
    _app()
    window = MainWindow(
        SettingsStore(tmp_path / "settings.json"),
        FakeWorkflow(tmp_path / "target" / "dashboard" / "index.html"),
    )
    window.show()
    _app().processEvents()

    def background(button):
        image = button.grab().toImage()
        return image.pixelColor(6, image.height() // 2).name()

    window.run_button.setEnabled(False)
    assert background(window.run_button) == "#e9e3d3"
    assert background(window.open_dashboard_button) == "#e9e3d3"

    window.run_button.setEnabled(True)
    window.open_dashboard_button.setEnabled(True)
    assert background(window.run_button) == "#09223f"
    assert background(window.open_dashboard_button) == "#245c9e"
    window.close()

def test_large_source_file_in_real_ai_mode_can_be_cancelled_before_workflow(tmp_path, monkeypatch):
    from hospital_marketing.documents.size_warnings import LARGE_SOURCE_FILE_THRESHOLD_BYTES

    _app()
    source = tmp_path / "source"
    source.mkdir()
    (source / "large.txt").write_text("x" * (LARGE_SOURCE_FILE_THRESHOLD_BYTES + 1), encoding="utf-8")
    target = tmp_path / "target"
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(AppSettings(
        provider_id="openai",
        mock_mode=False,
        enabled_extensions=(".txt",),
    ))
    workflow = FakeWorkflow(target / "dashboard" / "index.html")
    confirmations = []
    window = MainWindow(settings_store, workflow)
    monkeypatch.setattr(
        window,
        "_confirm_large_source_files",
        lambda files: confirmations.append(tuple(item.file_name for item in files)) or False,
        raising=False,
    )
    window.source_path_edit.setText(str(source))
    window.target_path_edit.setText(str(target))

    window.run_button.click()
    _wait_for_import(window)

    assert len(confirmations) == 1
    assert confirmations[0] == ("large.txt",)
    assert workflow.calls == []


def test_large_source_file_in_real_ai_mode_continues_after_confirmation(tmp_path, monkeypatch):
    from hospital_marketing.documents.size_warnings import LARGE_SOURCE_FILE_THRESHOLD_BYTES

    _app()
    source = tmp_path / "source"
    source.mkdir()
    (source / "large.txt").write_text("x" * (LARGE_SOURCE_FILE_THRESHOLD_BYTES + 1), encoding="utf-8")
    target = tmp_path / "target"
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(AppSettings(provider_id="openai", mock_mode=False, enabled_extensions=(".txt",)))
    workflow = FakeWorkflow(target / "dashboard" / "index.html")
    window = MainWindow(settings_store, workflow)
    monkeypatch.setattr(window, "_confirm_large_source_files", lambda _files: True, raising=False)
    window.source_path_edit.setText(str(source))
    window.target_path_edit.setText(str(target))

    window.run_button.click()
    _wait_for_import(window)

    assert len(workflow.calls) == 1
    assert "큰 원본 파일" in window.status_label.text()


def test_large_source_file_in_mock_mode_runs_without_confirmation_and_shows_warning(tmp_path, monkeypatch):
    from hospital_marketing.documents.size_warnings import LARGE_SOURCE_FILE_THRESHOLD_BYTES

    _app()
    source = tmp_path / "source"
    source.mkdir()
    (source / "large.txt").write_text("x" * (LARGE_SOURCE_FILE_THRESHOLD_BYTES + 1), encoding="utf-8")
    target = tmp_path / "target"
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(AppSettings(enabled_extensions=(".txt",), provider_id="mock", model_id="", mock_mode=True))
    workflow = FakeWorkflow(target / "dashboard" / "index.html")
    window = MainWindow(settings_store, workflow)
    monkeypatch.setattr(
        window,
        "_confirm_large_source_files",
        lambda _files: pytest.fail("목업 모드에서는 확인 창을 띄우지 않습니다."),
        raising=False,
    )
    window.source_path_edit.setText(str(source))
    window.target_path_edit.setText(str(target))

    window.run_button.click()
    _wait_for_import(window)

    assert len(workflow.calls) == 1
    assert "실제 AI로 실행하면" in window.status_label.text()
    assert "large.txt" in window.status_label.text()


def test_import_runs_off_ui_thread_and_keeps_window_responsive(tmp_path):
    _app()
    started = Event()
    release = Event()
    dashboard = tmp_path / "target" / "dashboard" / "index.html"

    class BlockingWorkflow(FakeWorkflow):
        def run(self, *args, **kwargs):
            started.set()
            assert release.wait(5)
            return super().run(*args, **kwargs)

    window = MainWindow(SettingsStore(tmp_path / "settings.json"), BlockingWorkflow(dashboard))
    window.source_path_edit.setText(str(tmp_path / "source"))
    window.target_path_edit.setText(str(tmp_path / "target"))
    window.show()
    timer_fired = []
    QtCore.QTimer.singleShot(100, lambda: (timer_fired.append(True), release.set()))

    window.run_button.click()
    try:
        assert started.wait(2)
        assert not window.run_button.isEnabled()
        assert not window.open_dashboard_button.isEnabled()
        assert window.import_progress.isVisible()
        assert "처리 중" in window.status_label.text()
        _app().processEvents()
        _wait_for_import(window)
        assert window.import_progress.isVisible()
        assert window.import_progress.value() == 100
        QtCore.QThread.msleep(550)
        _app().processEvents()

        assert timer_fired == [True]
        assert window.run_button.isEnabled()
        assert not window.import_progress.isVisible()
        assert "처리 완료" in window.status_label.text()
        assert window.open_dashboard_button.isEnabled()
    finally:
        release.set()
        _wait_for_import(window)
        window.close()


def test_import_progress_bar_shows_percentage_and_stage_then_hides(tmp_path):
    from hospital_marketing.workflow import WorkflowProgress

    _app()
    dashboard = tmp_path / "target" / "dashboard" / "index.html"
    window = MainWindow(SettingsStore(tmp_path / "settings.json"), FakeWorkflow(dashboard))
    window.show()

    assert window.import_progress.minimum() == 0
    assert window.import_progress.maximum() == 100
    window.import_progress.setVisible(True)
    window.import_progress_label.setVisible(True)
    window._on_import_progress(WorkflowProgress("channels", 3, 14, "채널 수집 · 3/14 · 목업 병원", 26))
    assert window.import_progress.value() == 26
    assert window.import_progress.isVisible()
    assert "2/4 단계" in window.import_progress_label.text()
    assert "3/14" in window.import_progress_label.text()
    window._cancel_import()
    assert not window.open_dashboard_button.isEnabled()
    assert window.import_progress.format() == "취소 중…"
    assert window.import_progress_label.text() == "취소 중…"
    window._on_import_finished(None, RuntimeError("failed"))
    assert not window.import_progress.isVisible()
    window.close()


def test_import_progress_text_stays_black_with_dark_system_palette(tmp_path):
    _app()
    window = MainWindow(SettingsStore(tmp_path / "settings.json"), FakeWorkflow(tmp_path / "dashboard.html"))
    dark_palette = QtGui.QPalette(window.palette())
    dark_palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("white"))
    dark_palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor("white"))
    window.setPalette(dark_palette)
    window.show()
    _app().processEvents()

    assert "QLabel#import_progress_label" in window.centralWidget().styleSheet()
    assert "QProgressBar#import_progress" in window.centralWidget().styleSheet()
    assert window.import_progress_label.palette().color(window.import_progress_label.foregroundRole()) == QtGui.QColor("black")
    assert window.import_progress.palette().color(window.import_progress.foregroundRole()) == QtGui.QColor("black")
    window.close()


def test_completed_progress_hides_after_import_context_cleanup(tmp_path):
    _app()
    window = MainWindow(SettingsStore(tmp_path / "settings.json"), FakeWorkflow(tmp_path / "dashboard.html"))
    window.show()
    window.import_progress.setVisible(True)
    window.import_progress_label.setVisible(True)
    window._import_context = (AppSettings(), tmp_path, [])

    window._hide_import_progress_if_idle()
    assert window.import_progress.isVisible()
    window._import_context = None
    QtCore.QThread.msleep(75)
    _app().processEvents()

    assert not window.import_progress.isVisible()
    window.close()


def test_closing_during_import_waits_for_completion_without_channel_prompt(tmp_path, monkeypatch):
    from datetime import date
    from hospital_marketing.domain import Hospital
    import hospital_marketing.ui.main_window as main_window_module

    _app()
    started = Event()
    release = Event()
    target = tmp_path / "target"
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(AppSettings(target_dir=target, provider_id="local-cli", model_id="claude"))


    class BlockingWorkflow(FakeWorkflow):
        def run(self, *args, **kwargs):
            started.set()
            assert release.wait(5)
            return super().run(*args, **kwargs)

    prompts = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *_args: prompts.append(True) or QtWidgets.QMessageBox.StandardButton.Yes,
    )
    window = MainWindow(settings_store, BlockingWorkflow(target / "dashboard" / "index.html"))
    window.source_path_edit.setText(str(tmp_path / "source"))
    window.target_path_edit.setText(str(target))
    window.show()
    window.run_button.click()

    try:
        assert started.wait(2)
        window.close()
        assert window.isVisible()
        assert window.status_label.text() == "가져오기가 끝난 뒤 앱이 종료됩니다."
    finally:
        release.set()
        _wait_for_import(window)

    assert not window.isVisible()
    assert prompts == []


def test_ai_settings_save_does_not_replace_paths_selected_on_main_window(tmp_path, monkeypatch):
    import hospital_marketing.ui.main_window as main_window_module

    _app()
    settings_store = SettingsStore(tmp_path / "settings.json")
    settings_store.save(AppSettings(source_dir=tmp_path / "old-source", target_dir=tmp_path / "old-target"))

    class AcceptedDialog:
        def __init__(self, *_args): pass
        def exec(self): return QtWidgets.QDialog.DialogCode.Accepted

    monkeypatch.setattr(main_window_module, "SettingsDialog", AcceptedDialog)
    target = tmp_path / "selected-target"
    source = tmp_path / "20261109"
    window = MainWindow(settings_store, FakeWorkflow(target / "dashboard" / "index.html"))
    window.source_path_edit.setText(str(source))
    window.target_path_edit.setText(str(target))

    window._open_settings()

    assert window.source_path_edit.text() == str(source)
    assert window.target_path_edit.text() == str(target)
    window.close()


def test_import_status_identifies_source_folder_before_and_after_read(tmp_path):
    _app()
    source = tmp_path / "20261109"
    source.mkdir()
    (source / "20261109_계약병원.xlsx").write_bytes(b"mock")
    target = tmp_path / "target"
    window = MainWindow(SettingsStore(tmp_path / "settings.json"), FakeWorkflow(target / "dashboard" / "index.html"))
    window.source_path_edit.setText(str(source))
    window.target_path_edit.setText(str(target))

    window.run_button.click()
    assert f"Source {source}" in window.status_label.text()
    _wait_for_import(window)

    assert f"Source {source}" in window.status_label.text()
    assert "20261109_계약병원.xlsx" in window.status_label.text()
    window.close()


def test_import_status_warns_when_every_hospital_is_unchanged(tmp_path):
    _app()
    source = tmp_path / "20261109"
    source.mkdir()
    target = tmp_path / "target"
    workflow = FakeWorkflow(target / "dashboard" / "index.html")

    def return_unchanged(*args, **kwargs):
        result = FakeWorkflow.run(workflow, *args, **kwargs)
        result.report.inserted_count = 0
        result.report.updated_count = 0
        result.report.unchanged_count = 2
        return result

    workflow.run = return_unchanged
    window = MainWindow(SettingsStore(tmp_path / "settings.json"), workflow)
    window.source_path_edit.setText(str(source))
    window.target_path_edit.setText(str(target))

    window.run_button.click()
    _wait_for_import(window)

    assert "신규 0" in window.status_label.text()
    assert "변경 없음 2" in window.status_label.text()
    assert "이미 가져온 파일과 같습니다. Source 폴더를 확인하세요." in window.status_label.text()
    window.close()
