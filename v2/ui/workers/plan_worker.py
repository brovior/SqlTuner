"""
실행 계획 분석 백그라운드 워커

PlanWorker.run():
  1. OracleClient.explain_plan() → plan_rows, xplan_text
     (explain_plan 내부에서 V$MYSTAT 사전 스냅샷 저장)
  2. PlanAnalyzer → plan_issues
  3. CompositeAnalyzer → sql_issues
  4. OracleClient.get_resource_analysis() → ResourceAnalysis (3단계 폴백 자동 처리)
  5. finished 시그널로 결과 전달
"""
from __future__ import annotations
from PyQt5.QtCore import QThread, pyqtSignal

from v2.core.db.oracle_client import OracleClient, PlanRow, ResourceAnalysis
from v2.core.db.plan_analyzer import PlanAnalyzer, PlanIssue
from v2.core.analysis.composite_analyzer import CompositeAnalyzer
from v2.core.analysis.base import SqlIssue


class PlanWorker(QThread):
    # plan_rows, xplan_text, sql_issues, plan_issues, engine_used, resource_analysis
    finished = pyqtSignal(list, str, list, list, str, object)
    error = pyqtSignal(str)

    def __init__(self, client: OracleClient, sql: str, bind_vars: dict | None = None):
        super().__init__()
        self._client = client
        self._sql = sql
        self._bind_vars = bind_vars
        self._analyzer = CompositeAnalyzer()

    def run(self):
        try:
            # explain_plan() 내부에서 V$MYSTAT 사전 스냅샷을 자동 저장
            plan_rows, xplan_text = self._client.explain_plan(self._sql, self._bind_vars)

            plan_analyzer = PlanAnalyzer(plan_rows)
            plan_analyzer.build_tree()
            plan_issues = plan_analyzer.analyze()

            sql_issues = self._analyzer.analyze(self._sql)
            engine_used = self._analyzer.last_engine

            # 3단계 폴백 포함 리소스 분석 (실패해도 항상 ResourceAnalysis 반환)
            resource: ResourceAnalysis = self._client.get_resource_analysis(
                sql_keyword=self._sql[:80]
            )

            self.finished.emit(
                plan_rows, xplan_text, sql_issues, plan_issues, engine_used, resource
            )
        except Exception as e:
            self.error.emit(str(e))
