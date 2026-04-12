"""
CompositeAnalyzer 단위 테스트

검증 항목:
  1. 중복 제거 — AST와 Regex가 같은 category를 감지할 때 이슈가 1건만 남는지
  2. Regex 전용 이슈 — AST 파싱 실패 시 Regex 이슈가 정상 포함되는지
  3. engine_name — 엔진 상태 문자열이 상황에 맞게 기록되는지
"""
import pytest
from unittest.mock import patch
from v2.core.analysis.composite_analyzer import CompositeAnalyzer
from v2.core.analysis.base import SqlIssue


@pytest.fixture
def comp():
    return CompositeAnalyzer()


# ── 중복 제거: (category, title) 완전 일치 ───────────────────────────

def test_no_dup_select_star(comp):
    """SELECT * — AST·Regex 양쪽에서 감지하지만 1건만 나와야 함"""
    sql = "SELECT * FROM emp WHERE empno = 7788"
    issues = comp.analyze(sql)
    star_issues = [i for i in issues if i.category == 'SELECT *']
    assert len(star_issues) == 1, \
        f"SELECT * 이슈가 {len(star_issues)}건: {[i.title for i in star_issues]}"


def test_no_dup_index_breaking_func(comp):
    """TRUNC — AST·Regex 양쪽이 '인덱스 무효화' 감지하지만 1건만 나와야 함"""
    sql = "SELECT empno FROM emp WHERE TRUNC(hiredate) = SYSDATE"
    issues = comp.analyze(sql)
    idx_issues = [i for i in issues if i.category == '인덱스 무효화']
    assert len(idx_issues) == 1, \
        f"인덱스 무효화 이슈가 {len(idx_issues)}건: {[i.title for i in idx_issues]}"


# ── 중복 제거: category 일치 + title 불일치 (핵심 시나리오) ────────────

def test_no_dup_implicit_conversion_category(comp):
    """
    EMPNO = '100' 패턴:
    - AST  → category='묵시적 형변환', title='숫자 컬럼에 문자열 리터럴 비교' [HIGH]
    - Regex → category='묵시적 형변환', title='묵시적 형변환 의심' [MEDIUM]
    title이 달라도 같은 category면 1건만 남아야 함 (AST 결과 우선)
    """
    sql = "SELECT * FROM EMP WHERE TRUNC(HIREDATE) = SYSDATE AND EMPNO = '100'"
    issues = comp.analyze(sql)
    conv_issues = [i for i in issues if i.category == '묵시적 형변환']
    assert len(conv_issues) == 1, \
        f"묵시적 형변환 이슈가 {len(conv_issues)}건: {[i.title for i in conv_issues]}"


def test_implicit_conversion_kept_issue_is_ast(comp):
    """중복 발생 시 남아있는 이슈는 AST 결과(HIGH)여야 함"""
    sql = "SELECT * FROM EMP WHERE EMPNO = '100'"
    issues = comp.analyze(sql)
    conv_issues = [i for i in issues if i.category == '묵시적 형변환']
    assert len(conv_issues) == 1
    assert conv_issues[0].severity == 'HIGH', \
        f"AST 결과(HIGH)가 아닌 Regex 결과가 남음: severity={conv_issues[0].severity}"


def test_total_issue_count_no_dup(comp):
    """검증용 SQL 전체 이슈 수 — 중복 없이 정확히 3건이어야 함"""
    sql = "SELECT * FROM EMP WHERE TRUNC(HIREDATE) = SYSDATE AND EMPNO = '100'"
    issues = comp.analyze(sql)
    assert len(issues) == 3, \
        f"예상 3건, 실제 {len(issues)}건: {[(i.category, i.title) for i in issues]}"


# ── Regex 전용 이슈: AST가 커버하지 않는 category는 포함돼야 함 ────────

def test_regex_only_issue_included(comp):
    """
    AST 파싱이 성공해도 Regex 전용 category는 포함돼야 함.
    sqlglot이 UNION을 감지하지 못하는 방언 차이 케이스를 모의로 확인.
    """
    sql = (
        "SELECT ename FROM emp WHERE deptno = 10 "
        "UNION "
        "SELECT ename FROM emp WHERE deptno = 20"
    )
    issues = comp.analyze(sql)
    union_issues = [i for i in issues if i.category == 'UNION vs UNION ALL']
    assert union_issues, "UNION 이슈가 포함되지 않음"


# ── AST 파싱 실패 시 Regex 폴백 ──────────────────────────────────────

def test_ast_failure_falls_back_to_regex(comp):
    """AST 파싱 실패 시 Regex 이슈가 정상 반환되어야 함"""
    sql = "SELECT * FROM emp WHERE UPPER(ename) = 'SMITH'"
    with patch.object(comp._ast, 'analyze', side_effect=ValueError("파싱 실패")):
        issues = comp.analyze(sql)
    assert issues, "Regex 폴백 이슈가 비어있음"
    assert comp.last_engine == 'Regex (AST 파싱 실패)'


def test_ast_failure_no_dup_in_regex_only(comp):
    """AST 실패 시 Regex 결과만 반환 — 자체 중복 없어야 함"""
    sql = "SELECT * FROM emp WHERE UPPER(ename) = 'SMITH'"
    with patch.object(comp._ast, 'analyze', side_effect=ValueError("파싱 실패")):
        issues = comp.analyze(sql)
    keys = [(i.category, i.title) for i in issues]
    assert len(keys) == len(set(keys)), f"Regex 결과 내 중복: {keys}"


# ── engine_name 상태 기록 ────────────────────────────────────────────

def test_engine_name_both_ok(comp):
    """정상 분석 시 engine = 'Regex + AST'"""
    comp.analyze("SELECT * FROM emp")
    assert comp.last_engine == 'Regex + AST'


def test_engine_name_ast_fail(comp):
    """AST 실패 시 engine = 'Regex (AST 파싱 실패)'"""
    with patch.object(comp._ast, 'analyze', side_effect=Exception("실패")):
        comp.analyze("SELECT * FROM emp")
    assert comp.last_engine == 'Regex (AST 파싱 실패)'
