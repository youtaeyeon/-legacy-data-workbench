import os
import re
from pathlib import Path
from typing import cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import keyring
import pytest
from PySide6 import QtCore, QtWidgets

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
    assert window.export_dashboard_button.isEnabled()


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

    status = window.status_label.text()
    assert "[REDACTED]" in status
    assert "sk-proj-" not in status
    assert "abcd" not in status
    window.close()


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


def test_dashboard_export_button_is_disabled_without_dashboard(tmp_path):
    _app()
    window = MainWindow(
        SettingsStore(tmp_path / "settings.json"),
        FakeWorkflow(tmp_path / "target" / "dashboard" / "index.html"),
    )

    assert not window.export_dashboard_button.isEnabled()
    window.close()


def test_dashboard_export_copies_standalone_html_with_date_name_and_extension(tmp_path, monkeypatch):
    _app()
    target = tmp_path / "target"
    dashboard = target / "dashboard" / "index.html"
    dashboard.parent.mkdir(parents=True)
    dashboard.write_text("<!doctype html><p>single file</p>", encoding="utf-8")
    settings = SettingsStore(tmp_path / "settings.json")
    settings.save(AppSettings(target_dir=target))
    documents = tmp_path / "내 문서 폴더"
    destination_without_extension = tmp_path / "공유 폴더" / "병원 마케팅 대시보드"
    destination_without_extension.parent.mkdir()
    dialog_call = {}

    def choose_destination(_parent, title, initial_path, file_filter):
        dialog_call.update(title=title, initial_path=initial_path, file_filter=file_filter)
        return str(destination_without_extension), "HTML 파일 (*.html)"

    monkeypatch.setattr(QtWidgets.QFileDialog, "getSaveFileName", choose_destination)
    monkeypatch.setattr(QtCore.QStandardPaths, "writableLocation", lambda *_args: str(documents))
    window = MainWindow(settings, FakeWorkflow(dashboard))

    window.export_dashboard_button.click()

    exported = destination_without_extension.with_suffix(".html")
    assert exported.read_text(encoding="utf-8") == dashboard.read_text(encoding="utf-8")
    assert dialog_call["title"] == "대시보드 HTML 내보내기"
    assert dialog_call["file_filter"] == "HTML 파일 (*.html)"
    assert Path(dialog_call["initial_path"]).parent == documents
    assert re.fullmatch(r"병원마케팅대시보드_\d{8}\.html", Path(dialog_call["initial_path"]).name)
    assert str(exported) in window.status_label.text()
    assert "외부 공유 전에 실제 회사 자료가 포함되지 않았는지 확인하세요" in window.status_label.text()
    window.close()


@pytest.mark.parametrize(
    ("answer", "expected_content"),
    [
        (QtWidgets.QMessageBox.StandardButton.Yes, "<!doctype html><p>new</p>"),
        (QtWidgets.QMessageBox.StandardButton.No, "old file"),
    ],
)
def test_dashboard_export_confirms_before_overwriting(tmp_path, monkeypatch, answer, expected_content):
    _app()
    target = tmp_path / "target"
    dashboard = target / "dashboard" / "index.html"
    dashboard.parent.mkdir(parents=True)
    dashboard.write_text("<!doctype html><p>new</p>", encoding="utf-8")
    settings = SettingsStore(tmp_path / "settings.json")
    settings.save(AppSettings(target_dir=target))
    destination = tmp_path / "공유 폴더" / "이미 있는 대시보드.html"
    destination.parent.mkdir()
    destination.write_text("old file", encoding="utf-8")
    confirmations = []
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(destination), "HTML 파일 (*.html)"),
    )

    def confirm_overwrite(_parent, title, message, buttons, default):
        confirmations.append((title, message, buttons, default))
        return answer

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", confirm_overwrite)
    window = MainWindow(settings, FakeWorkflow(dashboard))

    window.export_dashboard_button.click()

    assert len(confirmations) == 1
    assert "덮어쓰기" in confirmations[0][0]
    assert confirmations[0][3] == QtWidgets.QMessageBox.StandardButton.No
    assert destination.read_text(encoding="utf-8") == expected_content
    window.close()


def test_dashboard_export_rejects_explicit_non_html_extension_without_renaming(tmp_path, monkeypatch):
    _app()
    target = tmp_path / "target"
    dashboard = target / "dashboard" / "index.html"
    dashboard.parent.mkdir(parents=True)
    dashboard.write_text("<!doctype html><p>new</p>", encoding="utf-8")
    settings = SettingsStore(tmp_path / "settings.json")
    settings.save(AppSettings(target_dir=target))
    destination_dir = tmp_path / "공유 폴더"
    destination_dir.mkdir()
    requested_pdf = destination_dir / "report.pdf"
    existing_html = destination_dir / "report.html"
    existing_html.write_text("keep this file", encoding="utf-8")
    confirmations = []
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(requested_pdf), "HTML 파일 (*.html)"),
    )

    def confirm_overwrite(*args):
        confirmations.append(args)
        return QtWidgets.QMessageBox.StandardButton.No

    monkeypatch.setattr(QtWidgets.QMessageBox, "question", confirm_overwrite)
    window = MainWindow(settings, FakeWorkflow(dashboard))

    window.export_dashboard_button.click()

    assert confirmations == []
    assert not requested_pdf.exists()
    assert existing_html.read_text(encoding="utf-8") == "keep this file"
    assert ".html" in window.status_label.text()
    window.close()


def test_dashboard_export_does_not_copy_dashboard_onto_itself(tmp_path, monkeypatch):
    _app()
    target = tmp_path / "target"
    dashboard = target / "dashboard" / "index.html"
    dashboard.parent.mkdir(parents=True)
    dashboard.write_text("<!doctype html><p>original</p>", encoding="utf-8")
    settings = SettingsStore(tmp_path / "settings.json")
    settings.save(AppSettings(target_dir=target))
    monkeypatch.setattr(
        QtWidgets.QFileDialog,
        "getSaveFileName",
        lambda *_args: (str(dashboard), "HTML 파일 (*.html)"),
    )
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "question",
        lambda *_args: pytest.fail("원본 대시보드에는 덮어쓰기 확인이 필요하지 않습니다."),
    )
    window = MainWindow(settings, FakeWorkflow(dashboard))

    window.export_dashboard_button.click()

    assert dashboard.read_text(encoding="utf-8") == "<!doctype html><p>original</p>"
    assert "이미 대시보드 HTML입니다" in window.status_label.text()
    window.close()


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

    assert "secret-test-value" not in window.status_label.text()
    assert window.status_label.text() == "처리에 실패했습니다. 입력 파일과 설정을 확인한 뒤 다시 시도해 주세요."
    window.close()


def test_provider_error_disables_dashboard_export_when_previous_dashboard_exists(tmp_path):
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
    assert window.export_dashboard_button.isEnabled()
    window.run_button.click()

    assert not window.open_dashboard_button.isEnabled()
    assert not window.export_dashboard_button.isEnabled()
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

    assert "AI 모델을 찾을 수 없습니다" in window.status_label.text()
    assert "목업 모드로 다시 실행" in window.status_label.text()
    window.close()


def test_settings_default_to_offline_mock_mode(tmp_path):
    _app()
    dialog = SettingsDialog(SettingsStore(tmp_path / "settings.json"), CredentialStore(), ProviderRegistry())

    assert dialog.mock_mode_checkbox.isChecked()
    assert dialog.provider_combo.currentText() == "mock"


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
