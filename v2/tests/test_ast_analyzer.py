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
    assert any(i.category == '묵시적 형변환' for i in issues), issues


def test_implicit_conversion_string_ok(ana):
    """문자열 컬럼에 문자열 값 — 형변환 이슈 없어야 함"""
    sql = "SELECT * FROM emp WHERE ename = 'SMITH'"
    issues = ana.analyze(sql)
    assert not any('형변환' in i.title or '묵시적' in i.title for i in issues)


# ── 묵시적 형변환 강화 (P1/P2/P3) ───────────────────────────────

def test_implicit_conversion_p1_high_severity(ana):
    """P1: 숫자 컬럼에 문자열 리터럴 → severity=HIGH"""
    sql = "SELECT * FROM emp WHERE empno = '1234'"
    issues = ana.analyze(sql)
    conv = [i for i in issues if '형변환' in i.category]
    assert conv, "묵시적 형변환 이슈가 감지되지 않음"
    assert all(i.severity == 'HIGH' for i in conv), \
        f"severity 가 HIGH 여야 함: {[i.severity for i in conv]}"


def test_implicit_conversion_p2_to_number(ana):
    """P2: TO_NUMBER(컬럼) = 숫자 → 형변환 함수 직접 적용"""
    sql = "SELECT * FROM emp WHERE TO_NUMBER(emp_id) = 10"
    issues = ana.analyze(sql)
    conv = [i for i in issues if '형변환' in i.category]
    assert conv, "묵시적 형변환 이슈가 감지되지 않음"
    assert any('TO_NUMBER' in i.title for i in conv), \
        f"TO_NUMBER 가 title에 포함돼야 함: {[i.title for i in conv]}"
    assert all(i.severity == 'HIGH' for i in conv)


def test_implicit_conversion_p2_no_dup_with_function_check(ana):
    """P2: TO_NUMBER 는 _check_function_on_where_col 과 중복 감지되지 않아야 함"""
    sql = "SELECT * FROM emp WHERE TO_NUMBER(emp_id) = 10"
    issues = ana.analyze(sql)
    # 같은 컬럼·함수에 대해 '인덱스 무효화' + '묵시적 형변환' 동시 발생하면 중복
    index_issues = [i for i in issues if '인덱스' in i.category and 'TO_NUMBER' in i.title]
    assert not index_issues, \
        f"TO_NUMBER 가 인덱스 무효화로 중복 감지됨: {[i.title for i in index_issues]}"


def test_implicit_conversion_p3_concat_empty(ana):
    """P3: Column || '' = '값' → 문자열 연결 형변환"""
    sql = "SELECT * FROM emp WHERE salary || '' = '5000'"
    issues = ana.analyze(sql)
    conv = [i for i in issues if '형변환' in i.category]
    assert conv, "묵시적 형변환 이슈가 감지되지 않음"
    assert any('||' in i.title or '연결' in i.title for i in conv), \
        f"|| 패턴 title 이 없음: {[i.title for i in conv]}"
    assert all(i.severity == 'HIGH' for i in conv)


def test_implicit_conversion_bind_var_no_issue(ana):
    """바인드 변수(:b1) — 타입 불명이므로 형변환 이슈 없어야 함"""
    sql = "SELECT * FROM emp WHERE deptno = :b1"
    issues = ana.analyze(sql)
    assert not any('형변환' in i.category for i in issues), \
        f"바인드 변수에서 오탐: {[i.title for i in issues]}"


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


def test_rownum_nested_severity_medium(ana):
    """이중 중첩 ROWNUM 페이징 → severity=MEDIUM"""
    sql = "SELECT * FROM (SELECT *, ROWNUM RN FROM T WHERE ROWNUM <= 20) WHERE RN > 10"
    issues = ana.analyze(sql)
    paging = [i for i in issues if i.category == 'PAGING' and '구식' in i.title]
    assert paging, "구식 ROWNUM 페이징 이슈 없음"
    assert paging[0].severity == 'MEDIUM'


def test_rownum_no_order_detected(ana):
    """ORDER BY 없는 ROWNUM <= N 단독 사용 감지"""
    sql = "SELECT * FROM ORDERS WHERE ROWNUM <= 10"
    issues = ana.analyze(sql)
    assert any(i.category == 'PAGING' and 'ORDER BY' in i.title for i in issues), issues


def test_rownum_no_order_severity_medium(ana):
    """ORDER BY 없는 ROWNUM 페이징 → severity=MEDIUM"""
    sql = "SELECT * FROM ORDERS WHERE ROWNUM <= 5"
    issues = ana.analyze(sql)
    paging = [i for i in issues if 'ORDER BY' in i.title]
    assert paging, "ORDER BY 없는 ROWNUM 이슈 없음"
    assert paging[0].severity == 'MEDIUM'


def test_rownum_with_order_no_issue(ana):
    """ROWNUM <= N + ORDER BY → 'ORDER BY 없는' 경고 없음"""
    sql = (
        "SELECT * FROM ("
        "  SELECT * FROM ORDERS ORDER BY ORDER_DATE"
        ") WHERE ROWNUM <= 10"
    )
    issues = ana.analyze(sql)
    assert not any('ORDER BY 없는' in i.title for i in issues)


def test_rownum_no_paging_no_issue(ana):
    """ROWNUM 없는 쿼리 → PAGING 이슈 없음"""
    sql = "SELECT * FROM ORDERS WHERE ORDER_DATE > SYSDATE - 30"
    issues = ana.analyze(sql)
    assert not any(i.category == 'PAGING' for i in issues)


def test_rownum_nested_not_flagged_as_no_order(ana):
    """이중 중첩 ROWNUM → 'ORDER BY 없는' 이슈 없음 (중첩 이슈만 발생)"""
    sql = "SELECT * FROM (SELECT *, ROWNUM RN FROM T WHERE ROWNUM <= 20) WHERE RN > 10"
    issues = ana.analyze(sql)
    titles = [i.title for i in issues]
    assert not any('ORDER BY 없는' in t for t in titles)


def test_rownum_paging_suggestion_contains_row_number(ana):
    """구식 ROWNUM 이슈의 제안에 ROW_NUMBER 언급 포함"""
    sql = "SELECT * FROM (SELECT *, ROWNUM RN FROM T WHERE ROWNUM <= 20) WHERE RN > 10"
    issues = ana.analyze(sql)
    paging = [i for i in issues if i.category == 'PAGING' and '구식' in i.title]
    assert paging
    assert 'ROW_NUMBER' in paging[0].suggestion
