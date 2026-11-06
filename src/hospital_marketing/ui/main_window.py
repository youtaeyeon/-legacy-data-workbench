from __future__ import annotations

import os
import shutil
from datetime import date
from pathlib import Path
from typing import Callable

from PySide6 import QtCore, QtGui, QtWidgets

from ..documents import SUPPORTED_EXTENSIONS
from ..providers import ProviderConfigurationError, ProviderRequestError
from ..settings import AppSettings, SettingsStore
from ..workflow import ImportWorkflow
from .settings_dialog import SettingsDialog


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
        self.setWindowTitle("병원 마케팅 위키 MVP")
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
            QLineEdit { min-height: 34px; border: 1px solid rgba(9,34,63,0.2); border-radius: 4px; padding: 4px 8px; background: #faf7ee; color: #000000; }
            QCheckBox { color: #000000; }
            QPushButton { min-height: 36px; border: 1px solid rgba(9,34,63,0.18); border-radius: 4px; padding: 4px 14px; background: #faf7ee; color: #09223f; }
            QPushButton:hover { background: #e9e3d3; }
            QPushButton#run_import_button { background: #09223f; color: #f3eee2; font-weight: 700; }
            QPushButton#open_dashboard_button { background: #245c9e; color: #ffffff; font-weight: 600; }
            QPushButton:disabled { color: #7a7f83; background: #e9e3d3; }
            QLabel#status_label { background: #e9e3d3; border-left: 4px solid #5d6c58; border-radius: 4px; padding: 10px 12px; color: #09223f; }
        """)
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(12)
        self.title_label = QtWidgets.QLabel("병원 마케팅 위키")
        self.title_label.setObjectName("appTitle")
        layout.addWidget(self.title_label)
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
        self.path_guide_button = QtWidgets.QPushButton("경로 안내")
        self.path_guide_button.setObjectName("path_guide_button")
        self.path_guide_button.clicked.connect(self._show_path_guide)
        form.addWidget(self.path_guide_button, 2, 2)
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
        actions = QtWidgets.QHBoxLayout(self.actions_group)
        self.run_button = QtWidgets.QPushButton("선택 파일 읽고 위키 생성")
        self.run_button.setObjectName("run_import_button")
        self.run_button.clicked.connect(self._run_import)
        actions.addWidget(self.run_button, 2)
        self.settings_button = QtWidgets.QPushButton("AI 설정")
        self.settings_button.clicked.connect(self._open_settings)
        actions.addWidget(self.settings_button)
        self.open_dashboard_button = QtWidgets.QPushButton("대시보드 열기")
        self.open_dashboard_button.setObjectName("open_dashboard_button")
        self.open_dashboard_button.setEnabled(False)
        self.open_dashboard_button.clicked.connect(self._open_dashboard)
        actions.addWidget(self.open_dashboard_button)
        self.export_dashboard_button = QtWidgets.QPushButton("대시보드 HTML 내보내기")
        self.export_dashboard_button.setObjectName("export_dashboard_button")
        self.export_dashboard_button.setEnabled(False)
        self.export_dashboard_button.setToolTip("내보낸 파일에는 병원 정보가 포함될 수 있으므로 외부 공유 전 내용을 확인하세요.")
        self.export_dashboard_button.clicked.connect(self._export_dashboard)
        actions.addWidget(self.export_dashboard_button)
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
            settings = self.settings_store.load()
            self.source_path_edit.setText(str(settings.source_dir or ""))
            self.target_path_edit.setText(str(settings.target_dir or ""))

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
        updated = AppSettings(
            source_dir=source_dir,
            target_dir=target_dir,
            provider_id=settings.provider_id,
            model_id=settings.model_id,
            mock_mode=settings.mock_mode,
            enabled_extensions=selected_extensions,
        )
        self.settings_store.save(updated)
        self.run_button.setEnabled(False)
        self.status_label.setText("선택한 원본 파일을 읽고 Markdown 위키와 결과를 생성하고 있습니다.")
        QtWidgets.QApplication.processEvents()
        try:
            result = self.workflow.run(
                source_dir,
                target_dir,
                provider_id=updated.provider_id,
                model_id=updated.model_id,
                mock_mode=updated.mock_mode,
                enabled_extensions=updated.enabled_extensions,
            )
            self.dashboard_path = result.outputs.dashboard
            report = result.report
            status = (
                f"처리 완료 · 읽은 파일 {report.files_seen} · Markdown {report.documents_converted_count} · 신규 {report.inserted_count} · 변경 {report.updated_count} · "
                f"변경 없음 {report.unchanged_count} · 오류 {len(report.issues)} · "
                f"분류 {result.classified_count} · 검토 필요 {result.needs_review_count}"
            )
            if report.files_seen == 0:
                status += " · 읽을 파일이 없습니다. 선택 확장자 파일이 폴더 바로 아래에 있는지 확인하세요."
            self.status_label.setText(status)
            self._set_dashboard_path(self.dashboard_path)
        except (ProviderConfigurationError, ProviderRequestError) as exc:
            self.status_label.setText(f"AI 처리 실패: {exc} 목업 모드로 다시 실행할 수 있습니다.")
            self.open_dashboard_button.setEnabled(False)
            self.export_dashboard_button.setEnabled(False)
        except Exception:
            self.status_label.setText("처리에 실패했습니다. 입력 파일과 설정을 확인한 뒤 다시 시도해 주세요.")
            self.open_dashboard_button.setEnabled(False)
            self.export_dashboard_button.setEnabled(False)
        finally:
            self.run_button.setEnabled(True)

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
        self.export_dashboard_button.setEnabled(available)

    def _open_dashboard(self) -> None:
        if self.dashboard_path and self.dashboard_path.is_file():
            self.open_path(self.dashboard_path)

    def _export_dashboard(self) -> None:
        if not self.dashboard_path or not self.dashboard_path.is_file():
            self.export_dashboard_button.setEnabled(False)
            self.status_label.setText("내보낼 대시보드 파일이 없습니다. 먼저 위키 생성을 실행해 주세요.")
            return

        documents = QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.StandardLocation.DocumentsLocation
        )
        default_directory = Path(documents) if documents else Path.home()
        default_path = default_directory / f"병원마케팅대시보드_{date.today():%Y%m%d}.html"
        self.status_label.setText("외부 공유 전에 실제 회사 자료가 포함되지 않았는지 확인하세요.")
        selected_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            "대시보드 HTML 내보내기",
            str(default_path),
            "HTML 파일 (*.html)",
        )
        if not selected_path:
            return

        destination = Path(selected_path)
        if destination.suffix in {"", "."}:
            destination = destination.with_name(f"{destination.name.rstrip('.')}.html")
        elif destination.suffix.lower() != ".html":
            self.status_label.setText("공유용 대시보드 파일은 .html 확장자로 저장해 주세요.")
            return
        if self.dashboard_path.resolve() == destination.resolve():
            self.status_label.setText(f"이미 대시보드 HTML입니다: {destination}")
            return
        if destination.exists():
            answer = QtWidgets.QMessageBox.question(
                self,
                "덮어쓰기 확인",
                f"{destination} 파일이 이미 있습니다. 덮어쓸까요?",
                QtWidgets.QMessageBox.StandardButton.Yes | QtWidgets.QMessageBox.StandardButton.No,
                QtWidgets.QMessageBox.StandardButton.No,
            )
            if answer != QtWidgets.QMessageBox.StandardButton.Yes:
                self.status_label.setText("대시보드 내보내기를 취소했습니다.")
                return
        try:
            shutil.copyfile(self.dashboard_path, destination)
        except OSError:
            self.status_label.setText("HTML 내보내기에 실패했습니다. 저장 위치와 권한을 확인해 주세요.")
            return

        self.status_label.setText(
            f"공유용 HTML 저장 완료: {destination} · 외부 공유 전에 실제 회사 자료가 포함되지 않았는지 확인하세요."
        )

    @staticmethod
    def _open_local_path(path: Path) -> None:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(path.resolve())))
