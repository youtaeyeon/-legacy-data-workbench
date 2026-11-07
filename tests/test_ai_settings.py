import json
import os
import time
from datetime import datetime, timezone
from threading import Event
from typing import Any, cast

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import httpx
import pytest
from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest

from hospital_marketing.ai.registry import ProviderRegistry
from hospital_marketing.providers import ProviderRequestError
from hospital_marketing.settings import SettingsStore
from hospital_marketing.ui import settings_dialog
from hospital_marketing.ui.settings_dialog import SettingsDialog


_APP = None


def _app():
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    return _APP


class FakeCredentials:
    def __init__(self, saved_key=None, error=None):
        self.saved_key = saved_key
        self.error = error
        self.values = {}

    def get(self, provider_id):
        if self.error:
            raise self.error
        return self.values.get(provider_id, self.saved_key)

    def set(self, provider_id, api_key):
        self.values[provider_id] = api_key

    def delete(self, provider_id):
        self.values.pop(provider_id, None)


class FakeResponse:
    def __init__(self, status_code=200):
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("fake provider response", request=request, response=response)

    def json(self):
        return {"choices": [{"message": {"content": "{}"}}]}


class FakeHttpClient:
    def __init__(self, *, status_code=200, error=None):
        self.response = FakeResponse(status_code)
        self.error = error
        self.calls = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.closed = True

    def post(self, url, *, headers, json):
        self.calls.append((url, headers, json))
        if self.error:
            raise self.error
        return self.response


class BlockingFakeHttpClient(FakeHttpClient):
    def __init__(self):
        super().__init__()
        self.started = Event()
        self.release = Event()

    def post(self, url, *, headers, json):
        self.calls.append((url, headers, json))
        self.started.set()
        self.release.wait(timeout=0.5)
        return self.response


def _dialog(tmp_path, *, client=None, credentials=None, provider_registry=None, retry_sleep_fn=None):
    options = {"http_client": client}
    if retry_sleep_fn is not None:
        options["retry_sleep_fn"] = retry_sleep_fn
    return SettingsDialog(
        SettingsStore(tmp_path / "settings.json"),
        credentials or FakeCredentials(),
        provider_registry or ProviderRegistry(),
        **options,
    )


def _wait_for_connection():
    assert QtCore.QThreadPool.globalInstance().waitForDone(5_000)
    QTest.qWait(550)
    QtWidgets.QApplication.processEvents()


@pytest.mark.parametrize(
    "status_code,expected",
    [
        (200, "연결 성공"),
        (401, "인증"),
        (403, "인증"),
        (404, "모델"),
        (429, "한도"),
    ],
)
def test_connection_test_reports_http_status_without_exposing_key(tmp_path, status_code, expected):
    _app()
    client = FakeHttpClient(status_code=status_code)
    dialog = _dialog(tmp_path, client=client)
    dialog.provider_combo.setCurrentText("openai")
    dialog.api_key_edit.setText("secret-test-key")

    dialog.test_connection_button.click()
    _wait_for_connection()

    assert len(client.calls) == 1
    assert expected in dialog.connection_status_label.text()
    assert "secret-test-key" not in dialog.connection_status_label.text()
    assert "secret-test-key" not in dialog.message_label.text()
    assert dialog.test_connection_button.isEnabled()
    assert dialog.save_button.isEnabled()
    assert not dialog.connection_progress_bar.isVisible()


@pytest.mark.parametrize(
    "error,expected",
    [
        (httpx.ReadTimeout("fake timeout"), "초과됐습니다"),
        (httpx.ConnectError("fake network error", request=httpx.Request("POST", "https://api.openai.com")), "네트워크"),
    ],
)
def test_connection_test_distinguishes_timeout_and_network_errors(tmp_path, error, expected):
    _app()
    client = FakeHttpClient(error=error)
    sleep_calls = []
    dialog = _dialog(tmp_path, client=client, retry_sleep_fn=sleep_calls.append)
    dialog.provider_combo.setCurrentText("openai")
    dialog.api_key_edit.setText("secret-test-key")

    dialog.test_connection_button.click()
    _wait_for_connection()

    assert len(client.calls) == 2
    assert len(sleep_calls) == 1
    assert expected in dialog.connection_status_label.text()
    assert "한 차례 재시도" in dialog.connection_status_label.text()
    assert "secret-test-key" not in dialog.connection_status_label.text()


def test_connection_test_uses_saved_key_without_showing_it(tmp_path):
    _app()
    client = FakeHttpClient()
    credentials = FakeCredentials(saved_key="secret-test-key")
    dialog = _dialog(tmp_path, client=client, credentials=credentials)
    dialog.provider_combo.setCurrentText("openai")

    assert "저장됨" in dialog.key_status_label.text()
    assert "secret-test-key" not in dialog.key_status_label.text()
    dialog.test_connection_button.click()
    _wait_for_connection()

    assert len(client.calls) == 1
    assert client.calls[0][1]["Authorization"] == "Bearer secret-test-key"
    assert "secret-test-key" not in dialog.connection_status_label.text()


def test_connection_test_closes_its_real_client_owner(tmp_path, monkeypatch):
    _app()
    client = FakeHttpClient()
    monkeypatch.setattr("hospital_marketing.ui.settings_dialog.httpx.Client", lambda **_kwargs: client)
    dialog = _dialog(tmp_path)
    dialog.provider_combo.setCurrentText("openai")
    dialog.api_key_edit.setText("secret-test-key")

    dialog.test_connection_button.click()
    _wait_for_connection()

    assert len(client.calls) == 1
    assert client.closed is True


def test_connection_test_runs_in_background_and_restores_controls(tmp_path):
    _app()
    client = BlockingFakeHttpClient()
    dialog = _dialog(tmp_path, client=client)
    dialog.provider_combo.setCurrentText("openai")
    dialog.api_key_edit.setText("secret-test-key")
    dialog.show()
    QtWidgets.QApplication.processEvents()

    dialog.test_connection_button.click()

    assert client.started.wait(timeout=1)
    assert "연결 테스트 중" in dialog.connection_status_label.text()
    assert "openai" in dialog.connection_status_label.text()
    assert "gpt-6-luna" in dialog.connection_status_label.text()
    assert not dialog.test_connection_button.isEnabled()
    assert not dialog.save_button.isEnabled()
    assert not dialog.provider_combo.isEnabled()
    assert not dialog.model_combo.isEnabled()
    assert dialog.connection_progress_bar.isVisible()
    assert dialog.connection_progress_bar.minimum() == 0
    assert dialog.connection_progress_bar.maximum() == 0
    assert dialog.cancel_connection_button.isVisible()

    client.release.set()
    _wait_for_connection()

    assert "연결 성공" in dialog.connection_status_label.text()
    assert dialog.test_connection_button.isEnabled()
    assert dialog.save_button.isEnabled()
    assert dialog.provider_combo.isEnabled()
    assert dialog.model_combo.isEnabled()
    assert not dialog.connection_progress_bar.isVisible()
    assert not dialog.cancel_connection_button.isVisible()
    dialog.close()


def test_connection_test_displays_retry_progress_from_worker(tmp_path):
    _app()
    started = Event()
    release = Event()

    class RetryReportingProvider:
        def __init__(self, on_retry):
            self.on_retry = on_retry

        def test_connection(self):
            self.on_retry(2, 3, 2.0)
            started.set()
            release.wait(timeout=0.5)

    registry = ProviderRegistry(
        providers=cast(
            Any,
            {
                "mock": lambda **_kwargs: None,
                "openai": lambda **kwargs: RetryReportingProvider(kwargs["on_retry"]),
            },
        )
    )
    dialog = _dialog(tmp_path, client=object(), provider_registry=registry)
    dialog.provider_combo.setCurrentText("openai")
    dialog.api_key_edit.setText("secret-test-key")
    dialog.show()
    QtWidgets.QApplication.processEvents()

    dialog.test_connection_button.click()

    assert started.wait(timeout=1)
    QtWidgets.QApplication.processEvents()
    assert "다시 시도 중 (2/3)" in dialog.connection_status_label.text()
    assert "openai" in dialog.connection_status_label.text()
    assert "gpt-6-luna" in dialog.connection_status_label.text()
    assert dialog.connection_progress_bar.isVisible()

    release.set()
    _wait_for_connection()
    assert "연결 성공" in dialog.connection_status_label.text()
    dialog.close()


def test_cancel_during_retry_backoff_prevents_followup_request(tmp_path):
    _app()
    retry_started = Event()
    followup_requests = []

    class RetryingProvider:
        def __init__(self, on_retry, sleep_fn):
            self.on_retry = on_retry
            self.sleep_fn = sleep_fn

        def test_connection(self):
            self.on_retry(1, 3, 5.0)
            retry_started.set()
            self.sleep_fn(5.0)
            followup_requests.append("sent")

    registry = ProviderRegistry(
        providers=cast(
            Any,
            {
                "mock": lambda **_kwargs: None,
                "openai": lambda **kwargs: RetryingProvider(kwargs["on_retry"], kwargs["sleep_fn"]),
            },
        )
    )
    dialog = _dialog(tmp_path, client=object(), provider_registry=registry)
    dialog.provider_combo.setCurrentText("openai")
    dialog.api_key_edit.setText("secret-test-key")
    dialog.show()
    QtWidgets.QApplication.processEvents()
    dialog.test_connection_button.click()

    assert retry_started.wait(timeout=1)
    dialog.cancel_connection_button.click()
    _wait_for_connection()

    assert followup_requests == []
    assert "취소" in dialog.connection_status_label.text()
    dialog.close()


def test_cancel_connection_test_ignores_result_and_restores_controls(tmp_path):
    _app()
    client = BlockingFakeHttpClient()
    dialog = _dialog(tmp_path, client=client)
    dialog.provider_combo.setCurrentText("openai")
    dialog.api_key_edit.setText("secret-test-key")
    dialog.show()
    QtWidgets.QApplication.processEvents()
    dialog.test_connection_button.click()

    assert client.started.wait(timeout=1)
    dialog.cancel_connection_button.click()
    assert "취소" in dialog.connection_status_label.text()

    client.release.set()
    _wait_for_connection()

    assert "취소" in dialog.connection_status_label.text()
    assert "연결 성공" not in dialog.connection_status_label.text()
    assert dialog.test_connection_button.isEnabled()
    assert dialog.save_button.isEnabled()
    assert not dialog.connection_progress_bar.isVisible()
    dialog.close()


def test_closing_settings_dialog_ignores_late_connection_result(tmp_path):
    _app()
    client = BlockingFakeHttpClient()
    dialog = _dialog(tmp_path, client=client)
    dialog.provider_combo.setCurrentText("openai")
    dialog.api_key_edit.setText("secret-test-key")
    dialog.show()
    QtWidgets.QApplication.processEvents()
    dialog.test_connection_button.click()

    assert client.started.wait(timeout=1)
    dialog.reject()
    assert not dialog.isVisible()

    client.release.set()
    _wait_for_connection()

    assert "연결 성공" not in dialog.connection_status_label.text()


def test_connection_test_without_key_does_not_send_http_request(tmp_path, monkeypatch):
    _app()
    client = FakeHttpClient()
    warnings = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )
    dialog = _dialog(tmp_path, client=client)
    dialog.provider_combo.setCurrentText("openai")

    dialog.test_connection_button.click()

    assert client.calls == []
    assert "API 키" in dialog.connection_status_label.text()
    assert warnings and "저장" in warnings[0][1]


def test_model_selector_has_recommendations_and_accepts_direct_input(tmp_path):
    _app()
    dialog = _dialog(tmp_path)
    assert dialog.model_combo.isEditable()
    expected = {
        "openai": ("gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra"),
        "anthropic": ("claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5"),
        "gemini": ("gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-4-argon"),
    }
    for provider_id, expected_models in expected.items():
        dialog.provider_combo.setCurrentText(provider_id)
        options = [dialog.model_combo.itemText(index) for index in range(dialog.model_combo.count())]
        assert options == list(expected_models)
        assert dialog.model_combo.currentText() in options
    dialog.model_edit.setText("custom-model-2026")
    assert dialog.model_combo.currentText() == "custom-model-2026"


def test_key_status_shows_presence_without_revealing_saved_key(tmp_path):
    _app()
    dialog = _dialog(tmp_path, credentials=FakeCredentials(saved_key="secret-test-key"))

    assert dialog.key_status_label.text() == "저장됨"
    assert "secret-test-key" not in dialog.key_status_label.text()


def test_model_validation_blocks_blank_and_malformed_values_on_save(tmp_path):
    _app()
    dialog = _dialog(tmp_path)
    dialog.provider_combo.setCurrentText("gemini")
    original = dialog.settings_store.load()
    dialog.model_edit.setText(" ")

    dialog.save_button.click()

    assert "모델 ID" in dialog.message_label.text()
    assert dialog.settings_store.load() == original
    dialog.model_edit.setText("잼민이")

    dialog.save_button.click()

    assert "형식" in dialog.message_label.text()
    assert dialog.settings_store.load() == original


def test_settings_guide_explains_keys_mock_cost_and_privacy(tmp_path, monkeypatch):
    _app()
    messages = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda _parent, title, text: messages.append((title, text)),
    )
    dialog = _dialog(tmp_path)

    dialog.guide_button.click()

    assert len(messages) == 1
    title, text = messages[0]
    assert "설정 가이드" in title
    assert "platform.openai.com/api-keys" in text
    assert "console.anthropic.com/settings/keys" in text
    assert "aistudio.google.com/app/apikey" in text
    assert "developers.openai.com/api/docs/models" in text
    assert "platform.claude.com/docs/en/models/overview" in text
    assert "ai.google.dev/gemini-api/docs/models" in text
    assert "목업 모드" in text and "비용" in text
    assert "실제 회사 자료" in text


def test_mock_provider_explains_that_no_external_connection_is_made(tmp_path, monkeypatch):
    _app()
    notices = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda _parent, title, text: notices.append((title, text)),
    )
    client = FakeHttpClient()
    dialog = _dialog(tmp_path, client=client)
    dialog.show()
    QtWidgets.QApplication.processEvents()
    dialog.provider_combo.setCurrentText("mock")

    dialog.test_connection_button.click()

    assert client.calls == []
    assert notices
    assert "목업 모드" in notices[0][1]
    assert "외부" in notices[0][1]
    assert "목업 모드" in dialog.connection_status_label.text()
    dialog.close()


def test_missing_api_key_shows_prominent_save_or_input_guidance(tmp_path, monkeypatch):
    _app()
    warnings = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )
    client = FakeHttpClient()
    dialog = _dialog(tmp_path, client=client)
    dialog.show()
    QtWidgets.QApplication.processEvents()
    dialog.provider_combo.setCurrentText("openai")

    dialog.test_connection_button.click()

    assert client.calls == []
    assert warnings
    assert "저장" in warnings[0][1]
    assert "입력란" in warnings[0][1]
    assert "API 키" in dialog.connection_status_label.text()
    dialog.close()


def test_invalid_model_shows_prominent_result_without_request(tmp_path, monkeypatch):
    _app()
    warnings = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "warning",
        lambda _parent, title, text: warnings.append((title, text)),
    )
    client = FakeHttpClient()
    dialog = _dialog(tmp_path, client=client)
    dialog.show()
    QtWidgets.QApplication.processEvents()
    dialog.provider_combo.setCurrentText("openai")
    dialog.model_edit.setText("invalid model id")

    dialog.test_connection_button.click()

    assert client.calls == []
    assert warnings
    assert "모델 ID" in warnings[0][1]
    dialog.close()


def test_connection_request_keeps_progress_visible_for_at_least_half_second(tmp_path):
    _app()
    client = FakeHttpClient()
    dialog = _dialog(tmp_path, client=client)
    dialog.show()
    QtWidgets.QApplication.processEvents()
    dialog.provider_combo.setCurrentText("openai")
    dialog.api_key_edit.setText("secret-test-key")
    started_at = time.monotonic()

    dialog.test_connection_button.click()

    assert dialog.connection_progress_bar.isVisible()
    assert QtCore.QThreadPool.globalInstance().waitForDone(5_000)
    assert len(client.calls) == 1
    QtWidgets.QApplication.processEvents()
    assert dialog.connection_progress_bar.isVisible()
    QTest.qWait(550)
    QtWidgets.QApplication.processEvents()

    assert time.monotonic() - started_at >= 0.5
    assert "연결 성공" in dialog.connection_status_label.text()
    assert not dialog.connection_progress_bar.isVisible()
    dialog.close()


def test_connection_progress_bar_uses_explicit_contrast_colors(tmp_path):
    _app()
    dialog = _dialog(tmp_path)

    style = dialog.connection_progress_bar.styleSheet()

    assert "QProgressBar {" in style
    assert "QProgressBar::chunk" in style
    assert "#2b6cb8" in style
    assert "#e9e3d3" in style
    dialog.close()


def test_connection_failure_logs_sanitized_details_and_opens_details_view(tmp_path, monkeypatch):
    _app()
    fake_key = "test-key-for-redaction"

    class FailingProvider:
        def __init__(self, api_key):
            self.api_key = api_key

        def test_connection(self):
            raise ProviderRequestError(f"HTTP 503 Authorization: Bearer {self.api_key}")

    registry = ProviderRegistry(
        providers=cast(
            Any,
            {
                "mock": lambda **_kwargs: None,
                "openai": lambda **kwargs: FailingProvider(kwargs["api_key"]),
            },
        )
    )
    dialog = _dialog(
        tmp_path,
        client=object(),
        provider_registry=registry,
        retry_sleep_fn=lambda _delay: None,
    )
    dialog.show()
    QtWidgets.QApplication.processEvents()
    dialog.provider_combo.setCurrentText("openai")
    dialog.api_key_edit.setText(fake_key)

    dialog.test_connection_button.click()
    _wait_for_connection()

    log_path = tmp_path / "reports" / "ai-connection-errors.jsonl"
    assert log_path.is_file()
    entry = json.loads(log_path.read_text(encoding="utf-8").splitlines()[-1])
    assert entry["provider_id"] == "openai"
    assert entry["model_id"] == "gpt-6-luna"
    assert entry["status_code"] == 503
    assert "HTTP 503" in entry["message"]
    assert fake_key not in log_path.read_text(encoding="utf-8")

    details_button = getattr(dialog, "error_details_button", None)
    assert details_button is not None
    assert not details_button.isHidden()
    details = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda _parent, title, text: details.append((title, text)),
    )
    details_button.click()
    assert details
    assert "HTTP 503" in details[0][1]
    assert fake_key not in details[0][1]
    dialog.close()


@pytest.mark.parametrize(
    "error_prefix",
    ["Incorrect API key provided: ", "Provider echoed token "],
)
@pytest.mark.parametrize("star_count", [3, 9])
@pytest.mark.parametrize("split_suffix", [False, True])
def test_masked_provider_key_is_redacted_everywhere_and_ui_time_is_local(
    tmp_path,
    monkeypatch,
    error_prefix,
    star_count,
    split_suffix,
):
    _app()
    masked_token = "sk-proj-" + "*" * star_count + (" abcd" if split_suffix else "abcd")

    class FailingProvider:
        def test_connection(self):
            raise ProviderRequestError(f"HTTP 401 {error_prefix}{masked_token}")

    registry = ProviderRegistry(
        providers=cast(
            Any,
            {
                "mock": lambda **_kwargs: None,
                "openai": lambda **_kwargs: FailingProvider(),
            },
        )
    )
    dialog = _dialog(
        tmp_path,
        client=object(),
        provider_registry=registry,
        retry_sleep_fn=lambda _delay: None,
    )
    dialog.show()
    QtWidgets.QApplication.processEvents()
    dialog.provider_combo.setCurrentText("openai")
    dialog.api_key_edit.setText("fake-test-key")

    dialog.test_connection_button.click()
    _wait_for_connection()

    status_text = dialog.connection_status_label.text()
    log_path = tmp_path / "reports" / "ai-connection-errors.jsonl"
    log_text = log_path.read_text(encoding="utf-8")
    record = json.loads(log_text.splitlines()[-1])
    assert record["occurred_at"].endswith("+00:00")
    assert record["status_code"] == 401

    details = []
    monkeypatch.setattr(
        QtWidgets.QMessageBox,
        "information",
        lambda _parent, title, text: details.append((title, text)),
    )
    dialog.error_details_button.click()
    details_text = details[0][1]
    local_time = datetime.fromisoformat(record["occurred_at"]).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )

    for output in (status_text, log_text, details_text):
        assert "sk-proj-" not in output
        assert "abcd" not in output
        assert "[REDACTED]" in output
    assert f"시각(현지): {local_time}" in details_text
    assert record["occurred_at"] not in details_text
    dialog.close()


def test_local_error_time_assumes_utc_for_naive_timestamp(monkeypatch):
    class NaiveTimestamp:
        tzinfo = None

        def replace(self, *, tzinfo):
            assert tzinfo is timezone.utc
            return datetime(2026, 1, 1, tzinfo=tzinfo)

        def astimezone(self):
            raise AssertionError("naive log timestamps must first be interpreted as UTC")

    class FakeDateTime:
        @staticmethod
        def fromisoformat(_value):
            return NaiveTimestamp()

    monkeypatch.setattr(settings_dialog, "datetime", FakeDateTime)
    expected = datetime(2026, 1, 1, tzinfo=timezone.utc).astimezone().strftime(
        "%Y-%m-%d %H:%M:%S %Z"
    )

    assert settings_dialog._local_error_time("2026-01-01T00:00:00") == expected
