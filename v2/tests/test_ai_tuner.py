"""
AiSqlTuner 단위 테스트

컨텍스트 빌더 3개 + tune() 통합 프롬프트 검증.
AI 제공자는 mock으로 대체하여 실제 API 호출 없이 테스트합니다.
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock
from types import SimpleNamespace

from v2.core.ai.ai_tuner import AiSqlTuner


# ──────────────────────────────────────────────────────────────────────────────
# 헬퍼 팩토리
# ──────────────────────────────────────────────────────────────────────────────

def _make_tuner(response: str = 'SELECT 1 FROM DUAL') -> AiSqlTuner:
    """AI 제공자를 mock으로 대체한 AiSqlTuner 반환."""
    provider = MagicMock()
    provider.is_configured = True
    provider.label = 'Mock'
    provider.complete.return_value = response
    return AiSqlTuner(provider)


def _index_info(table: str, index_name: str, columns: list[str]) -> SimpleNamespace:
    """IndexInfo 유사 객체 생성."""
    return SimpleNamespace(table_name=table, index_name=index_name, columns=columns)


def _stats_info(
    table: str,
    num_rows: int | None,
    days: int | None,
    last_analyzed=object(),  # None 구분을 위해 sentinel 사용
) -> SimpleNamespace:
    """TableStatsInfo 유사 객체 생성."""
    # last_analyzed 를 명시하지 않으면 days 기반으로 자동 설정
    from datetime import datetime, timedelta
    if isinstance(last_analyzed, type(object())):  # sentinel
        last_analyzed = (datetime.now() - timedelta(days=days)) if days is not None else None
    return SimpleNamespace(
        table_name=table,
        num_rows=num_rows,
        days_since_analyzed=days,
        last_analyzed=last_analyzed,
    )


def _plan_row(
    table: str,
    e_rows: int | None,
    a_rows: int | None = None,
) -> SimpleNamespace:
    """PlanRow 유사 객체 생성 (cardinality=E-Rows, actual_rows=A-Rows)."""
    return SimpleNamespace(
        object_name=table,
        cardinality=e_rows,
        actual_rows=a_rows,
    )


# ──────────────────────────────────────────────────────────────────────────────
# _build_index_context
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildIndexContext:

    def test_empty_list_returns_empty_string(self):
        assert AiSqlTuner._build_index_context([]) == ''

    def test_single_table_single_index(self):
        infos = [_index_info('ORDERS', 'IDX_DATE', ['ORDER_DATE'])]
        result = AiSqlTuner._build_index_context(infos)
        assert '[인덱스 현황]' in result
        assert 'ORDERS' in result
        assert 'IDX_DATE(ORDER_DATE)' in result

    def test_composite_index_columns_joined(self):
        infos = [_index_info('ORDERS', 'IDX_COMP', ['CUSTOMER_ID', 'STATUS'])]
        result = AiSqlTuner._build_index_context(infos)
        assert 'IDX_COMP(CUSTOMER_ID, STATUS)' in result

    def test_multiple_indexes_same_table(self):
        infos = [
            _index_info('ORDERS', 'IDX_DATE', ['ORDER_DATE']),
            _index_info('ORDERS', 'IDX_CUST', ['CUSTOMER_ID', 'STATUS']),
        ]
        result = AiSqlTuner._build_index_context(infos)
        # 같은 테이블 줄에 두 인덱스 모두 포함
        assert 'IDX_DATE' in result
        assert 'IDX_CUST' in result

    def test_multiple_tables_each_on_own_line(self):
        infos = [
            _index_info('ORDERS', 'IDX_O', ['ORDER_DATE']),
            _index_info('CUSTOMERS', 'IDX_C', ['CUST_ID']),
        ]
        result = AiSqlTuner._build_index_context(infos)
        lines = result.splitlines()
        order_lines = [l for l in lines if 'ORDERS' in l]
        cust_lines  = [l for l in lines if 'CUSTOMERS' in l]
        assert len(order_lines) == 1
        assert len(cust_lines)  == 1

    def test_header_line_is_first(self):
        infos = [_index_info('T', 'IDX', ['C'])]
        result = AiSqlTuner._build_index_context(infos)
        assert result.splitlines()[0] == '[인덱스 현황]'


# ──────────────────────────────────────────────────────────────────────────────
# _build_stats_context
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildStatsContext:

    def test_empty_list_returns_empty_string(self):
        assert AiSqlTuner._build_stats_context([]) == ''

    def test_header_present(self):
        infos = [_stats_info('ORDERS', 1000, 3)]
        assert '[테이블 통계]' in AiSqlTuner._build_stats_context(infos)

    def test_num_rows_formatted_with_comma(self):
        infos = [_stats_info('ORDERS', 1_200_000, 3)]
        result = AiSqlTuner._build_stats_context(infos)
        assert '1,200,000건' in result

    def test_num_rows_none_shows_unknown(self):
        infos = [_stats_info('ORDERS', None, None, last_analyzed=None)]
        result = AiSqlTuner._build_stats_context(infos)
        assert '건수 미상' in result

    def test_no_stats_shows_미수집(self):
        infos = [_stats_info('ORDERS', None, None, last_analyzed=None)]
        result = AiSqlTuner._build_stats_context(infos)
        assert '미수집' in result

    def test_over_30_days_shows_오래됨(self):
        infos = [_stats_info('ORDERS', 5000, 88)]
        result = AiSqlTuner._build_stats_context(infos)
        assert '오래됨' in result
        assert '88일' in result

    def test_7_to_30_days_shows_주의(self):
        infos = [_stats_info('ORDERS', 5000, 10)]
        result = AiSqlTuner._build_stats_context(infos)
        assert '주의' in result

    def test_within_7_days_no_warning_tag(self):
        infos = [_stats_info('ORDERS', 5000, 3)]
        result = AiSqlTuner._build_stats_context(infos)
        assert '오래됨' not in result
        assert '주의' not in result
        assert '미수집' not in result

    def test_multiple_tables_each_on_own_line(self):
        infos = [
            _stats_info('ORDERS', 1000, 3),
            _stats_info('CUSTOMERS', 500, 40),
        ]
        result = AiSqlTuner._build_stats_context(infos)
        lines = [l for l in result.splitlines() if l.startswith('-')]
        assert len(lines) == 2


# ──────────────────────────────────────────────────────────────────────────────
# _build_cardinality_context
# ──────────────────────────────────────────────────────────────────────────────

class TestBuildCardinalityContext:

    def test_empty_list_returns_empty_string(self):
        assert AiSqlTuner._build_cardinality_context([]) == ''

    def test_no_actual_rows_returns_empty(self):
        """actual_rows 없는 PlanRow → 빈 문자열 (현재 EXPLAIN PLAN 모드)"""
        rows = [_plan_row('ORDERS', e_rows=100, a_rows=None)]
        assert AiSqlTuner._build_cardinality_context(rows) == ''

    def test_ratio_below_100_not_shown(self):
        """A-Rows/E-Rows < 100 → 표시 안 함"""
        rows = [_plan_row('ORDERS', e_rows=100, a_rows=99)]
        assert AiSqlTuner._build_cardinality_context(rows) == ''

    def test_ratio_exactly_100_shown(self):
        """비율 정확히 100 → 표시"""
        rows = [_plan_row('ORDERS', e_rows=1, a_rows=100)]
        result = AiSqlTuner._build_cardinality_context(rows)
        assert 'ORDERS' in result
        assert '100배' in result

    def test_ratio_over_100_shown(self):
        """비율 100 초과 → 표시"""
        rows = [_plan_row('ORDERS', e_rows=1, a_rows=98432)]
        result = AiSqlTuner._build_cardinality_context(rows)
        assert 'ORDERS' in result
        assert 'E-Rows=1' in result
        assert 'A-Rows=98,432' in result
        assert '98432배' in result

    def test_header_present_when_mismatch_found(self):
        rows = [_plan_row('ORDERS', e_rows=1, a_rows=500)]
        result = AiSqlTuner._build_cardinality_context(rows)
        assert '[카디널리티 오추정]' in result

    def test_e_rows_zero_skipped(self):
        """E-Rows=0 → 나눗셈 불가, 스킵"""
        rows = [_plan_row('ORDERS', e_rows=0, a_rows=1000)]
        assert AiSqlTuner._build_cardinality_context(rows) == ''

    def test_no_table_name_skipped(self):
        """object_name 이 빈 문자열 → 스킵"""
        rows = [_plan_row('', e_rows=1, a_rows=1000)]
        assert AiSqlTuner._build_cardinality_context(rows) == ''

    def test_multiple_rows_only_over_threshold_shown(self):
        """임계값 미달 행은 포함 안 함"""
        rows = [
            _plan_row('A', e_rows=1, a_rows=500),   # 500배 → 포함
            _plan_row('B', e_rows=10, a_rows=50),   # 5배 → 미포함
        ]
        result = AiSqlTuner._build_cardinality_context(rows)
        assert 'A' in result
        assert 'B' not in result

    def test_e_rows_none_skipped(self):
        rows = [_plan_row('ORDERS', e_rows=None, a_rows=1000)]
        assert AiSqlTuner._build_cardinality_context(rows) == ''


# ──────────────────────────────────────────────────────────────────────────────
# tune() 통합 프롬프트 검증
# ──────────────────────────────────────────────────────────────────────────────

class TestTunePromptIntegration:

    def _get_user_prompt(self, tuner: AiSqlTuner, **kwargs) -> str:
        """provider.complete 의 두 번째 인자(user 프롬프트)를 꺼낸다."""
        tuner.tune('SELECT * FROM ORDERS', [], **kwargs)
        return tuner._provider.complete.call_args[0][1]

    def test_index_section_in_prompt_when_provided(self):
        tuner = _make_tuner()
        infos = [_index_info('ORDERS', 'IDX_DATE', ['ORDER_DATE'])]
        prompt = self._get_user_prompt(tuner, index_infos=infos)
        assert '[인덱스 현황]' in prompt
        assert 'IDX_DATE' in prompt

    def test_stats_section_in_prompt_when_provided(self):
        tuner = _make_tuner()
        infos = [_stats_info('ORDERS', 1_200_000, 88)]
        prompt = self._get_user_prompt(tuner, stats_infos=infos)
        assert '[테이블 통계]' in prompt
        assert '오래됨' in prompt

    def test_cardinality_section_in_prompt_when_provided(self):
        tuner = _make_tuner()
        rows = [_plan_row('ORDERS', e_rows=1, a_rows=98432)]
        prompt = self._get_user_prompt(tuner, plan_rows=rows)
        assert '[카디널리티 오추정]' in prompt
        assert '98432배' in prompt

    def test_no_extra_sections_when_all_none(self):
        tuner = _make_tuner()
        prompt = self._get_user_prompt(tuner)
        assert '[인덱스 현황]' not in prompt
        assert '[테이블 통계]' not in prompt
        assert '[카디널리티 오추정]' not in prompt

    def test_all_three_sections_present(self):
        tuner = _make_tuner()
        prompt = self._get_user_prompt(
            tuner,
            index_infos=[_index_info('ORDERS', 'IDX', ['C'])],
            stats_infos=[_stats_info('ORDERS', 1000, 40)],
            plan_rows=[_plan_row('ORDERS', 1, 50000)],
        )
        assert '[인덱스 현황]' in prompt
        assert '[테이블 통계]' in prompt
        assert '[카디널리티 오추정]' in prompt

    def test_original_sql_in_prompt(self):
        tuner = _make_tuner()
        tuner.tune('SELECT * FROM DUAL', [])
        prompt = tuner._provider.complete.call_args[0][1]
        assert 'SELECT * FROM DUAL' in prompt

    def test_db_version_in_prompt(self):
        tuner = _make_tuner()
        tuner.tune('SELECT 1 FROM DUAL', [], db_version='Oracle 19c')
        prompt = tuner._provider.complete.call_args[0][1]
        assert 'Oracle 19c' in prompt

    def test_not_configured_raises(self):
        provider = MagicMock()
        provider.is_configured = False
        tuner = AiSqlTuner(provider)
        with pytest.raises(RuntimeError):
            tuner.tune('SELECT 1 FROM DUAL', [])

    def test_clean_output_strips_fence(self):
        tuner = _make_tuner('```sql\nSELECT 1 FROM DUAL\n```')
        result = tuner.tune('SELECT 1 FROM DUAL', [])
        assert result == 'SELECT 1 FROM DUAL'

    def test_clean_output_no_fence(self):
        tuner = _make_tuner('SELECT 1 FROM DUAL')
        result = tuner.tune('SELECT 1 FROM DUAL', [])
        assert result == 'SELECT 1 FROM DUAL'
