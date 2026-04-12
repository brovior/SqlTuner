"""
튜닝 이슈 탭 위젯
이슈 목록 테이블 + 상세 설명 패널
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QTextEdit, QLabel, QHeaderView, QAbstractItemView,
)
from PyQt5.QtGui import QFont, QColor


_SEVERITY_COLORS = {
    'HIGH':   ('#CC0000', '#FFE0E0'),
    'MEDIUM': ('#CC6600', '#FFF3E0'),
    'LOW':    ('#887700', '#FFFFF0'),
    'INFO':   ('#005599', '#E8F4FF'),
}


class IssuesTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(['심각도', '분류', '제목', '설명'])
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        self._detail = QTextEdit()
        self._detail.setReadOnly(True)
        self._detail.setMaximumHeight(180)
        self._detail.setFont(QFont('Consolas', 10))

        layout.addWidget(self._table, 2)
        layout.addWidget(QLabel('상세 설명 / 개선 제안:'))
        layout.addWidget(self._detail, 1)

        self._issues: list = []

    def populate(self, issues: list):
        self._issues = issues
        self._table.setRowCount(len(issues))

        for i, issue in enumerate(issues):
            fg, bg = _SEVERITY_COLORS.get(issue.severity, ('#000000', '#FFFFFF'))
            for col, text in enumerate([
                issue.severity,
                issue.category,
                issue.title,
                issue.description.split('\n')[0],
            ]):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(fg))
                item.setBackground(QColor(bg))
                self._table.setItem(i, col, item)

        self._table.resizeRowsToContents()
        if issues:
            self._table.selectRow(0)

    def clear(self):
        self._issues = []
        self._table.setRowCount(0)
        self._detail.clear()

    def _on_selection_changed(self):
        row_idx = self._table.currentRow()
        if row_idx < 0 or row_idx >= len(self._issues):
            return
        issue = self._issues[row_idx]
        detail = f'[{issue.severity}] {issue.title}\n\n'
        detail += f'■ 설명\n{issue.description}\n\n'
        detail += f'■ 개선 제안\n{issue.suggestion}'
        if getattr(issue, 'sample_sql', ''):
            detail += f'\n\n■ 예시 SQL\n{issue.sample_sql}'
        self._detail.setPlainText(detail)
