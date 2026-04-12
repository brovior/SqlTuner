"""
실행 계획 분석 백그라운드 워커

PlanWorker.run():
  1. OracleClient.explain_plan() → plan_rows, xplan_text
     (explain_plan 내부에서 V$MYSTAT 사전 스냅샷 저장)
  2. PlanAnalyzer → plan_issues
  3. CompositeAnalyzer → sql_issues
  4. OracleClient.get_resource_analysis() → ResourceAnalysis (3단계 폴백 자동 처리)
  5. IndexAdvisor.advise() → index_infos, index_advices (실패 시 빈 리스트)
  6. StatsAdvisor.advise() → stats_infos, stats_advices (실패 시 빈 리스트)
  7. OracleClient.check_stats_privilege() → has_stats_privilege
  8. finished 시그널로 결과 전달
"""
from __future__ import annotations
from PyQt5.QtCore import QThread, pyqtSignal

from v2.core.db.oracle_client import OracleClient, PlanRow, ResourceAnalysis
from v2.core.db.plan_analyzer import PlanAnalyzer, PlanIssue
from v2.core.analysis.composite_analyzer import CompositeAnalyzer
from v2.core.analysis.base import SqlIssue
from v2.core.analysis.index_advisor import IndexAdvisor
from v2.core.analysis.stats_advisor import StatsAdvisor


class PlanWorker(QThread):
    # plan_rows, xplan_text, sql_issues, plan_issues, engine_used, resource_analysis,
    # index_infos, index_advices, stats_infos, stats_advices, has_stats_privilege
    finished = pyqtSignal(list, str, list, list, str, object, list, list, list, list, bool)
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

            # 인덱스 어드바이저 (DB 권한 부족 등 실패 시 빈 리스트로 폴백)
            try:
                idx_advisor = IndexAdvisor(self._client)
                index_infos, index_advices = idx_advisor.advise(self._sql)
            except Exception:
                index_infos, index_advices = [], []

            # 통계 어드바이저 (DB 권한 부족 등 실패 시 빈 리스트로 폴백)
            try:
                stats_advisor = StatsAdvisor(self._client)
                stats_infos, stats_advices = stats_advisor.advise(self._sql)
                has_stats_privilege = self._client.check_stats_privilege()
            except Exception:
                stats_infos, stats_advices = [], []
                has_stats_privilege = False

            self.finished.emit(
                plan_rows, xplan_text, sql_issues, plan_issues, engine_used, resource,
                index_infos, index_advices, stats_infos, stats_advices, has_stats_privilege,
            )
        except Exception as e:
            self.error.emit(str(e))
