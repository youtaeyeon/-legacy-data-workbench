from __future__ import annotations

from dataclasses import replace

from PySide6 import QtWidgets

from ..ai.registry import ProviderRegistry
from ..credentials import CredentialStore, CredentialStoreError
from ..settings import SettingsStore


class SettingsDialog(QtWidgets.QDialog):
    def __init__(
        self,
        settings_store: SettingsStore,
        credential_store: CredentialStore,
        provider_registry: ProviderRegistry,
        parent=None,
    ):
        super().__init__(parent)
        self.settings_store = settings_store
        self.credential_store = credential_store
        self.provider_registry = provider_registry
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

        self.model_edit = QtWidgets.QLineEdit(settings.model_id)
        self.model_edit.setObjectName("model_edit")
        form.addRow("모델 이름", self.model_edit)

        self.api_key_edit = QtWidgets.QLineEdit()
        self.api_key_edit.setObjectName("api_key_edit")
        self.api_key_edit.setEchoMode(QtWidgets.QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("키는 설정 파일에 저장되지 않습니다")
        form.addRow("API 키 (선택)", self.api_key_edit)

        self.mock_mode_checkbox = QtWidgets.QCheckBox("목업 모드 (외부 AI 호출 안 함)")
        self.mock_mode_checkbox.setObjectName("mock_mode_checkbox")
        self.mock_mode_checkbox.setChecked(settings.mock_mode)
        form.addRow("과제 테스트", self.mock_mode_checkbox)
        layout.addLayout(form)

        self.message_label = QtWidgets.QLabel("API 키는 OS 자격 증명 저장소에 보관됩니다.")
        self.message_label.setWordWrap(True)
        layout.addWidget(self.message_label)

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

    def _save(self) -> None:
        provider_id = self.provider_combo.currentText()
        api_key = self.api_key_edit.text()
        try:
            if api_key:
                self.credential_store.set(provider_id, api_key)
            current = self.settings_store.load()
            self.settings_store.save(replace(
                current,
                provider_id=provider_id,
                model_id=self.model_edit.text().strip(),
                mock_mode=self.mock_mode_checkbox.isChecked(),
            ))
        except (CredentialStoreError, ValueError) as exc:
            self.message_label.setText(str(exc))
            return
        self.api_key_edit.clear()
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
                self.message_label.setText("선택한 제공자의 저장 키를 삭제했습니다.")
            except CredentialStoreError as exc:
                self.message_label.setText(str(exc))
