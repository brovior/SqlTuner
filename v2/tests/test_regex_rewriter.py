"""
RegexRewriter 단위 테스트

OR→IN, NOT IN→NOT EXISTS, UNION→UNION ALL 변환을 검증합니다.
파싱 실패 없이 항상 결과를 반환해야 합니다.
"""
import pytest
from v2.core.rewrite.regex_rewriter import RegexRewriter


@pytest.fixture
def rw():
    return RegexRewriter()


# ── OR → IN ──────────────────────────────────────────────────────

def test_or_to_in_two_values(rw):
    sql = "SELECT * FROM emp WHERE deptno = 10 OR deptno = 20"
    result = rw.rewrite(sql)
    assert 'IN' in result.rewritten_sql.upper()
    assert result.has_changes
    assert any('OR' in c and 'IN' in c for c in result.changes), result.changes


def test_or_to_in_string_values(rw):
    sql = "SELECT * FROM emp WHERE job = 'CLERK' OR job = 'MANAGER' OR job = 'ANALYST'"
    result = rw.rewrite(sql)
    assert 'IN' in result.rewritten_sql.upper()
    assert result.has_changes


def test_or_different_columns_no_change(rw):
    sql = "SELECT * FROM emp WHERE deptno = 10 OR empno = 20"
    result = rw.rewrite(sql)
    assert not any('OR' in c and 'IN' in c for c in result.changes)


# ── NOT IN → NOT EXISTS ───────────────────────────────────────────

def test_not_in_to_not_exists_simple(rw):
    sql = "SELECT * FROM emp WHERE deptno NOT IN (SELECT deptno FROM dept)"
    result = rw.rewrite(sql)
    assert 'NOT EXISTS' in result.rewritten_sql.upper()
    assert result.has_changes
    assert any('NOT IN' in c for c in result.changes), result.changes


def test_not_in_with_alias(rw):
    sql = "SELECT * FROM emp WHERE deptno NOT IN (SELECT deptno FROM dept d)"
    result = rw.rewrite(sql)
    assert 'NOT EXISTS' in result.rewritten_sql.upper()


def test_not_in_with_where(rw):
    sql = "SELECT * FROM emp WHERE deptno NOT IN (SELECT deptno FROM dept WHERE loc = 'NY')"
    result = rw.rewrite(sql)
    assert 'NOT EXISTS' in result.rewritten_sql.upper()
    assert 'loc' in result.rewritten_sql.lower() or 'LOC' in result.rewritten_sql


# ── UNION → UNION ALL ────────────────────────────────────────────

def test_union_to_union_all(rw):
    sql = (
        "SELECT ename FROM emp WHERE deptno = 10 "
        "UNION "
        "SELECT ename FROM emp WHERE deptno = 20"
    )
    result = rw.rewrite(sql)
    assert 'UNION ALL' in result.rewritten_sql.upper()
    assert result.has_changes


def test_union_all_not_doubled(rw):
    """UNION ALL 는 재변환하지 않아야 한다"""
    sql = (
        "SELECT ename FROM emp WHERE deptno = 10 "
        "UNION ALL "
        "SELECT ename FROM emp WHERE deptno = 20"
    )
    result = rw.rewrite(sql)
    assert not result.has_changes


# ── 복수 변환 동시 적용 ───────────────────────────────────────────

def test_multiple_transforms(rw):
    sql = (
        "SELECT * FROM emp WHERE deptno = 10 OR deptno = 20 "
        "UNION "
        "SELECT * FROM emp WHERE deptno NOT IN (SELECT deptno FROM dept)"
    )
    result = rw.rewrite(sql)
    assert len(result.changes) >= 2


# ── 변환 없는 SQL ────────────────────────────────────────────────

def test_no_changes(rw):
    sql = "SELECT empno, ename FROM emp WHERE deptno = 10"
    result = rw.rewrite(sql)
    assert not result.has_changes
    assert result.changes == []


# ── RewriteResult 메타 ────────────────────────────────────────────

def test_engine_name(rw):
    result = rw.rewrite("SELECT 1 FROM dual")
    assert '정규식' in result.engine_used or 'Regex' in result.engine_used


def test_original_preserved(rw):
    sql = "SELECT * FROM emp WHERE deptno = 10 OR deptno = 20"
    result = rw.rewrite(sql)
    assert result.original_sql == sql


# ── 잘못된 SQL 도 오류 없이 처리 ─────────────────────────────────

def test_invalid_sql_no_exception(rw):
    """Regex 엔진은 파싱하지 않으므로 예외 없이 원본을 반환해야 한다"""
    result = rw.rewrite("THIS IS NOT SQL @@ !!")
    assert result.rewritten_sql is not None
