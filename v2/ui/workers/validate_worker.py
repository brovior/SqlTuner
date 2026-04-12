"""
튜닝 SQL 검증 백그라운드 워커

ValidateWorker.run():
  TuningValidator.validate(original_sql, tuned_sql) → ValidationResult
  finished 시그널로 결과 전달
"""
from __future__ import annotations
from PyQt5.QtCore import QThread, pyqtSignal

from v2.core.db.oracle_client import OracleClient
from v2.core.pipeline.validation import TuningValidator, ValidationResult


class ValidateWorker(QThread):
    finished = pyqtSignal(object)   # ValidationResult
    error = pyqtSignal(str)

    def __init__(self, client: OracleClient, original_sql: str, tuned_sql: str):
        super().__init__()
        self._validator = TuningValidator(client)
        self._original_sql = original_sql
        self._tuned_sql = tuned_sql

    def run(self):
        try:
            result = self._validator.validate(self._original_sql, self._tuned_sql)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
