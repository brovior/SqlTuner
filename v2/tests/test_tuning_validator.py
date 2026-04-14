"""
TuningValidator 단위 테스트

OracleClient 를 Mock 으로 대체해 DB 없이 검증 로직을 테스트합니다.
"""
import pytest
from unittest.mock import MagicMock

from v2.core.db.oracle_client import PlanRow
from v2.core.pipeline.validation import TuningValidator, ValidationResult


# ── 헬퍼 ──────────────────────────────────────────────────────────


def make_row(
    id: int,
    operation: str = 'SELECT STATEMENT',
    options: str = '',
    object_name: str = '',
    parent_id=None,
    cost: int = 100,
    cardinality: int = 1000,
    depth: int = 0,
) -> PlanRow:
    return PlanRow(
        id=id,
        parent_id=parent_id,
        operation=operation,
        options=options,
        object_name=object_name,
        cost=cost,
        cardinality=cardinality,
        bytes=8000,
        cpu_cost=None,
        io_cost=None,
        depth=depth,
    )


def _make_client(orig_rows, orig_xplan='', tuned_rows=None, tuned_xplan='',
                 tuned_side_effect=None) -> MagicMock:
    """explain_plan 을 흉내내는 Mock OracleClient 생성"""
    client = MagicMock()
    client.is_connected = True

    if tuned_side_effect is not None:
        client.explain_plan.side_effect = [
            (orig_rows, orig_xplan),
            tuned_side_effect,
        ]
    else:
        client.explain_plan.side_effect = [
            (orig_rows, orig_xplan),
            (tuned_rows, tuned_xplan),
        ]
    return client


# ── SQL 전처리 ────────────────────────────────────────────────────


def test_preprocess_strips_semicolon_and_whitespace():
    """세미콜론과 공백이 제거되어야 한다"""
    cleaned = TuningValidator._preprocess("  SELECT 1 FROM DUAL;  ")
    assert cleaned == "SELECT 1 FROM DUAL"


def test_preprocess_no_semicolon_unchanged():
    sql = "SELECT * FROM EMP"
    assert TuningValidator._preprocess(sql) == sql


# ── 정상 비교 (cost 개선) ─────────────────────────────────────────


def test_validate_cost_improved():
    """튜닝 후 Cost 가 감소하면 quality_verdict=IMPROVED"""
    orig_rows = [
        make_row(1, 'SELECT STATEMENT', cost=200),
        make_row(2, 'TABLE ACCESS', 'FULL', 'EMP', parent_id=1, cost=200, depth=1),
    ]
    tuned_rows = [
        make_row(1, 'SELECT STATEMENT', cost=50),
        make_row(2, 'TABLE ACCESS', 'BY INDEX ROWID', 'EMP', parent_id=1,
                 cost=50, depth=1),
        make_row(3, 'INDEX', 'RANGE SCAN', 'EMP_IDX', parent_id=2,
                 cost=5, depth=2),
    ]

    client = _make_client(orig_rows, tuned_rows=tuned_rows)
    result = TuningValidator(client).validate(
        'SELECT * FROM EMP WHERE ID = 1',
        'SELECT /*+ INDEX(EMP EMP_IDX) */ * FROM EMP WHERE ID = 1',
    )

    assert result.is_valid is True
    assert result.original_cost == 200
    assert result.tuned_cost == 50
    assert result.cost_delta_pct == pytest.approx(-75.0)
    assert result.quality_verdict == 'IMPROVED'
    assert result.cost_improved is True


def test_validate_resolved_issues_detected():
    """원본의 FTS 이슈가 튜닝 후 사라지면 resolved_issues 에 포함"""
    orig_rows = [
        make_row(1, 'SELECT STATEMENT', cost=500, cardinality=100_000),
        make_row(2, 'TABLE ACCESS', 'FULL', 'BIG_TABLE', parent_id=1,
                 cost=500, cardinality=100_000, depth=1),
    ]
    tuned_rows = [
        make_row(1, 'SELECT STATEMENT', cost=10),
        make_row(2, 'TABLE ACCESS', 'BY INDEX ROWID', 'BIG_TABLE',
                 parent_id=1, cost=10, depth=1),
        make_row(3, 'INDEX', 'RANGE SCAN', 'BIG_IDX', parent_id=2,
                 cost=3, depth=2),
    ]

    client = _make_client(orig_rows, tuned_rows=tuned_rows)
    result = TuningValidator(client).validate(
        'SELECT * FROM BIG_TABLE',
        'SELECT /*+ INDEX(BIG_TABLE BIG_IDX) */ * FROM BIG_TABLE WHERE ID = 1',
    )

    assert result.is_valid is True
    assert len(result.resolved_issues) > 0
    assert len(result.new_issues) == 0


# ── tuned_sql 문법 오류 ───────────────────────────────────────────


def test_validate_tuned_sql_syntax_error():
    """tuned_sql EXPLAIN PLAN 실패 시 is_valid=False, ORA 오류 메시지 포함"""
    orig_rows = [make_row(1, 'SELECT STATEMENT', cost=100)]

    ora_error = Exception('ORA-00923: FROM keyword not found where expected')
    client = _make_client(orig_rows, tuned_side_effect=ora_error)

    result = TuningValidator(client).validate(
        'SELECT * FROM EMP',
        'SELECT FROM EMP',
    )

    assert result.is_valid is False
    assert 'ORA-00923' in result.error_message
    assert result.quality_verdict == 'INVALID'
    assert result.verdict == 'REJECT'
    assert any('문법 오류' in r for r in result.verdict_reasons)


# ── DB 미연결 ─────────────────────────────────────────────────────


def test_validate_not_connected():
    """DB 미연결 시 즉시 is_valid=False 반환"""
    client = MagicMock()
    client.is_connected = False

    result = TuningValidator(client).validate('SELECT 1 FROM DUAL', 'SELECT 1 FROM DUAL')

    assert result.is_valid is False
    assert '연결' in result.error_message
    client.explain_plan.assert_not_called()


# ── cost_delta_pct 경계값 ─────────────────────────────────────────


def test_validate_zero_original_cost_no_delta():
    """원본 Cost 가 0 이면 cost_delta_pct = None"""
    orig_rows = [make_row(1, 'SELECT STATEMENT', cost=0)]
    tuned_rows = [make_row(1, 'SELECT STATEMENT', cost=10)]

    client = _make_client(orig_rows, tuned_rows=tuned_rows)
    result = TuningValidator(client).validate('SELECT 1 FROM DUAL', 'SELECT 1 FROM DUAL')

    assert result.cost_delta_pct is None
    assert result.quality_verdict == 'NEUTRAL'


def test_validate_cost_increase_verdict_warning():
    """튜닝 후 Cost 100% 증가 → quality_verdict=WARNING, verdict=REJECT"""
    orig_rows = [make_row(1, 'SELECT STATEMENT', cost=100)]
    tuned_rows = [make_row(1, 'SELECT STATEMENT', cost=200)]

    client = _make_client(orig_rows, tuned_rows=tuned_rows)
    result = TuningValidator(client).validate('SELECT 1 FROM DUAL', 'SELECT 1 FROM DUAL')

    assert result.cost_delta_pct == pytest.approx(100.0)
    assert result.quality_verdict == 'WARNING'
    assert result.verdict == 'REJECT'
    assert any('증가' in r for r in result.verdict_reasons)


# ── measure_time 기본값 (False) ───────────────────────────────────


def test_validate_measure_time_false_no_elapsed():
    """measure_time=False(기본값) 시 elapsed 필드가 모두 None 이어야 한다"""
    orig_rows = [make_row(1, 'SELECT STATEMENT', cost=100)]
    tuned_rows = [make_row(1, 'SELECT STATEMENT', cost=80)]

    client = _make_client(orig_rows, tuned_rows=tuned_rows)
    result = TuningValidator(client).validate('SELECT 1 FROM DUAL', 'SELECT 1 FROM DUAL')

    assert result.original_elapsed_ms is None
    assert result.tuned_elapsed_ms is None
    assert result.elapsed_delta_pct is None
    client.execute_sql.assert_not_called()


# ── 세미콜론 포함 SQL ─────────────────────────────────────────────


def test_validate_semicolon_in_sql_is_stripped():
    """세미콜론 포함 SQL 도 explain_plan 에 정상 전달(세미콜론 없이)"""
    orig_rows = [make_row(1, 'SELECT STATEMENT', cost=100)]
    tuned_rows = [make_row(1, 'SELECT STATEMENT', cost=80)]

    client = _make_client(orig_rows, tuned_rows=tuned_rows)
    TuningValidator(client).validate('SELECT 1 FROM DUAL;', 'SELECT 1 FROM DUAL;')

    for call in client.explain_plan.call_args_list:
        sql_arg = call[0][0]
        assert not sql_arg.endswith(';'), f"세미콜론이 남아 있음: {sql_arg!r}"


# ── 자동 판정 (APPROVE / REVIEW / REJECT) ────────────────────────


def test_auto_verdict_approve():
    """비용 10% 이상 감소 + 이슈 해소 + 신규 이슈 없음 → APPROVE"""
    # 원본: 대형 FTS (이슈 발생)
    orig_rows = [
        make_row(1, 'SELECT STATEMENT', cost=1000, cardinality=100_000),
        make_row(2, 'TABLE ACCESS', 'FULL', 'BIG_TABLE', parent_id=1,
                 cost=1000, cardinality=100_000, depth=1),
    ]
    # 튜닝: INDEX RANGE SCAN (이슈 없음, cost -95%)
    tuned_rows = [
        make_row(1, 'SELECT STATEMENT', cost=50),
        make_row(2, 'TABLE ACCESS', 'BY INDEX ROWID', 'BIG_TABLE',
                 parent_id=1, cost=50, depth=1),
        make_row(3, 'INDEX', 'RANGE SCAN', 'BIG_IDX', parent_id=2,
                 cost=5, depth=2),
    ]

    client = _make_client(orig_rows, tuned_rows=tuned_rows)
    result = TuningValidator(client).validate(
        'SELECT * FROM BIG_TABLE',
        'SELECT /*+ INDEX(BIG_TABLE BIG_IDX) */ * FROM BIG_TABLE WHERE ID = 1',
    )

    assert result.verdict == 'APPROVE'
    assert len(result.resolved_issues) > 0
    assert len(result.new_issues) == 0
    assert any('감소' in r for r in result.verdict_reasons)
    assert any('신규 이슈 없음' in r for r in result.verdict_reasons)


def test_auto_verdict_review():
    """소폭 Cost 감소(-3%) + 이슈 변화 없음 → REVIEW"""
    orig_rows = [make_row(1, 'SELECT STATEMENT', cost=100)]
    tuned_rows = [make_row(1, 'SELECT STATEMENT', cost=97)]

    client = _make_client(orig_rows, tuned_rows=tuned_rows)
    result = TuningValidator(client).validate('SELECT 1 FROM DUAL', 'SELECT 1 FROM DUAL')

    assert result.verdict == 'REVIEW'
    assert result.cost_delta_pct == pytest.approx(-3.0)
    assert len(result.verdict_reasons) > 0


def test_auto_verdict_reject_cost_increase():
    """비용 10% 초과 증가 → REJECT, 이유에 '증가' 포함"""
    orig_rows = [make_row(1, 'SELECT STATEMENT', cost=100)]
    tuned_rows = [make_row(1, 'SELECT STATEMENT', cost=150)]   # +50%

    client = _make_client(orig_rows, tuned_rows=tuned_rows)
    result = TuningValidator(client).validate('SELECT 1 FROM DUAL', 'SELECT 1 FROM DUAL')

    assert result.verdict == 'REJECT'
    assert any('증가' in r for r in result.verdict_reasons)
