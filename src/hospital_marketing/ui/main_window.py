from __future__ import annotations

import os
import inspect
from threading import Event
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from PySide6 import QtCore, QtGui, QtWidgets

from ..documents import SUPPORTED_EXTENSIONS
from ..ai import cli_status
from ..credentials import CredentialStore, CredentialStoreError
from ..providers import (
    ProviderConfigurationError,
    ProviderRequestError,
    sanitize_provider_error_message,
)
from ..documents.size_warnings import (
    LargeSourceFile,
    find_large_source_files,
    format_large_source_file_list,
    format_large_source_file_prompt,
)
from ..settings import AppSettings, SettingsStore

from ..version import APP_VERSION
from ..workflow import ImportWorkflow, WorkflowProgress
from .settings_dialog import SettingsDialog
from .product_keywords_dialog import ProductKeywordsDialog


PATH_GUIDE_BUTTON_SIZE = 20
PATH_GUIDE_BUTTON_RIGHT_MARGIN = 14


class _ImportWorker(QtCore.QObject):
    finished = QtCore.Signal(object, object)
    progress = QtCore.Signal(object)

    def __init__(self, workflow: ImportWorkflow, source_dir: Path, target_dir: Path, settings: AppSettings, cancel_event: Event):
        super().__init__()
        self.workflow = workflow
        self.source_dir = source_dir
        self.target_dir = target_dir
        self.settings = settings
        self.cancel_event = cancel_event

    @QtCore.Slot()
    def run(self) -> None:
        try:
            workflow_options = {}
            if "on_progress" in inspect.signature(self.workflow.run).parameters:
                workflow_options["on_progress"] = self.progress.emit
            if "cancel_event" in inspect.signature(self.workflow.run).parameters:
                workflow_options["cancel_event"] = self.cancel_event
            result = self.workflow.run(
                self.source_dir,
                self.target_dir,
                provider_id=self.settings.provider_id,
                model_id=self.settings.model_id,
                mock_mode=self.settings.mock_mode,
                enabled_extensions=self.settings.enabled_extensions,
                **workflow_options,
            )
        except Exception as exc:
            self.finished.emit(None, exc)
        else:
            self.finished.emit(result, None)


class _AIStatusSignals(QtCore.QObject):
    finished = QtCore.Signal(str, object, object)


class _AIStatusWorker(QtCore.QRunnable):
    def __init__(self, model_id: str):
        super().__init__()
        self.model_id = model_id
        self.signals = _AIStatusSignals()

    @QtCore.Slot()
    def run(self) -> None:
        try:
            status = cli_status.check_cli_status(self.model_id)
            auth_status = cli_status.check_cli_auth_status(self.model_id) if status.installed else (False, status.error)
        except Exception:
            status = None
            auth_status = (None, "CLI 로그인 상태를 확인하지 못했습니다.")
        self.signals.finished.emit(self.model_id, status, auth_status)


class MainWindow(QtWidgets.QMainWindow):
    def __init__(
        self,
        settings_store: SettingsStore,
        workflow: ImportWorkflow,
        *,
        open_path: Callable[[Path], None] | None = None,
    ):
        super().__init__()
        self.settings_store = settings_store
        self.workflow = workflow
        self.open_path = open_path or self._open_local_path
        self.dashboard_path: Path | None = None
        self._import_thread: QtCore.QThread | None = None
        self._import_worker: _ImportWorker | None = None
        self._import_context: tuple[AppSettings, Path, list[LargeSourceFile]] | None = None
        self._close_when_import_finishes = False
        self._cancel_event = Event()
        self._ai_status_worker: _AIStatusWorker | None = None
        self.setWindowTitle(f"병원 마케팅 위키 MVP · v{APP_VERSION}")
        self.resize(900, 500)
        self.setMinimumWidth(780)

        settings = self.settings_store.load()
        central = QtWidgets.QWidget(self)
        central.setObjectName("appRoot")
        central.setStyleSheet("""
            QWidget#appRoot { background: #f3eee2; color: #09223f; }
            QLabel#appTitle { color: #09223f; font-size: 26px; font-weight: 700; }
            QLabel#appSubtitle { color: #5f666d; font-size: 14px; }
            QGroupBox { border: 1px solid rgba(9,34,63,0.18); border-radius: 6px; margin-top: 12px; padding: 18px 14px 12px; font-weight: 600; color: #000000; }
            QGroupBox::title { subcontrol-origin: margin; left: 14px; padding: 0 6px; color: #000000; }
            QLabel#source_label, QLabel#target_label { color: #000000; }
            QLabel#import_progress_label { color: #000000; }
            QProgressBar#import_progress { color: #000000; text-align: center; border: 1px solid rgba(9,34,63,0.2); border-radius: 5px; background: #faf7ee; }
            QProgressBar#import_progress::chunk { background: #9fc0e8; border-radius: 4px; }
            QLineEdit { min-height: 34px; border: 1px solid rgba(9,34,63,0.2); border-radius: 4px; padding: 4px 8px; background: #faf7ee; color: #000000; }
            QCheckBox { color: #000000; }
            QPushButton { min-height: 36px; border: 1px solid rgba(9,34,63,0.18); border-radius: 4px; padding: 4px 14px; background: #faf7ee; color: #09223f; }
            QPushButton:hover { background: #e9e3d3; }
            QPushButton#run_import_button:enabled { background: #09223f; color: #f3eee2; font-weight: 700; }
            QPushButton#open_dashboard_button:enabled { background: #245c9e; color: #ffffff; font-weight: 600; }
            QPushButton:disabled { color: #7a7f83; background: #e9e3d3; }
            QLabel#status_label { background: #e9e3d3; border-left: 4px solid #5d6c58; border-radius: 4px; padding: 10px 12px; color: #09223f; }
            QToolButton#path_guide_button { border: 1.5px solid #09223f; border-radius: 10px; background: #f3eee2; color: #09223f; font-size: 12px; font-weight: 700; padding: 0; }
            QToolButton#path_guide_button:hover { background: #09223f; color: #f3eee2; }
        """)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(12)
        title_row = QtWidgets.QHBoxLayout()
        self.title_label = QtWidgets.QLabel("병원 마케팅 위키")
        self.title_label.setObjectName("appTitle")
        title_row.addWidget(self.title_label)
        title_row.addStretch(1)
        self.ai_status_badge = QtWidgets.QToolButton()
        self.ai_status_badge.setObjectName("ai_status_badge")
        self.ai_status_badge.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.ai_status_badge.setToolButtonStyle(QtCore.Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.ai_status_badge.setStyleSheet(
            "QToolButton { border: 1px solid #8a8f93; border-radius: 12px; padding: 5px 10px; "
            "background: #e9e3d3; color: #09223f; font-weight: 600; }"
        )
        self.ai_status_badge.clicked.connect(self._open_settings)
        title_row.addWidget(self.ai_status_badge, 0, QtCore.Qt.AlignmentFlag.AlignRight)
        layout.addLayout(title_row)
        self._refresh_ai_status()
        subtitle = QtWidgets.QLabel("선택한 원본 파일을 읽어 병원별 Markdown 위키와 검색형 대시보드를 생성합니다. 목업 데이터로 먼저 확인하세요.")
        subtitle.setObjectName("appSubtitle")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self.paths_group = QtWidgets.QGroupBox("1. 폴더 설정")
        self.paths_group.setObjectName("paths_group")
        form = QtWidgets.QGridLayout(self.paths_group)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)
        self.source_label = QtWidgets.QLabel("Source · 원본 폴더")
        self.source_label.setObjectName("source_label")
        self.source_label.setStyleSheet("color: #000000;")
        form.addWidget(self.source_label, 0, 0)
        self.source_path_edit = QtWidgets.QLineEdit(str(settings.source_dir or ""))
        self.source_path_edit.setObjectName("source_path_edit")
        form.addWidget(self.source_path_edit, 0, 1)
        self.source_browse_button = QtWidgets.QPushButton("찾아보기")
        self.source_browse_button.clicked.connect(self._choose_source)
        form.addWidget(self.source_browse_button, 0, 2)
        self.target_label = QtWidgets.QLabel("Target · 결과 저장")
        self.target_label.setObjectName("target_label")
        self.target_label.setStyleSheet("color: #000000;")
        form.addWidget(self.target_label, 1, 0)
        self.target_path_edit = QtWidgets.QLineEdit(str(settings.target_dir or ""))
        self.target_path_edit.setObjectName("target_path_edit")
        form.addWidget(self.target_path_edit, 1, 1)
        self.target_browse_button = QtWidgets.QPushButton("찾아보기")
        self.target_browse_button.clicked.connect(self._choose_target)
        form.addWidget(self.target_browse_button, 1, 2)
        # Small circled "?" on the group's top-right border; repositioned on resize.
        self.path_guide_button = QtWidgets.QToolButton(self.paths_group)
        self.path_guide_button.setObjectName("path_guide_button")
        self.path_guide_button.setText("?")
        self.path_guide_button.setToolTip("사용법 안내 · Source / Target 경로 지정 방법")
        self.path_guide_button.setAccessibleName("경로 안내")
        self.path_guide_button.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self.path_guide_button.setFixedSize(PATH_GUIDE_BUTTON_SIZE, PATH_GUIDE_BUTTON_SIZE)
        self.path_guide_button.clicked.connect(self._show_path_guide)
        self.paths_group.installEventFilter(self)
        layout.addWidget(self.paths_group)

        self.extensions_group = QtWidgets.QGroupBox("읽을 파일 확장자")
        extension_layout = QtWidgets.QGridLayout(self.extensions_group)
        extension_layout.setHorizontalSpacing(18)
        extension_layout.setVerticalSpacing(8)
        self.extension_checkboxes: dict[str, QtWidgets.QCheckBox] = {}
        enabled_extensions = set(settings.enabled_extensions)
        for index, extension in enumerate(SUPPORTED_EXTENSIONS):
            checkbox = QtWidgets.QCheckBox(extension)
            checkbox.setObjectName(f"extension_checkbox_{extension.lstrip('.')}")
            checkbox.setChecked(extension in enabled_extensions)
            extension_layout.addWidget(checkbox, index // 4, index % 4)
            self.extension_checkboxes[extension] = checkbox
        layout.addWidget(self.extensions_group)

        self.actions_group = QtWidgets.QGroupBox("2. 처리 및 결과")
        actions = QtWidgets.QVBoxLayout(self.actions_group)
        action_buttons = QtWidgets.QHBoxLayout()
        self.run_button = QtWidgets.QPushButton("선택 파일 읽고 위키 생성")
        self.run_button.setObjectName("run_import_button")
        self.run_button.clicked.connect(self._run_import)
        action_buttons.addWidget(self.run_button, 2)
        self.settings_button = QtWidgets.QPushButton("AI 설정")
        self.settings_button.clicked.connect(self._open_settings)
        action_buttons.addWidget(self.settings_button)
        self.product_keywords_button = QtWidgets.QPushButton("검색 단어 관리")
        self.product_keywords_button.setObjectName("product_keywords_button")
        self.product_keywords_button.clicked.connect(self._open_product_keywords)
        action_buttons.addWidget(self.product_keywords_button)
        self.open_dashboard_button = QtWidgets.QPushButton("대시보드 열기")
        self.open_dashboard_button.setObjectName("open_dashboard_button")
        self.open_dashboard_button.setEnabled(False)
        self.open_dashboard_button.clicked.connect(self._open_dashboard)
        action_buttons.addWidget(self.open_dashboard_button)

        self.import_progress = QtWidgets.QProgressBar()
        self.import_progress.setObjectName("import_progress")
        self.import_progress.setRange(0, 100)
        self.import_progress.setFormat("%p%")
        self.import_progress.setTextVisible(True)
        self.import_progress.setMinimumHeight(28)
        self.import_progress.setVisible(False)
        self.import_progress_label = QtWidgets.QLabel()
        self.import_progress_label.setObjectName("import_progress_label")
        self.import_progress_label.setVisible(False)
        actions.addLayout(action_buttons)
        actions.addWidget(self.import_progress_label)
        actions.addWidget(self.import_progress)
        self.cancel_button = QtWidgets.QPushButton("취소")
        self.cancel_button.setObjectName("cancel_import_button")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_import)
        action_buttons.addWidget(self.cancel_button)
        layout.addWidget(self.actions_group)

        self.status_label = QtWidgets.QLabel("Source와 Target을 정한 뒤 실행하세요.")
        self.status_label.setObjectName("status_label")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        layout.addStretch(1)
        self.setCentralWidget(central)
        if settings.target_dir:
            self._set_dashboard_path(settings.target_dir / "dashboard" / "index.html")


    def _choose_source(self) -> None:
        current = self.source_path_edit.text().strip()
        selected = QtWidgets.QFileDialog.getExistingDirectory(self, "Source 폴더 선택", current)
        if selected:
            self.source_path_edit.setText(selected)

    def _choose_target(self) -> None:
        current = self.target_path_edit.text().strip()
        selected = QtWidgets.QFileDialog.getExistingDirectory(self, "Target 폴더 선택", current)
        if selected:
            self.target_path_edit.setText(selected)

    def eventFilter(self, watched: QtCore.QObject, event: QtCore.QEvent) -> bool:
        if watched is self.paths_group and event.type() in (
            QtCore.QEvent.Type.Resize,
            QtCore.QEvent.Type.Show,
        ):
            self._place_path_guide_button()
        return super().eventFilter(watched, event)

    def _place_path_guide_button(self) -> None:
        # Sit on the group's top border line, mirroring the title on the left.
        button = self.path_guide_button
        x = self.paths_group.width() - button.width() - PATH_GUIDE_BUTTON_RIGHT_MARGIN
        button.move(max(0, x), 0)
        button.raise_()

    def _show_path_guide(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "Source / Target 경로 안내",
            "Source는 원본 파일이 바로 들어 있는 폴더입니다. 하위 폴더는 읽지 않습니다.\n\n"
            "Target은 위키·대시보드·데이터가 저장되는 별도 폴더입니다. Source와 같거나 "
            "Source를 포함하는 상위 폴더로 지정하지 마세요. Target을 Source 안에 둘 수는 있지만 "
            "Target 하위 폴더는 원본 검색에서 제외됩니다.\n\n"
            "날짜별 업데이트는 20261102 → 20261103 → 20261106 순서로 폴더를 하나씩 지정하세요.\n\n"
            "좋은 예: Source ...\\source\\20261102, Target ...\\output\n"
            "나쁜 예: Source ...\\data\\source\\20261102, Target ...\\data",
        )

    def _open_settings(self) -> None:
        from ..ai.registry import ProviderRegistry
        from ..credentials import CredentialStore

        dialog = SettingsDialog(self.settings_store, CredentialStore(), ProviderRegistry(), self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self._refresh_ai_status()

    def _refresh_ai_status(self) -> None:
        settings = self.settings_store.load()
        model_id = settings.model_id.strip()
        if settings.mock_mode or settings.provider_id == "mock":
            self._set_ai_status("목업 모드", "목업", "#e9e3d3", "외부 AI를 호출하지 않는 목업 모드입니다.")
            return
        if settings.provider_id == "local-cli":
            cli_label = f"{model_id or 'local'}-cli"
            self._set_ai_status(
                cli_label, "확인 중…", "#e9e3d3", f"모델 ID: {model_id or '(없음)'}"
            )
            worker = _AIStatusWorker(model_id)
            worker.signals.finished.connect(self._on_cli_ai_status_finished)
            self._ai_status_worker = worker
            QtCore.QThreadPool.globalInstance().start(worker)
            return

        provider_label = {"gemini": "gemini-api", "openai": "openai-api", "anthropic": "anthropic-api"}.get(
            settings.provider_id, f"{settings.provider_id}-api"
        )
        try:
            has_key = bool(CredentialStore().get(settings.provider_id))
        except CredentialStoreError as exc:
            self._set_ai_status(provider_label, "연결 안 됨", "#f4cccc", str(exc), model_id)
            return
        if not has_key:
            self._set_ai_status(provider_label, "연결 안 됨", "#f4cccc", "API 키 없음", model_id)
            return
        check = settings.last_connection_check
        if (
            check
            and check.get("provider_id") == settings.provider_id
            and check.get("model_id") == model_id
        ):
            if check.get("succeeded") is True:
                self._set_ai_status(provider_label, "연결 완료", "#d9ead3", "마지막 연결 테스트 성공", model_id)
            else:
                self._set_ai_status(provider_label, "연결 안 됨", "#f4cccc", "마지막 연결 테스트 실패", model_id)
            return
        self._set_ai_status(provider_label, "확인 필요", "#fce5cd", "저장된 연결 테스트 결과가 없습니다.", model_id)

    def _set_ai_status(self, provider_label: str, state: str, color: str, reason: str, model_id: str = "") -> None:
        self.ai_status_badge.setText(f"{provider_label} : {state}")
        tooltip = reason
        if model_id:
            tooltip = f"모델 ID: {model_id}\n{reason}"
        self.ai_status_badge.setToolTip(tooltip)
        self.ai_status_badge.setStyleSheet(
            "QToolButton { border: 1px solid #8a8f93; border-radius: 12px; padding: 5px 10px; "
            f"background: {color}; color: #09223f; font-weight: 600; }}"
        )

    @QtCore.Slot(str, object, object)
    def _on_cli_ai_status_finished(self, model_id: str, status, auth_status) -> None:
        if self.settings_store.load().model_id.strip() != model_id:
            return
        self._ai_status_worker = None
        settings = self.settings_store.load()
        check = settings.last_connection_check
        if status is None or not status.installed:
            reason = status.error if status is not None else "CLI 상태를 확인하지 못했습니다."
            self._set_ai_status(f"{model_id or 'local'}-cli", "연결 안 됨", "#f4cccc", reason or "CLI 설치 안 됨", model_id)
        elif auth_status[0] is True:
            self._set_ai_status(f"{model_id}-cli", "연결 완료", "#d9ead3", "CLI 설치 및 로그인 완료", model_id)
        elif auth_status[0] is False:
            self._set_ai_status(f"{model_id}-cli", "연결 안 됨", "#f4cccc", auth_status[1] or "CLI 로그인이 필요합니다.", model_id)
        elif check and check.get("provider_id") == "local-cli" and check.get("model_id") == model_id and check.get("succeeded") is True:
            self._set_ai_status(f"{model_id}-cli", "연결 완료", "#d9ead3", "마지막 연결 테스트 성공", model_id)
        else:
            self._set_ai_status(f"{model_id}-cli", "확인 필요", "#fce5cd", auth_status[1] or "로그인 상태를 확인할 수 없습니다.", model_id)

    def _open_product_keywords(self) -> None:
        settings = self.settings_store.load()
        dialog = ProductKeywordsDialog(settings.product_keywords, self)
        if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
            self.settings_store.save(replace(settings, product_keywords=dialog.keywords()))

    def _confirm_large_source_files(self, files: list[LargeSourceFile]) -> bool:
        message_box = QtWidgets.QMessageBox(self)
        message_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
        message_box.setWindowTitle("큰 원본 파일 경고")
        message_box.setText(format_large_source_file_prompt(files))
        continue_button = message_box.addButton("계속", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        cancel_button = message_box.addButton("취소", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        message_box.setDefaultButton(cancel_button)
        message_box.exec()
        return message_box.clickedButton() is continue_button

    def _run_import(self) -> None:
        source_text = self.source_path_edit.text().strip()
        target_text = self.target_path_edit.text().strip()
        if not source_text or not target_text:
            self.status_label.setText("Source와 Target 경로를 모두 지정해 주세요.")
            return
        source_dir = Path(source_text)
        target_dir = Path(target_text)
        if self._source_conflicts_with_target(source_dir, target_dir):
            message = (
                "Target 폴더 안에 Source가 있어 파일을 읽을 수 없습니다. "
                "Target을 Source와 겹치지 않는 별도 폴더로 지정해 주세요."
            )
            self.status_label.setText(message)
            QtWidgets.QMessageBox.warning(self, "폴더 경로 확인", message)
            return
        selected_extensions = tuple(
            extension
            for extension in SUPPORTED_EXTENSIONS
            if self.extension_checkboxes[extension].isChecked()
        )
        if not selected_extensions:
            self.status_label.setText("읽을 파일 확장자를 하나 이상 선택해 주세요.")
            return
        settings = self.settings_store.load()
        if not any(keyword.enabled for keyword in settings.product_keywords):
            self.status_label.setText("검색 단어를 하나 이상 선택해 주세요.")
            return
        large_source_files = find_large_source_files(
            source_dir,
            selected_extensions,
            exclude_dir=target_dir,
        )
        updated = replace(settings,
            source_dir=source_dir,
            target_dir=target_dir,
            enabled_extensions=selected_extensions,
        )
        if large_source_files and not updated.mock_mode and not self._confirm_large_source_files(large_source_files):
            self.status_label.setText("큰 원본 파일 경고로 처리를 취소했습니다.")
            return
        self.settings_store.save(updated)
        self._cancel_event.clear()
        self.run_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.import_progress.setVisible(True)
        self.import_progress.setValue(0)
        self.import_progress.setFormat("%p%")
        self.import_progress_label.setVisible(True)
        self.import_progress_label.setText("1/4 단계 · 원본 파일 읽기·문서 변환")
        self.status_label.setText(
            f"처리 중 · Source {source_dir} · 선택한 원본 파일을 읽고 Markdown 위키와 결과를 생성하고 있습니다."
        )
        self._import_context = (updated, target_dir, large_source_files)
        self._import_thread = QtCore.QThread(self)
        self._import_worker = _ImportWorker(self.workflow, source_dir, target_dir, updated, self._cancel_event)
        self._import_worker.moveToThread(self._import_thread)
        self._import_thread.started.connect(self._import_worker.run)
        self._import_worker.finished.connect(self._on_import_finished)
        self._import_worker.progress.connect(self._on_import_progress)
        self._import_worker.finished.connect(self._import_thread.quit)
        self._import_worker.finished.connect(self._import_worker.deleteLater)
        self._import_thread.finished.connect(self._cleanup_import_thread)
        self._import_thread.start()

    @QtCore.Slot(object, object)
    def _on_import_finished(self, result, error) -> None:
        self.run_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        context = self._import_context
        if context is None:
            self._hide_import_progress()
            return
        updated, target_dir, large_source_files = context
        try:
            if error is not None:
                raise error
            if result is None:
                raise RuntimeError("가져오기 결과가 없습니다.")
            self.dashboard_path = result.outputs.dashboard
            report = result.report
            source_files = " · ".join(report.source_files) if report.source_files else "읽은 파일 없음"
            status = (
                f"처리 완료 · Source {report.source_dir or updated.source_dir} · {source_files} · 읽은 파일 {report.files_seen} · Markdown {report.documents_converted_count} · 신규 {report.inserted_count} · 변경 {report.updated_count} · "
                f"변경 없음 {report.unchanged_count} · 오류 {sum(issue.code != 'large_source_file' for issue in report.issues)} · "
                f"분류 {result.classified_count} · 검토 필요 {result.needs_review_count} · "
                f"자동 수집 채널 {result.channels_collected} · 게시물 {result.posts_collected} · "
                f"채널 확인 필요 {result.channels_needing_review} · 수집 실패 병원 {result.channel_failures} · "
                f"폐기 항목 {result.channel_discarded}"
            )
            if result.channel_collection_skipped_reason:
                status += f" · {result.channel_collection_skipped_reason}"
            if result.channel_collection_cancelled:
                status += " · 자동 수집 취소됨"
            if report.inserted_count == 0 and report.updated_count == 0 and report.unchanged_count > 0:
                status += " · 이미 가져온 파일과 같습니다. Source 폴더를 확인하세요."
            if report.files_seen == 0:
                status += " · 읽을 파일이 없습니다. 선택 확장자 파일이 폴더 바로 아래에 있는지 확인하세요."
            if large_source_files:
                details = format_large_source_file_list(large_source_files)
                if updated.mock_mode:
                    status += (
                        f"\n실제 AI로 실행하면 입력 한도를 넘을 수 있는 파일 {len(large_source_files)}개:\n"
                        f"{details}"
                    )
                else:
                    status += (
                        f"\n큰 원본 파일 {len(large_source_files)}개를 처리했습니다. "
                        f"AI 입력 한도를 넘을 수 있습니다.\n{details}"
                    )
            self.status_label.setText(status)
            if not updated.mock_mode and result.classified_count > 0:
                self._record_ai_connection_check(updated, True)
            self._set_dashboard_path(self.dashboard_path)
            self.import_progress.setValue(100)
            self.import_progress.setFormat("%p%")
            self.import_progress_label.setText("4/4 단계 · 처리 완료")
            QtCore.QTimer.singleShot(500, self._hide_import_progress_if_idle)
        except (ProviderConfigurationError, ProviderRequestError) as exc:
            self._hide_import_progress()
            safe_message = sanitize_provider_error_message(str(exc))
            self.status_label.setText(f"AI 처리 실패: {safe_message} 목업 모드로 다시 실행할 수 있습니다.")
            if not updated.mock_mode:
                self._record_ai_connection_check(updated, False)
            self.open_dashboard_button.setEnabled(False)
        except Exception:
            self._hide_import_progress()
            self.status_label.setText("처리에 실패했습니다. 입력 파일과 설정을 확인한 뒤 다시 시도해 주세요.")
            self.open_dashboard_button.setEnabled(False)

    def _record_ai_connection_check(self, settings: AppSettings, succeeded: bool) -> None:
        current = self.settings_store.load()
        self.settings_store.save(replace(
            current,
            last_connection_check={
                "provider_id": settings.provider_id,
                "model_id": settings.model_id,
                "succeeded": succeeded,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
        ))
        self._refresh_ai_status()

    def _hide_import_progress(self) -> None:
        self.import_progress.setVisible(False)
        self.import_progress_label.setVisible(False)

    @QtCore.Slot()
    def _hide_import_progress_if_idle(self) -> None:
        if self._import_context is None:
            self._hide_import_progress()
        else:
            QtCore.QTimer.singleShot(50, self._hide_import_progress_if_idle)

    @QtCore.Slot()
    def _cleanup_import_thread(self) -> None:
        self._import_thread = None
        self._import_worker = None
        self._import_context = None
        if self._close_when_import_finishes:
            self.close()

    def _cancel_import(self) -> None:
        self._cancel_event.set()
        self.cancel_button.setEnabled(False)
        self.import_progress.setFormat("취소 중…")
        self.import_progress_label.setText("취소 중…")
        self.status_label.setText("현재 처리 중인 작업이 끝나면 자동 수집을 취소합니다.")

    @QtCore.Slot(object)
    def _on_import_progress(self, progress: WorkflowProgress) -> None:
        if self._cancel_event.is_set():
            self.import_progress.setFormat("취소 중…")
            self.import_progress_label.setText("취소 중…")
            return
        stage_labels = {
            "files": (1, "원본 파일 읽기·문서 변환"),
            "channels": (2, "신규 병원 채널·게시물 수집"),
            "classification": (3, "AI 콘텐츠 분류"),
            "outputs": (4, "위키·대시보드·엑셀 생성"),
        }
        stage_number, stage_label = stage_labels[progress.stage]
        self.import_progress.setFormat("%p%")
        self.import_progress.setValue(progress.percent)
        self.import_progress_label.setText(
            f"{stage_number}/4 단계 · {stage_label} · {progress.current}/{progress.total} · {progress.message}"
        )

    def closeEvent(self, event) -> None:
        if self._import_thread is not None and self._import_thread.isRunning():
            self._cancel_event.set()
            self._close_when_import_finishes = True
            self.status_label.setText("가져오기가 끝난 뒤 앱이 종료됩니다.")
            event.ignore()
            return
        super().closeEvent(event)

    @staticmethod
    def _source_conflicts_with_target(source_dir: Path, target_dir: Path) -> bool:
        source_path = Path(os.path.normcase(str(Path(source_dir).resolve())))
        target_path = Path(os.path.normcase(str(Path(target_dir).resolve())))
        try:
            return source_path == target_path or source_path.is_relative_to(target_path)
        except ValueError:
            return False

    def _set_dashboard_path(self, path: Path) -> None:
        self.dashboard_path = Path(path)
        available = self.dashboard_path.is_file()
        self.open_dashboard_button.setEnabled(available)

    def _open_dashboard(self) -> None:
        if self.dashboard_path and self.dashboard_path.is_file():
            self.open_path(self.dashboard_path)


    @staticmethod
    def _open_local_path(path: Path) -> None:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path.resolve())))
