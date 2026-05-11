"""
튜닝 SQL 검증 파이프라인

TuningValidator.validate(original_sql, tuned_sql, measure_time) 흐름:
  1. tuned_sql 에 EXPLAIN PLAN 실행 → 파싱/문법 오류 감지
  2. 원본 Cost vs 튜닝 Cost 비교 (cost_delta_pct)
  3. PlanIssue 목록 비교
     - resolved_issues : 원본에 있었지만 튜닝 후 사라진 이슈
     - new_issues      : 튜닝 후 새로 생긴 이슈 (회귀)
  4. measure_time=True 시 실제 SELECT 를 실행해 실행시간(ms) 측정
  5. APPROVE / REVIEW / REJECT 자동 판정 (ValidationResult.__post_init__)
  6. ValidationResult 반환 — UI 가 이를 그대로 표시

DB 미연결 또는 EXPLAIN PLAN 권한 없음 → is_valid=False, error_message 에 이유 기록
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Optional

from ..db.oracle_client import OracleClient
from ..db.plan_analyzer import PlanAnalyzer, PlanIssue
from ..constants import COST_DELTA_WARN_PCT


# ──────────────────────────────────────────────────────────────────────────────
# 자동 판정 로직 (모듈 수준 순수 함수 — 테스트 용이)
# ──────────────────────────────────────────────────────────────────────────────

def _compute_auto_verdict(r: 'ValidationResult') -> tuple[str, list[str]]:
    """
    ValidationResult 의 필드를 기반으로 (verdict, verdict_reasons) 를 계산합니다.

    REJECT 조건 (하나라도 해당하면):
      - is_valid = False (문법 오류)
      - row_count_match = False (결과 행 수 불일치)
      - cost_delta_pct > 10 (비용 10% 이상 증가)
      - new_issues 존재 (신규 이슈 발생)

    APPROVE 조건 (모두 만족해야):
      - is_valid = True
      - cost_delta_pct <= -10 (비용 10% 이상 감소)
      - resolved_issues 1개 이상
      - new_issues 없음
      - row_count_match = True 또는 None (미검증)

    REVIEW: REJECT 도 APPROVE 도 아닌 경우
    """
    # ── REJECT ────────────────────────────────────────────────────
    reject_reasons: list[str] = []

    if not r.is_valid:
        reject_reasons.append('문법 오류 — 실행 불가')
    if r.row_count_match is False:
        reject_reasons.append('결과 행 수 불일치')
    if r.cost_delta_pct is not None and r.cost_delta_pct > COST_DELTA_WARN_PCT:
        reject_reasons.append(f'비용 +{r.cost_delta_pct:.1f}% 증가')
    if r.new_issues:
        reject_reasons.append(f'신규 이슈 {len(r.new_issues)}건 발생')

    if reject_reasons:
        return 'REJECT', reject_reasons

    # ── APPROVE ───────────────────────────────────────────────────
    cost_ok = r.cost_delta_pct is not None and r.cost_delta_pct <= -COST_DELTA_WARN_PCT
    resolved_ok = len(r.resolved_issues) >= 1
    row_ok = r.row_count_match is not False   # True 또는 None(미검증) 허용

    if cost_ok and resolved_ok and row_ok:
        approve_reasons: list[str] = []
        pct = abs(r.cost_delta_pct)  # type: ignore[arg-type]
        approve_reasons.append(f'비용 {pct:.1f}% 감소')
        n = len(r.resolved_issues)
        if n == 1:
            approve_reasons.append(f'{r.resolved_issues[0].title} 이슈 해소')
        else:
            approve_reasons.append(f'{n}개 이슈 해소')
        approve_reasons.append('신규 이슈 없음')
        return 'APPROVE', approve_reasons

    # ── REVIEW ────────────────────────────────────────────────────
    review_reasons: list[str] = []
    if r.cost_delta_pct is not None:
        sign = '+' if r.cost_delta_pct >= 0 else ''
        review_reasons.append(f'비용 {sign}{r.cost_delta_pct:.1f}%')
    if r.resolved_issues:
        review_reasons.append(f'{len(r.resolved_issues)}개 이슈 해소')
    if not review_reasons:
        review_reasons.append('변화 없음')
    return 'REVIEW', review_reasons


# ──────────────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────────────────────────

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

    # ── 결과 행 수 일치 여부 (measure_time 실행 시 채워질 수 있음) ──
    row_count_match: Optional[bool] = None
    # True  → 원본/튜닝 행 수 동일
    # False → 행 수 불일치 (REJECT 조건)
    # None  → 미검증

    # ── 실행시간 비교 (measure_time=True 일 때만 채워짐) ────────────
    original_elapsed_ms: Optional[float] = None  # 원본 SQL 실제 실행시간 (ms)
    tuned_elapsed_ms: Optional[float] = None     # 튜닝 SQL 실제 실행시간 (ms)
    elapsed_delta_pct: Optional[float] = None
    # elapsed_delta_pct 해석:
    #   음수 → 실행시간 감소 (빨라짐)
    #   양수 → 실행시간 증가 (느려짐)
    #   None → 측정 안 함 또는 측정 불가

    # ── 메타 ────────────────────────────────────────
    original_xplan: str = ''    # 원본 DBMS_XPLAN 텍스트
    tuned_xplan: str = ''       # 튜닝 DBMS_XPLAN 텍스트

    # ── 자동 판정 (APPROVE / REVIEW / REJECT) — __post_init__ 에서 계산 ──
    verdict: str = field(default='', init=False)
    verdict_reasons: list[str] = field(default_factory=list, init=False)

    def __post_init__(self):
        self.verdict, self.verdict_reasons = _compute_auto_verdict(self)

    # ── 편의 프로퍼티 ────────────────────────────────

    @property
    def quality_verdict(self) -> str:
        """
        세분화된 품질 판정 문자열 (내부 분석용)
          INVALID   — EXPLAIN PLAN 실패 (문법 오류 등)
          IMPROVED  — Cost 감소 + 회귀 없음
          REGRESSED — 새로운 HIGH 이슈 발생
          NEUTRAL   — 변화 없음 또는 판단 불가
          WARNING   — Cost 증가이나 회귀는 없음
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
        """자동 판정 한국어 레이블 (색상 표시용)"""
        return {
            'APPROVE': '✅ 승인 — 튜닝 효과 확인',
            'REVIEW':  '🔍 검토 필요',
            'REJECT':  '❌ 반려',
        }.get(self.verdict, self.verdict)

    @property
    def quality_verdict_label(self) -> str:
        """세분화 품질 판정 한국어 레이블"""
        return {
            'INVALID':   '❌ 문법 오류 — 실행 불가',
            'REGRESSED': '⚠️ 회귀 — 새로운 HIGH 이슈 발생',
            'IMPROVED':  '✅ 개선됨',
            'WARNING':   '⚠️ 주의 — Cost 증가',
            'NEUTRAL':   'ℹ️ 변화 없음',
        }.get(self.quality_verdict, self.quality_verdict)

    @property
    def cost_improved(self) -> bool:
        """Cost 가 감소한 경우 True"""
        return self.cost_delta_pct is not None and self.cost_delta_pct < 0

    @property
    def has_regression(self) -> bool:
        """HIGH 심각도 신규 이슈가 생긴 경우 True"""
        return any(i.severity == 'HIGH' for i in self.new_issues)

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

    @property
    def elapsed_summary(self) -> str:
        """실행시간 비교 한 줄 요약"""
        if self.original_elapsed_ms is None or self.tuned_elapsed_ms is None:
            return '실행시간 정보 없음'
        delta = self.elapsed_delta_pct
        sign = '+' if delta >= 0 else ''
        return (
            f"원본 실행시간: {self.original_elapsed_ms:.1f}ms  →  "
            f"튜닝 실행시간: {self.tuned_elapsed_ms:.1f}ms  "
            f"({sign}{delta:.1f}%)"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 검증기
# ──────────────────────────────────────────────────────────────────────────────

class TuningValidator:
    """
    원본 SQL 과 튜닝 SQL 의 실행 계획을 비교하여 ValidationResult 를 반환합니다.
    DB 에 연결된 OracleClient 인스턴스가 필요합니다.
    """

    def __init__(self, client: OracleClient):
        self._client = client

    # ------------------------------------------------------------------
    # SQL 전처리
    # ------------------------------------------------------------------

    @staticmethod
    def _preprocess(sql: str) -> str:
        """세미콜론 제거 + 앞뒤 공백 제거"""
        return sql.strip().rstrip(';').strip()

    def validate(
        self,
        original_sql: str,
        tuned_sql: str,
        measure_time: bool = False,
    ) -> ValidationResult:
        """
        두 SQL 의 실행 계획을 비교합니다.
        measure_time=True 시 SELECT 를 직접 실행해 실행시간(ms)도 측정합니다.
        DB 미연결 또는 권한 없음 시 is_valid=False 로 반환합니다.
        """
        original_sql = self._preprocess(original_sql)
        tuned_sql = self._preprocess(tuned_sql)

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

        # ── 실행시간 측정 (옵션) ───────────────────
        orig_elapsed: Optional[float] = None
        tuned_elapsed: Optional[float] = None
        elapsed_delta: Optional[float] = None

        if measure_time:
            orig_elapsed, err = self._measure_elapsed(original_sql)
            if err:
                return ValidationResult(
                    is_valid=False,
                    error_message=f'원본 SQL 실행시간 측정 오류:\n{err}',
                    original_xplan=orig_xplan,
                    tuned_xplan=tuned_xplan,
                )
            tuned_elapsed, err = self._measure_elapsed(tuned_sql)
            if err:
                return ValidationResult(
                    is_valid=False,
                    error_message=f'튜닝 SQL 실행시간 측정 오류:\n{err}',
                    original_xplan=orig_xplan,
                    tuned_xplan=tuned_xplan,
                )
            elapsed_delta = self._calc_delta_float(orig_elapsed, tuned_elapsed)

        return ValidationResult(
            is_valid=True,
            original_cost=orig_cost,
            tuned_cost=tuned_cost,
            cost_delta_pct=cost_delta_pct,
            original_issues=original_issues,
            tuned_issues=tuned_issues,
            resolved_issues=resolved,
            new_issues=new,
            original_elapsed_ms=orig_elapsed,
            tuned_elapsed_ms=tuned_elapsed,
            elapsed_delta_pct=elapsed_delta,
            original_xplan=orig_xplan,
            tuned_xplan=tuned_xplan,
        )

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _measure_elapsed(self, sql: str) -> tuple[Optional[float], str]:
        """
        SQL 을 실행하고 (elapsed_ms, error_message) 를 반환합니다.
        SELECT / WITH 가 아닌 DML 은 client.execute_sql() 의 가드에 의해 거부됩니다.
        성공 시 error_message 는 빈 문자열입니다.
        """
        try:
            _, _, elapsed_ms, _ = self._client.execute_sql(sql)
            return elapsed_ms, ''
        except Exception as e:
            return None, str(e)

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

    @staticmethod
    def _calc_delta_float(orig: Optional[float], tuned: Optional[float]) -> Optional[float]:
        """실수 값의 변화율(%) 계산. 원본 값이 0 이하이면 None."""
        if orig is None or tuned is None:
            return None
        if orig <= 0:
            return None
        return round((tuned - orig) / orig * 100, 1)
