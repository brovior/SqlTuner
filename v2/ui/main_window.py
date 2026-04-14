"""
메인 윈도우 — 조립 전담 (위젯/워커는 각 모듈로 분리)

구성:
  상단 — SqlEditor (SQL 입력)
  하단 — QTabWidget
    0: Plan Tree      (PlanTreeTab)
    1: DBMS_XPLAN     (XplanTab)
    2: 실제 플랜       (CursorPlanTab)
    3: 튜닝 제안       (IssuesTab)
    4: 리소스 분석     (WaitEventTab) — V$SESSION_WAIT / V$SQL / V$MYSTAT 폴백
    5: V$SQL 통계      (StatsTab)
    6: 실행 결과       (ResultTab)
    7: 튜닝된 SQL      (RewriteTab)
"""
from __future__ import annotations
import os
import base64

from PyQt5.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QSplitter, QTabWidget, QGroupBox, QPushButton,
    QToolBar, QStatusBar, QLabel, QMessageBox, QDialog,
    QAction, QComboBox,
)
from PyQt5.QtCore import Qt, QSettings, QSize

from v2.core.db.oracle_client import OracleClient
from v2.core.db.plan_analyzer import PlanIssue
from v2.core.analysis.base import SqlIssue
from v2.core.analysis.hint_advisor import HintAdvisor
from v2.core.ai.ai_provider import AIProviderConfig, create_provider
from v2.core.ai.ai_tuner import AiSqlTuner
from v2.core.app_logger import get_logger, LOG_FILE_PATH

_logger = get_logger('main_window')

from v2.ui.workers.plan_worker import PlanWorker
from v2.ui.workers.execute_worker import ExecuteWorker
from v2.ui.workers.cursor_plan_worker import CursorPlanWorker
from v2.ui.widgets.sql_editor import SqlEditor
from v2.ui.widgets.plan_tree_tab import PlanTreeTab
from v2.ui.widgets.xplan_tab import XplanTab
from v2.ui.widgets.issues_tab import IssuesTab
from v2.ui.widgets.stats_tab import StatsTab
from v2.ui.widgets.rewrite_tab import RewriteTab
from v2.ui.widgets.result_tab import ResultTab
from v2.ui.widgets.cursor_plan_tab import CursorPlanTab
from v2.ui.widgets.wait_event_tab import WaitEventTab
from v2.ui.widgets.index_tab import IndexTab
from v2.ui.dialogs.connection_dialog import ConnectionDialog
from v2.ui.dialogs.ai_settings_dialog import AISettingsDialog
from v2.ui.dialogs.bind_vars_dialog import extract_bind_vars, BindVarsDialog

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config.ini',
)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._client = OracleClient()
        self._worker: PlanWorker | None = None
        self._exec_worker: ExecuteWorker | None = None
        self._cursor_plan_worker: CursorPlanWorker | None = None
        # {sql_key: {변수명: 마지막 입력값}} — 앱 실행 중 메모리 내 유지
        self._bind_cache: dict[str, dict[str, str]] = {}
        self._current_sql: str = ''
        self._current_issues: list = []

        self._has_stats_privilege: bool = False  # DB 연결 시점에 1회 조회

        self._ai_provider = self._load_ai_provider()
        self._ai_tuner = AiSqlTuner(self._ai_provider)

        self.setWindowTitle('Oracle SQL Tuner v2')
        self.setMinimumSize(1200, 750)

        self._build_ui()
        self._build_toolbar()
        self._build_statusbar()
        self._update_connection_ui()

    # ── UI 조립 ─────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        splitter = QSplitter(Qt.Vertical)

        # 상단: SQL 편집기
        editor_group = QGroupBox('SQL 입력')
        editor_vbox = QVBoxLayout(editor_group)
        editor_vbox.setContentsMargins(4, 4, 4, 4)

        self._sql_editor = SqlEditor()
        editor_vbox.addWidget(self._sql_editor)

        btn_row = QHBoxLayout()
        self._btn_analyze = QPushButton('실행 계획 분석  (Ctrl+Enter)')
        self._btn_analyze.setFixedHeight(32)
        self._btn_analyze.setEnabled(False)
        self._btn_analyze.clicked.connect(self._run_analysis)

        self._btn_execute = QPushButton('SQL 직접 실행  (Ctrl+Shift+Enter)')
        self._btn_execute.setFixedHeight(32)
        self._btn_execute.setEnabled(False)
        self._btn_execute.clicked.connect(self._run_execute)

        btn_clear = QPushButton('지우기')
        btn_clear.setFixedHeight(32)
        btn_clear.setFixedWidth(80)
        btn_clear.clicked.connect(self._sql_editor.clear)

        btn_row.addWidget(self._btn_analyze)
        btn_row.addWidget(self._btn_execute)
        btn_row.addWidget(btn_clear)
        editor_vbox.addLayout(btn_row)

        splitter.addWidget(editor_group)

        # 하단: 결과 탭
        self._tabs = QTabWidget()

        self._plan_tree_tab = PlanTreeTab()
        self._xplan_tab = XplanTab()
        self._cursor_plan_tab = CursorPlanTab()
        self._issues_tab = IssuesTab()
        self._stats_tab = StatsTab(self._client)
        self._result_tab = ResultTab()
        self._result_tab.run_button.clicked.connect(self._run_execute)
        self._rewrite_tab = RewriteTab()
        self._rewrite_tab.set_client(self._client)
        self._rewrite_tab.set_tuner(self._ai_tuner)
        self._rewrite_tab.update_ai_provider_label(self._ai_provider.label)

        self._wait_event_tab = WaitEventTab()
        self._index_tab = IndexTab()

        self._tabs.addTab(self._plan_tree_tab,   'Plan Tree')
        self._tabs.addTab(self._xplan_tab,       'DBMS_XPLAN')
        self._tabs.addTab(self._cursor_plan_tab, '실제 플랜')
        self._tabs.addTab(self._issues_tab,      '튜닝 제안')
        self._tabs.addTab(self._index_tab,       '인덱스 분석')
        self._tabs.addTab(self._wait_event_tab,  '리소스 분석')
        self._tabs.addTab(self._stats_tab,       'V$SQL 통계')
        self._tabs.addTab(self._result_tab,      '실행 결과')
        self._tabs.addTab(self._rewrite_tab,     '튜닝된 SQL')

        splitter.addWidget(self._tabs)
        splitter.setSizes([320, 480])
        layout.addWidget(splitter)

    def _build_toolbar(self):
        tb = QToolBar('메인')
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        self.addToolBar(tb)

        self._action_connect = QAction('DB 연결', self)
        self._action_connect.triggered.connect(self._on_connect)
        tb.addAction(self._action_connect)

        self._action_disconnect = QAction('연결 해제', self)
        self._action_disconnect.triggered.connect(self._on_disconnect)
        self._action_disconnect.setEnabled(False)
        tb.addAction(self._action_disconnect)

        tb.addSeparator()

        action_run = QAction('실행 계획 분석', self)
        action_run.setShortcut('Ctrl+Return')
        action_run.triggered.connect(self._run_analysis)
        tb.addAction(action_run)

        action_exec = QAction('SQL 직접 실행', self)
        action_exec.setShortcut('Ctrl+Shift+Return')
        action_exec.triggered.connect(self._run_execute)
        tb.addAction(action_exec)

        tb.addSeparator()

        action_ai_settings = QAction('AI 설정', self)
        action_ai_settings.triggered.connect(self._on_ai_settings)
        tb.addAction(action_ai_settings)

        tb.addSeparator()

        action_log = QAction('로그 보기', self)
        action_log.triggered.connect(self._show_log_viewer)
        tb.addAction(action_log)

        tb.addSeparator()

        self._conn_label = QLabel('  미연결')
        self._conn_label.setStyleSheet('color: #888888; font-weight: bold;')
        tb.addWidget(self._conn_label)

    def _build_statusbar(self):
        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._statusbar.showMessage('Oracle SQL Tuner v2 준비됨')

        # DB 버전 영구 표시 레이블
        self._db_version_label = QLabel()
        self._db_version_label.setStyleSheet('color: #555555; padding-right: 4px;')
        self._statusbar.addPermanentWidget(self._db_version_label)

        # 유저/스키마 영구 표시 레이블 (showMessage에 덮이지 않도록 permanent widget 사용)
        self._user_schema_label = QLabel()
        self._user_schema_label.setStyleSheet('color: #555555; padding-right: 8px;')
        self._statusbar.addPermanentWidget(self._user_schema_label)

    # ── 연결 처리 ────────────────────────────────

    def _on_connect(self):
        dlg = ConnectionDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        conn_info = dlg.connection_info
        self._statusbar.showMessage(f'연결 중: {conn_info.tns_alias}...')
        try:
            self._client.connect(conn_info)
            self._update_connection_ui()
            self._update_user_schema_label()
            self._update_db_version()
            # 통계 수집 권한 1회 조회 (분석 시 재사용)
            try:
                self._has_stats_privilege = self._client.check_stats_privilege()
            except Exception:
                self._has_stats_privilege = False
            mode = self._client.connection_mode
            msg = f'연결 성공: {self._client.current_connection_label} [{mode} 모드]'
            if mode == 'Thin':
                msg += '  ※ Thin 모드로 연결'
            self._statusbar.showMessage(msg, 7000)
        except (RuntimeError, ConnectionError) as e:
            _logger.error('DB 연결 실패: %s', e, exc_info=True)
            QMessageBox.critical(self, 'DB 연결 실패', str(e))
            self._statusbar.showMessage('연결 실패', 3000)

    def _on_disconnect(self):
        self._client.disconnect()
        self._has_stats_privilege = False
        self._update_connection_ui()
        self._user_schema_label.clear()
        self._db_version_label.clear()
        self._rewrite_tab.set_db_version('')
        self._statusbar.showMessage('연결 해제됨', 3000)

    def _update_user_schema_label(self):
        """연결된 세션의 유저/스키마 정보를 상태바에 표시한다."""
        try:
            user, schema = self._client.get_current_user_schema()
            if user == schema:
                self._user_schema_label.setText(f'유저: {user}')
            else:
                self._user_schema_label.setText(f'유저: {user}  /  스키마: {schema}')
        except Exception:
            self._user_schema_label.clear()

    def _update_db_version(self):
        """DB 버전을 조회해 상태바에 표시하고 RewriteTab에도 전달한다."""
        try:
            short_ver, _full = self._client.get_db_version()
            self._db_version_label.setText(short_ver)
            self._rewrite_tab.set_db_version(short_ver)
        except Exception:
            self._db_version_label.clear()
            self._rewrite_tab.set_db_version('')

    def _update_connection_ui(self):
        connected = self._client.is_connected
        self._btn_analyze.setEnabled(connected)
        self._btn_execute.setEnabled(connected)
        self._action_connect.setEnabled(not connected)
        self._action_disconnect.setEnabled(connected)

        if connected:
            label = self._client.current_connection_label
            mode  = self._client.connection_mode
            self._conn_label.setText(f'  연결됨: {label}  [{mode}]')
            self._conn_label.setStyleSheet('color: #006600; font-weight: bold;')
            self.setWindowTitle(f'Oracle SQL Tuner v2  [{label}] [{mode}]')
        else:
            self._conn_label.setText('  미연결')
            self._conn_label.setStyleSheet('color: #888888; font-weight: bold;')
            self.setWindowTitle('Oracle SQL Tuner v2')

    # ── 바인드 변수 처리 ──────────────────────────

    @staticmethod
    def _sql_cache_key(sql: str) -> str:
        """SQL 텍스트를 정규화하여 캐시 키로 사용할 문자열을 반환한다."""
        import hashlib, re
        normalized = re.sub(r'\s+', ' ', sql.strip().lower())
        return hashlib.md5(normalized.encode()).hexdigest()

    def _collect_bind_vars(self, sql: str) -> dict[str, str] | None:
        """
        SQL에서 :변수명을 감지하고 다이얼로그를 통해 값을 수집한다.
        - 변수 없음: 빈 dict 반환
        - 사용자 취소: None 반환
        - 이전에 동일한 SQL로 입력한 값이 있으면 다이얼로그에 미리 채워준다.
        """
        names = extract_bind_vars(sql)
        if not names:
            return {}
        key = self._sql_cache_key(sql)
        defaults = self._bind_cache.get(key, {})
        dlg = BindVarsDialog(names, self, defaults=defaults)
        if dlg.exec() != QDialog.Accepted:
            return None
        values = dlg.bind_values
        # 입력값 캐시 갱신 (빈 값도 포함하여 덮어씀)
        self._bind_cache[key] = values
        return values

    # ── 분석 실행 ────────────────────────────────

    def _run_analysis(self):
        if not self._client.is_connected:
            QMessageBox.warning(self, '연결 필요', 'DB에 먼저 연결하세요.')
            return

        sql = self._sql_editor.toPlainText().strip().rstrip(';').strip()
        if not sql:
            QMessageBox.warning(self, '입력 필요', 'SQL을 입력하세요.')
            return

        bind_vars = self._collect_bind_vars(sql)
        if bind_vars is None:  # 사용자 취소
            return

        self._btn_analyze.setEnabled(False)
        self._statusbar.showMessage('실행 계획 분석 중...')
        self._clear_results()

        # 실제 플랜 fetch에서 사용하기 위해 저장
        self._current_bind_vars = bind_vars or None

        self._worker = PlanWorker(self._client, sql, bind_vars or None)
        self._worker.finished.connect(self._on_analysis_done)
        self._worker.error.connect(self._on_analysis_error)
        self._worker.start()

    def _clear_results(self):
        self._plan_tree_tab.clear()
        self._xplan_tab.clear()
        self._cursor_plan_tab.clear()
        self._issues_tab.clear()
        self._index_tab.clear()
        self._wait_event_tab.clear()
        self._stats_tab.clear()
        self._result_tab.clear()
        self._rewrite_tab.clear()

    def _on_analysis_done(
        self,
        plan_rows: list,
        xplan_text: str,
        sql_issues: list,
        plan_issues: list,
        engine_used: str,
        resource,           # ResourceAnalysis
        index_infos: list,
        index_advices: list,
        stats_infos: list,
        stats_advices: list,
        has_stats_privilege: bool,
    ):
        self._btn_analyze.setEnabled(True)

        self._plan_tree_tab.populate(plan_rows)
        self._xplan_tab.populate(xplan_text)
        self._cursor_plan_tab.set_estimated(xplan_text)

        # 인덱스 분석 탭 채우기
        self._index_tab.populate(index_infos, index_advices)

        # 리소스 분석 탭 채우기
        self._wait_event_tab.populate(resource)

        # HIGH 심각도 리소스 항목 → 튜닝 제안 이슈로 추가
        resource_issues = [
            SqlIssue(
                severity=m.severity,
                category=f'리소스 ({m.category})',
                title=m.name,
                description=(
                    f'조회 방법: {resource.method}\n'
                    f'값: {m.display_value}'
                ),
                suggestion=m.suggestion,
            )
            for m in getattr(resource, 'metrics', [])
            if m.severity == 'HIGH' and m.suggestion
        ]

        all_issues = sql_issues + plan_issues + resource_issues
        self._issues_tab.populate(all_issues)

        # 힌트 자동 추천
        hint_suggestions = HintAdvisor().advise(plan_rows, index_infos)
        self._issues_tab.populate_hints(hint_suggestions)

        self._current_sql = self._sql_editor.toPlainText().strip().rstrip(';').strip()
        self._current_issues = all_issues

        self._stats_tab.set_sql(self._current_sql)
        self._stats_tab.populate_stats(stats_infos, stats_advices, has_stats_privilege)
        self._result_tab.set_sql(self._current_sql)
        self._rewrite_tab.refresh(
            self._current_sql,
            all_issues,
            index_infos=index_infos,
            stats_infos=stats_infos,
            plan_rows=plan_rows,
        )

        issue_count = len(all_issues)
        high_count = sum(1 for i in all_issues if i.severity == 'HIGH')
        engine_note = f'  [{engine_used}]' if engine_used else ''
        self._statusbar.showMessage(
            f'분석 완료{engine_note} | 이슈 {issue_count}건'
            + (f' (HIGH {high_count}건)' if high_count else '')
        )

        if all_issues:
            self._tabs.setCurrentIndex(self._tabs.indexOf(self._issues_tab))

    def _on_analysis_error(self, msg: str):
        self._btn_analyze.setEnabled(True)
        self._statusbar.showMessage('분석 오류', 3000)
        _logger.error('분석 오류 (UI): %s', msg)
        QMessageBox.critical(
            self, '분석 오류',
            f'{msg}\n\n자세한 내용은 로그 파일을 확인하세요:\n{LOG_FILE_PATH}',
        )

    # ── SQL 직접 실행 ─────────────────────────────

    def _run_execute(self):
        if not self._client.is_connected:
            QMessageBox.warning(self, '연결 필요', 'DB에 먼저 연결하세요.')
            return

        sql = self._sql_editor.toPlainText().strip().rstrip(';').strip()
        if not sql:
            QMessageBox.warning(self, '입력 필요', 'SQL을 입력하세요.')
            return

        bind_vars = self._collect_bind_vars(sql)
        if bind_vars is None:  # 사용자 취소
            return

        # 실행 결과 탭으로 전환
        result_tab_index = self._tabs.indexOf(self._result_tab)
        self._tabs.setCurrentIndex(result_tab_index)

        self._result_tab.set_sql(sql)
        self._result_tab.show_running()
        # 실행 계획 분석 없이 직접 실행한 경우에도 V$SQL 조회 가능하도록 sql 설정
        self._stats_tab.set_sql(sql)
        self._statusbar.showMessage('SQL 실행 중...')

        # 실제 플랜 fetch에서 사용하기 위해 저장
        self._current_bind_vars = bind_vars or None

        self._exec_worker = ExecuteWorker(
            self._client, sql, self._result_tab.max_rows, bind_vars or None
        )
        self._exec_worker.finished.connect(self._on_execute_done)
        self._exec_worker.error.connect(self._on_execute_error)
        self._exec_worker.start()

    def _on_execute_done(
        self, columns: list, rows: list, elapsed_ms: float, fetched: int, sql_id: str
    ):
        self._result_tab.show_result(columns, rows, elapsed_ms, fetched)
        capped = f' (최대 {fetched}행)' if fetched == self._result_tab.max_rows else ''
        id_note = f'  |  SQL_ID: {sql_id}' if sql_id else ''
        self._statusbar.showMessage(
            f'실행 완료 | {fetched:,}행  |  {elapsed_ms:.1f} ms{capped}{id_note}'
        )
        # 원본 SQL_ID를 stats_tab에 전달 (힌트 버전 SQL_ID 아님)
        self._stats_tab.set_sql_id(sql_id)
        # GATHER_PLAN_STATISTICS 힌트 버전으로 내부 실행 후 실제 플랜 조회
        sql = self._sql_editor.toPlainText().strip().rstrip(';').strip()
        self._fetch_actual_plan(sql, self._current_bind_vars)

    def _on_execute_error(self, msg: str):
        self._result_tab.show_error(msg)
        self._statusbar.showMessage('실행 오류', 3000)

    def _fetch_actual_plan(self, sql: str, bind_vars: dict | None = None):
        """GATHER_PLAN_STATISTICS 힌트를 주입하여 내부 실행 후 실제 플랜을 조회한다.
        원본 SQL과 분리된 별도 실행이며 실제 플랜 탭 표시 전용이다."""
        self._cursor_plan_worker = CursorPlanWorker(self._client, sql, bind_vars)
        self._cursor_plan_worker.finished.connect(self._cursor_plan_tab.populate_actual)
        self._cursor_plan_worker.start()

    # ── AI 설정 ──────────────────────────────────

    def _on_ai_settings(self):
        dlg = AISettingsDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self._ai_provider = self._load_ai_provider()
            self._ai_tuner = AiSqlTuner(self._ai_provider)
            self._rewrite_tab.set_tuner(self._ai_tuner)
            self._rewrite_tab.update_ai_provider_label(self._ai_provider.label)
            self._statusbar.showMessage(f'AI 제공자 변경: {self._ai_provider.label}', 4000)

    def _load_ai_provider(self):
        settings = QSettings(_CONFIG_PATH, QSettings.IniFormat)
        raw_key = settings.value('AI/api_key', '')
        api_key = ''
        if raw_key:
            try:
                api_key = base64.b64decode(raw_key.encode()).decode()
            except Exception:
                pass
        config = AIProviderConfig(
            provider_type=settings.value('AI/provider_type', 'none'),
            api_key=api_key,
            base_url=settings.value('AI/base_url', ''),
            model=settings.value('AI/model', ''),
        )
        return create_provider(config)

    # ── 로그 뷰어 ────────────────────────────────

    def _show_log_viewer(self):
        """로그 파일 내용을 다이얼로그로 표시합니다."""
        from PyQt5.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTextEdit, QPushButton
        from PyQt5.QtGui import QFont

        dlg = QDialog(self)
        dlg.setWindowTitle(f'로그 뷰어 — {LOG_FILE_PATH}')
        dlg.resize(900, 560)

        layout = QVBoxLayout(dlg)

        text = QTextEdit()
        text.setReadOnly(True)
        text.setFont(QFont('Consolas', 9))
        text.setLineWrapMode(QTextEdit.NoWrap)

        if os.path.exists(LOG_FILE_PATH):
            try:
                with open(LOG_FILE_PATH, encoding='utf-8', errors='replace') as f:
                    content = f.read()
                # 최근 2000줄만 표시
                lines = content.splitlines()
                if len(lines) > 2000:
                    lines = ['[... 오래된 로그 생략 ...]'] + lines[-2000:]
                text.setPlainText('\n'.join(lines))
                # 스크롤을 맨 아래로
                cursor = text.textCursor()
                cursor.movePosition(cursor.End)
                text.setTextCursor(cursor)
            except Exception as e:
                text.setPlainText(f'로그 파일 읽기 오류: {e}')
        else:
            text.setPlainText(f'로그 파일이 없습니다.\n{LOG_FILE_PATH}')

        layout.addWidget(text)

        btn_row = QHBoxLayout()
        btn_refresh = QPushButton('새로고침')
        btn_refresh.clicked.connect(lambda: self._refresh_log_text(text))
        btn_open = QPushButton('탐색기에서 열기')
        btn_open.clicked.connect(lambda: os.startfile(os.path.dirname(LOG_FILE_PATH)))
        btn_close = QPushButton('닫기')
        btn_close.clicked.connect(dlg.accept)
        btn_row.addWidget(btn_refresh)
        btn_row.addWidget(btn_open)
        btn_row.addStretch()
        btn_row.addWidget(btn_close)
        layout.addLayout(btn_row)

        dlg.exec()

    def _refresh_log_text(self, text_widget):
        """로그 뷰어 텍스트를 파일에서 다시 읽어 갱신합니다."""
        if not os.path.exists(LOG_FILE_PATH):
            text_widget.setPlainText('로그 파일이 없습니다.')
            return
        try:
            with open(LOG_FILE_PATH, encoding='utf-8', errors='replace') as f:
                content = f.read()
            lines = content.splitlines()
            if len(lines) > 2000:
                lines = ['[... 오래된 로그 생략 ...]'] + lines[-2000:]
            text_widget.setPlainText('\n'.join(lines))
            cursor = text_widget.textCursor()
            cursor.movePosition(cursor.End)
            text_widget.setTextCursor(cursor)
        except Exception as e:
            text_widget.setPlainText(f'로그 파일 읽기 오류: {e}')

    # ── 종료 ─────────────────────────────────────

    def closeEvent(self, event):
        self._client.disconnect()
        event.accept()
