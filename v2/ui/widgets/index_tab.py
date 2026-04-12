"""
인덱스 어드바이저 탭 위젯

상단 — 현재 인덱스 목록 (IndexInfo)
하단 — 누락 인덱스 개선 제안 (IndexAdvice) + DDL 복사 버튼
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem,
    QLabel, QHeaderView, QAbstractItemView,
    QPushButton, QSplitter, QGroupBox,
    QApplication,
)
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtCore import Qt


_SEVERITY_COLORS = {
    'HIGH':   ('#CC0000', '#FFE0E0'),
    'MEDIUM': ('#CC6600', '#FFF3E0'),
    'INFO':   ('#005599', '#E8F4FF'),
}

_PLACEHOLDER_STYLE = (
    'color: #888888; font-size: 13px; '
    'padding: 20px; background: #F8F8F8; border: 1px solid #DDDDDD;'
)


class IndexTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── 플레이스홀더 (DB 미연결 / 분석 전) ──────────────
        self._placeholder = QLabel('DB 연결 후 실행 계획 분석 시 인덱스 정보가 표시됩니다.')
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet(_PLACEHOLDER_STYLE)
        layout.addWidget(self._placeholder)

        # ── 데이터 영역 (분석 완료 후 표시) ─────────────────
        self._content = QWidget()
        content_layout = QVBoxLayout(self._content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(4)

        splitter = QSplitter(Qt.Vertical)

        # 현재 인덱스 그룹
        idx_group = QGroupBox('현재 인덱스 목록')
        idx_vbox = QVBoxLayout(idx_group)
        idx_vbox.setContentsMargins(4, 4, 4, 4)

        self._idx_table = QTableWidget(0, 5)
        self._idx_table.setHorizontalHeaderLabels(
            ['테이블', '인덱스명', '컬럼 (순서)', '유형', '상태']
        )
        self._idx_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._idx_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._idx_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._idx_table.setAlternatingRowColors(True)
        self._idx_table.verticalHeader().setVisible(False)
        idx_vbox.addWidget(self._idx_table)
        splitter.addWidget(idx_group)

        # 개선 제안 그룹
        adv_group = QGroupBox('누락 인덱스 개선 제안')
        adv_vbox = QVBoxLayout(adv_group)
        adv_vbox.setContentsMargins(4, 4, 4, 4)
        adv_vbox.setSpacing(4)

        self._adv_table = QTableWidget(0, 4)
        self._adv_table.setHorizontalHeaderLabels(
            ['심각도', '테이블', '누락 컬럼', '추천 DDL']
        )
        self._adv_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._adv_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._adv_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._adv_table.setAlternatingRowColors(True)
        self._adv_table.verticalHeader().setVisible(False)
        self._adv_table.itemSelectionChanged.connect(self._on_advice_selected)
        adv_vbox.addWidget(self._adv_table)

        # DDL 복사 버튼 행
        btn_row = QHBoxLayout()
        self._btn_copy_selected = QPushButton('선택 DDL 복사')
        self._btn_copy_selected.setFixedHeight(28)
        self._btn_copy_selected.setEnabled(False)
        self._btn_copy_selected.clicked.connect(self._copy_selected_ddl)

        self._btn_copy_all = QPushButton('전체 DDL 복사')
        self._btn_copy_all.setFixedHeight(28)
        self._btn_copy_all.setEnabled(False)
        self._btn_copy_all.clicked.connect(self._copy_all_ddl)

        btn_row.addStretch()
        btn_row.addWidget(self._btn_copy_selected)
        btn_row.addWidget(self._btn_copy_all)
        adv_vbox.addLayout(btn_row)

        splitter.addWidget(adv_group)
        splitter.setSizes([200, 200])
        content_layout.addWidget(splitter)

        layout.addWidget(self._content)
        self._content.hide()

        # 내부 상태
        self._advices: list = []

    # ── Public API ───────────────────────────────────────────────────────────

    def populate(self, index_infos: list, index_advices: list) -> None:
        """분석 완료 후 IndexInfo / IndexAdvice 목록을 채웁니다."""
        self._advices = index_advices

        self._fill_index_table(index_infos)
        self._fill_advice_table(index_advices)

        self._btn_copy_all.setEnabled(bool(index_advices))
        self._btn_copy_selected.setEnabled(False)

        self._placeholder.hide()
        self._content.show()

    def clear(self) -> None:
        """탭 초기화 (분석 시작 전 / 연결 해제 시 호출)."""
        self._advices = []
        self._idx_table.setRowCount(0)
        self._adv_table.setRowCount(0)
        self._btn_copy_selected.setEnabled(False)
        self._btn_copy_all.setEnabled(False)
        self._content.hide()
        self._placeholder.show()

    # ── 내부: 테이블 채우기 ──────────────────────────────────────────────────

    def _fill_index_table(self, index_infos: list) -> None:
        self._idx_table.setRowCount(len(index_infos))
        for row, info in enumerate(index_infos):
            col_str = ', '.join(info.columns)
            status = info.status
            for col, text in enumerate([
                info.table_name,
                info.index_name,
                col_str,
                info.uniqueness,
                status,
            ]):
                item = QTableWidgetItem(text)
                # UNUSABLE 인덱스는 회색 표시
                if status.upper() == 'UNUSABLE':
                    item.setForeground(QColor('#999999'))
                    item.setBackground(QColor('#F4F4F4'))
                self._idx_table.setItem(row, col, item)
        self._idx_table.resizeColumnsToContents()
        self._idx_table.resizeRowsToContents()

    def _fill_advice_table(self, index_advices: list) -> None:
        self._adv_table.setRowCount(len(index_advices))
        for row, adv in enumerate(index_advices):
            fg, bg = _SEVERITY_COLORS.get(adv.severity, ('#000000', '#FFFFFF'))
            for col, text in enumerate([
                adv.severity,
                adv.table_name,
                ', '.join(adv.missing_columns),
                adv.suggested_ddl,
            ]):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(fg))
                item.setBackground(QColor(bg))
                item.setToolTip(adv.reason)
                self._adv_table.setItem(row, col, item)
        self._adv_table.resizeColumnsToContents()
        self._adv_table.resizeRowsToContents()

    # ── 내부: DDL 복사 ────────────────────────────────────────────────────────

    def _on_advice_selected(self) -> None:
        has_selection = self._adv_table.currentRow() >= 0
        self._btn_copy_selected.setEnabled(has_selection)

    def _copy_selected_ddl(self) -> None:
        row = self._adv_table.currentRow()
        if row < 0 or row >= len(self._advices):
            return
        ddl = self._advices[row].suggested_ddl
        QApplication.clipboard().setText(ddl)

    def _copy_all_ddl(self) -> None:
        ddls = '\n'.join(adv.suggested_ddl for adv in self._advices)
        QApplication.clipboard().setText(ddls)
