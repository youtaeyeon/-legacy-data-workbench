import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets
from typing import cast

from hospital_marketing.channel_discovery import ChannelCandidate, ChannelDiscoveryService
from hospital_marketing.domain import Hospital
from hospital_marketing.repository import Repository
from hospital_marketing.ui import channel_candidates_dialog as channel_dialog_module
from hospital_marketing.ui.channel_candidates_dialog import ChannelCandidatesDialog

_APP = None


def _app():
    global _APP
    if _APP is None:
        _APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_approving_candidate_refreshes_dashboard_wiki_and_excel(tmp_path):
    _app()
    target = tmp_path / "target"
    repository = Repository(target / "data" / "app.db")
    repository.initialize()
    hospital = Hospital("MOCK-CHANNEL", "목업 병원", "가상 지역")
    repository.upsert_hospital(hospital)
    service = ChannelDiscoveryService(repository)
    candidate = service.save_candidates(hospital.hospital_id, [
        ChannelCandidate("유튜브", "목업 채널", "https://youtube.com/@mock", "가상 목업 근거", 0.8)
    ])[0]
    dialog = ChannelCandidatesDialog(repository, object(), [hospital], target)

    action = dialog.table.cellWidget(0, 6)
    approve_button = cast(QtWidgets.QPushButton, action.findChild(QtWidgets.QPushButton))
    assert approve_button is not None
    approve_button.click()

    assert repository.list_channels(hospital.hospital_id)[0].url == candidate.url
    assert (target / "dashboard" / "index.html").is_file()
    assert (target / "wiki" / f"{hospital.hospital_id}.md").is_file()
    assert (target / "exports" / "marketing.xlsx").is_file()
    assert candidate.url in (target / "wiki" / f"{hospital.hospital_id}.md").read_text(encoding="utf-8")
    assert "갱신했습니다" in dialog.status_label.text()
    dialog.close()
    repository.close()


def test_closing_dialog_after_discovery_finishes_keeps_thread_reference_valid(tmp_path, monkeypatch):
    _app()
    target = tmp_path / "target"
    repository = Repository(target / "data" / "app.db")
    repository.initialize()
    hospital = Hospital("MOCK-CHANNEL", "목업 병원", "가상 지역")
    repository.upsert_hospital(hospital)
    monkeypatch.setattr(channel_dialog_module, "find_hospital_channels", lambda _provider, _hospital: [])
    dialog = ChannelCandidatesDialog(repository, object(), [hospital], target)

    dialog._start_discovery()
    deadline = QtCore.QDeadlineTimer(5000)
    while (not dialog.find_button.isEnabled() or dialog._worker_thread.isRunning()) and not deadline.hasExpired():
        QtWidgets.QApplication.processEvents()
        QtCore.QThread.msleep(10)
    QtWidgets.QApplication.processEvents()

    assert dialog.find_button.isEnabled()
    assert not dialog._worker_thread.isRunning()
    dialog.close()
    repository.close()
