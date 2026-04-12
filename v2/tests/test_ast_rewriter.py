"""
AstRewriter 단위 테스트

OR→IN, NOT IN→NOT EXISTS, UNION→UNION ALL 변환을 검증합니다.
"""
import pytest
from v2.core.rewrite.ast_rewriter import AstRewriter


@pytest.fixture
def rw():
    return AstRewriter()


# ── OR → IN ──────────────────────────────────────────────────────

def test_or_to_in_two_values(rw):
    sql = "SELECT * FROM emp WHERE deptno = 10 OR deptno = 20"
    result = rw.rewrite(sql)
    assert 'IN' in result.rewritten_sql.upper()
    assert result.has_changes
    assert any('OR' in c and 'IN' in c for c in result.changes), result.changes


def test_or_to_in_three_values(rw):
    sql = "SELECT * FROM emp WHERE deptno = 10 OR deptno = 20 OR deptno = 30"
    result = rw.rewrite(sql)
    assert 'IN' in result.rewritten_sql.upper()
    assert result.has_changes


def test_or_different_columns_no_change(rw):
    """다른 컬럼 OR는 IN으로 변환하지 않는다"""
    sql = "SELECT * FROM emp WHERE deptno = 10 OR empno = 20"
    result = rw.rewrite(sql)
    assert not any('OR' in c and 'IN' in c for c in result.changes)


# ── NOT IN → NOT EXISTS ───────────────────────────────────────────

def test_not_in_to_not_exists(rw):
    sql = "SELECT * FROM emp WHERE deptno NOT IN (SELECT deptno FROM dept)"
    result = rw.rewrite(sql)
    assert 'NOT EXISTS' in result.rewritten_sql.upper()
    assert result.has_changes
    assert any('NOT IN' in c and 'NOT EXISTS' in c for c in result.changes), result.changes


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
    assert any('UNION ALL' in c for c in result.changes), result.changes


def test_union_all_no_change(rw):
    sql = (
        "SELECT ename FROM emp WHERE deptno = 10 "
        "UNION ALL "
        "SELECT ename FROM emp WHERE deptno = 20"
    )
    result = rw.rewrite(sql)
    assert not any('UNION ALL' in c for c in result.changes)


# ── 변환 없는 SQL ────────────────────────────────────────────────

def test_no_changes(rw):
    sql = "SELECT empno, ename FROM emp WHERE deptno = 10"
    result = rw.rewrite(sql)
    assert not result.has_changes
    assert result.changes == []


# ── RewriteResult 메타 ────────────────────────────────────────────

def test_engine_name(rw):
    result = rw.rewrite("SELECT 1 FROM dual")
    assert 'AST' in result.engine_used or 'sqlglot' in result.engine_used.lower()


def test_original_preserved(rw):
    sql = "SELECT * FROM emp WHERE deptno = 10 OR deptno = 20"
    result = rw.rewrite(sql)
    assert result.original_sql == sql


# ── 파싱 실패 → Exception ─────────────────────────────────────────

def test_invalid_sql_raises(rw):
    with pytest.raises(Exception):
        rw.rewrite("THIS IS NOT @@ SQL !!")
