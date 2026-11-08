from __future__ import annotations

from threading import Event

from PySide6 import QtCore, QtGui, QtWidgets

from ..channel_discovery import ChannelCandidate, ChannelDiscoveryService, find_hospital_channels
from ..domain import Hospital
from ..providers import ProviderRequestError
from ..repository import Repository
from ..ai.mock import MockProvider
from ..outputs.generate import generate_outputs


class _DiscoveryWorker(QtCore.QObject):
    finished = QtCore.Signal(object, object)
    progress = QtCore.Signal(int, int, str)

    def __init__(self, provider: object, hospitals: list[Hospital], cancel_event: Event):
        super().__init__()
        self.provider = provider
        self.hospitals = hospitals
        self.cancel_event = cancel_event

    @QtCore.Slot()
    def run(self) -> None:
        results: dict[str, list[ChannelCandidate]] = {}
        errors: dict[str, str] = {}
        for index, hospital in enumerate(self.hospitals, 1):
            if self.cancel_event.is_set():
                break
            self.progress.emit(index, len(self.hospitals), hospital.hospital_name)
            try:
                results[hospital.hospital_id] = find_hospital_channels(self.provider, hospital)
            except ProviderRequestError as exc:
                errors[hospital.hospital_id] = str(exc)
        self.finished.emit(results, errors)


class ChannelCandidatesDialog(QtWidgets.QDialog):
    def __init__(self, repository: Repository, provider: object, hospitals: list[Hospital], target_dir,
                 *, batch: bool = False, parent=None):
        super().__init__(parent)
        self.repository = repository
        self.provider = provider
        self.hospitals = hospitals
        self.target_dir = target_dir
        self.batch = batch
        self.cancel_event = Event()
        self._worker_thread: QtCore.QThread | None = None
        self._close_when_finished = False
        self.service = ChannelDiscoveryService(repository)
        self.setWindowTitle("온라인 채널 후보 승인")
        self.resize(900, 480)
        layout = QtWidgets.QVBoxLayout(self)
        self.hospital_combo = QtWidgets.QComboBox()
        for hospital in hospitals:
            self.hospital_combo.addItem(f"{hospital.hospital_name} ({hospital.region or '지역 미상'})", hospital.hospital_id)
        layout.addWidget(self.hospital_combo)
        controls = QtWidgets.QHBoxLayout()
        self.find_button = QtWidgets.QPushButton("채널 찾기")
        self.find_button.clicked.connect(self._start_discovery)
        controls.addWidget(self.find_button)
        self.progress = QtWidgets.QProgressBar()
        self.progress.setVisible(False)
        controls.addWidget(self.progress)
        self.cancel_button = QtWidgets.QPushButton("취소")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel_discovery)
        controls.addWidget(self.cancel_button)
        layout.addLayout(controls)
        self.status_label = QtWidgets.QLabel("AI가 찾은 링크는 후보로만 저장됩니다. 승인한 링크만 채널로 등록됩니다.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["채널", "이름", "링크", "근거", "확신도", "상태", "처리"])
        self.table.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        self.hospital_combo.currentIndexChanged.connect(self._reload_candidates)
        self.table.cellDoubleClicked.connect(self._open_link)
        self._reload_candidates()

    def _hospital_id(self) -> str:
        return str(self.hospital_combo.currentData())

    def _reload_candidates(self) -> None:
        candidates = self.service.list_candidates(self._hospital_id())
        self.table.setRowCount(len(candidates))
        for row, candidate in enumerate(candidates):
            values = [candidate.platform, candidate.channel_name, candidate.url, candidate.evidence,
                      f"{candidate.confidence:.0%}", candidate.status]
            for column, value in enumerate(values):
                item = QtWidgets.QTableWidgetItem(value)
                if column == 2:
                    item.setForeground(QtGui.QColor("#245c9e"))
                    item.setToolTip("더블 클릭하여 브라우저에서 열기")
                self.table.setItem(row, column, item)
            approve = QtWidgets.QPushButton("승인")
            reject = QtWidgets.QPushButton("거절")
            action = QtWidgets.QWidget()
            buttons = QtWidgets.QHBoxLayout(action)
            buttons.setContentsMargins(0, 0, 0, 0)
            buttons.addWidget(approve)
            buttons.addWidget(reject)
            if candidate.status != "pending":
                approve.setEnabled(False)
                reject.setEnabled(False)
            approve.clicked.connect(lambda _checked=False, cid=candidate.id: self._approve(cid))
            reject.clicked.connect(lambda _checked=False, cid=candidate.id: self._reject(cid))
            self.table.setCellWidget(row, 6, action)


    def _open_link(self, row: int, column: int) -> None:
        item = self.table.item(row, column)
        if column == 2 and item is not None:
            QtGui.QDesktopServices.openUrl(QtCore.QUrl(item.text()))

    def _approve(self, candidate_id: int) -> None:
        self.service.approve(candidate_id)
        try:
            generate_outputs(self.repository, self.target_dir, MockProvider())
        except OSError:
            self.status_label.setText("채널은 등록했지만 결과물 갱신에 실패했습니다. 결과 저장 폴더와 권한을 확인해 주세요.")
            self._reload_candidates()
            return
        self._reload_candidates()
        self.status_label.setText("승인한 채널을 등록하고 대시보드·위키·엑셀 결과물을 갱신했습니다.")

    def _reject(self, candidate_id: int) -> None:
        self.service.reject(candidate_id)
        self._reload_candidates()

    def _start_discovery(self) -> None:
        self.cancel_event.clear()
        self.find_button.setEnabled(False)
        self.hospital_combo.setEnabled(False)
        self.cancel_button.setEnabled(True)
        selected_id = self._hospital_id()
        discovery_hospitals = self.hospitals if self.batch else [
            hospital for hospital in self.hospitals if hospital.hospital_id == selected_id
        ]
        if not discovery_hospitals:
            self.find_button.setEnabled(True)
            self.hospital_combo.setEnabled(True)
            self.cancel_button.setEnabled(False)
            self.status_label.setText("검색할 병원이 없습니다.")
            return
        self.progress.setRange(0, len(discovery_hospitals))
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self._worker_thread = QtCore.QThread(self)
        self.worker = _DiscoveryWorker(self.provider, discovery_hospitals, self.cancel_event)
        self.worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(self.worker.run)
        self.worker.progress.connect(self._set_progress)
        self.worker.finished.connect(self._discovery_finished)
        self.worker.finished.connect(self._worker_thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self._worker_thread.finished.connect(self._worker_thread.deleteLater)
        self._worker_thread.start()

    def _set_progress(self, current: int, total: int, name: str) -> None:
        self.progress.setMaximum(total)
        self.progress.setValue(current - 1)
        self.status_label.setText(f"채널 검색 중 {current}/{total}: {name}")

    def _cancel_discovery(self) -> None:
        self.cancel_event.set()
        self.cancel_button.setEnabled(False)
        self.status_label.setText("현재 병원 검색이 끝난 뒤 취소됩니다.")

    @QtCore.Slot(object, object)
    def _discovery_finished(self, results: dict, errors: dict) -> None:
        count = 0
        for hospital_id, candidates in results.items():
            count += len(self.service.save_candidates(hospital_id, candidates))
        self.find_button.setEnabled(True)
        self.hospital_combo.setEnabled(True)
        self.cancel_button.setEnabled(False)
        self.progress.setVisible(False)
        messages = [f"후보 {count}개를 저장했습니다."]
        messages.extend(errors.values())
        if self.cancel_event.is_set():
            messages.append("검색을 취소했습니다.")
        self.status_label.setText("\n".join(messages))
        self._reload_candidates()
        if self._close_when_finished:
            self.accept()

    def closeEvent(self, event) -> None:
        if self._worker_thread and self._worker_thread.isRunning():
            self.cancel_event.set()
            self._close_when_finished = True
            event.ignore()
            return
        super().closeEvent(event)
