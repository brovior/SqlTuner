"""
복합 SQL 분석기 — Regex 사전 점검 + AST 구조 분석 순차 실행 + 결과 병합

설계 의도:
  - RegexAnalyzer : "이 쿼리는 위험하다"를 빠르게 잡는 사전 점검 용도
  - AstAnalyzer   : SQL 구조를 정확히 분석해서 어떤 부분을 어떻게 바꿀지 판단

사용 흐름:
  1. [사전 점검] RegexAnalyzer.analyze() — 항상 실행, 빠른 위험 패턴 탐지
  2. [구조 분석] AstAnalyzer.analyze()   — 항상 시도, sqlglot 파싱 실패 시 건너뜀
  3. 두 결과를 병합 후 (category, title) 기준 중복 제거
     - 동일 이슈는 AST 결과를 우선 유지 (더 정밀한 설명 포함 가능)
  4. 사용된 엔진 상태를 _last_engine 에 기록 (UI 표시용)
"""
from __future__ import annotations
from .base import SqlAnalyzer, SqlIssue
from .ast_analyzer import AstAnalyzer
from .regex_analyzer import RegexAnalyzer


class CompositeAnalyzer(SqlAnalyzer):
    """
    Regex 사전 점검 후 AST 구조 분석을 순차 실행합니다.
    두 엔진이 같은 (category, title) 이슈를 중복 반환하는 경우
    AST 결과를 우선하고 Regex 결과를 제거합니다.
    """

    def __init__(self):
        self._ast = AstAnalyzer()
        self._regex = RegexAnalyzer()
        self._last_engine: str = ''   # 직전 analyze() 에서 실제 사용된 엔진 상태

    @property
    def engine_name(self) -> str:
        return self._last_engine or 'Composite (Regex → AST)'

    @property
    def last_engine(self) -> str:
        """직전 분석에 실제 사용된 엔진 상태 문자열"""
        return self._last_engine

    def analyze(self, sql: str) -> list[SqlIssue]:
        # ── ① 사전 점검: 규칙기반 빠른 위험 탐지 (항상 실행) ──────────────
        regex_issues = self._regex.analyze(sql)

        # ── ② 구조 분석: AST 기반 정밀 분석 (파싱 실패 시 건너뜀) ─────────
        ast_issues: list[SqlIssue] = []
        ast_ok = False
        try:
            ast_issues = self._ast.analyze(sql)
            ast_ok = True
        except Exception:
            pass

        # ── ③ 병합: AST 결과 우선, Regex 전용 이슈 추가 ─────────────────
        ast_keys = {(i.category, i.title) for i in ast_issues}
        regex_only = [i for i in regex_issues if (i.category, i.title) not in ast_keys]

        merged = ast_issues + regex_only

        # ── ④ 엔진 상태 기록 ─────────────────────────────────────────────
        if ast_ok:
            self._last_engine = 'Regex + AST'
        else:
            self._last_engine = 'Regex (AST 파싱 실패)'

        return self.sort_issues(self.deduplicate(merged))
