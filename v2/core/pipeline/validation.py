"""
튜닝 SQL 검증 파이프라인

TuningValidator.validate(original_sql, tuned_sql) 흐름:
  1. tuned_sql 에 EXPLAIN PLAN 실행 → 파싱/문법 오류 감지
  2. 원본 Cost vs 튜닝 Cost 비교 (cost_delta_pct)
  3. PlanIssue 목록 비교
     - resolved_issues : 원본에 있었지만 튜닝 후 사라진 이슈
     - new_issues      : 튜닝 후 새로 생긴 이슈 (회귀)
  4. ValidationResult 반환 — UI 가 이를 그대로 표시

DB 미연결 또는 EXPLAIN PLAN 권한 없음 → is_valid=False, error_message 에 이유 기록
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional

from ..db.oracle_client import OracleClient
from ..db.plan_analyzer import PlanAnalyzer, PlanIssue


@dataclass
class ValidationResult:
    """튜닝 SQL 검증 결과"""

    # ── 기본 상태 ──────────────────────────────────
    is_valid: bool                      # EXPLAIN PLAN 성공 여부
    error_message: str = ''             # 실패 시 오류 메시지

    # ── Cost 비교 ───────────────────────────────────
    original_cost: Optional[int] = None # 원본 SQL 총 Cost (루트 노드)
    tuned_cost: Optional[int] = None    # 튜닝 SQL 총 Cost
    cost_delta_pct: Optional[float] = None
    # cost_delta_pct 해석:
    #   음수 → 비용 감소 (개선)
    #   양수 → 비용 증가 (악화)
    #   None → Cost 정보 없음

    # ── 이슈 비교 ───────────────────────────────────
    original_issues: list[PlanIssue] = field(default_factory=list)
    tuned_issues: list[PlanIssue] = field(default_factory=list)
    resolved_issues: list[PlanIssue] = field(default_factory=list)  # 원본에만 있던 이슈
    new_issues: list[PlanIssue] = field(default_factory=list)       # 튜닝 후 새로 생긴 이슈

    # ── 메타 ────────────────────────────────────────
    original_xplan: str = ''    # 원본 DBMS_XPLAN 텍스트
    tuned_xplan: str = ''       # 튜닝 DBMS_XPLAN 텍스트

    # ── 편의 프로퍼티 ────────────────────────────────

    @property
    def cost_improved(self) -> bool:
        """Cost 가 감소한 경우 True"""
        return self.cost_delta_pct is not None and self.cost_delta_pct < 0

    @property
    def has_regression(self) -> bool:
        """HIGH 심각도 신규 이슈가 생긴 경우 True"""
        return any(i.severity == 'HIGH' for i in self.new_issues)

    @property
    def verdict(self) -> str:
        """
        종합 판정 문자열 (UI 표시용)
          INVALID  — EXPLAIN PLAN 실패 (문법 오류 등)
          IMPROVED — Cost 감소 + 회귀 없음
          REGRESSED — 새로운 HIGH 이슈 발생
          NEUTRAL  — 변화 없음 또는 판단 불가
          WARNING  — Cost 증가이나 회귀는 없음
        """
        if not self.is_valid:
            return 'INVALID'
        if self.has_regression:
            return 'REGRESSED'
        if self.cost_improved:
            return 'IMPROVED'
        if self.cost_delta_pct is not None and self.cost_delta_pct > 5:
            return 'WARNING'
        return 'NEUTRAL'

    @property
    def verdict_label(self) -> str:
        """판정 한국어 레이블"""
        return {
            'INVALID':   '❌ 문법 오류 — 실행 불가',
            'REGRESSED': '⚠️ 회귀 — 새로운 HIGH 이슈 발생',
            'IMPROVED':  '✅ 개선됨',
            'WARNING':   '⚠️ 주의 — Cost 증가',
            'NEUTRAL':   'ℹ️ 변화 없음',
        }.get(self.verdict, self.verdict)

    @property
    def cost_summary(self) -> str:
        """Cost 비교 한 줄 요약"""
        if self.original_cost is None or self.tuned_cost is None:
            return 'Cost 정보 없음'
        delta = self.cost_delta_pct
        sign = '+' if delta >= 0 else ''
        return (
            f"원본 Cost: {self.original_cost:,}  →  "
            f"튜닝 Cost: {self.tuned_cost:,}  "
            f"({sign}{delta:.1f}%)"
        )


class TuningValidator:
    """
    원본 SQL 과 튜닝 SQL 의 실행 계획을 비교하여 ValidationResult 를 반환합니다.
    DB 에 연결된 OracleClient 인스턴스가 필요합니다.
    """

    def __init__(self, client: OracleClient):
        self._client = client

    def validate(self, original_sql: str, tuned_sql: str) -> ValidationResult:
        """
        두 SQL 의 실행 계획을 비교합니다.
        DB 미연결 또는 권한 없음 시 is_valid=False 로 반환합니다.
        """
        if not self._client.is_connected:
            return ValidationResult(
                is_valid=False,
                error_message='DB 에 연결되어 있지 않습니다. 검증을 수행할 수 없습니다.',
            )

        # ── 원본 SQL 플랜 ──────────────────────────
        try:
            orig_rows, orig_xplan = self._client.explain_plan(original_sql)
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                error_message=f'원본 SQL EXPLAIN PLAN 오류:\n{e}',
            )

        # ── 튜닝 SQL 플랜 ──────────────────────────
        try:
            tuned_rows, tuned_xplan = self._client.explain_plan(tuned_sql)
        except Exception as e:
            return ValidationResult(
                is_valid=False,
                error_message=f'튜닝 SQL EXPLAIN PLAN 오류 (문법 오류 가능):\n{e}',
                original_xplan=orig_xplan,
            )

        # ── 이슈 분석 ─────────────────────────────
        orig_analyzer = PlanAnalyzer(orig_rows)
        orig_analyzer.build_tree()
        original_issues = orig_analyzer.analyze()

        tuned_analyzer = PlanAnalyzer(tuned_rows)
        tuned_analyzer.build_tree()
        tuned_issues = tuned_analyzer.analyze()

        # ── Cost 추출 (루트 노드) ──────────────────
        orig_cost = self._root_cost(orig_rows)
        tuned_cost = self._root_cost(tuned_rows)
        cost_delta_pct = self._calc_delta(orig_cost, tuned_cost)

        # ── 이슈 비교 ─────────────────────────────
        orig_keys = {(i.category, i.title) for i in original_issues}
        tuned_keys = {(i.category, i.title) for i in tuned_issues}

        resolved = [i for i in original_issues if (i.category, i.title) not in tuned_keys]
        new = [i for i in tuned_issues if (i.category, i.title) not in orig_keys]

        return ValidationResult(
            is_valid=True,
            original_cost=orig_cost,
            tuned_cost=tuned_cost,
            cost_delta_pct=cost_delta_pct,
            original_issues=original_issues,
            tuned_issues=tuned_issues,
            resolved_issues=resolved,
            new_issues=new,
            original_xplan=orig_xplan,
            tuned_xplan=tuned_xplan,
        )

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    @staticmethod
    def _root_cost(rows) -> Optional[int]:
        """루트 노드(parent_id=None)의 Cost 반환. 없으면 None."""
        for row in rows:
            if row.parent_id is None:
                return row.cost
        return None

    @staticmethod
    def _calc_delta(orig: Optional[int], tuned: Optional[int]) -> Optional[float]:
        """Cost 변화율(%) 계산. 원본 Cost 가 0 이하이면 None."""
        if orig is None or tuned is None:
            return None
        if orig <= 0:
            return None
        return round((tuned - orig) / orig * 100, 1)
