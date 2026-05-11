"""
V$SQL 통계 탭 위젯
- 상단: V$SQL 실행 통계 (수동 조회)
- 하단: 테이블 통계 현황 (분석 완료 시 자동 채워짐)
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QTableWidget, QTableWidgetItem, QPlainTextEdit,
    QPushButton, QLabel, QHeaderView, QAbstractItemView,
    QGroupBox, QApplication, QMessageBox,
)
from PyQt5.QtGui import QColor
from PyQt5.QtCore import Qt

from v2.core.db.oracle_client import OracleClient
from v2.core.constants import STALE_STATS_HIGH_DAYS, STALE_STATS_MEDIUM_DAYS

# 경과일 기준 색상
_COLOR_RED    = QColor('#FFCCCC')
_COLOR_ORANGE = QColor('#FFE5B4')
_COLOR_GREEN  = QColor('#CCFFCC')


class StatsTab(QWidget):
    def __init__(self, client: OracleClient, parent=None):
        super().__init__(parent)
        self._client = client
        self._current_advices: list = []
        self._has_privilege: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        splitter = QSplitter(Qt.Vertical)

        # ── 상단: V$SQL 통계 ──────────────────────────────────────────────
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(4)

        self._label = QLabel(
            'V$SQL 통계는 실제 실행 이력을 조회합니다. 버튼을 눌러 수동으로 조회하세요.'
        )
        self._label.setWordWrap(True)

        self._btn_load = QPushButton('V$SQL 통계 조회')
        self._btn_load.setFixedHeight(28)
        self._btn_load.setEnabled(False)
        self._btn_load.clicked.connect(self._on_load)

        self._table = QTableWidget(0, 8)
        self._table.setHorizontalHeaderLabels([
            'SQL_ID', '실행횟수', '총시간(ms)', 'CPU(ms)',
            'Buffer Gets', 'Disk Reads', '처리행수', 'Parse호출',
        ])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)

        top_layout.addWidget(self._label)
        top_layout.addWidget(self._btn_load)
        top_layout.addWidget(self._table)

        # ── 하단: 테이블 통계 현황 ────────────────────────────────────────
        bottom_grp = QGroupBox('테이블 통계 현황')
        bottom_layout = QVBoxLayout(bottom_grp)
        bottom_layout.setContentsMargins(6, 6, 6, 6)
        bottom_layout.setSpacing(4)

        self._stats_table = QTableWidget(0, 5)
        self._stats_table.setHorizontalHeaderLabels(
            ['테이블명', '건수', '최종분석일', '경과일', '상태']
        )
        self._stats_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._stats_table.horizontalHeader().setStretchLastSection(True)
        self._stats_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._stats_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._stats_table.verticalHeader().setVisible(False)
        self._stats_table.setMaximumHeight(160)

        script_label = QLabel('DBMS_STATS 수집 스크립트:')
        self._script_edit = QPlainTextEdit()
        self._script_edit.setReadOnly(True)
        self._script_edit.setMaximumHeight(110)
        self._script_edit.setPlaceholderText('분석 완료 후 통계 이상 테이블의 스크립트가 표시됩니다.')

        btn_row = QHBoxLayout()
        self._btn_exec_stats = QPushButton('통계 수집 실행')
        self._btn_exec_stats.setFixedHeight(28)
        self._btn_exec_stats.setEnabled(False)
        self._btn_exec_stats.clicked.connect(self._on_execute_stats)

        self._btn_copy_script = QPushButton('스크립트 복사')
        self._btn_copy_script.setFixedHeight(28)
        self._btn_copy_script.setEnabled(False)
        self._btn_copy_script.clicked.connect(self._on_copy_script)

        self._stats_status_label = QLabel()
        self._stats_status_label.setWordWrap(True)
        self._stats_status_label.setStyleSheet('color: #885500;')

        btn_row.addWidget(self._btn_exec_stats)
        btn_row.addWidget(self._btn_copy_script)
        btn_row.addWidget(self._stats_status_label, 1)

        bottom_layout.addWidget(self._stats_table)
        bottom_layout.addWidget(script_label)
        bottom_layout.addWidget(self._script_edit)
        bottom_layout.addLayout(btn_row)

        splitter.addWidget(top_widget)
        splitter.addWidget(bottom_grp)
        splitter.setSizes([300, 350])

        layout.addWidget(splitter)

        self._current_sql: str = ''
        self._current_sql_id: str = ''

    # ── Public API ────────────────────────────────────────────────────────

    def set_sql(self, sql: str):
        """분석할 SQL을 설정하고 조회 버튼을 활성화합니다."""
        self._current_sql = sql
        self._current_sql_id = ''
        self._btn_load.setEnabled(bool(sql))

    def set_sql_id(self, sql_id: str):
        """SQL 직접 실행 후 얻은 SQL_ID를 설정합니다. 다음 조회 시 정확한 매칭에 사용됩니다."""
        self._current_sql_id = sql_id

    def populate_stats(
        self,
        stats_infos: list,
        stats_advices: list,
        has_privilege: bool,
    ) -> None:
        """
        테이블 통계 현황 섹션을 채웁니다.

        Parameters
        ----------
        stats_infos   : list[TableStatsInfo]
        stats_advices : list[StatsAdvice]
        has_privilege : 현재 세션이 DBMS_STATS를 직접 실행할 수 있는지 여부
        """
        self._current_advices = stats_advices
        self._has_privilege = has_privilege

        # 테이블 목록 채우기
        self._stats_table.setRowCount(len(stats_infos))
        for row_idx, info in enumerate(stats_infos):
            # 건수
            num_rows_str = f'{info.num_rows:,}' if info.num_rows is not None else '-'
            # 최종분석일
            if info.last_analyzed is not None:
                analyzed_str = info.last_analyzed.strftime('%Y-%m-%d') \
                    if hasattr(info.last_analyzed, 'strftime') \
                    else str(info.last_analyzed)[:10]
            else:
                analyzed_str = '-'
            # 경과일 + 상태
            days = info.days_since_analyzed
            if info.last_analyzed is None:
                status_str = '미수집'
                bg = _COLOR_RED
            elif days is not None and days > STALE_STATS_HIGH_DAYS:
                status_str = f'{days}일 경과 (HIGH)'
                bg = _COLOR_RED
            elif days is not None and days > STALE_STATS_MEDIUM_DAYS:
                status_str = f'{days}일 경과 (MEDIUM)'
                bg = _COLOR_ORANGE
            else:
                status_str = '정상'
                bg = _COLOR_GREEN

            days_str = str(days) if days is not None else '-'

            values = [info.table_name, num_rows_str, analyzed_str, days_str, status_str]
            for col_idx, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setBackground(bg)
                self._stats_table.setItem(row_idx, col_idx, item)

        # 스크립트 영역
        if stats_advices:
            scripts = '\n\n'.join(a.suggested_sql for a in stats_advices)
            self._script_edit.setPlainText(scripts)
            self._btn_copy_script.setEnabled(True)
        else:
            self._script_edit.setPlainText('')
            self._btn_copy_script.setEnabled(False)

        # 실행 버튼: 항상 표시, 권한 없으면 비활성화
        has_issues = bool(stats_advices)
        self._btn_exec_stats.setEnabled(has_privilege and has_issues)

        if not has_privilege and has_issues:
            self._stats_status_label.setText(
                '※ ANALYZE ANY / DBA 권한 없음 — 스크립트를 복사하여 DBA에게 전달하세요'
            )
        elif not has_issues:
            self._stats_status_label.setText(
                '통계 이상 없음' if stats_infos else ''
            )
        else:
            self._stats_status_label.setText('')

    def clear(self):
        self._table.setRowCount(0)
        self._btn_load.setEnabled(False)
        self._current_sql_id = ''
        self._label.setText('V$SQL 통계는 실제 실행 이력을 조회합니다. 버튼을 눌러 수동으로 조회하세요.')
        # 테이블 통계 섹션 초기화
        self._stats_table.setRowCount(0)
        self._script_edit.setPlainText('')
        self._btn_exec_stats.setEnabled(False)
        self._btn_copy_script.setEnabled(False)
        self._stats_status_label.setText('')
        self._current_advices = []

    # ── V$SQL 조회 ────────────────────────────────────────────────────────

    def _on_load(self):
        if not self._current_sql:
            return
        self._btn_load.setEnabled(False)
        first_line = self._current_sql.strip().split('\n')[0].strip()
        keyword = first_line[:80]
        try:
            stats_list = self._client.get_sql_stats(keyword, self._current_sql_id)
            self._table.setRowCount(len(stats_list))
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
                    self._table.setItem(i, col, QTableWidgetItem(val))
            self._label.setText(f'V$SQL 통계 조회 완료 — {len(stats_list)}건')
        except Exception as e:
            self._label.setText(f'조회 실패: {e}')
        finally:
            self._btn_load.setEnabled(True)

    # ── 통계 수집 실행 / 복사 ─────────────────────────────────────────────

    def _on_execute_stats(self):
        if not self._current_advices:
            return
        tables = [a.table_name for a in self._current_advices]
        reply = QMessageBox.question(
            self,
            '통계 수집 실행',
            f'다음 {len(tables)}개 테이블의 통계를 수집합니다:\n'
            + '\n'.join(f'  • {t}' for t in tables)
            + '\n\n계속하시겠습니까?',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._btn_exec_stats.setEnabled(False)
        self._stats_status_label.setText('통계 수집 중...')
        QApplication.processEvents()

        try:
            ok, msg = self._client.execute_stats_collection(tables)
            if ok:
                self._stats_status_label.setText(f'완료: {msg}')
                self._stats_status_label.setStyleSheet('color: #006600;')
            else:
                self._stats_status_label.setText(f'실패: {msg}')
                self._stats_status_label.setStyleSheet('color: #CC0000;')
        finally:
            self._btn_exec_stats.setEnabled(self._has_privilege and bool(self._current_advices))

    def _on_copy_script(self):
        text = self._script_edit.toPlainText()
        if text:
            QApplication.clipboard().setText(text)
            self._stats_status_label.setText('스크립트가 클립보드에 복사되었습니다.')
            self._stats_status_label.setStyleSheet('color: #005588;')
