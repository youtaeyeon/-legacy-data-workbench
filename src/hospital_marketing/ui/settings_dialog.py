from __future__ import annotations

from dataclasses import replace
from typing import Any

import httpx
from PySide6 import QtWidgets

from ..ai.models import RECOMMENDED_MODELS, model_id_error
from ..ai.registry import ProviderRegistry
from ..credentials import CredentialStore, CredentialStoreError
from ..providers import ProviderConfigurationError, ProviderRequestError
from ..settings import SettingsStore


class SettingsDialog(QtWidgets.QDialog):
    def __init__(
        self,
        settings_store: SettingsStore,
        credential_store: CredentialStore,
        provider_registry: ProviderRegistry,
        parent=None,
        http_client: Any | None = None,
    ):
        super().__init__(parent)
        self.settings_store = settings_store
        self.credential_store = credential_store
        self.provider_registry = provider_registry
        self.http_client = http_client
        settings = settings_store.load()
        self.setWindowTitle("AI 제공자 설정")
        self.setModal(True)

        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self.provider_combo = QtWidgets.QComboBox()
        self.provider_combo.addItems(provider_registry.available())
        self.provider_combo.setCurrentText(settings.provider_id)
        self.provider_combo.setObjectName("provider_combo")
        form.addRow("제공자", self.provider_combo)

        self.model_combo = QtWidgets.QComboBox()
        self.model_combo.setObjectName("model_combo")
        self.model_combo.setEditable(True)
        self.model_edit = self.model_combo.lineEdit()
        if self.model_edit is not None:
            self.model_edit.setObjectName("model_edit")
            self.model_edit.setPlaceholderText("권장 모델을 고르거나 모델 ID를 입력하세요")
        self._populate_model_choices(settings.provider_id, settings.model_id, preserve_custom=True)
        self.provider_combo.currentTextChanged.connect(self._provider_changed)
        form.addRow("모델 ID (직접 입력 가능)", self.model_combo)

        self.api_key_edit = QtWidgets.QLineEdit()
        self.api_key_edit.setObjectName("api_key_edit")
        self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("키는 설정 파일에 저장되지 않습니다")
        form.addRow("API 키 (선택)", self.api_key_edit)

        self.mock_mode_checkbox = QtWidgets.QCheckBox("목업 모드 (외부 AI 호출 안 함)")
        self.mock_mode_checkbox.setObjectName("mock_mode_checkbox")
        self.mock_mode_checkbox.setChecked(settings.mock_mode)
        form.addRow("과제 테스트", self.mock_mode_checkbox)

        self.key_status_label = QtWidgets.QLabel()
        self.key_status_label.setObjectName("key_status_label")
        form.addRow("저장된 키", self.key_status_label)
        layout.addLayout(form)

        self.message_label = QtWidgets.QLabel("API 키는 OS 자격 증명 저장소에 보관됩니다.")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

        connection_buttons = QtWidgets.QHBoxLayout()
        self.test_connection_button = QtWidgets.QPushButton("연결 테스트")
        self.test_connection_button.setObjectName("test_connection_button")
        self.test_connection_button.clicked.connect(self._test_connection)
        connection_buttons.addWidget(self.test_connection_button)
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

        buttons = QtWidgets.QHBoxLayout()
        self.clear_key_button = QtWidgets.QPushButton("선택 제공자 키 삭제")
        self.clear_key_button.clicked.connect(self._clear_key)
        buttons.addWidget(self.clear_key_button)
        buttons.addStretch(1)
        self.save_button = QtWidgets.QPushButton("저장")
        self.save_button.setObjectName("save_settings_button")
        self.save_button.clicked.connect(self._save)
        buttons.addWidget(self.save_button)
        cancel = QtWidgets.QPushButton("취소")
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        layout.addLayout(buttons)
        self._refresh_key_status()

    def _populate_model_choices(
        self,
        provider_id: str,
        model_id: str,
        *,
        preserve_custom: bool,
    ) -> None:
        models = RECOMMENDED_MODELS.get(provider_id, ())
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
        self.model_combo.setCurrentText(selected_model)
        self.model_combo.blockSignals(False)

    def _provider_changed(self, provider_id: str) -> None:
        self._populate_model_choices(
            provider_id,
            self.model_combo.currentText(),
            preserve_custom=False,
        )
        self._refresh_key_status()

    def _refresh_key_status(self) -> None:
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
        provider_id = self.provider_combo.currentText()
        if provider_id == "mock":
            self.connection_status_label.setText("목업 모드는 외부 연결을 사용하지 않습니다.")
            return

        model_id = self.model_combo.currentText().strip()
        validation_error = model_id_error(provider_id, model_id)
        if validation_error:
            self.connection_status_label.setText(f"연결 테스트를 시작할 수 없습니다. {validation_error}")
            return

        api_key = self.api_key_edit.text().strip()
        try:
            if not api_key:
                api_key = self.credential_store.get(provider_id) or ""
            if not api_key:
                self.connection_status_label.setText("API 키가 없습니다. 키를 입력하거나 제공자 키를 저장해 주세요.")
                return
            if self.http_client is None:
                with httpx.Client(timeout=30.0) as client:
                    self._send_connection_test(provider_id, model_id, api_key, client)
            else:
                self._send_connection_test(provider_id, model_id, api_key, self.http_client)
        except (CredentialStoreError, ProviderConfigurationError, ProviderRequestError) as exc:
            self.connection_status_label.setText(f"연결 실패: {exc}")
        except Exception:
            self.connection_status_label.setText("연결 테스트 중 오류가 발생했습니다. 설정과 네트워크를 확인하세요.")
        else:
            self.connection_status_label.setText("연결 성공: 선택한 제공자와 모델을 사용할 수 있습니다.")

    def _send_connection_test(
        self,
        provider_id: str,
        model_id: str,
        api_key: str,
        http_client: Any,
    ) -> None:
        provider = self.provider_registry.create(
            provider_id,
            api_key=api_key,
            model=model_id,
            http_client=http_client,
        )
        connection_test = getattr(provider, "test_connection", None)
        if not callable(connection_test):
            raise ProviderConfigurationError("선택한 제공자는 연결 테스트를 지원하지 않습니다.")
        connection_test()

    def _save(self) -> None:
        provider_id = self.provider_combo.currentText()
        model_id = self.model_combo.currentText().strip()
        validation_error = model_id_error(provider_id, model_id)
        if validation_error:
            self.message_label.setText(validation_error)
            return
        api_key = self.api_key_edit.text()
        try:
            if api_key:
                self.credential_store.set(provider_id, api_key)
            current = self.settings_store.load()
            self.settings_store.save(replace(
                current,
                provider_id=provider_id,
                model_id=model_id,
                mock_mode=self.mock_mode_checkbox.isChecked(),
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
