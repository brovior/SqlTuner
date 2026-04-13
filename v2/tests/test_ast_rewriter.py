"""
AstRewriter 단위 테스트

OR→IN, NOT IN→NOT EXISTS, UNION→UNION ALL, 스칼라 서브쿼리→LEFT JOIN 변환을 검증합니다.
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


# ── 스칼라 서브쿼리 → LEFT JOIN ───────────────────────────────────

def test_scalar_subquery_simple_converted(rw):
    """단순 스칼라 서브쿼리 → LEFT JOIN 변환"""
    sql = "SELECT A.ID, (SELECT B.NAME FROM B WHERE B.ID = A.ID) AS BNAME FROM A"
    result = rw.rewrite(sql)
    assert result.has_changes
    assert 'LEFT JOIN' in result.rewritten_sql.upper()
    assert 'BNAME' in result.rewritten_sql.upper()
    # 원본 서브쿼리 구조 제거됐는지 확인
    assert '(SELECT' not in result.rewritten_sql.upper().replace(' ', '').replace('\n', '')


def test_scalar_subquery_alias_preserved(rw):
    """outer alias 가 LEFT JOIN 결과 컬럼에 유지됨"""
    sql = "SELECT A.ID, (SELECT B.VAL FROM B WHERE B.ID = A.ID) AS MY_VAL FROM A"
    result = rw.rewrite(sql)
    assert 'MY_VAL' in result.rewritten_sql.upper()
    assert 'LEFT JOIN' in result.rewritten_sql.upper()


def test_scalar_subquery_with_table_alias(rw):
    """FROM 테이블 alias 포함 서브쿼리 변환 (실제 쿼리 패턴)"""
    sql = (
        "SELECT O.ORDER_ID, O.TOTAL_AMOUNT, "
        "(SELECT C.CUSTOMER_NAME FROM TUNING_CUSTOMER C "
        " WHERE C.CUSTOMER_ID = O.CUSTOMER_ID) AS CUST_NAME "
        "FROM TUNING_ORDERS O "
        "WHERE O.ORDER_DATE >= SYSDATE - 30"
    )
    result = rw.rewrite(sql)
    assert result.has_changes
    sql_up = result.rewritten_sql.upper()
    assert 'LEFT JOIN' in sql_up
    assert 'TUNING_CUSTOMER' in sql_up
    assert 'CUST_NAME' in sql_up
    # WHERE 절 보존
    assert 'ORDER_DATE' in sql_up


def test_scalar_subquery_change_log_mentions_table(rw):
    """변환 로그에 조인 대상 테이블명이 포함된다"""
    sql = "SELECT A.ID, (SELECT B.NAME FROM B WHERE B.ID = A.ID) AS BNAME FROM A"
    result = rw.rewrite(sql)
    assert any('LEFT JOIN' in c and 'B' in c for c in result.changes), result.changes


def test_scalar_subquery_two_subqueries_both_converted(rw):
    """SELECT 절에 스칼라 서브쿼리 2개 → 모두 LEFT JOIN 으로 변환"""
    sql = (
        "SELECT A.ID, "
        "(SELECT B.NAME FROM B WHERE B.ID = A.ID) AS BNAME, "
        "(SELECT C.VAL  FROM C WHERE C.ID = A.ID) AS CVAL  "
        "FROM A"
    )
    result = rw.rewrite(sql)
    assert result.rewritten_sql.upper().count('LEFT JOIN') == 2
    assert any('B' in c for c in result.changes)
    assert any('C' in c for c in result.changes)


def test_scalar_subquery_complex_aggregation_warned(rw):
    """집계함수 포함 서브쿼리 → 변환 안 하고 경고 change 추가"""
    sql = (
        "SELECT A.ID, "
        "(SELECT COUNT(*) FROM B WHERE B.A_ID = A.ID) AS CNT "
        "FROM A"
    )
    result = rw.rewrite(sql)
    # 변환 안 됨
    assert 'LEFT JOIN' not in result.rewritten_sql.upper()
    # 경고 change 는 추가됨
    assert any('경고' in c or '복잡' in c for c in result.changes), result.changes


def test_scalar_subquery_complex_group_by_warned(rw):
    """GROUP BY 포함 서브쿼리 → 경고"""
    sql = (
        "SELECT A.ID, "
        "(SELECT MAX(B.VAL) FROM B WHERE B.ID = A.ID GROUP BY B.TYPE) AS MX "
        "FROM A"
    )
    result = rw.rewrite(sql)
    assert 'LEFT JOIN' not in result.rewritten_sql.upper()
    assert any('경고' in c or '복잡' in c for c in result.changes), result.changes


def test_scalar_subquery_no_where_warned(rw):
    """WHERE 없는 서브쿼리 → 경고 (조인 조건 판단 불가)"""
    sql = "SELECT A.ID, (SELECT B.NAME FROM B) AS BNAME FROM A"
    result = rw.rewrite(sql)
    assert 'LEFT JOIN' not in result.rewritten_sql.upper()
    assert any('경고' in c or '복잡' in c for c in result.changes), result.changes


def test_scalar_subquery_no_subquery_no_change(rw):
    """스칼라 서브쿼리 없는 쿼리 → PAGING 관련 변경 없음"""
    sql = "SELECT A.ID, A.NAME FROM A WHERE A.STATUS = 'Y'"
    result = rw.rewrite(sql)
    assert not any('LEFT JOIN' in c for c in result.changes)
    assert 'LEFT JOIN' not in result.rewritten_sql.upper()


def test_scalar_subquery_original_sql_preserved(rw):
    """original_sql 필드는 항상 입력 SQL 그대로"""
    sql = "SELECT A.ID, (SELECT B.NAME FROM B WHERE B.ID = A.ID) AS BN FROM A"
    result = rw.rewrite(sql)
    assert result.original_sql == sql


# ── IN 서브쿼리 → JOIN ────────────────────────────────────────────

def test_in_subquery_to_join_converted(rw):
    """단순 IN 서브쿼리 → JOIN 변환"""
    sql = "SELECT * FROM A WHERE A.ID IN (SELECT ID FROM B WHERE B.STATUS = 'Y')"
    result = rw.rewrite(sql)
    assert result.has_changes
    sql_up = result.rewritten_sql.upper()
    assert 'JOIN' in sql_up
    assert 'A.ID' in sql_up
    assert "STATUS" in sql_up
    assert any('IN 서브쿼리' in c and 'JOIN' in c for c in result.changes), result.changes


def test_in_subquery_group_by_warned(rw):
    """GROUP BY 포함 IN 서브쿼리 → 변환 안 하고 경고 change"""
    sql = (
        "SELECT * FROM A "
        "WHERE A.DEPT_ID IN (SELECT DEPT_ID FROM B GROUP BY DEPT_ID)"
    )
    result = rw.rewrite(sql)
    assert 'JOIN' not in result.rewritten_sql.upper().split('WHERE')[0]  # FROM 절에 JOIN 없음
    assert any('SUBQUERY_TO_JOIN' in c or '감지' in c or '복잡' in c
               for c in result.changes), result.changes
