"""
HintAdvisor 단위 테스트

규칙별 1개:
  - 규칙 1 LEADING   : E-Rows 작은 테이블이 드라이빙 순서 앞에 오는지 검증
  - 규칙 2 USE_NL    : JOIN 자식 테이블 E-Rows < 1000 → USE_NL 힌트 생성
  - 규칙 3 INDEX     : TABLE ACCESS FULL + 인덱스 존재 → INDEX 힌트 생성
  - 규칙 4 PUSH_PRED : VIEW 행의 조상에 FILTER 존재 → PUSH_PRED 힌트 생성
  - 규칙 5 NO_MERGE  : VIEW Cost / 전체 Cost ≥ 70% → NO_MERGE 힌트 생성
"""
from types import SimpleNamespace

from v2.core.analysis.hint_advisor import HintAdvisor


# ── 헬퍼 ──────────────────────────────────────────────────────────

def _row(id_, op, opts, obj, card, parent_id=None, cost=None):
    """PlanRow 유사 객체"""
    return SimpleNamespace(
        id=id_,
        parent_id=parent_id,
        operation=op,
        options=opts or '',
        object_name=obj or '',
        cardinality=card,
        cost=cost,
    )


def _index(table, name, cols=None):
    """IndexInfo 유사 객체"""
    return SimpleNamespace(
        table_name=table,
        index_name=name,
        columns=cols or [],
    )


# ── 규칙 1: LEADING ───────────────────────────────────────────────

def test_leading_smallest_drives_first():
    """E-Rows 가 더 작은 DEPT 가 LEADING 순서 첫 번째여야 한다."""
    rows = [
        _row(1, 'NESTED LOOPS', '',              None,  None),
        _row(2, 'TABLE ACCESS', 'FULL',           'DEPT', 10,   parent_id=1),
        _row(3, 'TABLE ACCESS', 'BY INDEX ROWID', 'EMP',  500,  parent_id=1),
    ]
    hints = HintAdvisor().advise(rows)
    leading = [h for h in hints if h.hint.startswith('LEADING')]
    assert leading, '규칙 1: LEADING 힌트가 생성되지 않음'
    assert leading[0].hint == 'LEADING(DEPT EMP)', leading[0].hint
    assert '/*+' in leading[0].full_hint
    assert 'LEADING' in leading[0].full_hint


# ── 규칙 2: USE_NL ────────────────────────────────────────────────

def test_use_nl_for_small_join_child():
    """NESTED LOOPS 의 자식 TABLE ACCESS E-Rows=5 → USE_NL 힌트 생성."""
    rows = [
        _row(1, 'NESTED LOOPS', '', None,   None),
        _row(2, 'TABLE ACCESS', 'FULL', 'DEPT', 5, parent_id=1),
    ]
    hints = HintAdvisor().advise(rows)
    nl = [h for h in hints if 'USE_NL' in h.hint]
    assert nl, '규칙 2: USE_NL 힌트가 생성되지 않음'
    assert 'DEPT' in nl[0].hint
    assert '/*+ USE_NL(DEPT) */' == nl[0].full_hint


# ── 규칙 3: INDEX ─────────────────────────────────────────────────

def test_index_hint_when_fts_and_index_exists():
    """TABLE ACCESS FULL + 인덱스 존재 → INDEX 힌트 생성."""
    rows = [
        _row(1, 'TABLE ACCESS', 'FULL', 'ORDERS', 50_000),
    ]
    index_infos = [_index('ORDERS', 'IDX_ORDERS_DATE', ['ORDER_DATE'])]
    hints = HintAdvisor().advise(rows, index_infos)
    idx = [h for h in hints if h.hint.startswith('INDEX')]
    assert idx, '규칙 3: INDEX 힌트가 생성되지 않음'
    assert 'ORDERS' in idx[0].hint
    assert 'IDX_ORDERS_DATE' in idx[0].hint
    assert '/*+ INDEX(ORDERS IDX_ORDERS_DATE) */' == idx[0].full_hint


# ── 규칙 4: PUSH_PRED ─────────────────────────────────────────────

def test_push_pred_when_filter_is_ancestor():
    """VIEW 행의 부모가 FILTER 오퍼레이션이면 PUSH_PRED 힌트가 생성돼야 한다."""
    rows = [
        _row(1, 'FILTER',       '',     None,       100, parent_id=None, cost=100),
        _row(2, 'VIEW',         '',     'V_ORDERS',  50, parent_id=1,    cost=50),
        _row(3, 'TABLE ACCESS', 'FULL', 'ORDERS',    50, parent_id=2,    cost=50),
    ]
    hints = HintAdvisor().advise(rows)
    pp = [h for h in hints if 'PUSH_PRED' in h.hint]
    assert pp, '규칙 4: PUSH_PRED 힌트가 생성되지 않음'
    assert 'V_ORDERS' in pp[0].hint
    assert '/*+' in pp[0].full_hint
    assert 'PUSH_PRED' in pp[0].full_hint


# ── 규칙 5: NO_MERGE ──────────────────────────────────────────────

def test_no_merge_when_view_dominates_cost():
    """VIEW Cost 가 전체 Cost 의 70% 이상이면 NO_MERGE 힌트가 생성돼야 한다."""
    rows = [
        _row(1, 'HASH JOIN',    '',     None,      100, parent_id=None, cost=100),
        _row(2, 'VIEW',         '',     'V_SALES',  75, parent_id=1,    cost=75),
        _row(3, 'TABLE ACCESS', 'FULL', 'SALES',    75, parent_id=2,    cost=75),
    ]
    hints = HintAdvisor().advise(rows)
    nm = [h for h in hints if 'NO_MERGE' in h.hint]
    assert nm, '규칙 5: NO_MERGE 힌트가 생성되지 않음'
    assert 'V_SALES' in nm[0].hint
    assert '/*+' in nm[0].full_hint
    assert 'NO_MERGE' in nm[0].full_hint
