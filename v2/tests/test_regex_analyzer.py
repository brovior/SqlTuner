"""
RegexAnalyzer 단위 테스트

정규식 기반 분석기가 각 패턴을 올바르게 감지하는지 검증합니다.
AstAnalyzer 와 동일한 규칙을 커버하며, 추가로 UPDATE/DELETE without WHERE 도 포함합니다.
"""
import pytest
from v2.core.analysis.regex_analyzer import RegexAnalyzer


@pytest.fixture
def ana():
    return RegexAnalyzer()


# ── UPDATE/DELETE without WHERE ──────────────────────────────────

def test_update_without_where(ana):
    sql = "UPDATE emp SET sal = 5000"
    issues = ana.analyze(sql)
    assert any('WHERE' in i.title or 'UPDATE' in i.title for i in issues), issues


def test_delete_without_where(ana):
    sql = "DELETE FROM emp"
    issues = ana.analyze(sql)
    assert any('WHERE' in i.title or 'DELETE' in i.title for i in issues), issues


def test_update_with_where_ok(ana):
    sql = "UPDATE emp SET sal = 5000 WHERE empno = 7788"
    issues = ana.analyze(sql)
    assert not any('WHERE' in i.title and 'UPDATE' in i.title for i in issues)


# ── 함수로 감싼 WHERE 컬럼 ────────────────────────────────────────

def test_where_function_upper(ana):
    sql = "SELECT * FROM emp WHERE UPPER(ename) = 'SMITH'"
    issues = ana.analyze(sql)
    assert any('인덱스' in i.title or '함수' in i.title for i in issues), issues


def test_where_function_to_char(ana):
    sql = "SELECT * FROM emp WHERE TO_CHAR(hiredate, 'YYYY') = '2020'"
    issues = ana.analyze(sql)
    assert any('인덱스' in i.title or '함수' in i.title for i in issues), issues


# ── 묵시적 형변환 ────────────────────────────────────────────────

def test_implicit_conversion(ana):
    sql = "SELECT * FROM emp WHERE empno = '7788'"
    issues = ana.analyze(sql)
    assert any('형변환' in i.title or '묵시적' in i.title for i in issues), issues


# ── NOT IN 서브쿼리 ──────────────────────────────────────────────

def test_not_in_subquery(ana):
    sql = "SELECT * FROM emp WHERE deptno NOT IN (SELECT deptno FROM dept)"
    issues = ana.analyze(sql)
    assert any('NOT IN' in i.title for i in issues), issues


# ── LIKE 앞 와일드카드 ────────────────────────────────────────────

def test_like_leading_wildcard(ana):
    sql = "SELECT * FROM emp WHERE ename LIKE '%SMITH'"
    issues = ana.analyze(sql)
    assert any('LIKE' in i.title or '와일드카드' in i.title for i in issues), issues


# ── SELECT * ─────────────────────────────────────────────────────

def test_select_star(ana):
    sql = "SELECT * FROM emp"
    issues = ana.analyze(sql)
    assert any('SELECT *' in i.title or '*' in i.title for i in issues), issues


# ── 스칼라 서브쿼리 3개 이상 ─────────────────────────────────────

def test_scalar_subquery_three(ana):
    sql = (
        "SELECT "
        "(SELECT COUNT(*) FROM t1), "
        "(SELECT COUNT(*) FROM t2), "
        "(SELECT COUNT(*) FROM t3) "
        "FROM dual"
    )
    issues = ana.analyze(sql)
    assert any('스칼라' in i.title for i in issues), issues


def test_scalar_subquery_two_ok(ana):
    sql = (
        "SELECT "
        "(SELECT COUNT(*) FROM t1), "
        "(SELECT COUNT(*) FROM t2) "
        "FROM dual"
    )
    issues = ana.analyze(sql)
    assert not any('스칼라' in i.title for i in issues)


# ── OR 조건 3개 이상 ─────────────────────────────────────────────

def test_or_three(ana):
    # OR 키워드 3개 이상(조건 4개)이어야 규칙 발동
    sql = "SELECT deptno FROM emp WHERE deptno=10 OR deptno=20 OR deptno=30 OR deptno=40"
    issues = ana.analyze(sql)
    assert any('OR' in i.title for i in issues), issues


# ── DISTINCT + JOIN ──────────────────────────────────────────────

def test_distinct_join(ana):
    sql = "SELECT DISTINCT e.ename FROM emp e JOIN dept d ON e.deptno = d.deptno"
    issues = ana.analyze(sql)
    assert any('DISTINCT' in i.title for i in issues), issues


# ── UNION ────────────────────────────────────────────────────────

def test_union_detected(ana):
    sql = "SELECT ename FROM emp WHERE deptno=10 UNION SELECT ename FROM emp WHERE deptno=20"
    issues = ana.analyze(sql)
    assert any('UNION' in i.title for i in issues), issues


# ── 중복 제거 ─────────────────────────────────────────────────────

def test_deduplication(ana):
    """같은 카테고리+제목의 이슈가 중복되지 않아야 함"""
    sql = "SELECT * FROM emp"
    issues = ana.analyze(sql)
    keys = [(i.category, i.title) for i in issues]
    assert len(keys) == len(set(keys))


# ── 심각도 정렬 ───────────────────────────────────────────────────

def test_severity_order(ana):
    """HIGH → MEDIUM → LOW → INFO 순서 보장"""
    sql = (
        "UPDATE emp SET sal=1000\n"          # HIGH
        "-- WHERE empno=7788\n"
        "UNION SELECT * FROM dept"           # SELECT *, UNION
    )
    issues = ana.analyze(sql)
    order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2, 'INFO': 3}
    ranks = [order.get(i.severity, 99) for i in issues]
    assert ranks == sorted(ranks)


# ── ROWNUM 페이징 안티패턴 ───────────────────────────────────────

def test_rownum_nested_paging_detected(ana):
    """ROWNUM 이중 중첩 페이징 패턴 감지"""
    sql = (
        "SELECT * FROM ("
        "  SELECT A.*, ROWNUM RN FROM ("
        "    SELECT * FROM ORDERS ORDER BY ORDER_DATE"
        "  ) A WHERE ROWNUM <= 100"
        ") WHERE RN >= 1"
    )
    issues = ana.analyze(sql)
    assert any(i.category == 'PAGING' and '구식' in i.title for i in issues), issues


def test_rownum_nested_two_occurrences_detected(ana):
    """ROWNUM 2회 등장 → 이중 중첩 페이징"""
    sql = "SELECT * FROM (SELECT *, ROWNUM RN FROM T WHERE ROWNUM <= 20) WHERE RN > 10"
    issues = ana.analyze(sql)
    assert any('구식' in i.title for i in issues), issues


def test_rownum_single_no_order_detected(ana):
    """ORDER BY 없는 ROWNUM <= N 단독 사용 감지"""
    sql = "SELECT * FROM ORDERS WHERE ROWNUM <= 10"
    issues = ana.analyze(sql)
    assert any(i.category == 'PAGING' and 'ORDER BY' in i.title for i in issues), issues


def test_rownum_single_with_order_ok(ana):
    """ROWNUM <= N + ORDER BY 포함 → 경고 없음"""
    sql = "SELECT * FROM (SELECT * FROM ORDERS ORDER BY ORDER_DATE) WHERE ROWNUM <= 10"
    issues = ana.analyze(sql)
    assert not any('ORDER BY 없는' in i.title for i in issues)


def test_rownum_no_paging_no_issue(ana):
    """ROWNUM 없는 일반 쿼리 → PAGING 이슈 없음"""
    sql = "SELECT * FROM ORDERS WHERE ORDER_DATE > SYSDATE - 30"
    issues = ana.analyze(sql)
    assert not any(i.category == 'PAGING' for i in issues)


def test_rownum_nested_not_flagged_as_no_order(ana):
    """이중 중첩 패턴 → '구식 ROWNUM' 이슈만 발생, 'ORDER BY 없는' 이슈 없음"""
    sql = "SELECT * FROM (SELECT *, ROWNUM RN FROM T WHERE ROWNUM <= 20) WHERE RN > 10"
    issues = ana.analyze(sql)
    titles = [i.title for i in issues]
    assert not any('ORDER BY 없는' in t for t in titles)
