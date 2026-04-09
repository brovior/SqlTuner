"""
메인 윈도우 - SQL Tuner 어플리케이션 메인 화면
"""
from __future__ import annotations
import re
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTextEdit, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel,
    QStatusBar, QToolBar, QMessageBox, QHeaderView,
    QPlainTextEdit, QGroupBox, QFrame
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import (
    QFont, QColor, QTextCharFormat, QSyntaxHighlighter,
    QAction, QIcon, QPalette
)

from core.oracle_client import OracleClient, PlanRow
from core.plan_analyzer import PlanAnalyzer, SEVERITY_HIGH, SEVERITY_MEDIUM
from core.tuning_rules import SqlTextAnalyzer
from ui.connection_dialog import ConnectionDialog


# ─────────────────────────────────────────────
# SQL 구문 강조 (Syntax Highlighter)
# ─────────────────────────────────────────────
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
        self._rules = []

        # 키워드 (파란색)
        kw_fmt = QTextCharFormat()
        kw_fmt.setForeground(QColor('#0000CC'))
        kw_fmt.setFontWeight(700)
        for kw in self.KEYWORDS:
            self._rules.append((re.compile(rf'\b{kw}\b', re.IGNORECASE), kw_fmt))

        # 문자열 리터럴 (갈색)
        str_fmt = QTextCharFormat()
        str_fmt.setForeground(QColor('#AA4400'))
        self._rules.append((re.compile(r"'[^']*'"), str_fmt))

        # 숫자 (보라색)
        num_fmt = QTextCharFormat()
        num_fmt.setForeground(QColor('#8800AA'))
        self._rules.append((re.compile(r'\b\d+\b'), num_fmt))

        # 주석 (녹색)
        cmt_fmt = QTextCharFormat()
        cmt_fmt.setForeground(QColor('#006600'))
        cmt_fmt.setFontItalic(True)
        self._rules.append((re.compile(r'--[^\n]*'), cmt_fmt))

    def highlightBlock(self, text):
        for pattern, fmt in self._rules:
            for m in pattern.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


# ─────────────────────────────────────────────
# 백그라운드 실행 스레드
# ─────────────────────────────────────────────
class PlanWorker(QThread):
    finished = pyqtSignal(list, str, list, list)   # plan_rows, xplan_text, sql_issues, plan_issues
    error = pyqtSignal(str)

    def __init__(self, client: OracleClient, sql: str):
        super().__init__()
        self._client = client
        self._sql = sql

    def run(self):
        try:
            # EXPLAIN PLAN 1회 실행으로 PlanRow + DBMS_XPLAN 텍스트 동시 획득
            plan_rows, xplan_text = self._client.explain_plan(self._sql)

            analyzer = PlanAnalyzer(plan_rows)
            analyzer.build_tree()
            plan_issues = analyzer.analyze()

            sql_analyzer = SqlTextAnalyzer()
            sql_issues = sql_analyzer.analyze(self._sql)

            self.finished.emit(plan_rows, xplan_text, sql_issues, plan_issues)
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────
# 메인 윈도우
# ─────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._client = OracleClient()
        self._worker: PlanWorker | None = None

        self.setWindowTitle('Oracle SQL Tuner')
        self.setMinimumSize(1200, 750)

        self._build_ui()
        self._build_toolbar()
        self._build_statusbar()
        self._update_connection_status()

    # ── UI 구성 ─────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # 상단: SQL 편집기
        editor_group = QGroupBox('SQL 입력')
        editor_layout = QVBoxLayout(editor_group)
        editor_layout.setContentsMargins(4, 4, 4, 4)

        self._sql_editor = QPlainTextEdit()
        self._sql_editor.setFont(QFont('Consolas', 11))
        self._sql_editor.setPlaceholderText(
            '-- SQL 문을 입력하세요 (Ctrl+Enter: 실행 계획 분석)\n'
            '-- 예: SELECT * FROM EMP WHERE DEPTNO = 10'
        )
        self._highlighter = SqlHighlighter(self._sql_editor.document())
        editor_layout.addWidget(self._sql_editor)

        # SQL 편집기 하단 버튼
        editor_btn_layout = QHBoxLayout()
        self._btn_analyze = QPushButton('실행 계획 분석  (Ctrl+Enter)')
        self._btn_analyze.setFixedHeight(32)
        self._btn_analyze.setEnabled(False)
        self._btn_analyze.clicked.connect(self._run_analysis)

        btn_clear = QPushButton('지우기')
        btn_clear.setFixedHeight(32)
        btn_clear.setFixedWidth(80)
        btn_clear.clicked.connect(self._sql_editor.clear)

        editor_btn_layout.addWidget(self._btn_analyze)
        editor_btn_layout.addWidget(btn_clear)
        editor_layout.addLayout(editor_btn_layout)

        splitter.addWidget(editor_group)

        # 하단: 결과 탭
        self._result_tabs = QTabWidget()
        self._build_plan_tree_tab()
        self._build_xplan_tab()
        self._build_issues_tab()
        self._build_stats_tab()
        splitter.addWidget(self._result_tabs)

        splitter.setSizes([320, 480])
        main_layout.addWidget(splitter)

        # 단축키 (툴바 action_run에 이미 Ctrl+Return 등록됨 — QShortcut 중복 제거)

    def _build_plan_tree_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        self._plan_tree = QTreeWidget()
        self._plan_tree.setHeaderLabels([
            'ID', 'Operation', '테이블/인덱스', 'Cost', '예측 행수', 'Bytes'
        ])
        self._plan_tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._plan_tree.setAlternatingRowColors(True)
        self._plan_tree.setFont(QFont('Consolas', 10))

        layout.addWidget(self._plan_tree)
        self._result_tabs.addTab(widget, 'Plan Tree')

    def _build_xplan_tab(self):
        self._xplan_text = QPlainTextEdit()
        self._xplan_text.setReadOnly(True)
        self._xplan_text.setFont(QFont('Consolas', 10))
        self._xplan_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._result_tabs.addTab(self._xplan_text, 'DBMS_XPLAN')

    def _build_issues_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        self._issues_table = QTableWidget(0, 4)
        self._issues_table.setHorizontalHeaderLabels(['심각도', '분류', '제목', '설명'])
        self._issues_table.horizontalHeader().setSectionResizeMode(
            3, QHeaderView.ResizeMode.Stretch
        )
        self._issues_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._issues_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._issues_table.setAlternatingRowColors(True)
        self._issues_table.verticalHeader().setVisible(False)
        self._issues_table.itemSelectionChanged.connect(self._on_issue_selected)

        self._issue_detail = QTextEdit()
        self._issue_detail.setReadOnly(True)
        self._issue_detail.setMaximumHeight(180)
        self._issue_detail.setFont(QFont('Consolas', 10))

        layout.addWidget(self._issues_table, 2)
        layout.addWidget(QLabel('상세 설명 / 개선 제안:'))
        layout.addWidget(self._issue_detail, 1)

        self._result_tabs.addTab(widget, '튜닝 제안')

    def _build_stats_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)

        self._stats_label = QLabel('V$SQL 통계는 실제 실행 이력을 조회합니다. 버튼을 눌러 수동으로 조회하세요.')
        self._stats_label.setWordWrap(True)

        # 수동 조회 버튼 (자동 조회 제거 — V$SQL 전체 스캔 부하 방지)
        self._btn_load_stats = QPushButton('V$SQL 통계 조회')
        self._btn_load_stats.setFixedHeight(28)
        self._btn_load_stats.setEnabled(False)
        self._btn_load_stats.clicked.connect(self._on_load_stats_clicked)

        self._stats_table = QTableWidget(0, 8)
        self._stats_table.setHorizontalHeaderLabels([
            'SQL_ID', '실행횟수', '총시간(ms)', 'CPU(ms)',
            'Buffer Gets', 'Disk Reads', '처리행수', 'Parse호출'
        ])
        self._stats_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )
        self._stats_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._stats_table.setAlternatingRowColors(True)
        self._stats_table.verticalHeader().setVisible(False)

        layout.addWidget(self._stats_label)
        layout.addWidget(self._btn_load_stats)
        layout.addWidget(self._stats_table)
        self._result_tabs.addTab(widget, 'V$SQL 통계')

    def _build_toolbar(self):
        toolbar = QToolBar('메인')
        toolbar.setMovable(False)
        toolbar.setIconSize(QSize(20, 20))
        self.addToolBar(toolbar)

        # 연결 버튼
        self._action_connect = QAction('DB 연결', self)
        self._action_connect.setToolTip('Oracle DB에 연결합니다')
        self._action_connect.triggered.connect(self._on_connect)
        toolbar.addAction(self._action_connect)

        self._action_disconnect = QAction('연결 해제', self)
        self._action_disconnect.triggered.connect(self._on_disconnect)
        self._action_disconnect.setEnabled(False)
        toolbar.addAction(self._action_disconnect)

        toolbar.addSeparator()

        # 분석 버튼
        action_run = QAction('실행 계획 분석', self)
        action_run.setShortcut('Ctrl+Return')
        action_run.triggered.connect(self._run_analysis)
        toolbar.addAction(action_run)

        toolbar.addSeparator()

        # 연결 상태 표시
        self._conn_label = QLabel('  미연결')
        self._conn_label.setStyleSheet('color: #888888; font-weight: bold;')
        toolbar.addWidget(self._conn_label)

    def _build_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage('Oracle SQL Tuner 준비됨')

    # ── 연결 처리 ────────────────────────────────

    def _on_connect(self):
        dlg = ConnectionDialog(self)
        if dlg.exec() != ConnectionDialog.DialogCode.Accepted:
            return

        conn_info = dlg.connection_info
        self._statusbar.showMessage(f'연결 중: {conn_info.tns_alias}...')

        try:
            self._client.connect(conn_info)
            self._update_connection_status()
            self._statusbar.showMessage(
                f'연결 성공: {self._client.current_connection_label}', 5000
            )
        except (RuntimeError, ConnectionError) as e:
            QMessageBox.critical(self, 'DB 연결 실패', str(e))
            self._statusbar.showMessage('연결 실패', 3000)

    def _on_disconnect(self):
        self._client.disconnect()
        self._update_connection_status()
        self._statusbar.showMessage('연결 해제됨', 3000)

    def _update_connection_status(self):
        connected = self._client.is_connected
        self._btn_analyze.setEnabled(connected)
        self._action_connect.setEnabled(not connected)
        self._action_disconnect.setEnabled(connected)

        if connected:
            label = self._client.current_connection_label
            self._conn_label.setText(f'  연결됨: {label}')
            self._conn_label.setStyleSheet('color: #006600; font-weight: bold;')
            self.setWindowTitle(f'Oracle SQL Tuner  [{label}]')
        else:
            self._conn_label.setText('  미연결')
            self._conn_label.setStyleSheet('color: #888888; font-weight: bold;')
            self.setWindowTitle('Oracle SQL Tuner')

    # ── 분석 실행 ────────────────────────────────

    def _run_analysis(self):
        if not self._client.is_connected:
            QMessageBox.warning(self, '연결 필요', 'DB에 먼저 연결하세요.')
            return

        sql = self._sql_editor.toPlainText().strip()
        if not sql:
            QMessageBox.warning(self, '입력 필요', 'SQL을 입력하세요.')
            return

        # 세미콜론 제거
        if sql.endswith(';'):
            sql = sql[:-1].strip()

        self._btn_analyze.setEnabled(False)
        self._statusbar.showMessage('실행 계획 분석 중...')
        self._clear_results()

        self._worker = PlanWorker(self._client, sql)
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.start()

    def _clear_results(self):
        self._plan_tree.clear()
        self._xplan_text.clear()
        self._issues_table.setRowCount(0)
        self._issue_detail.clear()
        self._stats_table.setRowCount(0)
        self._btn_load_stats.setEnabled(False)

    def _on_analysis_done(
        self,
        plan_rows: list[PlanRow],
        xplan_text: str,
        sql_issues: list,
        plan_issues: list
    ):
        self._btn_analyze.setEnabled(True)

        # Plan Tree 탭
        self._populate_plan_tree(plan_rows)

        # DBMS_XPLAN 탭
        self._xplan_text.setPlainText(xplan_text)

        # 튜닝 이슈 탭
        all_issues = sql_issues + plan_issues
        self._populate_issues(all_issues)

        # V$SQL 통계 버튼 활성화 (자동 조회 제거 — DB 부하 방지)
        self._btn_load_stats.setEnabled(True)
        self._stats_table.setRowCount(0)
        self._stats_label.setText('V$SQL 통계 조회 버튼을 눌러 실행 이력을 확인하세요.')

        issue_count = len(all_issues)
        high_count = sum(1 for i in all_issues if i.severity == SEVERITY_HIGH)
        self._statusbar.showMessage(
            f'분석 완료 | 이슈 {issue_count}건'
            + (f' (HIGH {high_count}건)' if high_count else '')
        )

        # 이슈가 있으면 튜닝 제안 탭으로 포커스
        if all_issues:
            self._result_tabs.setCurrentIndex(2)

    def _on_analysis_error(self, msg: str):
        self._btn_analyze.setEnabled(True)
        self._statusbar.showMessage('분석 오류', 3000)
        QMessageBox.critical(self, '분석 오류', msg)

    # ── Plan Tree 채우기 ──────────────────────────

    def _populate_plan_tree(self, rows: list[PlanRow]):
        self._plan_tree.clear()
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

            # Full Table Scan → 빨간색
            if row.operation == 'TABLE ACCESS' and row.options == 'FULL':
                for col in range(6):
                    item.setForeground(col, QColor('#CC0000'))
                item.setBackground(0, QColor('#FFF0F0'))
                item.setBackground(1, QColor('#FFF0F0'))

            for child in row.children:
                add_node(item, child)

            item.setExpanded(True)

        for root in roots:
            add_node(self._plan_tree, root)

        self._plan_tree.expandAll()

    # ── 이슈 테이블 채우기 ────────────────────────

    SEVERITY_COLORS = {
        'HIGH':   ('#CC0000', '#FFE0E0'),
        'MEDIUM': ('#CC6600', '#FFF3E0'),
        'LOW':    ('#887700', '#FFFFF0'),
        'INFO':   ('#005599', '#E8F4FF'),
    }

    def _populate_issues(self, issues: list):
        self._issues_table.setRowCount(len(issues))
        self._all_issues = issues

        for i, issue in enumerate(issues):
            fg, bg = self.SEVERITY_COLORS.get(issue.severity, ('#000000', '#FFFFFF'))

            for col, text in enumerate([
                issue.severity, issue.category, issue.title, issue.description.split('\n')[0]
            ]):
                item = QTableWidgetItem(text)
                item.setForeground(QColor(fg))
                item.setBackground(QColor(bg))
                self._issues_table.setItem(i, col, item)

        self._issues_table.resizeRowsToContents()

        if issues:
            self._issues_table.selectRow(0)

    def _on_issue_selected(self):
        rows = self._issues_table.selectedItems()
        if not rows:
            return
        row_idx = self._issues_table.currentRow()
        if not hasattr(self, '_all_issues') or row_idx >= len(self._all_issues):
            return

        issue = self._all_issues[row_idx]
        detail = f"[{issue.severity}] {issue.title}\n\n"
        detail += f"■ 설명\n{issue.description}\n\n"
        detail += f"■ 개선 제안\n{issue.suggestion}"
        if issue.sample_sql:
            detail += f"\n\n■ 예시 SQL\n{issue.sample_sql}"

        self._issue_detail.setPlainText(detail)

    # ── V$SQL 통계 ────────────────────────────────

    def _on_load_stats_clicked(self):
        sql = self._sql_editor.toPlainText().strip()
        if not sql:
            return
        self._btn_load_stats.setEnabled(False)
        self._statusbar.showMessage('V$SQL 통계 조회 중...')
        keyword = ' '.join(sql.split()[:8])
        try:
            stats_list = self._client.get_sql_stats(keyword)
            self._stats_table.setRowCount(len(stats_list))
            for i, s in enumerate(stats_list):
                values = [
                    s.sql_id,
                    str(s.executions),
                    f'{s.elapsed_time_ms:.1f}',
                    f'{s.cpu_time_ms:.1f}',
                    f'{s.buffer_gets:,}',
                    f'{s.disk_reads:,}',
                    f'{s.rows_processed:,}',
                    str(s.parse_calls),
                ]
                for col, val in enumerate(values):
                    self._stats_table.setItem(i, col, QTableWidgetItem(val))
            count = len(stats_list)
            self._stats_label.setText(f'V$SQL 통계 조회 완료 — {count}건')
            self._statusbar.showMessage(f'V$SQL 통계 {count}건 조회 완료', 3000)
        except Exception as e:
            self._stats_label.setText(f'조회 실패: {e}')
            self._statusbar.showMessage('V$SQL 통계 조회 실패', 3000)
        finally:
            self._btn_load_stats.setEnabled(True)

    # ── 종료 시 연결 해제 ─────────────────────────

    def closeEvent(self, event):
        self._client.disconnect()
        event.accept()
