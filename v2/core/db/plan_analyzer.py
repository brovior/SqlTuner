"""
SQL Execution Plan 분석 모듈
PLAN_TABLE에서 추출한 PlanRow 목록을 트리 구조로 변환하고
문제 패턴을 감지합니다.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
from .oracle_client import PlanRow
from ..constants import NL_INNER_CARD_THRESHOLD, NO_STATS_COST_THRESHOLD, HIGH_COST_MIN_ROOT


# 심각도 레벨
SEVERITY_HIGH = 'HIGH'
SEVERITY_MEDIUM = 'MEDIUM'
SEVERITY_LOW = 'LOW'
SEVERITY_INFO = 'INFO'


@dataclass
class PlanIssue:
    """감지된 플랜 문제"""
    severity: str          # HIGH / MEDIUM / LOW / INFO
    category: str          # 문제 분류
    title: str             # 짧은 제목
    description: str       # 상세 설명
    suggestion: str        # 개선 제안
    related_node_id: Optional[int] = None  # 관련 Plan 노드 ID
    sample_sql: str = ''   # 제안 SQL 예시 (있는 경우)


class PlanAnalyzer:
    """
    PlanRow 목록을 받아서 트리 구조로 변환하고
    규칙 기반으로 튜닝 이슈를 감지합니다.
    """

    # Full Table Scan 경고 기준 (예측 행 수)
    FTS_ROW_THRESHOLD = 10_000
    # Cardinality 오차 경고 비율
    CARDINALITY_ERROR_RATIO = 10.0

    def __init__(self, plan_rows: list[PlanRow]):
        self.rows = plan_rows
        self._row_map: dict[int, PlanRow] = {r.id: r for r in plan_rows}
        self._issues: list[PlanIssue] = []

    # ------------------------------------------------------------------
    # 트리 구조 변환
    # ------------------------------------------------------------------

    def build_tree(self) -> list[PlanRow]:
        """루트 노드 목록을 반환합니다 (children 연결된 트리)."""
        roots = []
        for row in self.rows:
            row.children = []

        for row in self.rows:
            if row.parent_id is None or row.parent_id not in self._row_map:
                roots.append(row)
            else:
                parent = self._row_map[row.parent_id]
                parent.children.append(row)

        return roots

    # ------------------------------------------------------------------
    # 이슈 감지
    # ------------------------------------------------------------------

    def analyze(self) -> list[PlanIssue]:
        """모든 규칙을 실행하고 이슈 목록을 반환합니다."""
        self._issues = []
        self._check_full_table_scan()
        self._check_cartesian_join()
        self._check_merge_join_cartesian()
        self._check_sort_operations()
        self._check_buffer_sort()
        self._check_index_full_scan()
        self._check_high_cost_ratio()
        self._check_nested_loop_large()
        self._check_no_stats()
        return sorted(self._issues, key=lambda x: {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2, 'INFO': 3}[x.severity])

    def _check_full_table_scan(self):
        for row in self.rows:
            if row.operation == 'TABLE ACCESS' and row.options == 'FULL':
                cardinality = row.cardinality or 0
                if cardinality >= self.FTS_ROW_THRESHOLD:
                    severity = SEVERITY_HIGH
                    desc = (
                        f"테이블 '{row.object_name}'에 Full Table Scan이 발생합니다.\n"
                        f"예측 행 수: {cardinality:,}건 / Cost: {row.cost or 'N/A'}\n"
                        f"대용량 테이블에서 Full Scan은 성능 저하의 주요 원인입니다."
                    )
                elif cardinality > 0:
                    severity = SEVERITY_LOW
                    desc = (
                        f"테이블 '{row.object_name}'에 Full Table Scan이 발생합니다.\n"
                        f"예측 행 수: {cardinality:,}건 (소규모 테이블은 허용될 수 있음)"
                    )
                else:
                    severity = SEVERITY_MEDIUM
                    desc = (
                        f"테이블 '{row.object_name}'에 Full Table Scan이 발생합니다.\n"
                        "테이블 통계가 없어 정확한 행 수를 알 수 없습니다."
                    )

                self._issues.append(PlanIssue(
                    severity=severity,
                    category='Full Table Scan',
                    title=f"Full Table Scan: {row.object_name}",
                    description=desc,
                    suggestion=(
                        f"WHERE 절 조건 컬럼에 인덱스 생성을 검토하세요.\n"
                        f"예시: CREATE INDEX IDX_{row.object_name}_조건컬럼 "
                        f"ON {row.object_name}(조건컬럼);"
                    ),
                    related_node_id=row.id,
                    sample_sql=(
                        f"-- 단일 컬럼 인덱스\n"
                        f"CREATE INDEX IDX_{row.object_name}_COL1\n"
                        f"  ON {row.object_name}(컬럼명);\n\n"
                        f"-- 복합 인덱스 (선택도 높은 컬럼 우선)\n"
                        f"CREATE INDEX IDX_{row.object_name}_COL1_COL2\n"
                        f"  ON {row.object_name}(컬럼1, 컬럼2);"
                    )
                ))

    def _check_cartesian_join(self):
        for row in self.rows:
            if 'CARTESIAN' in (row.options or '').upper():
                self._issues.append(PlanIssue(
                    severity=SEVERITY_HIGH,
                    category='Cartesian Join',
                    title=f"Cartesian Join 감지: {row.object_name or row.operation}",
                    description=(
                        "Cartesian Join(카테시안 곱)이 발생하고 있습니다.\n"
                        "JOIN 조건이 누락되거나 잘못된 경우 모든 행의 조합이 생성되어\n"
                        "데이터 양에 따라 결과가 폭발적으로 증가합니다."
                    ),
                    suggestion=(
                        "테이블 간 JOIN 조건(ON/WHERE)이 올바르게 작성되었는지 확인하세요.\n"
                        "의도하지 않은 CROSS JOIN이 있다면 INNER JOIN으로 변경하세요."
                    ),
                    related_node_id=row.id,
                ))

    def _check_merge_join_cartesian(self):
        """Operation 자체가 MERGE JOIN CARTESIAN인 경우 감지"""
        for row in self.rows:
            if 'MERGE JOIN CARTESIAN' in (row.operation or '').upper():
                self._issues.append(PlanIssue(
                    severity=SEVERITY_HIGH,
                    category='Merge Join Cartesian',
                    title=f"MERGE JOIN CARTESIAN 감지: {row.object_name or row.operation}",
                    description=(
                        "MERGE JOIN CARTESIAN이 발생하고 있습니다.\n"
                        "조인 조건이 누락됐을 수 있습니다.\n"
                        "모든 행의 조합이 생성되어 결과가 폭발적으로 증가할 수 있습니다."
                    ),
                    suggestion=(
                        "테이블 간 JOIN 조건(ON/WHERE)이 올바르게 작성되었는지 확인하세요.\n"
                        "의도하지 않은 CROSS JOIN이 있다면 INNER JOIN으로 변경하세요."
                    ),
                    related_node_id=row.id,
                ))

    def _check_sort_operations(self):
        sort_ops = []
        for row in self.rows:
            if 'SORT' in (row.operation or '').upper():
                sort_ops.append(row)

        if len(sort_ops) >= 3:
            self._issues.append(PlanIssue(
                severity=SEVERITY_MEDIUM,
                category='과도한 SORT',
                title=f"SORT 연산 {len(sort_ops)}회 감지",
                description=(
                    f"플랜에서 SORT 연산이 {len(sort_ops)}회 발생합니다.\n"
                    "SORT 연산은 임시 공간(TEMP)을 사용하며 성능에 영향을 줍니다.\n"
                    f"SORT 노드: {', '.join(str(r.id) for r in sort_ops)}"
                ),
                suggestion=(
                    "ORDER BY, GROUP BY, DISTINCT 절을 검토하세요.\n"
                    "불필요한 정렬을 제거하거나 인덱스로 정렬을 대체할 수 있습니다.\n"
                    "예: ORDER BY 컬럼에 인덱스가 있으면 SORT를 건너뜁니다."
                ),
            ))
        elif any('DISK' in (r.options or '').upper() for r in sort_ops):
            self._issues.append(PlanIssue(
                severity=SEVERITY_HIGH,
                category='SORT DISK',
                title="SORT 디스크 사용 감지",
                description=(
                    "SORT 연산이 메모리를 초과하여 디스크(TEMP)를 사용 중입니다.\n"
                    "디스크 I/O로 인해 심각한 성능 저하가 발생할 수 있습니다."
                ),
                suggestion=(
                    "SORT_AREA_SIZE / PGA_AGGREGATE_TARGET 증가를 DBA에게 요청하세요.\n"
                    "또는 데이터 필터링을 강화하여 SORT 대상 행 수를 줄이세요."
                ),
            ))

    def _check_buffer_sort(self):
        """Operation이 BUFFER SORT인 경우 감지"""
        for row in self.rows:
            if 'BUFFER SORT' in (row.operation or '').upper():
                self._issues.append(PlanIssue(
                    severity=SEVERITY_MEDIUM,
                    category='Buffer Sort',
                    title=f"BUFFER SORT 감지 (노드 {row.id})",
                    description=(
                        f"노드 ID {row.id}에서 BUFFER SORT가 발생합니다.\n"
                        "정렬 버퍼 사용 중, ORDER BY 또는 조인 방식 검토 필요합니다.\n"
                        "BUFFER SORT는 MERGE JOIN 등에서 내부 집합을 정렬할 때 사용됩니다."
                    ),
                    suggestion=(
                        "ORDER BY 절이 꼭 필요한지 검토하세요.\n"
                        "조인 방식을 HASH JOIN으로 변경하면 BUFFER SORT를 줄일 수 있습니다.\n"
                        "예: SELECT /*+ USE_HASH(테이블명) */ ..."
                    ),
                    related_node_id=row.id,
                ))

    def _check_index_full_scan(self):
        for row in self.rows:
            if row.operation == 'INDEX' and row.options == 'FULL SCAN':
                self._issues.append(PlanIssue(
                    severity=SEVERITY_MEDIUM,
                    category='Index Full Scan',
                    title=f"Index Full Scan: {row.object_name}",
                    description=(
                        f"인덱스 '{row.object_name}'에 Full Scan이 발생합니다.\n"
                        "Index Full Scan은 Table Full Scan보다 낫지만\n"
                        "Index Range Scan이 더 효율적입니다."
                    ),
                    suggestion=(
                        "WHERE 절에 인덱스 선두 컬럼 조건이 있는지 확인하세요.\n"
                        "선두 컬럼 조건이 없으면 인덱스 구조 변경을 검토하세요."
                    ),
                    related_node_id=row.id,
                ))

    def _check_high_cost_ratio(self):
        """단일 노드의 Cost가 전체의 70% 이상이면 HIGH로 보고"""
        # 루트 노드(parent_id가 None)의 cost를 전체 비용으로 사용
        root = next((r for r in self.rows if r.parent_id is None), None)
        if root is None or root.cost is None or root.cost <= HIGH_COST_MIN_ROOT:
            return
        total_cost = root.cost

        # 루트를 제외한 노드 중 cost 비율이 70% 이상인 첫 번째 노드 보고
        for row in self.rows:
            if row is root or row.cost is None or row.cost <= 0:
                continue
            ratio = (row.cost / total_cost) * 100
            if ratio >= 70:
                self._issues.append(PlanIssue(
                    severity=SEVERITY_HIGH,
                    category='비용 집중',
                    title=f"단일 노드 비용 집중: {row.full_operation} ({ratio:.0f}%)",
                    description=(
                        f"단일 노드에 비용이 집중되어 있습니다.\n"
                        f"노드 ID {row.id} '{row.full_operation}' "
                        f"({row.object_name})\n"
                        f"이 전체 비용의 약 {ratio:.0f}%를 차지합니다.\n"
                        f"Cost: {row.cost:,} / 총 Cost: {total_cost:,}"
                    ),
                    suggestion="위 노드를 집중적으로 튜닝하면 전체 성능을 크게 개선할 수 있습니다.",
                    related_node_id=row.id,
                ))
                break  # 가장 높은 비율의 노드 하나만 보고

    def _check_nested_loop_large(self):
        """대용량 테이블에 Nested Loop Join 사용 시 경고"""
        for row in self.rows:
            if row.operation == 'NESTED LOOPS':
                children_cards = []
                for child in row.children:
                    if child.cardinality:
                        children_cards.append(child.cardinality)
                if len(children_cards) >= 2:
                    inner_card = max(children_cards)
                    if inner_card > NL_INNER_CARD_THRESHOLD:
                        self._issues.append(PlanIssue(
                            severity=SEVERITY_MEDIUM,
                            category='Join 방식',
                            title=f"대용량 Nested Loop Join (예측 {inner_card:,}건)",
                            description=(
                                f"Nested Loop Join에서 Inner 집합의 예측 행 수가 {inner_card:,}건입니다.\n"
                                "대용량 데이터에서는 Hash Join이 더 효율적일 수 있습니다."
                            ),
                            suggestion=(
                                "Hash Join 유도 힌트 사용을 검토하세요:\n"
                                "SELECT /*+ USE_HASH(테이블명) */ ..."
                            ),
                            related_node_id=row.id,
                        ))

    def _check_no_stats(self):
        """통계가 없는 테이블 감지 (Cardinality가 1인 경우 의심)"""
        no_stat_tables = []
        for row in self.rows:
            if (row.operation == 'TABLE ACCESS'
                    and row.object_name
                    and row.cardinality == 1
                    and row.cost is not None and row.cost > NO_STATS_COST_THRESHOLD):
                no_stat_tables.append(row.object_name)

        if no_stat_tables:
            tables_str = ', '.join(set(no_stat_tables))
            self._issues.append(PlanIssue(
                severity=SEVERITY_MEDIUM,
                category='통계 정보 부재',
                title=f"테이블 통계 부재 의심: {tables_str}",
                description=(
                    f"테이블 [{tables_str}]의 Cardinality가 1로 표시됩니다.\n"
                    "통계 정보가 없으면 옵티마이저가 잘못된 실행 계획을 선택할 수 있습니다."
                ),
                suggestion=(
                    "DBA에게 테이블 통계 수집을 요청하세요:\n"
                    f"EXEC DBMS_STATS.GATHER_TABLE_STATS('스키마명', '테이블명');"
                ),
                sample_sql=(
                    f"-- 통계 수집 (DBA 권한 필요)\n"
                    f"BEGIN\n"
                    f"  DBMS_STATS.GATHER_TABLE_STATS(\n"
                    f"    ownname => '스키마명',\n"
                    f"    tabname => '{no_stat_tables[0]}',\n"
                    f"    cascade => TRUE\n"
                    f"  );\n"
                    f"END;"
                ),
            ))

    # ------------------------------------------------------------------
    # 요약
    # ------------------------------------------------------------------

    def get_summary(self) -> dict:
        """플랜 요약 정보를 반환합니다."""
        if not self.rows:
            return {}

        root = next((r for r in self.rows if r.parent_id is None), None)
        return {
            'total_cost': root.cost if root else None,
            'total_cardinality': root.cardinality if root else None,
            'node_count': len(self.rows),
            'max_depth': max((r.depth for r in self.rows), default=0),
            'has_fts': any(
                r.operation == 'TABLE ACCESS' and r.options == 'FULL'
                for r in self.rows
            ),
            'has_sort': any('SORT' in (r.operation or '') for r in self.rows),
            'join_types': list({r.operation for r in self.rows if 'JOIN' in (r.operation or '') or r.operation == 'NESTED LOOPS'}),
        }
