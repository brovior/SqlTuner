"""
TuningReporter 단위 테스트

DB 없이 ValidationResult 를 직접 구성해 HTML 생성 결과를 검증합니다.
"""
import pytest

from v2.core.db.plan_analyzer import PlanIssue
from v2.core.pipeline.validation import ValidationResult
from v2.core.report.tuning_report import TuningReporter


# ── 헬퍼 ──────────────────────────────────────────────────────────

def make_issue(title: str, severity: str = 'HIGH', category: str = 'PLAN') -> PlanIssue:
    return PlanIssue(
        severity=severity,
        category=category,
        title=title,
        description=f'{title} 상세 설명',
        suggestion='인덱스를 추가하세요.',
    )


# ── HTML 생성 + 필수 태그 포함 여부 ───────────────────────────────

def test_generate_html_contains_required_sections():
    """
    APPROVE 판정 결과로 HTML 을 생성하고 필수 구성 요소가 포함되었는지 확인합니다.
    - <html>, <head>, <body> 기본 구조
    - 판정 배지 (APPROVE)
    - 원본 / 튜닝 SQL 텍스트
    - 성능 비교 테이블 (Cost 행)
    - 해소된 이슈 제목
    - 판정 근거 텍스트
    """
    original_sql = 'SELECT * FROM EMP WHERE DEPTNO = 10'
    tuned_sql    = 'SELECT /*+ INDEX(EMP EMP_IDX) */ * FROM EMP WHERE DEPTNO = 10'

    result = ValidationResult(
        is_valid=True,
        original_cost=1000,
        tuned_cost=50,
        cost_delta_pct=-95.0,
        resolved_issues=[make_issue('Full Table Scan on EMP')],
        new_issues=[],
    )
    # __post_init__ 이 APPROVE 를 계산했는지 확인
    assert result.verdict == 'APPROVE'

    reporter = TuningReporter()
    html_str = reporter.generate_html(original_sql, tuned_sql, result)

    # ── 기본 HTML 구조 ──
    assert '<!DOCTYPE html>' in html_str
    assert '<html' in html_str
    assert '<head>' in html_str
    assert '<body>' in html_str

    # ── 판정 배지 ──
    assert 'APPROVE' in html_str

    # ── SQL 텍스트 (html.escape 후에도 검색 가능) ──
    assert 'EMP WHERE DEPTNO = 10' in html_str

    # ── 성능 비교 테이블 ──
    assert 'Cost' in html_str
    assert '1,000' in html_str   # original_cost 천 단위 구분자
    assert '50' in html_str      # tuned_cost
    assert '-95.0%' in html_str  # delta

    # ── 이슈 분석 ──
    assert 'Full Table Scan on EMP' in html_str
    assert '해소된 이슈' in html_str

    # ── 판정 근거 ──
    assert '판정 근거' in html_str
    assert '감소' in html_str    # '비용 95.0% 감소' 등
    assert '신규 이슈 없음' in html_str


def test_generate_html_reject_shows_error_message():
    """REJECT(문법 오류) 시 오류 메시지가 HTML 에 포함되어야 한다."""
    result = ValidationResult(
        is_valid=False,
        error_message='ORA-00923: FROM keyword not found where expected',
    )
    assert result.verdict == 'REJECT'

    html_str = TuningReporter().generate_html(
        'SELECT * FROM EMP', 'SELECT FROM EMP', result
    )

    assert 'REJECT' in html_str
    assert 'ORA-00923' in html_str


def test_generate_html_elapsed_row_shown_only_when_measured():
    """실행시간은 measure_time=True 로 측정된 경우에만 표시된다."""
    base_rows = [None]  # 더미 — ValidationResult 직접 구성

    # 측정 안 한 경우
    result_no_time = ValidationResult(is_valid=True, original_cost=100, tuned_cost=90)
    html_no = TuningReporter().generate_html('SELECT 1 FROM DUAL', 'SELECT 1 FROM DUAL', result_no_time)
    assert '실행시간' not in html_no

    # 측정한 경우
    result_with_time = ValidationResult(
        is_valid=True,
        original_cost=100,
        tuned_cost=90,
        original_elapsed_ms=250.5,
        tuned_elapsed_ms=80.2,
        elapsed_delta_pct=-67.9,
    )
    html_yes = TuningReporter().generate_html('SELECT 1 FROM DUAL', 'SELECT 1 FROM DUAL', result_with_time)
    assert '실행시간' in html_yes
    assert '250.5' in html_yes
    assert '80.2' in html_yes


def test_save_html_writes_file(tmp_path):
    """save_html 이 지정 경로에 유효한 HTML 파일을 생성한다."""
    result = ValidationResult(is_valid=True, original_cost=200, tuned_cost=180)
    path = str(tmp_path / 'report.html')

    TuningReporter().save_html(path, 'SELECT 1 FROM DUAL', 'SELECT 1 FROM DUAL', result)

    with open(path, encoding='utf-8') as f:
        content = f.read()

    assert '<!DOCTYPE html>' in content
    assert len(content) > 500   # 최소한의 내용이 있어야 함
