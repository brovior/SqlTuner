"""
SQL 편집기 위젯 + SQL 구문 강조
"""
from __future__ import annotations
import re

from PyQt5.QtWidgets import QPlainTextEdit
from PyQt5.QtGui import QFont, QColor, QTextCharFormat, QSyntaxHighlighter


class SqlHighlighter(QSyntaxHighlighter):
    KEYWORDS = [
        'SELECT', 'FROM', 'WHERE', 'JOIN', 'INNER', 'LEFT', 'RIGHT', 'OUTER',
        'FULL', 'ON', 'AND', 'OR', 'NOT', 'IN', 'EXISTS', 'BETWEEN', 'LIKE',
        'IS', 'NULL', 'GROUP', 'BY', 'ORDER', 'HAVING', 'DISTINCT', 'AS',
        'UNION', 'ALL', 'INSERT', 'UPDATE', 'DELETE', 'SET', 'INTO', 'VALUES',
        'CREATE', 'DROP', 'ALTER', 'TABLE', 'INDEX', 'VIEW', 'WITH',
        'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'ROWNUM', 'ROWID',
    ]

    def __init__(self, document):
        super().__init__(document)
        self._rules: list[tuple] = []

        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor('#0000CC'))
        kw_fmt.setFontWeight(700)
        for kw in self.KEYWORDS:
            self._rules.append((re.compile(rf'\b{kw}\b', re.IGNORECASE), kw_fmt))

        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor('#AA4400'))
        self._rules.append((re.compile(r"'[^']*'"), str_fmt))

        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor('#8800AA'))
        self._rules.append((re.compile(r'\b\d+\b'), num_fmt))

        cmt_fmt = QTextCharFormat()
        cmt_fmt.setForeground(QColor('#006600'))
        cmt_fmt.setFontItalic(True)
        self._rules.append((re.compile(r'--[^\n]*'), cmt_fmt))

    def highlightBlock(self, text: str):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


class SqlEditor(QPlainTextEdit):
    """구문 강조가 내장된 SQL 편집기"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(QFont('Consolas', 11))
        self.setPlaceholderText(
            '-- SQL 문을 입력하세요 (Ctrl+Enter: 실행 계획 분석)\n'
            '-- 예: SELECT * FROM EMP WHERE DEPTNO = 10'
        )
        self._highlighter = SqlHighlighter(self.document())
