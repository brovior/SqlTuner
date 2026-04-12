"""
리소스 분석 탭 위젯

SQL 실행 계획 분석 후 ResourceAnalysis 결과를 표시한다.

조회 방법 우선순위:
  1. V$SESSION_WAIT  — 실시간 Wait Event
  2. V$SQL 통계      — DISK_READS / BUFFER_GETS 등
  3. V$MYSTAT 차이   — 분석 전후 세션 통계 차이

어떤 방법으로 조회됐는지 탭 상단에 레이블로 표시하고,
상위 방법이 실패한 경우 그 원인도 함께 표시한다.
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QLabel, QHeaderView, QAbstractItemView, QFrame,
)
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtCore import Qt


_SEVERITY_COLORS = {
    'HIGH':   ('#CC0000', '#FFE0E0'),
    'MEDIUM': ('#CC6600', '#FFF3E0'),
    'LOW':    ('#887700', '#FFFFF0'),
    'INFO':   ('#005599', '#E8F4FF'),
}

_METHOD_STYLES = {
    'V$SESSION_WAIT 기준': ('color:#004400; background:#E8FFE8; border:1px solid #66AA66;'),
    'V$SQL 통계 기준':      ('color:#003366; background:#E8F0FF; border:1px solid #6688AA;'),
    'V$MYSTAT 차이 기준':   ('color:#444400; background:#FFFFF0; border:1px solid #AAAA44;'),
    '조회 불가':            ('color:#880000; background:#FFE8E8; border:1px solid #AA6666;'),
}
_DEFAULT_METHOD_STYLE = 'color:#444444; background:#F4F4F4; border:1px solid #CCCCCC;'

_COLUMNS = ['심각도', '분류', '항목', '값']


class WaitEventTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 조회 방법 레이블
        self._method_label = QLabel('실행 계획 분석 후 리소스 분석 결과가 표시됩니다.')
        self._method_label.setStyleSheet(
            'color:#888888; padding:5px 8px; border-radius:3px;'
        )
        self._method_label.setWordWrap(True)
        layout.addWidget(self._method_label)

        # 폴백 원인 레이블 (상위 방법 실패 시에만 표시)
        self._fallback_label = QLabel()
        self._fallback_label.setStyleSheet(
            'color:#885500; background:#FFF8E0; padding:4px 8px; '
            'border:1px solid #DDBB44; border-radius:3px; font-size:10px;'
        )
        self._fallback_label.setWordWrap(True)
        self._fallback_label.hide()
        layout.addWidget(self._fallback_label)

        # 결과 테이블
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.setFont(QFont('Consolas', 10))
        layout.addWidget(self._table)

    # ------------------------------------------------------------------

    def populate(self, resource) -> None:
        """ResourceAnalysis 객체를 받아 테이블을 채운다."""
        self._table.setRowCount(0)
        self._fallback_label.hide()

        method = getattr(resource, 'method', '')
        metrics = getattr(resource, 'metrics', [])
        error_chain = getattr(resource, 'error_chain', [])

        # 조회 방법 레이블 업데이트
        count_str = f'  ({len(metrics)}건)' if metrics else ''
        self._method_label.setText(f'조회 방법: {method}{count_str}')
        style = _METHOD_STYLES.get(method, _DEFAULT_METHOD_STYLE)
        self._method_label.setStyleSheet(
            f'{style} padding:5px 8px; border-radius:3px; font-weight:bold;'
        )

        # 폴백 원인 표시
        if error_chain:
            self._fallback_label.setText(
                '※ 상위 방법 실패로 폴백:\n' + '\n'.join(f'  • {e}' for e in error_chain)
            )
            self._fallback_label.show()

        if not metrics:
            return

        self._table.setRowCount(len(metrics))
        for row, m in enumerate(metrics):
            fg, bg = _SEVERITY_COLORS.get(m.severity, ('#000000', '#FFFFFF'))
            values = [m.severity, m.category, m.name, m.display_value]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(fg))
                item.setBackground(QColor(bg))
                if col == 3:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self._table.setItem(row, col, item)

        self._table.resizeRowsToContents()

    def clear(self) -> None:
        self._table.setRowCount(0)
        self._method_label.setText('실행 계획 분석 후 리소스 분석 결과가 표시됩니다.')
        self._method_label.setStyleSheet('color:#888888; padding:5px 8px; border-radius:3px;')
        self._fallback_label.hide()
