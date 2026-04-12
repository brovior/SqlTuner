"""
AI 튜닝 백그라운드 워커

AiTuneWorker.run():
  AiSqlTuner.tune(sql, issues) → tuned_sql 문자열
  finished 시그널로 결과 전달
"""
from __future__ import annotations
from PyQt5.QtCore import QThread, pyqtSignal

from v2.core.ai.ai_tuner import AiSqlTuner


class AiTuneWorker(QThread):
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, tuner: AiSqlTuner, sql: str, issues: list, db_version: str = ''):
        super().__init__()
        self._tuner = tuner
        self._sql = sql
        self._issues = issues
        self._db_version = db_version

    def run(self):
        try:
            result = self._tuner.tune(self._sql, self._issues, self._db_version)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
