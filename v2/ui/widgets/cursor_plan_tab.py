"""
실제 플랜 탭 위젯

예상 플랜(DBMS_XPLAN.DISPLAY)과 실제 플랜(DBMS_XPLAN.DISPLAY_CURSOR)을
QSplitter로 나란히 표시합니다.

사용 흐름:
  1. 분석 완료 → set_estimated(xplan_text) 호출 → 좌측 갱신
  2. SQL 실행 완료 → populate_actual(cursor_text) 호출 → 우측 갱신
  3. 결과 초기화 → clear() 호출
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QPlainTextEdit, QSplitter,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont

_PLACEHOLDER_ESTIMATED = '실행 계획 분석을 먼저 실행하세요.\n(Ctrl+Enter)'
_PLACEHOLDER_ACTUAL    = 'SQL을 직접 실행하면 실제 플랜이 표시됩니다.\n(Ctrl+Shift+Enter)'

_FONT = QFont('Consolas', 10)


def _make_pane(title: str, placeholder: str) -> tuple[QWidget, QPlainTextEdit]:
    """레이블 + 텍스트 영역으로 구성된 단일 패널을 반환합니다."""
    widget = QWidget()
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(2, 2, 2, 2)
    layout.setSpacing(2)

    label = QLabel(title)
    label.setStyleSheet('font-weight: bold; color: #333333; padding: 2px 0;')
    layout.addWidget(label)

    edit = QPlainTextEdit()
    edit.setReadOnly(True)
    edit.setFont(_FONT)
    edit.setLineWrapMode(QPlainTextEdit.NoWrap)
    edit.setPlaceholderText(placeholder)
    layout.addWidget(edit)

    return widget, edit


class CursorPlanTab(QWidget):
    """예상 플랜 / 실제 플랜 비교 탭."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(0)

        splitter = QSplitter(Qt.Horizontal)

        left_widget,  self._estimated_edit = _make_pane(
            '예상 플랜  (DBMS_XPLAN.DISPLAY)', _PLACEHOLDER_ESTIMATED
        )
        right_widget, self._actual_edit = _make_pane(
            '실제 플랜  (DBMS_XPLAN.DISPLAY_CURSOR)', _PLACEHOLDER_ACTUAL
        )

        splitter.addWidget(left_widget)
        splitter.addWidget(right_widget)
        splitter.setSizes([1, 1])   # 50:50 비율

        layout.addWidget(splitter)

    # ── 외부 인터페이스 ──────────────────────────

    def set_estimated(self, xplan_text: str):
        """EXPLAIN PLAN 완료 후 예상 플랜 텍스트를 설정합니다."""
        self._estimated_edit.setPlainText(xplan_text)

    def populate_actual(self, cursor_text: str):
        """SQL 직접 실행 완료 후 실제 플랜 텍스트를 설정합니다."""
        self._actual_edit.setPlainText(cursor_text)

    def clear(self):
        self._estimated_edit.clear()
        self._actual_edit.clear()
