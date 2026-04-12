"""
DBMS_XPLAN 텍스트 탭 위젯
"""
from __future__ import annotations

from PyQt5.QtWidgets import QPlainTextEdit
from PyQt5.QtGui import QFont


class XplanTab(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont('Consolas', 10))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)

    def populate(self, text: str):
        self.setPlainText(text)
