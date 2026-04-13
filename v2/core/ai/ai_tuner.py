"""
AI 기반 SQL 튜닝 모듈
AIProvider를 통해 SQL과 감지된 이슈를 전달하고 튜닝된 SQL을 받습니다.

tune() 에 전달할 수 있는 추가 컨텍스트:
  index_infos  : list[IndexInfo]      — 테이블별 현재 인덱스 목록 (5단계)
  stats_infos  : list[TableStatsInfo] — 테이블 통계 현황 (6단계)
  plan_rows    : list[PlanRow]        — EXPLAIN PLAN 행 목록
                  cardinality  → E-Rows(추정 행수)
                  actual_rows  → A-Rows(실제 행수, 실제 실행 시에만 존재)
"""
from __future__ import annotations
import re
from collections import defaultdict
from .ai_provider import AIProvider

# 소형 로컬 모델(Ollama 등)에서도 잘 동작하도록 지시를 구체적으로 작성
_SYSTEM_PROMPT = """\
You are an Oracle SQL tuning expert.
Return ONLY the optimized SQL query. No explanations outside the SQL.
Add -- comments inside the SQL to explain each change.
Do NOT use markdown code fences (```).
Do NOT add any text before or after the SQL.
The optimized SQL must return exactly the same result as the original.\
"""

# 카디널리티 오추정 경고 임계값 (A-Rows / E-Rows)
_CARDINALITY_WARN_RATIO = 100


class AiSqlTuner:
    def __init__(self, provider: AIProvider):
        self._provider = provider

    @property
    def is_available(self) -> bool:
        return self._provider.is_configured

    @property
    def provider_label(self) -> str:
        return self._provider.label

    def tune(
        self,
        sql: str,
        issues: list,
        db_version: str = '',
        *,
        index_infos: list | None = None,
        stats_infos: list | None = None,
        plan_rows: list | None = None,
    ) -> str:
        """
        Oracle SQL 튜닝을 AI에 요청하고 결과를 반환합니다.

        Parameters
        ----------
        sql         : 원본 SQL
        issues      : 감지된 이슈 목록 (SqlIssue / PlanIssue)
        db_version  : Oracle DB 버전 문자열 (없으면 빈 문자열)
        index_infos : 테이블별 인덱스 현황 (IndexInfo 목록)
        stats_infos : 테이블 통계 현황 (TableStatsInfo 목록)
        plan_rows   : EXPLAIN PLAN 행 목록 (cardinality=E-Rows, actual_rows=A-Rows)
        """
        if not self._provider.is_configured:
            raise RuntimeError(
                "AI 제공자가 설정되지 않았습니다.\n"
                "도구 모음의 'AI 설정' 버튼에서 설정하세요."
            )

        # ── 이슈 목록 ───────────────────────────────────────────────────
        if issues:
            issue_lines = [
                f'- [{i.severity}] {i.title}: {i.description.splitlines()[0]}'
                for i in issues
            ]
            issues_str = '\n'.join(issue_lines)
        else:
            issues_str = 'No issues detected'

        # ── 추가 컨텍스트 섹션 ──────────────────────────────────────────
        extra_sections: list[str] = []

        index_ctx = self._build_index_context(index_infos or [])
        if index_ctx:
            extra_sections.append(index_ctx)

        stats_ctx = self._build_stats_context(stats_infos or [])
        if stats_ctx:
            extra_sections.append(stats_ctx)

        card_ctx = self._build_cardinality_context(plan_rows or [])
        if card_ctx:
            extra_sections.append(card_ctx)

        extra_block = ('\n\n' + '\n\n'.join(extra_sections)) if extra_sections else ''

        # ── 최종 프롬프트 조합 ──────────────────────────────────────────
        version_line = f'[Database Version]\n{db_version}\n\n' if db_version else ''

        user = (
            f'Tune the following Oracle SQL.\n\n'
            f'{version_line}'
            f'[Original SQL]\n{sql}\n\n'
            f'[Detected performance issues]\n{issues_str}'
            f'{extra_block}\n\n'
            'Return ONLY the optimized SQL with -- comments explaining each change. '
            'No markdown, no explanation text outside the SQL.'
        )

        raw = self._provider.complete(_SYSTEM_PROMPT, user)
        return self._clean_output(raw)

    # ── 컨텍스트 빌더 ────────────────────────────────────────────────────

    @staticmethod
    def _build_index_context(index_infos: list) -> str:
        """
        인덱스 현황 섹션 문자열을 생성합니다.

        예:
          [인덱스 현황]
          - ORDERS: IDX_ORDERS_DATE(ORDER_DATE), IDX_ORDERS_CUST(CUSTOMER_ID, STATUS)
        """
        if not index_infos:
            return ''

        table_map: dict[str, list[str]] = defaultdict(list)
        for info in index_infos:
            col_str = ', '.join(info.columns)
            table_map[info.table_name].append(f'{info.index_name}({col_str})')

        lines = ['[인덱스 현황]']
        for table, idx_list in table_map.items():
            lines.append(f'- {table}: {", ".join(idx_list)}')
        return '\n'.join(lines)

    @staticmethod
    def _build_stats_context(stats_infos: list) -> str:
        """
        테이블 통계 현황 섹션 문자열을 생성합니다.

        예:
          [테이블 통계]
          - ORDERS: 1,200,000건, 마지막수집 88일 전 (오래됨)
        """
        if not stats_infos:
            return ''

        lines = ['[테이블 통계]']
        for info in stats_infos:
            num_rows_str = (
                f'{info.num_rows:,}건' if info.num_rows is not None else '건수 미상'
            )

            days = getattr(info, 'days_since_analyzed', None)
            last = getattr(info, 'last_analyzed', None)

            if last is None:
                age_str = '미수집'
            elif days is not None and days > 30:
                age_str = f'마지막수집 {days}일 전 (오래됨)'
            elif days is not None and days > 7:
                age_str = f'마지막수집 {days}일 전 (주의)'
            elif days is not None:
                age_str = f'마지막수집 {days}일 전'
            else:
                age_str = '날짜 미상'

            lines.append(f'- {info.table_name}: {num_rows_str}, {age_str}')
        return '\n'.join(lines)

    @staticmethod
    def _build_cardinality_context(plan_rows: list) -> str:
        """
        카디널리티 오추정 섹션 문자열을 생성합니다.

        PlanRow.cardinality = E-Rows (EXPLAIN PLAN 추정치)
        PlanRow.actual_rows = A-Rows (실제 실행 시에만 존재, 없으면 건너뜀)

        비율 = A-Rows / E-Rows ≥ 100 인 경우만 표시.

        예:
          [카디널리티 오추정]
          - ORDERS: E-Rows=1, A-Rows=98,432 (98432배 오추정)
        """
        if not plan_rows:
            return ''

        lines: list[str] = []
        for row in plan_rows:
            e_rows = getattr(row, 'cardinality', None)
            a_rows = getattr(row, 'actual_rows', None)
            table  = getattr(row, 'object_name', '') or ''

            if e_rows is None or a_rows is None or not table:
                continue
            if e_rows <= 0:
                continue

            ratio = a_rows / e_rows
            if ratio >= _CARDINALITY_WARN_RATIO:
                lines.append(
                    f'- {table}: E-Rows={e_rows:,}, A-Rows={a_rows:,}'
                    f' ({int(ratio)}배 오추정)'
                )

        if not lines:
            return ''
        return '[카디널리티 오추정]\n' + '\n'.join(lines)

    @staticmethod
    def _clean_output(text: str) -> str:
        """모델 응답에서 마크다운 코드 펜스 등 불필요한 래퍼를 제거합니다."""
        # ```sql ... ``` 또는 ``` ... ``` 블록 추출
        fence = re.search(r'```(?:sql)?\s*\n?(.*?)```', text, re.DOTALL | re.IGNORECASE)
        if fence:
            return fence.group(1).strip()
        # 펜스가 없으면 앞뒤 공백만 정리
        return text.strip()
