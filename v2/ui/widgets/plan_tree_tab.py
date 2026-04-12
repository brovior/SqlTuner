"""
실행 계획 트리 탭 위젯
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QHeaderView,
)
from PyQt5.QtGui import QFont, QColor

from v2.core.db.oracle_client import PlanRow
from v2.core.db.plan_analyzer import PlanAnalyzer


class PlanTreeTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(['ID', 'Operation', '테이블/인덱스', 'Cost', '예측 행수', 'Bytes'])
        self._tree.header().setSectionResizeMode(1, QHeaderView.Stretch)
        self._tree.setAlternatingRowColors(True)
        self._tree.setFont(QFont('Consolas', 10))
        layout.addWidget(self._tree)

    def populate(self, rows: list[PlanRow]):
        self._tree.clear()
        if not rows:
            return

        analyzer = PlanAnalyzer(rows)
        roots = analyzer.build_tree()

        def add_node(parent_widget, row: PlanRow):
            item = QTreeWidgetItem(parent_widget)
            item.setText(0, str(row.id))
            item.setText(1, '  ' * row.depth + row.full_operation)
            item.setText(2, row.object_name)
            item.setText(3, str(row.cost) if row.cost is not None else '')
            item.setText(4, f'{row.cardinality:,}' if row.cardinality is not None else '')
            item.setText(5, str(row.bytes) if row.bytes is not None else '')

            if row.operation == 'TABLE ACCESS' and row.options == 'FULL':
                for col in range(6):
                    item.setForeground(col, QColor('#CC0000'))
                item.setBackground(0, QColor('#FFF0F0'))
                item.setBackground(1, QColor('#FFF0F0'))

            for child in row.children:
                add_node(item, child)
            item.setExpanded(True)

        for root in roots:
            add_node(self._tree, root)

        self._tree.expandAll()

    def clear(self):
        self._tree.clear()
