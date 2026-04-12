"""
AstAnalyzer 단위 테스트

각 규칙이 올바른 SQL 패턴을 감지하는지 검증합니다.
sqlglot 파싱이 불가능한 SQL은 ValueError 를 raise 해야 합니다.
"""
import pytest
from v2.core.analysis.ast_analyzer import AstAnalyzer


@pytest.fixture
def ana():
    return AstAnalyzer()


# ── 함수로 감싼 WHERE 컬럼 ────────────────────────────────────────

def test_where_function_upper(ana):
    sql = "SELECT * FROM emp WHERE UPPER(ename) = 'SMITH'"
    issues = ana.analyze(sql)
    titles = [i.title for i in issues]
    assert any('인덱스' in t or 'WHERE' in t or '함수' in t for t in titles), issues


def test_where_function_substr(ana):
    sql = "SELECT * FROM emp WHERE SUBSTR(col, 1, 3) = 'ABC'"
    issues = ana.analyze(sql)
    assert any('인덱스' in i.title or '함수' in i.title for i in issues), issues


def test_where_function_clean(ana):
    """함수 없이 단순 비교 — 인덱스 무효화 이슈 없어야 함"""
    sql = "SELECT ename FROM emp WHERE empno = 7788"
    issues = ana.analyze(sql)
    assert not any('인덱스' in i.title for i in issues)


# ── 묵시적 형변환 ────────────────────────────────────────────────

def test_implicit_conversion_detected(ana):
    sql = "SELECT * FROM emp WHERE empno = '7788'"
    issues = ana.analyze(sql)
    assert any('형변환' in i.title or '묵시적' in i.title for i in issues), issues


def test_implicit_conversion_string_ok(ana):
    """문자열 컬럼에 문자열 값 — 형변환 이슈 없어야 함"""
    sql = "SELECT * FROM emp WHERE ename = 'SMITH'"
    issues = ana.analyze(sql)
    assert not any('형변환' in i.title or '묵시적' in i.title for i in issues)


# ── NOT IN 서브쿼리 ──────────────────────────────────────────────

def test_not_in_subquery(ana):
    sql = "SELECT * FROM emp WHERE deptno NOT IN (SELECT deptno FROM dept)"
    issues = ana.analyze(sql)
    assert any('NOT IN' in i.title for i in issues), issues


def test_not_in_literal_list_no_issue(ana):
    """리터럴 목록 NOT IN — 서브쿼리 NULL 위험 없음"""
    sql = "SELECT * FROM emp WHERE deptno NOT IN (10, 20, 30)"
    issues = ana.analyze(sql)
    assert not any('NOT IN' in i.title for i in issues)


# ── LIKE 앞 와일드카드 ────────────────────────────────────────────

def test_like_leading_wildcard(ana):
    sql = "SELECT * FROM emp WHERE ename LIKE '%SMITH'"
    issues = ana.analyze(sql)
    assert any('LIKE' in i.title or '와일드카드' in i.title for i in issues), issues


def test_like_trailing_wildcard_ok(ana):
    sql = "SELECT * FROM emp WHERE ename LIKE 'SMITH%'"
    issues = ana.analyze(sql)
    assert not any('LIKE' in i.title and '와일드카드' in i.title for i in issues)


# ── SELECT * ─────────────────────────────────────────────────────

def test_select_star(ana):
    sql = "SELECT * FROM emp"
    issues = ana.analyze(sql)
    assert any('SELECT *' in i.title or '*' in i.title for i in issues), issues


# ── OR 조건 3개 이상 ─────────────────────────────────────────────

def test_or_conditions_three(ana):
    # OR 키워드 3개 이상(조건 4개)이어야 규칙 발동
    sql = "SELECT deptno FROM emp WHERE deptno=10 OR deptno=20 OR deptno=30 OR deptno=40"
    issues = ana.analyze(sql)
    assert any('OR' in i.title for i in issues), issues


def test_or_conditions_two_ok(ana):
    # OR 2개(조건 3개) — 임계값 미달이므로 OR 이슈 없어야 함
    sql = "SELECT deptno FROM emp WHERE deptno=10 OR deptno=20 OR deptno=30"
    issues = ana.analyze(sql)
    assert not any('OR' in i.title for i in issues)


# ── UNION ────────────────────────────────────────────────────────

def test_union_detected(ana):
    sql = "SELECT ename FROM emp WHERE deptno=10 UNION SELECT ename FROM emp WHERE deptno=20"
    issues = ana.analyze(sql)
    assert any('UNION' in i.title for i in issues), issues


def test_union_all_ok(ana):
    sql = "SELECT ename FROM emp WHERE deptno=10 UNION ALL SELECT ename FROM emp WHERE deptno=20"
    issues = ana.analyze(sql)
    assert not any('UNION' in i.title and 'ALL' not in i.title for i in issues)


# ── 파싱 실패 → ValueError ────────────────────────────────────────

def test_invalid_sql_raises(ana):
    with pytest.raises(Exception):
        ana.analyze("THIS IS NOT SQL @@##!!")
