from __future__ import annotations

from collections.abc import Sequence

from PySide6 import QtCore, QtWidgets

from ..settings import DEFAULT_PRODUCTS, ProductKeyword


class ProductKeywordsDialog(QtWidgets.QDialog):
    def __init__(self, keywords: Sequence[ProductKeyword], parent=None):
        super().__init__(parent)
        self.setWindowTitle("검색 단어 관리")
        self.setMinimumWidth(420)
        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(QtWidgets.QLabel("콘텐츠 분류에 사용할 제품 검색 단어를 선택하세요."))

        self.keyword_list = QtWidgets.QListWidget(self)
        self.keyword_list.setObjectName("product_keyword_list")
        self.keyword_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.SingleSelection)
        layout.addWidget(self.keyword_list)
        self._set_keywords(keywords)

        actions = QtWidgets.QHBoxLayout()
        self.add_button = QtWidgets.QPushButton("추가")
        self.add_button.setObjectName("add_product_keyword_button")
        self.add_button.clicked.connect(self._add_keyword)
        actions.addWidget(self.add_button)
        self.edit_button = QtWidgets.QPushButton("수정")
        self.edit_button.setObjectName("edit_product_keyword_button")
        self.edit_button.clicked.connect(self._edit_keyword)
        actions.addWidget(self.edit_button)
        self.remove_button = QtWidgets.QPushButton("삭제")
        self.remove_button.setObjectName("remove_product_keyword_button")
        self.remove_button.clicked.connect(self._remove_keyword)
        actions.addWidget(self.remove_button)
        self.restore_button = QtWidgets.QPushButton("기본값으로 되돌리기")
        self.restore_button.setObjectName("restore_product_keywords_button")
        self.restore_button.clicked.connect(self._restore_defaults)
        actions.addWidget(self.restore_button)
        layout.addLayout(actions)

        self.button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Save | QtWidgets.QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def keywords(self) -> tuple[ProductKeyword, ...]:
        result = []
        for index in range(self.keyword_list.count()):
            item = self.keyword_list.item(index)
            result.append(ProductKeyword(item.text(), item.checkState() == QtCore.Qt.CheckState.Checked))
        return tuple(result)

    def _set_keywords(self, keywords: Sequence[ProductKeyword]) -> None:
        self.keyword_list.clear()
        for keyword in keywords:
            item = QtWidgets.QListWidgetItem(keyword.term)
            item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                QtCore.Qt.CheckState.Checked if keyword.enabled else QtCore.Qt.CheckState.Unchecked
            )
            self.keyword_list.addItem(item)

    @staticmethod
    def _normalized_key(term: str) -> str:
        return " ".join(term.split()).casefold()

    def _add_keyword(self) -> None:
        term, accepted = QtWidgets.QInputDialog.getText(self, "검색 단어 추가", "제품 검색 단어")
        if not accepted:
            return
        term = term.strip()
        if not term:
            QtWidgets.QMessageBox.warning(self, "검색 단어 확인", "빈 검색 단어는 추가할 수 없습니다.")
            return
        if any(self._normalized_key(keyword.term) == self._normalized_key(term) for keyword in self.keywords()):
            QtWidgets.QMessageBox.warning(self, "검색 단어 확인", "같은 검색 단어가 이미 있습니다.")
            return
        item = QtWidgets.QListWidgetItem(term)
        item.setFlags(item.flags() | QtCore.Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(QtCore.Qt.CheckState.Checked)
        self.keyword_list.addItem(item)
        self.keyword_list.setCurrentItem(item)

    def _edit_keyword(self) -> None:
        index = self.keyword_list.currentRow()
        if index < 0:
            return
        current = self.keyword_list.item(index)
        term, accepted = QtWidgets.QInputDialog.getText(
            self, "검색 단어 수정", "제품 검색 단어", text=current.text()
        )
        if not accepted:
            return
        term = term.strip()
        if not term:
            QtWidgets.QMessageBox.warning(self, "검색 단어 확인", "빈 검색 단어는 사용할 수 없습니다.")
            return
        for other_index, keyword in enumerate(self.keywords()):
            if other_index != index and self._normalized_key(keyword.term) == self._normalized_key(term):
                QtWidgets.QMessageBox.warning(self, "검색 단어 확인", "같은 검색 단어가 이미 있습니다.")
                return
        current.setText(term)

    def _remove_keyword(self) -> None:
        index = self.keyword_list.currentRow()
        if index >= 0:
            self.keyword_list.takeItem(index)

    def _restore_defaults(self) -> None:
        self._set_keywords(tuple(ProductKeyword(term) for term in DEFAULT_PRODUCTS))
