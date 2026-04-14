"""
실제 플랜 조회 백그라운드 워커

GATHER_PLAN_STATISTICS 힌트를 주입하여 SQL을 내부 실행한 뒤
DBMS_XPLAN.DISPLAY_CURSOR('ALLSTATS LAST') 결과를 반환합니다.

- 원본 SQL은 변경하지 않습니다 (힌트 삽입 사본은 내부에서만 사용)
- 실제 플랜 탭 전용이며 결과 행은 버립니다
- SELECT / WITH 이외 문장은 안내 문자열을 반환합니다
"""
from __future__ import annotations
from PyQt5.QtCore import QThread, pyqtSignal

from v2.core.db.oracle_client import OracleClient
from v2.core.app_logger import get_logger

_logger = get_logger('cursor_plan_worker')


class CursorPlanWorker(QThread):
    finished = pyqtSignal(str)  # 조회된 텍스트 (에러 포함 항상 finished 발신)

    def __init__(
        self,
        client: OracleClient,
        sql: str,
        bind_vars: dict | None = None,
    ):
        super().__init__()
        self._client = client
        self._sql = sql
        self._bind_vars = bind_vars

    def run(self):
        try:
            _, plan_text = self._client.execute_with_gather_stats(
                self._sql, self._bind_vars
            )
        except Exception as e:
            _logger.error('실제 플랜 조회 오류', exc_info=True)
            plan_text = f'[워커 오류]\n{e}'
        self.finished.emit(plan_text)
