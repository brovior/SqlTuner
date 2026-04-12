"""
SQL 직접 실행 결과 탭 위젯

- 상단: 실행 버튼 + 최대 행 수 선택 + 결과 요약 라벨
- 하단: 결과 테이블
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QComboBox, QHeaderView, QAbstractItemView,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor


class ResultTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── 상단 컨트롤 행 ──────────────────────────
        ctrl = QHBoxLayout()

        self._btn_run = QPushButton('SQL 직접 실행  (Ctrl+Shift+Enter)')
        self._btn_run.setFixedHeight(28)
        self._btn_run.setEnabled(False)

        ctrl.addWidget(self._btn_run)

        ctrl.addWidget(QLabel('최대 행 수:'))
        self._combo_rows = QComboBox()
        self._combo_rows.addItems(['100', '300', '500', '1000', '2000'])
        self._combo_rows.setCurrentIndex(2)  # 기본 500
        self._combo_rows.setFixedWidth(70)
        ctrl.addWidget(self._combo_rows)

        ctrl.addStretch()

        self._label = QLabel('SELECT / WITH 문만 실행할 수 있습니다.')
        self._label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        ctrl.addWidget(self._label)

        layout.addLayout(ctrl)

        # ── 결과 테이블 ─────────────────────────────
        self._table = QTableWidget(0, 0)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.horizontalHeader().setStretchLastSection(True)

        layout.addWidget(self._table)

        self._current_sql: str = ''

    # ── 외부 인터페이스 ──────────────────────────────

    def set_sql(self, sql: str):
        """분석할 SQL을 설정하고 실행 버튼을 활성화합니다."""
        self._current_sql = sql
        first_word = sql.strip().upper().split()[0] if sql.strip() else ''
        is_select = first_word in ('SELECT', 'WITH')
        self._btn_run.setEnabled(is_select)
        if not is_select and sql:
            self._label.setText('SELECT / WITH 문만 실행 가능합니다.')

    def clear(self):
        self._table.setRowCount(0)
        self._table.setColumnCount(0)
        self._btn_run.setEnabled(False)
        self._label.setText('SELECT / WITH 문만 실행할 수 있습니다.')
        self._current_sql = ''

    @property
    def run_button(self) -> QPushButton:
        return self._btn_run

    @property
    def max_rows(self) -> int:
        return int(self._combo_rows.currentText())

    # ── 결과 표시 ────────────────────────────────────

    def show_running(self):
        self._btn_run.setEnabled(False)
        self._label.setText('실행 중...')
        self._table.setRowCount(0)
        self._table.setColumnCount(0)

    def show_result(
        self,
        columns: list[str],
        rows: list[tuple],
        elapsed_ms: float,
        fetched: int,
    ):
        self._table.setColumnCount(len(columns))
        self._table.setHorizontalHeaderLabels(columns)
        self._table.setRowCount(fetched)

        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                text = '' if val is None else str(val)
                item = QTableWidgetItem(text)
                if val is None:
                    item.setForeground(QColor('#999999'))
                    item.setText('(null)')
                self._table.setItem(r, c, item)

        capped = f' (최대 {fetched}행까지만 표시)' if fetched == self.max_rows else ''
        self._label.setText(
            f'{fetched:,}행 반환  |  실행시간 {elapsed_ms:.1f} ms{capped}'
        )
        self._btn_run.setEnabled(True)

    def show_error(self, msg: str):
        self._label.setText(f'오류: {msg}')
        self._btn_run.setEnabled(True)
