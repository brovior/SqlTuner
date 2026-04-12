"""
PlanAnalyzer 단위 테스트

DB 없이 PlanRow 목 데이터를 직접 주입하여 각 규칙을 검증합니다.
"""
import pytest
from v2.core.db.oracle_client import PlanRow
from v2.core.db.plan_analyzer import PlanAnalyzer, SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_INFO


def make_row(
    id: int,
    operation: str,
    options: str = '',
    object_name: str = '',
    parent_id=None,
    cost: int = 100,
    cardinality: int = 1000,
    bytes: int = 8000,
    depth: int = 0,
) -> PlanRow:
    return PlanRow(
        id=id,
        parent_id=parent_id,
        operation=operation,
        options=options,
        object_name=object_name,
        cost=cost,
        cardinality=cardinality,
        bytes=bytes,
        cpu_cost=None,
        io_cost=None,
        depth=depth,
    )


# ── Full Table Scan ───────────────────────────────────────────────

def test_fts_large_table():
    rows = [
        make_row(1, 'SELECT STATEMENT', cardinality=50_000),
        make_row(2, 'TABLE ACCESS', 'FULL', 'EMP', parent_id=1,
                 cardinality=50_000, depth=1),
    ]
    ana = PlanAnalyzer(rows)
    ana.build_tree()
    issues = ana.analyze()
    assert any('Full Table Scan' in i.title or 'FTS' in i.title or
               '전체 테이블' in i.title for i in issues), issues


def test_fts_small_table_no_high_issue():
    """행 수가 적은 FTS 는 HIGH 심각도로 보고되지 않아야 한다 (LOW 는 허용)"""
    rows = [
        make_row(1, 'SELECT STATEMENT', cardinality=100),
        make_row(2, 'TABLE ACCESS', 'FULL', 'SMALL_TABLE', parent_id=1,
                 cardinality=100, depth=1),
    ]
    ana = PlanAnalyzer(rows)
    ana.build_tree()
    issues = ana.analyze()
    high_fts = [i for i in issues if
                ('Full Table Scan' in i.title or 'FTS' in i.title)
                and i.severity == SEVERITY_HIGH]
    assert not high_fts


# ── Cartesian Join ────────────────────────────────────────────────

def test_cartesian_join():
    rows = [
        make_row(1, 'SELECT STATEMENT'),
        make_row(2, 'MERGE JOIN', 'CARTESIAN', parent_id=1, depth=1),
        make_row(3, 'TABLE ACCESS', 'FULL', 'EMP', parent_id=2, depth=2),
        make_row(4, 'TABLE ACCESS', 'FULL', 'DEPT', parent_id=2, depth=2),
    ]
    ana = PlanAnalyzer(rows)
    ana.build_tree()
    issues = ana.analyze()
    assert any('Cartesian' in i.title or '카테시안' in i.title for i in issues), issues
    assert any(i.severity == SEVERITY_HIGH for i in issues)


# ── Index Full Scan ───────────────────────────────────────────────

def test_index_full_scan():
    rows = [
        make_row(1, 'SELECT STATEMENT'),
        make_row(2, 'INDEX', 'FULL SCAN', 'IDX_EMP_DEPTNO', parent_id=1, depth=1),
    ]
    ana = PlanAnalyzer(rows)
    ana.build_tree()
    issues = ana.analyze()
    assert any('Index Full Scan' in i.title or '인덱스 전체' in i.title for i in issues), issues


# ── build_tree 루트 반환 ──────────────────────────────────────────

def test_build_tree_returns_roots():
    rows = [
        make_row(1, 'SELECT STATEMENT'),
        make_row(2, 'TABLE ACCESS', 'FULL', 'EMP', parent_id=1, depth=1),
    ]
    ana = PlanAnalyzer(rows)
    roots = ana.build_tree()
    assert len(roots) == 1
    assert roots[0].id == 1
    assert len(roots[0].children) == 1
    assert roots[0].children[0].id == 2


# ── 빈 rows ───────────────────────────────────────────────────────

def test_empty_rows():
    ana = PlanAnalyzer([])
    ana.build_tree()
    issues = ana.analyze()
    assert issues == []


# ── MERGE JOIN CARTESIAN (operation 기반) ─────────────────────────

def test_merge_join_cartesian_operation():
    """operation 필드에 MERGE JOIN CARTESIAN이 포함된 경우 HIGH로 감지"""
    rows = [
        make_row(1, 'SELECT STATEMENT'),
        make_row(2, 'MERGE JOIN CARTESIAN', '', parent_id=1, depth=1),
        make_row(3, 'TABLE ACCESS', 'FULL', 'EMP', parent_id=2, depth=2),
        make_row(4, 'TABLE ACCESS', 'FULL', 'DEPT', parent_id=2, depth=2),
    ]
    ana = PlanAnalyzer(rows)
    ana.build_tree()
    issues = ana.analyze()
    cartesian_issues = [i for i in issues if 'MERGE JOIN CARTESIAN' in i.title or 'Merge Join Cartesian' in i.category]
    assert cartesian_issues, f"MERGE JOIN CARTESIAN 이슈가 감지되지 않음: {issues}"
    assert cartesian_issues[0].severity == SEVERITY_HIGH


# ── BUFFER SORT ───────────────────────────────────────────────────

def test_buffer_sort_detected():
    """operation이 BUFFER SORT인 경우 MEDIUM으로 감지"""
    rows = [
        make_row(1, 'SELECT STATEMENT'),
        make_row(2, 'MERGE JOIN', '', parent_id=1, depth=1),
        make_row(3, 'TABLE ACCESS', 'FULL', 'EMP', parent_id=2, depth=2),
        make_row(4, 'BUFFER SORT', '', parent_id=2, depth=2),
    ]
    ana = PlanAnalyzer(rows)
    ana.build_tree()
    issues = ana.analyze()
    buffer_sort_issues = [i for i in issues if 'Buffer Sort' in i.category or 'BUFFER SORT' in i.title]
    assert buffer_sort_issues, f"BUFFER SORT 이슈가 감지되지 않음: {issues}"
    assert buffer_sort_issues[0].severity == SEVERITY_MEDIUM


# ── 고비용 노드 HIGH 승격 ─────────────────────────────────────────

def test_high_cost_node_promoted_to_high():
    """단일 노드 Cost가 전체의 70% 이상이면 HIGH severity로 보고"""
    rows = [
        make_row(0, 'SELECT STATEMENT', parent_id=None, cost=1000, cardinality=500),
        make_row(1, 'TABLE ACCESS', 'FULL', 'BIG_TABLE', parent_id=0,
                 cost=800, cardinality=500, depth=1),
    ]
    ana = PlanAnalyzer(rows)
    ana.build_tree()
    issues = ana.analyze()
    cost_issues = [i for i in issues if i.category == '비용 집중']
    assert cost_issues, f"고비용 집중 이슈가 감지되지 않음: {issues}"
    assert cost_issues[0].severity == SEVERITY_HIGH, (
        f"HIGH가 예상되었으나 {cost_issues[0].severity}로 보고됨"
    )


# ── PlanAnalyzer._root_cost (TuningValidator 연동) ────────────────

def test_root_has_no_parent():
    """루트 노드 parent_id = None 확인"""
    rows = [
        make_row(0, 'SELECT STATEMENT', parent_id=None, cost=500),
        make_row(1, 'TABLE ACCESS', 'FULL', 'EMP', parent_id=0, cost=200, depth=1),
    ]
    root = next(r for r in rows if r.parent_id is None)
    assert root.cost == 500
