"""
SQL 직접 실행 백그라운드 워커
"""
from __future__ import annotations
from PyQt5.QtCore import QThread, pyqtSignal

from v2.core.db.oracle_client import OracleClient


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
        try:
            columns, rows, elapsed_ms, sql_id = self._client.execute_sql(
                self._sql, self._max_rows, self._bind_vars
            )
            self.finished.emit(columns, rows, elapsed_ms, len(rows), sql_id)
        except Exception as e:
            self.error.emit(str(e))
