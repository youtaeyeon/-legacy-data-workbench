from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import re
from threading import Event
import time
from typing import Any

import httpx
from PySide6 import QtCore, QtGui, QtWidgets

from ..ai import cli_status
from ..ai.models import RECOMMENDED_MODELS, model_id_error
from ..ai.registry import ProviderRegistry
from ..credentials import CredentialStore, CredentialStoreError
from ..providers import ProviderConfigurationError, ProviderRequestError, sanitize_provider_error_message
from ..settings import SettingsStore


MIN_CONNECTION_PROGRESS_SECONDS = 0.5
CONNECTION_ERROR_LOG_NAME = "ai-connection-errors.jsonl"


def _is_windows() -> bool:
    return os.name == "nt"


def _sanitize_connection_error(message: str, api_key: str) -> str:
    return sanitize_provider_error_message(message, api_key)[:1000]


def _provider_status_code(message: str) -> int | None:
    match = re.search(r"\bHTTP\s+(\d{3})\b", message, flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _local_error_time(utc_timestamp: str) -> str:
    try:
        timestamp = datetime.fromisoformat(utc_timestamp)
    except (TypeError, ValueError):
        return utc_timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def _format_connection_attempts(attempts: list[dict[str, Any]], api_key: str = "") -> str:
    if not attempts:
        return "시도 정보 없음"
    formatted = []
    for index, attempt in enumerate(attempts, start=1):
        elapsed = attempt.get("elapsed_seconds")
        elapsed_text = f"{elapsed}초" if elapsed is not None else "시간 미상"
        if attempt.get("timeout"):
            outcome = "시간 초과"
        elif attempt.get("status_code") is not None:
            outcome = f"HTTP {attempt['status_code']}"
        else:
            outcome = "연결 실패"
        if attempt.get("status"):
            safe_status = sanitize_provider_error_message(str(attempt["status"]), api_key)
            outcome += f" {safe_status}"
        formatted.append(f"{index}차: {outcome} ({elapsed_text})")
    return " / ".join(formatted)


class _CancellationAwareHttpClient:
    def __init__(self, client: Any, cancel_event: Event):
        self._client = client
        self._cancel_event = cancel_event

    def post(self, *args, **kwargs):
        if self._cancel_event.is_set():
            raise ProviderRequestError("연결 테스트가 취소되었습니다.")
        return self._client.post(*args, **kwargs)


def _send_connection_test(
    provider_registry: ProviderRegistry,
    provider_id: str,
    model_id: str,
    api_key: str,
    http_client: Any | None,
    on_retry: Callable[[int, int, float], None],
    sleep_fn: Callable[[float], None],
    cancel_event: Event,
) -> None:
    def run_with_client(client: Any) -> None:
        if provider_id == "local-cli":
            provider = provider_registry.create(provider_id, cli=model_id, cancel_event=cancel_event)
        else:
            provider = provider_registry.create(
                provider_id,
                api_key=api_key,
                model=model_id,
                http_client=_CancellationAwareHttpClient(client, cancel_event),
                on_retry=on_retry,
                sleep_fn=sleep_fn,
            )
        connection_test = getattr(provider, "test_connection", None)
        if not callable(connection_test):
            raise ProviderConfigurationError("선택한 제공자는 연결 테스트를 지원하지 않습니다.")
        connection_test()

    if provider_id == "local-cli":
        run_with_client(None)
    elif http_client is None:
        with httpx.Client(timeout=30.0) as client:
            run_with_client(client)
    else:
        run_with_client(http_client)


class _ConnectionTestSignals(QtCore.QObject):
    retry = QtCore.Signal(int, int, float)
    finished = QtCore.Signal(bool, str, object)


class _ConnectionTestWorker(QtCore.QRunnable):
    def __init__(
        self,
        provider_registry: ProviderRegistry,
        provider_id: str,
        model_id: str,
        api_key: str,
        http_client: Any | None,
        cancel_event: Event,
        retry_sleep_fn: Callable[[float], None] | None,
    ):
        super().__init__()
        self.signals = _ConnectionTestSignals()
        self.provider_registry = provider_registry
        self.provider_id = provider_id
        self.model_id = model_id
        self.api_key = api_key
        self.http_client = http_client
        self.cancel_event = cancel_event
        self.retry_sleep_fn = retry_sleep_fn

    @QtCore.Slot()
    def run(self) -> None:
        if self.cancel_event.is_set():
            self.signals.finished.emit(False, "", [])
            return

        def cancellable_sleep(delay: float) -> None:
            if self.retry_sleep_fn is None:
                cancelled = self.cancel_event.wait(delay)
            else:
                self.retry_sleep_fn(delay)
                cancelled = self.cancel_event.is_set()
            if cancelled:
                raise ProviderRequestError("연결 테스트가 취소되었습니다.")

        def report_retry(retry_number: int, max_retries: int, delay: float) -> None:
            if self.cancel_event.is_set():
                raise ProviderRequestError("연결 테스트가 취소되었습니다.")
            self.signals.retry.emit(retry_number, max_retries, delay)

        try:
            _send_connection_test(
                self.provider_registry,
                self.provider_id,
                self.model_id,
                self.api_key,
                self.http_client,
                report_retry,
                cancellable_sleep,
                self.cancel_event,
            )
        except (ProviderConfigurationError, ProviderRequestError) as exc:
            attempts = getattr(exc, "attempts", [])
            self.signals.finished.emit(
                False, _sanitize_connection_error(str(exc), self.api_key), attempts
            )
        except Exception:
            self.signals.finished.emit(False, "연결 테스트 중 오류가 발생했습니다. 설정과 네트워크를 확인하세요.", [])
        else:
            self.signals.finished.emit(True, "연결 성공: 선택한 제공자와 모델을 사용할 수 있습니다.", [])


class _CLIStatusSignals(QtCore.QObject):
    finished = QtCore.Signal(object, object)


class _CLIStatusWorker(QtCore.QRunnable):
    def __init__(self):
        super().__init__()
        self.signals = _CLIStatusSignals()

    @QtCore.Slot()
    def run(self) -> None:
        try:
            statuses = cli_status.check_all_cli_statuses()
            node_statuses = cli_status.check_node_tool_status()
        except Exception:
            statuses = {}
            node_statuses = {}
        self.signals.finished.emit(statuses, node_statuses)


class SettingsDialog(QtWidgets.QDialog):
    def __init__(
        self,
        settings_store: SettingsStore,
        credential_store: CredentialStore,
        provider_registry: ProviderRegistry,
        parent=None,
        http_client: Any | None = None,
        retry_sleep_fn: Callable[[float], None] | None = None,
    ):
        super().__init__(parent)
        self.settings_store = settings_store
        self.credential_store = credential_store
        self.provider_registry = provider_registry
        self.http_client = http_client
        self.retry_sleep_fn = retry_sleep_fn
        self._connection_worker: _ConnectionTestWorker | None = None
        self._connection_cancel_event: Event | None = None
        self._connection_provider_id = ""
        self._connection_model_id = ""
        self._connection_api_key = ""
        self._connection_started_at: float | None = None
        self._pending_connection_result: tuple[bool, str, list[dict[str, Any]]] | None = None
        self._last_connection_error: dict[str, Any] | None = None
        self._connection_error_log_path: Path | None = None
        self._cli_statuses: dict[str, cli_status.CLIStatus] = {}
        self._node_statuses: dict[str, str | None] = {}
        self._cli_status_worker: _CLIStatusWorker | None = None
        self._cli_install_process: Any | None = None
        self._closing = False
        settings = settings_store.load()
        self.setWindowTitle("AI 제공자 설정")
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout(self)
        self.subscription_heading = QtWidgets.QLabel("연결 방식")
        self.subscription_heading.setObjectName("subscription_heading")
        self.subscription_heading.setStyleSheet("font-weight: bold; font-size: 16px")
        layout.addWidget(self.subscription_heading)
        mode_row = QtWidgets.QHBoxLayout()
        self.connection_mode_group = QtWidgets.QButtonGroup(self)
        self.subscription_radio = QtWidgets.QRadioButton("구독 계정 연결 (권장)")
        self.api_radio = QtWidgets.QRadioButton("API 키 사용 (선택)")
        self.mock_radio = QtWidgets.QRadioButton("과제 테스트(목업)")
        for radio, mode in (
            (self.subscription_radio, "local-cli"),
            (self.api_radio, "api"),
            (self.mock_radio, "mock"),
        ):
            self.connection_mode_group.addButton(radio)
            radio.setProperty("connection_mode", mode)
            mode_row.addWidget(radio)
        layout.addLayout(mode_row)
        initial_mode = "local-cli" if settings.provider_id == "local-cli" else "mock" if settings.provider_id == "mock" else "api"
        initial_radio = {"local-cli": self.subscription_radio, "api": self.api_radio, "mock": self.mock_radio}[initial_mode]
        initial_radio.setChecked(True)

        form = QtWidgets.QFormLayout()
        self._settings_form = form
        self.model_combo = QtWidgets.QComboBox()
        self.model_label = QtWidgets.QLabel("모델 ID (직접 입력 가능)")
        self.model_combo.setObjectName("model_combo")
        self.model_combo.setEditable(True)
        self.model_combo.currentTextChanged.connect(self._update_cli_status_label)
        self.model_combo.activated.connect(self._on_cli_selected)
        self.model_edit = self.model_combo.lineEdit()
        if self.model_edit is not None:
            self.model_edit.setObjectName("model_edit")
            self.model_edit.setPlaceholderText("권장 모델을 고르거나 모델 ID를 입력하세요")
        self._populate_model_choices(settings.provider_id, settings.model_id, preserve_custom=True)
        self.cli_install_status_label = QtWidgets.QLabel("CLI 설치 상태를 확인해 주세요.")
        self.cli_install_status_label.setObjectName("cli_install_status_label")
        self.cli_install_status_label.setWordWrap(True)
        self.cli_install_status_title = QtWidgets.QLabel("선택 CLI 상태")
        form.addRow(self.cli_install_status_title, self.cli_install_status_label)
        self.cli_node_status_label = QtWidgets.QLabel("Node.js / npm: 확인 전")
        self.cli_node_status_label.setObjectName("cli_node_status_label")
        self.cli_node_status_title = QtWidgets.QLabel("CLI 설치 요건")
        form.addRow(self.cli_node_status_title, self.cli_node_status_label)

        self.provider_combo = QtWidgets.QComboBox()
        self.provider_combo.addItems(provider_registry.available())
        self.provider_combo.setCurrentText(settings.provider_id)
        self.provider_combo.setObjectName("provider_combo")
        self.provider_combo.currentTextChanged.connect(self._provider_changed)
        self.provider_combo.hide()
        self.subscription_panel = QtWidgets.QWidget()
        subscription_layout = QtWidgets.QVBoxLayout(self.subscription_panel)
        subscription_layout.setContentsMargins(0, 0, 0, 0)
        self.subscription_message = QtWidgets.QLabel(
            "개인 구독 계정으로 로그인한 CLI를 사용합니다. 서비스 약관과 사용량 한도가 적용됩니다."
        )
        self.subscription_message.setWordWrap(True)
        subscription_layout.addWidget(self.subscription_message)
        form.addRow(self.model_label, self.model_combo)
        subscription_layout.addLayout(form)
        layout.addWidget(self.subscription_panel)

        self.api_options_panel = QtWidgets.QWidget()
        self.api_options_panel.setObjectName("api_options_panel")
        api_form = QtWidgets.QFormLayout(self.api_options_panel)
        self._api_form = api_form
        self.api_provider_combo = QtWidgets.QComboBox()
        self.api_provider_combo.addItems(["openai", "anthropic", "gemini"])
        self.api_provider_combo.setCurrentText(settings.provider_id if settings.provider_id in ("openai", "anthropic", "gemini") else "openai")
        self.api_provider_combo.currentTextChanged.connect(self._select_api_provider)
        api_form.addRow("API 제공자", self.api_provider_combo)
        self.api_provider_label = QtWidgets.QLabel(f"선택된 API 제공자: {self.api_provider_combo.currentText()}")
        api_form.addRow(self.api_provider_label)
        api_form.addRow(self.model_label, self.model_combo)

        self.api_key_edit = QtWidgets.QLineEdit()
        self.api_key_edit.setObjectName("api_key_edit")
        self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("키는 설정 파일에 저장되지 않습니다")
        api_form.addRow("API 키", self.api_key_edit)
        self.key_status_label = QtWidgets.QLabel()
        self.key_status_label.setObjectName("key_status_label")
        api_form.addRow("저장된 키", self.key_status_label)
        layout.addWidget(self.api_options_panel)
        self.mock_message = QtWidgets.QLabel("목업 모드입니다. 외부 AI를 호출하지 않습니다.")
        self.mock_message.setWordWrap(True)
        layout.addWidget(self.mock_message)
        self.connection_mode_group.buttonClicked.connect(self._connection_mode_changed)
        if initial_mode == "api":
            self.provider_combo.setCurrentText(self.api_provider_combo.currentText())
        self._set_local_cli_controls(settings.provider_id == "local-cli")

        self.mock_mode_checkbox = QtWidgets.QCheckBox("목업 모드 (외부 AI 호출 안 함)")
        self.mock_mode_checkbox.setObjectName("mock_mode_checkbox")
        self.mock_mode_checkbox.setChecked(settings.mock_mode)
        if settings.provider_id == "local-cli":
            self.mock_mode_checkbox.setChecked(False)
            self.mock_mode_checkbox.setEnabled(False)
        self.mock_mode_checkbox.hide()
        self.auto_collect_checkbox = QtWidgets.QCheckBox("신규 병원 채널·게시물 자동 수집")
        self.auto_collect_checkbox.setObjectName("auto_collect_hospital_channels_checkbox")
        self.auto_collect_checkbox.setChecked(settings.auto_collect_hospital_channels)
        layout.addWidget(self.auto_collect_checkbox)
        self.message_label = QtWidgets.QLabel("API 키는 OS 자격 증명 저장소에 보관됩니다.")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        connection_buttons = QtWidgets.QHBoxLayout()
        self.test_connection_button = QtWidgets.QPushButton("연결 테스트")
        self.test_connection_button.setObjectName("test_connection_button")
        self.test_connection_button.clicked.connect(self._test_connection)
        connection_buttons.addWidget(self.test_connection_button)
        self.check_cli_install_button = QtWidgets.QPushButton("CLI 설치 확인")
        self.check_cli_install_button.setObjectName("check_cli_install_button")
        self.check_cli_install_button.clicked.connect(self._refresh_cli_status)
        connection_buttons.addWidget(self.check_cli_install_button)
        self.install_cli_button = QtWidgets.QPushButton("CLI 설치")
        self.install_cli_button.setObjectName("install_cli_button")
        self.install_cli_button.setVisible(False)
        self.install_cli_button.clicked.connect(self._install_selected_cli)
        connection_buttons.addWidget(self.install_cli_button)
        self.login_cli_button = QtWidgets.QPushButton("CLI 로그인")
        self.login_cli_button.setObjectName("login_cli_button")
        self.login_cli_button.setVisible(False)
        self.login_cli_button.clicked.connect(self._login_cli)
        connection_buttons.addWidget(self.login_cli_button)
        self.cancel_connection_button = QtWidgets.QPushButton("테스트 취소")
        self.cancel_connection_button.setObjectName("cancel_connection_button")
        self.cancel_connection_button.setVisible(False)
        self.cancel_connection_button.clicked.connect(self._cancel_connection_test)
        connection_buttons.addWidget(self.cancel_connection_button)
        self.guide_button = QtWidgets.QPushButton("설정 가이드")
        self.guide_button.setObjectName("ai_settings_guide_button")
        self.guide_button.clicked.connect(self._show_guide)
        connection_buttons.addWidget(self.guide_button)
        layout.addLayout(connection_buttons)

        self.connection_status_label = QtWidgets.QLabel(
            "연결 테스트는 실제 API 요청이며 사용량에 따라 비용이 발생할 수 있습니다."
        )
        self.connection_status_label.setObjectName("connection_status_label")
        self.connection_status_label.setWordWrap(True)
        layout.addWidget(self.connection_status_label)
        self.connection_progress_bar = QtWidgets.QProgressBar()
        self.connection_progress_bar.setObjectName("connection_progress_bar")
        self.connection_progress_bar.setRange(0, 0)
        self.connection_progress_bar.setTextVisible(False)
        self.connection_progress_bar.setVisible(False)
        self.connection_progress_bar.setStyleSheet("""
            QProgressBar {
                min-height: 12px;
                border: 1px solid #5f666d;
                border-radius: 4px;
                background: #e9e3d3;
            }
            QProgressBar::chunk {
                background: #2b6cb8;
            }
        """)
        layout.addWidget(self.connection_progress_bar)
        self.error_details_button = QtWidgets.QPushButton("오류 자세히 보기")
        self.error_details_button.setObjectName("connection_error_details_button")
        self.error_details_button.setVisible(False)
        self.error_details_button.clicked.connect(self._show_connection_error_details)
        layout.addWidget(self.error_details_button)

        buttons = QtWidgets.QHBoxLayout()
        self.clear_key_button = QtWidgets.QPushButton("선택 제공자 키 삭제")
        self.clear_key_button.setEnabled(settings.provider_id != "local-cli")
        self.clear_key_button.clicked.connect(self._clear_key)
        buttons.addWidget(self.clear_key_button)
        buttons.addStretch(1)
        self.save_button = QtWidgets.QPushButton("저장")
        self.save_button.setObjectName("save_settings_button")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)
        self.dialog_cancel_button = QtWidgets.QPushButton("취소")
        self.dialog_cancel_button.clicked.connect(self.reject)
        buttons.addWidget(self.dialog_cancel_button)
        layout.addLayout(buttons)
        self._connection_mode_changed(initial_radio)
        self._refresh_key_status()
        if settings.provider_id == "local-cli":
            self._refresh_cli_status()

    def _populate_model_choices(
        self,
        provider_id: str,
        model_id: str,
        *,
        preserve_custom: bool,
    ) -> None:
        models = RECOMMENDED_MODELS.get(provider_id, ())
        is_local_cli = provider_id == "local-cli"
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItems(models)
        if provider_id == "mock":
            selected_model = ""
            self.model_combo.setEnabled(False)
        else:
            self.model_combo.setEnabled(True)
            if preserve_custom and model_id.strip():
                selected_model = model_id.strip()
            elif model_id in models:
                selected_model = model_id
            else:
                selected_model = models[0] if models else model_id.strip()
        self.model_combo.setEditable(not is_local_cli)
        if is_local_cli and selected_model in models:
            self.model_combo.setCurrentIndex(self.model_combo.findText(selected_model))
        else:
            self.model_combo.setCurrentText(selected_model)
        self.model_combo.blockSignals(False)
        self.model_label.setText("CLI 선택" if is_local_cli else "모델 ID (직접 입력 가능)")
        self._set_local_cli_controls(is_local_cli)
        if hasattr(self, "cli_install_status_title"):
            for control in (
                self.cli_install_status_title,
                self.cli_install_status_label,
                self.cli_node_status_title,
                self.cli_node_status_label,
            ):
                control.setVisible(is_local_cli)
        if hasattr(self, "message_label") and is_local_cli:
            self.message_label.setText(
                "구독 계정 연결 · 본인 PC에 설치·로그인한 CLI를 사용합니다. 각 서비스 약관과 사용량 한도가 적용됩니다. API 키는 사용하지 않습니다."
            )
        if hasattr(self, "key_status_label"):
            self.key_status_label.setText("사용 안 함" if is_local_cli else "")

    def _set_local_cli_controls(self, is_local_cli: bool) -> None:
        for name in ("api_key_edit", "clear_key_button"):
            control = getattr(self, name, None)
            if control is not None:
                control.setEnabled(not is_local_cli)

    def _provider_changed(self, provider_id: str) -> None:
        self.install_cli_button.setVisible(False)
        self.login_cli_button.setVisible(False)
        self._populate_model_choices(
            provider_id,
            self.model_combo.currentText(),
            preserve_custom=False,
        )
        if provider_id != "local-cli" and "구독 계정 연결" in self.message_label.text():
            self.message_label.setText("API 키는 OS 자격 증명 저장소에 보관됩니다.")
        self.mock_mode_checkbox.setEnabled(provider_id != "local-cli")
        if provider_id == "local-cli":
            self.mock_mode_checkbox.setChecked(False)
        self._refresh_key_status()
        if provider_id == "local-cli":
            self._refresh_cli_status()
        if provider_id in ("openai", "anthropic", "gemini"):
            self.api_provider_combo.setCurrentText(provider_id)
            self.api_provider_label.setText(f"선택된 API 제공자: {provider_id}")

    def _select_api_provider(self, provider_id: str) -> None:
        if self.provider_combo.currentText() != provider_id:
            self.provider_combo.setCurrentText(provider_id)

    def _connection_mode_changed(self, radio) -> None:
        mode = radio.property("connection_mode")
        provider_id = mode if mode in ("local-cli", "mock") else self.api_provider_combo.currentText()
        if self.provider_combo.currentText() != provider_id:
            self.provider_combo.setCurrentText(provider_id)
        self.mock_mode_checkbox.setEnabled(mode == "mock")
        self.mock_mode_checkbox.setChecked(mode == "mock")
        self.subscription_panel.setVisible(mode == "local-cli")
        self.api_options_panel.setVisible(mode == "api")
        self.mock_message.setVisible(mode == "mock")
        self.check_cli_install_button.setVisible(mode == "local-cli")
        self.install_cli_button.setVisible(
            mode == "local-cli"
            and _is_windows()
            and (status := self._cli_statuses.get(self.model_combo.currentText())) is not None
            and not status.installed
        )
        if mode != "local-cli":
            self.login_cli_button.setVisible(False)
        if mode == "api" and self.model_combo.parentWidget() is not self.api_options_panel:
            self._settings_form.removeWidget(self.model_label)
            self._settings_form.removeWidget(self.model_combo)
            self._api_form.insertRow(0, self.model_label, self.model_combo)
        elif mode != "api" and self.model_combo.parentWidget() is self.api_options_panel:
            self._api_form.removeWidget(self.model_label)
            self._api_form.removeWidget(self.model_combo)
            self._settings_form.insertRow(0, self.model_label, self.model_combo)

    def _refresh_cli_status(self) -> None:
        if self._cli_status_worker is not None:
            return
        self.cli_install_status_label.setText("CLI 설치 상태 확인 중…")
        self.cli_node_status_label.setText("Node.js / npm 확인 중…")
        worker = _CLIStatusWorker()
        worker.signals.finished.connect(self._on_cli_status_finished)
        self._cli_status_worker = worker
        self.check_cli_install_button.setEnabled(False)
        QtCore.QThreadPool.globalInstance().start(worker)

    def _on_cli_status_finished(self, statuses: dict, node_statuses: dict) -> None:
        self._cli_status_worker = None
        self._cli_statuses = statuses
        self._node_statuses = node_statuses
        self.check_cli_install_button.setEnabled(True)
        self._update_cli_status_label()
        node = "설치됨" if node_statuses.get("node") else "없음"
        npm = "설치됨" if node_statuses.get("npm") else "없음"
        self.cli_node_status_label.setText(f"Node.js {node} · npm {npm}")

    def _update_cli_status_label(self, *_args) -> None:
        selected_cli = self.model_combo.currentText()
        status = self._cli_statuses.get(selected_cli)
        self.install_cli_button.setVisible(
            self.provider_combo.currentText() == "local-cli"
            and _is_windows()
            and status is not None
            and not status.installed
        )
        self.login_cli_button.setVisible(False)
        if status is None:
            self.cli_install_status_label.setText("CLI 설치 상태를 확인하지 못했습니다. 다시 확인해 주세요.")
        elif status.installed:
            version_text = status.version or ""
            if version_text and not version_text.lower().startswith("v"):
                version_text = f"v{version_text}"
            version = f" {version_text}" if version_text else " (버전 확인 실패)"
            self.cli_install_status_label.setText(f"{selected_cli}: 설치됨{version}")
        else:
            self.cli_install_status_label.setText(f"{selected_cli}: 설치 안 됨")

    def _on_cli_selected(self, *_args) -> None:
        if self.provider_combo.currentText() != "local-cli":
            return
        status = self._cli_statuses.get(self.model_combo.currentText())
        if status is not None and not status.installed:
            self._show_cli_install_guide(self.model_combo.currentText())

    def _install_selected_cli(self, _checked: bool = False) -> None:
        self._show_cli_install_guide(self.model_combo.currentText())

    def _require_cli_installed(self) -> bool:
        if self.provider_combo.currentText() != "local-cli":
            return True
        cli = self.model_combo.currentText().strip()
        status = self._cli_statuses.get(cli)
        if status is None:
            message = "CLI 설치 상태를 확인 중이거나 아직 확인하지 않았습니다. ‘CLI 설치 확인’을 눌러 주세요."
            self.message_label.setText(message)
            self.connection_status_label.setText(message)
            return False
        if status.installed:
            return True
        self._show_cli_install_guide(cli)
        return False

    def _show_cli_install_guide(self, cli: str) -> None:
        if cli not in cli_status.SUPPORTED_CLIS:
            return
        node_available = bool(self._node_statuses.get("node") and self._node_statuses.get("npm"))
        command = cli_status.cli_install_command(cli, node_available=node_available)
        node_note = "Node.js LTS가 없다면 먼저 설치합니다.\n" if cli in ("codex", "gemini") else ""
        message = (
            f"{cli}가 설치되어 있지 않습니다. 지금 설치할까요?\n\n{node_note}"
            f"실행할 명령:\n{command}\n\n공식 문서: {cli_status.CLI_INSTALL_DOCS[cli]}"
        )
        self.message_label.setText(message)
        self.connection_status_label.setText(f"설치 필요: {cli}")
        if not _is_windows():
            QtWidgets.QMessageBox.warning(self, "CLI 설치 필요", f"{message}\n\nWindows에서 설치할 수 있습니다.")
            return
        if self._confirm_cli_install(message):
            self._start_cli_install(cli, node_available)

    def _confirm_cli_install(self, message: str) -> bool:
        box = QtWidgets.QMessageBox(self)
        box.setWindowTitle("CLI 설치 확인")
        box.setText(message)
        install_button = box.addButton("설치", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
        box.addButton("취소", QtWidgets.QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is install_button

    def _start_cli_install(self, cli: str, node_available: bool) -> None:
        if self._cli_install_process is not None:
            return
        try:
            self._cli_install_process = cli_status.start_cli_terminal(
                cli, install=True, node_available=node_available
            )
        except OSError as exc:
            self.connection_status_label.setText(f"설치 터미널을 열지 못했습니다: {exc}")
            return
        self.install_cli_button.setEnabled(False)
        self.connection_status_label.setText(f"{cli} 설치 중… PowerShell 창에서 진행 상황을 확인하세요.")
        QtCore.QTimer.singleShot(500, self._poll_cli_install)

    def _poll_cli_install(self) -> None:
        if self._closing:
            self._cli_install_process = None
            return
        if self._cli_install_process is None:
            return
        if self._cli_install_process.poll() is None:
            QtCore.QTimer.singleShot(500, self._poll_cli_install)
            return
        self._cli_install_process = None
        self.install_cli_button.setEnabled(True)
        self.connection_status_label.setText("설치 터미널이 종료되었습니다. CLI 설치 상태를 다시 확인합니다.")
        self._refresh_cli_status()

    def _login_cli(self) -> None:
        cli = self.model_combo.currentText().strip()
        try:
            cli_status.start_cli_terminal(cli)
        except OSError as exc:
            self.connection_status_label.setText(f"로그인 터미널을 열지 못했습니다: {exc}")
            return
        message = "로그인이 끝나면 창을 닫고 연결 테스트를 다시 누르세요."
        self.connection_status_label.setText(message)
        self.message_label.setText(message)

    def _refresh_key_status(self) -> None:
        if self.provider_combo.currentText() == "local-cli":
            self.key_status_label.setText("사용 안 함")
            return
        try:
            has_key = bool(self.credential_store.get(self.provider_combo.currentText()))
        except CredentialStoreError:
            self.key_status_label.setText("저장 상태를 확인할 수 없습니다.")
            return
        self.key_status_label.setText("저장됨" if has_key else "없음")

    def _show_guide(self) -> None:
        QtWidgets.QMessageBox.information(
            self,
            "AI 설정 가이드",
            "API 키 발급 위치:\n"
            "• OpenAI: https://platform.openai.com/api-keys\n"
            "• Anthropic: https://console.anthropic.com/settings/keys\n"
            "• Google AI Studio: https://aistudio.google.com/app/apikey\n\n"
            "모델 ID 예시 (최신 가용성은 공식 카탈로그에서 확인하세요):\n"
            "• OpenAI: gpt-6-luna (효율), gpt-6.1-sol (균형), gpt-6-astra (고성능)\n"
            "• Anthropic: claude-haiku-5-5, claude-sonnet-5-5, claude-opus-5-5\n"
            "• Gemini: gemini-3.5-flash-lite, gemini-3.8-flash, gemini-4-argon\n\n"
            "모델 카탈로그:\n"
            "• OpenAI: https://developers.openai.com/api/docs/models\n"
            "• Anthropic: https://platform.claude.com/docs/en/models/overview\n"
            "• Gemini: https://ai.google.dev/gemini-api/docs/models\n\n"
            "목업 모드는 외부 AI를 호출하지 않으며 비용이 들지 않습니다. 실제 제공자를 사용하면 "
            "선택한 파일의 내용이 외부로 전송되고 사용량에 따라 비용이 발생할 수 있습니다. "
            "실제 회사 자료나 개인정보는 외부 AI에 보내지 마세요.",
        )

    def _test_connection(self) -> None:
        if self._connection_worker is not None:
            return
        provider_id = self.provider_combo.currentText()
        if not self._require_cli_installed():
            return
        if provider_id == "mock":
            message = "목업 모드는 외부 AI API에 연결하지 않습니다. 실제 연결을 테스트하려면 제공자를 선택하세요."
            self.message_label.setText(message)
            self.connection_status_label.setText(message)
            QtWidgets.QMessageBox.information(self, "목업 모드", message)
            return

        model_id = self.model_combo.currentText().strip()
        validation_error = model_id_error(provider_id, model_id)
        if validation_error:
            self.connection_status_label.setText(f"연결 테스트를 시작할 수 없습니다. {validation_error}")
            self.message_label.setText(validation_error)
            QtWidgets.QMessageBox.warning(self, "모델 설정 확인", validation_error)
            return

        api_key = self.api_key_edit.text().strip() if provider_id != "local-cli" else ""
        try:
            if provider_id != "local-cli" and not api_key:
                api_key = self.credential_store.get(provider_id) or ""
        except CredentialStoreError as exc:
            self.connection_status_label.setText(f"연결 실패: {exc}")
            self.message_label.setText(str(exc))
            QtWidgets.QMessageBox.warning(self, "API 키 확인", str(exc))
            return
        if provider_id != "local-cli" and not api_key:
            message = "API 키가 없습니다. 키를 입력한 뒤 저장하거나, 입력란에 키를 입력한 상태로 테스트하세요."
            self.connection_status_label.setText(message)
            self.message_label.setText(message)
            QtWidgets.QMessageBox.warning(self, "API 키 확인", message)
            return

        self._connection_provider_id = provider_id
        self._connection_model_id = model_id
        self._connection_api_key = api_key
        self._connection_started_at = time.monotonic()
        self._pending_connection_result = None
        self._last_connection_error = None
        self._connection_error_log_path = None
        self.error_details_button.setVisible(False)
        cancel_event = Event()
        worker = _ConnectionTestWorker(
            self.provider_registry,
            provider_id,
            model_id,
            api_key,
            self.http_client,
            cancel_event,
            self.retry_sleep_fn,
        )
        worker.signals.retry.connect(self._on_retry_progress)
        worker.signals.finished.connect(self._on_connection_finished)
        self._connection_cancel_event = cancel_event
        self._connection_worker = worker
        self._set_connection_test_running(True)
        self.connection_status_label.setText(f"연결 테스트 중… ({provider_id} · {model_id})")
        QtCore.QThreadPool.globalInstance().start(worker)

    def _set_connection_test_running(self, running: bool) -> None:
        for control in (
            self.test_connection_button,
            self.save_button,
            self.provider_combo,
            self.model_combo,
            self.api_key_edit,
            self.mock_mode_checkbox,
            self.clear_key_button,
        ):
            control.setEnabled(not running)
        self.connection_progress_bar.setVisible(running)
        self.cancel_connection_button.setVisible(running)
        self.cancel_connection_button.setEnabled(running)

    def _on_retry_progress(self, retry_number: int, max_retries: int, _delay: float) -> None:
        cancel_event = self._connection_cancel_event
        if self._closing or (cancel_event is not None and cancel_event.is_set()):
            return
        self.connection_status_label.setText(
            f"연결 테스트 중… ({self._connection_provider_id} · {self._connection_model_id}) · "
            f"다시 시도 중 ({retry_number}/{max_retries})…"
        )

    def _cancel_connection_test(self) -> None:
        if self._connection_cancel_event is None:
            return
        self._connection_cancel_event.set()
        self.cancel_connection_button.setEnabled(False)
        self.connection_status_label.setText("연결 테스트 취소 중… 완료되는 요청 결과는 무시합니다.")

    def _on_connection_finished(self, succeeded: bool, message: str, attempts: list[dict[str, Any]]) -> None:
        if self._closing:
            self._connection_worker = None
            self._connection_cancel_event = None
            self._connection_api_key = ""
            self._pending_connection_result = None
            return
        self._pending_connection_result = (succeeded, message, attempts)
        elapsed = (
            time.monotonic() - self._connection_started_at
            if self._connection_started_at is not None
            else MIN_CONNECTION_PROGRESS_SECONDS
        )
        remaining = MIN_CONNECTION_PROGRESS_SECONDS - elapsed
        if remaining > 0:
            QtCore.QTimer.singleShot(math.ceil(remaining * 1000), self._complete_pending_connection_test)
            return
        self._complete_pending_connection_test()

    def _complete_pending_connection_test(self) -> None:
        result = self._pending_connection_result
        if result is None:
            return
        if self._closing:
            self._connection_worker = None
            self._connection_cancel_event = None
            self._connection_api_key = ""
            self._connection_started_at = None
            self._pending_connection_result = None
            return
        succeeded, message, attempts = result
        self._pending_connection_result = None
        cancel_event = self._connection_cancel_event
        cancelled = cancel_event is not None and cancel_event.is_set()
        api_key = self._connection_api_key
        self._connection_worker = None
        self._connection_cancel_event = None
        self._connection_api_key = ""
        self._connection_started_at = None
        self._set_connection_test_running(False)
        if cancelled:
            self.connection_status_label.setText("연결 테스트가 취소되었습니다. 진행 중 요청 결과는 무시했습니다.")
        elif succeeded:
            self.connection_status_label.setText(message)
            self.login_cli_button.setVisible(False)
            self._save_connection_check(True)
        else:
            safe_message = _sanitize_connection_error(message, api_key)
            attempt_summary = _format_connection_attempts(attempts, api_key)
            self.connection_status_label.setText(f"연결 실패: {attempt_summary} · {safe_message}")
            self._save_connection_check(False)
            self._record_connection_failure(safe_message, attempts, api_key)
            self.login_cli_button.setVisible(
                _is_windows()
                and self._connection_provider_id == "local-cli"
                and any(word in safe_message.casefold() for word in ("login", "logged in", "authenticate", "authentication", "인증", "로그인"))
            )
            if self.login_cli_button.isVisible():
                self.message_label.setText("CLI 인증이 필요합니다. [CLI 로그인]을 눌러 로그인한 뒤 연결 테스트를 다시 하세요.")

    def _save_connection_check(self, succeeded: bool) -> None:
        settings = self.settings_store.load()
        self.settings_store.save(replace(
            settings,
            last_connection_check={
                "provider_id": self._connection_provider_id,
                "model_id": self._connection_model_id,
                "succeeded": succeeded,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
        ))

    def _get_connection_error_log_path(self) -> Path:
        settings = self.settings_store.load()
        base_dir = settings.target_dir or self.settings_store.path.parent
        return base_dir / "reports" / CONNECTION_ERROR_LOG_NAME

    def _record_connection_failure(
        self, message: str, attempts: list[dict[str, Any]], api_key: str
    ) -> None:
        safe_attempts = [
            {
                "status_code": attempt.get("status_code"),
                "status": sanitize_provider_error_message(str(attempt["status"]), api_key)[:100]
                if attempt.get("status") else None,
                "timeout": bool(attempt.get("timeout", False)),
                "elapsed_seconds": attempt.get("elapsed_seconds"),
            }
            for attempt in attempts
        ]
        record = {
            "occurred_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "provider_id": self._connection_provider_id,
            "model_id": self._connection_model_id,
            "status_code": _provider_status_code(message),
            "message": message,
            "attempts": safe_attempts,
        }
        self._last_connection_error = record
        try:
            path = self._get_connection_error_log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as log_file:
                log_file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._connection_error_log_path = path
        except OSError:
            self._connection_error_log_path = None
            self.connection_status_label.setText(
                f"{self.connection_status_label.text()} · 오류 로그를 저장하지 못했습니다."
            )
        self.error_details_button.setVisible(True)

    def _show_connection_error_details(self) -> None:
        record = self._last_connection_error
        if record is None:
            return
        status_code = record["status_code"]
        status_text = f"HTTP {status_code}" if status_code is not None else "제공자 상태 코드 없음"
        log_text = (
            f"\n\n로그 파일: {self._connection_error_log_path}"
            if self._connection_error_log_path is not None
            else "\n\n로그 파일을 저장하지 못했습니다."
        )
        details = (
            f"시각(현지): {_local_error_time(record['occurred_at'])}\n"
            f"제공자: {record['provider_id']}\n"
            f"모델: {record['model_id']}\n"
            f"상태: {status_text}\n"
            f"시도: {_format_connection_attempts(record.get('attempts', []))}\n"
            f"오류: {record['message']}"
            f"{log_text}"
        )
        QtWidgets.QMessageBox.information(self, "연결 오류 자세히 보기", details)

    def reject(self) -> None:
        self._closing = True
        self._cli_install_process = None
        if self._connection_cancel_event is not None:
            self._connection_cancel_event.set()
        super().reject()

    def closeEvent(self, event: QtGui.QCloseEvent) -> None:
        self._closing = True
        self._cli_install_process = None
        if self._connection_cancel_event is not None:
            self._connection_cancel_event.set()
        super().closeEvent(event)

    def _save(self) -> None:
        provider_id = self.provider_combo.currentText()
        if not self._require_cli_installed():
            return
        model_id = self.model_combo.currentText().strip()
        validation_error = model_id_error(provider_id, model_id)
        if validation_error:
            self.message_label.setText(validation_error)
            return
        api_key = self.api_key_edit.text() if provider_id != "local-cli" else ""
        try:
            if api_key:
                self.credential_store.set(provider_id, api_key)
            current = self.settings_store.load()
            self.settings_store.save(replace(
                current,
                provider_id=provider_id,
                model_id=model_id,
                mock_mode=self.mock_mode_checkbox.isChecked(),
                auto_collect_hospital_channels=self.auto_collect_checkbox.isChecked(),
            ))
        except (CredentialStoreError, ValueError) as exc:
            self.message_label.setText(str(exc))
            return
        self.api_key_edit.clear()
        self._refresh_key_status()
        self.accept()

    def _clear_key(self) -> None:
        provider_id = self.provider_combo.currentText()
        answer = QtWidgets.QMessageBox.question(
            self,
            "API 키 삭제",
            f"{provider_id}에 저장된 API 키를 삭제할까요?",
        )
        if answer == QtWidgets.QMessageBox.StandardButton.Yes:
            try:
                self.credential_store.delete(provider_id)
                self.message_label.setText("선택한 제공자의 저장 API 키를 삭제했습니다.")
                self._refresh_key_status()
            except CredentialStoreError as exc:
                self.message_label.setText(str(exc))
