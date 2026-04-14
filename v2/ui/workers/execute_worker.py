"""
SQL 직접 실행 백그라운드 워커
"""
from __future__ import annotations
from PyQt5.QtCore import QThread, pyqtSignal

from v2.core.db.oracle_client import OracleClient
from v2.core.app_logger import get_logger

_logger = get_logger('execute_worker')


class ExecuteWorker(QThread):
    # columns, rows, elapsed_ms, fetched_count, sql_id
    finished = pyqtSignal(list, list, float, int, str)
    error = pyqtSignal(str)

    def __init__(
        self, client: OracleClient, sql: str,
        max_rows: int = 500, bind_vars: dict | None = None,
    ):
        super().__init__()
        self._client = client
        self._sql = sql
        self._max_rows = max_rows
        self._bind_vars = bind_vars

    def run(self):
        _logger.info('SQL 실행 — %s', self._sql[:120].replace('\n', ' '))
        try:
            columns, rows, elapsed_ms, sql_id = self._client.execute_sql(
                self._sql, self._max_rows, self._bind_vars
            )
            _logger.info('SQL 실행 완료 — rows=%d, elapsed=%.1fms', len(rows), elapsed_ms)
            self.finished.emit(columns, rows, elapsed_ms, len(rows), sql_id)
        except Exception as e:
            _logger.error('SQL 실행 오류', exc_info=True)
            self.error.emit(str(e))
