"""
sql_utils.inject_hint 단위 테스트
"""
import pytest
from v2.utils.sql_utils import inject_hint


# ── ① SELECT 힌트 없음 → 새 힌트 블록 삽입 ──────────────────────────

def test_no_existing_hint():
    sql = "SELECT id, name FROM employees"
    result = inject_hint(sql, 'GATHER_PLAN_STATISTICS')
    assert result == "SELECT /*+ GATHER_PLAN_STATISTICS */ id, name FROM employees"


# ── ② SELECT 기존 힌트 있음 → 기존 블록 안에 추가 ───────────────────

def test_existing_hint_appended():
    sql = "SELECT /*+ FULL(e) */ id FROM employees e"
    result = inject_hint(sql, 'GATHER_PLAN_STATISTICS')
    assert '/*+' in result
    assert 'FULL(e)' in result
    assert 'GATHER_PLAN_STATISTICS' in result
    # 힌트 블록이 두 개로 분리되지 않아야 한다
    assert result.count('/*+') == 1


# ── ③ 앞뒤 공백/개행 처리 ────────────────────────────────────────────

def test_leading_trailing_whitespace():
    sql = "  \n  SELECT id FROM t  \n  "
    result = inject_hint(sql, 'INDEX(t idx)')
    # strip 후 처리되어 힌트가 정상 삽입된다
    assert '/*+ INDEX(t idx) */' in result
    # SELECT 로 시작해야 한다 (앞 공백 제거)
    assert result.startswith('SELECT')


# ── ④ SELECT 외 구문은 원본 그대로 반환 ─────────────────────────────

def test_non_select_returned_as_is():
    statements = [
        "UPDATE employees SET salary = 1000",
        "DELETE FROM employees WHERE id = 1",
        "INSERT INTO t VALUES (1)",
        "BEGIN NULL; END;",
    ]
    for sql in statements:
        assert inject_hint(sql, 'GATHER_PLAN_STATISTICS') == sql
