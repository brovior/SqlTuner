"""
V$SQL 통계 탭 위젯
수동 조회 버튼 + 결과 테이블
"""
from __future__ import annotations

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QAbstractItemView,
)

from v2.core.db.oracle_client import OracleClient


class StatsTab(QWidget):
    def __init__(self, client: OracleClient, parent=None):
        super().__init__(parent)
        self._client = client

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

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

        layout.addWidget(self._label)
        layout.addWidget(self._btn_load)
        layout.addWidget(self._table)

        self._current_sql: str = ''
        self._current_sql_id: str = ''

    def set_sql(self, sql: str):
        """분석할 SQL을 설정하고 조회 버튼을 활성화합니다."""
        self._current_sql = sql
        self._current_sql_id = ''
        self._btn_load.setEnabled(bool(sql))

    def set_sql_id(self, sql_id: str):
        """SQL 직접 실행 후 얻은 SQL_ID를 설정합니다. 다음 조회 시 정확한 매칭에 사용됩니다."""
        self._current_sql_id = sql_id

    def clear(self):
        self._table.setRowCount(0)
        self._btn_load.setEnabled(False)
        self._current_sql_id = ''
        self._label.setText('V$SQL 통계는 실제 실행 이력을 조회합니다. 버튼을 눌러 수동으로 조회하세요.')

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
