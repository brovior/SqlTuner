"""
IndexAdvisor – SQL WHERE 절 기반 누락 인덱스 분석기

흐름:
  1. OracleClient.get_tables_from_sql()   → SQL에서 테이블명 추출
  2. OracleClient.get_table_indexes()     → 테이블별 현재 인덱스 조회
  3. _extract_where_columns()             → WHERE / JOIN ON 절 컬럼 추출 (sqlglot AST)
  4. _find_missing_columns()              → 인덱스 선두(leading) 컬럼과 비교
  5. _build_advice()                      → 누락 컬럼별 DDL + 심각도 생성

외부 의존: OracleClient (DB 조회), sqlglot (SQL 파싱)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from v2.core.db.oracle_client import OracleClient


# ──────────────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class IndexInfo:
    """테이블의 기존 인덱스 하나를 나타냅니다."""
    table_name: str
    index_name: str
    columns: list[str]          # COLUMN_POSITION 순서
    uniqueness: str             # "UNIQUE" | "NONUNIQUE"
    status: str                 # "VALID" | "UNUSABLE" | ...


@dataclass
class IndexAdvice:
    """누락 인덱스에 대한 개선 제안 하나를 나타냅니다."""
    severity: str               # "HIGH" | "MEDIUM" | "INFO"
    table_name: str
    missing_columns: list[str]  # 인덱스가 없는 WHERE 절 컬럼 목록
    suggested_ddl: str          # CREATE INDEX ...
    reason: str                 # 사람이 읽을 수 있는 이유 설명


# ──────────────────────────────────────────────────────────────────────────────
# 메인 클래스
# ──────────────────────────────────────────────────────────────────────────────

class IndexAdvisor:
    """
    SQL 텍스트와 DB 인덱스 메타데이터를 결합하여
    누락 인덱스를 감지하고 DDL을 제안합니다.
    """

    def __init__(self, client: "OracleClient") -> None:
        self._client = client

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def advise(self, sql: str) -> tuple[list[IndexInfo], list[IndexAdvice]]:
        """
        SQL을 분석하여 현재 인덱스 목록과 개선 제안을 반환합니다.

        Parameters
        ----------
        sql : str
            분석할 SQL 텍스트

        Returns
        -------
        (index_info_list, advice_list)
            index_info_list : SQL에 등장하는 모든 테이블의 현재 인덱스
            advice_list     : 누락 인덱스 개선 제안 (심각도 높은 순)
        """
        if not sql or not sql.strip():
            return [], []

        # 1. SQL에서 테이블 추출
        tables: list[str] = self._client.get_tables_from_sql(sql)
        if not tables:
            return [], []

        # 2. 테이블별 현재 인덱스 조회 → IndexInfo 목록 구성
        indexes_by_table: dict[str, list[dict]] = {}
        all_index_info: list[IndexInfo] = []
        for table in tables:
            raw = self._client.get_table_indexes(table)
            indexes_by_table[table] = raw
            for idx in raw:
                all_index_info.append(IndexInfo(
                    table_name=table,
                    index_name=idx["index_name"],
                    columns=idx["columns"],
                    uniqueness=idx["uniqueness"],
                    status=idx["status"],
                ))

        # 3. WHERE / JOIN ON 절에서 테이블별 컬럼 추출
        where_cols: dict[str, list[str]] = self._extract_where_columns(sql, tables)
        if not where_cols:
            return all_index_info, []

        # 4. 누락 인덱스 감지 → 제안 생성
        advices: list[IndexAdvice] = []
        for table in tables:
            cols = where_cols.get(table, [])
            if not cols:
                continue
            existing = indexes_by_table.get(table, [])
            advice = self._build_advice(table, cols, existing)
            if advice:
                advices.append(advice)

        # 심각도 순 정렬 (HIGH → MEDIUM → INFO)
        _SEV_ORDER = {"HIGH": 0, "MEDIUM": 1, "INFO": 2}
        advices.sort(key=lambda a: _SEV_ORDER.get(a.severity, 9))

        return all_index_info, advices

    # ──────────────────────────────────────────────────────────────────────
    # 내부: WHERE / JOIN ON 컬럼 추출
    # ──────────────────────────────────────────────────────────────────────

    def _extract_where_columns(
        self, sql: str, known_tables: list[str]
    ) -> dict[str, list[str]]:
        """
        sqlglot AST를 사용해 WHERE 절과 JOIN ON 조건에서
        테이블별 컬럼 목록을 추출합니다.

        반환값: {TABLE_NAME: [COL1, COL2, ...]}  (대문자, 순서 유지, 중복 제거)
        파싱 실패 시 빈 딕셔너리 반환.
        """
        try:
            import sqlglot
            from sqlglot import exp
        except ImportError:
            return {}

        try:
            tree = sqlglot.parse_one(sql, dialect="oracle",
                                     error_level=sqlglot.ErrorLevel.IGNORE)
        except Exception:
            return {}

        if tree is None:
            return {}

        # 테이블 별칭 → 실제 테이블명 맵 구성
        known_set = set(known_tables)
        alias_map: dict[str, str] = {}
        for tbl in tree.find_all(exp.Table):
            name = tbl.name.upper() if tbl.name else None
            if not name:
                continue
            alias_map[name] = name          # 테이블명 자체도 키로 등록
            if tbl.alias:
                alias_map[tbl.alias.upper()] = name

        # 결과 컨테이너
        result: dict[str, list[str]] = {t: [] for t in known_tables}
        seen: dict[str, set[str]] = {t: set() for t in known_tables}

        def _add(table: str, col: str) -> None:
            if table in known_set and col not in seen[table]:
                seen[table].add(col)
                result[table].append(col)

        def _collect(node: "exp.Expression | None") -> None:
            """노드 하위의 모든 Column 을 순회하며 테이블에 배정합니다."""
            if node is None:
                return
            for col_node in node.find_all(exp.Column):
                col_name = col_node.name.upper() if col_node.name else None
                if not col_name:
                    continue
                table_ref = col_node.table.upper() if col_node.table else None

                if table_ref:
                    real = alias_map.get(table_ref)
                    if real:
                        _add(real, col_name)
                else:
                    # 테이블 한정자 없음 → 테이블이 1개면 그쪽으로 배정
                    if len(known_tables) == 1:
                        _add(known_tables[0], col_name)

        # WHERE 절
        for where in tree.find_all(exp.Where):
            _collect(where)

        # JOIN ON 절
        for join in tree.find_all(exp.Join):
            _collect(join.args.get("on"))

        return {t: cols for t, cols in result.items() if cols}

    # ──────────────────────────────────────────────────────────────────────
    # 내부: 누락 인덱스 감지 및 조언 생성
    # ──────────────────────────────────────────────────────────────────────

    def _find_missing_columns(
        self, where_cols: list[str], existing_indexes: list[dict]
    ) -> list[str]:
        """
        WHERE 절 컬럼 중 어떤 인덱스의 선두(leading) 컬럼도 아닌 것을 반환합니다.

        선두 컬럼 기준을 사용하는 이유:
          복합 인덱스는 선두 컬럼부터 순서대로만 Range Scan이 가능하므로,
          선두가 아닌 컬럼만 사용하는 쿼리는 인덱스 혜택을 받지 못합니다.
        """
        # UNUSABLE 인덱스는 제외
        leading_indexed: set[str] = set()
        for idx in existing_indexes:
            if idx.get("status", "").upper() == "UNUSABLE":
                continue
            cols = idx.get("columns", [])
            if cols:
                leading_indexed.add(cols[0].upper())

        return [c for c in where_cols if c.upper() not in leading_indexed]

    def _build_advice(
        self,
        table: str,
        where_cols: list[str],
        existing_indexes: list[dict],
    ) -> "IndexAdvice | None":
        """
        누락 인덱스가 있을 때 IndexAdvice를 생성합니다.
        모든 WHERE 컬럼이 이미 인덱스 선두 컬럼이면 None 반환.

        심각도 결정 기준:
          HIGH   – 해당 테이블에 유효 인덱스가 전혀 없음 (Full Table Scan 확실)
          MEDIUM – 일부 인덱스는 있으나 WHERE 컬럼이 미커버 상태
          INFO   – 사용 가능한 인덱스 있지만 복합 인덱스 최적화 여지 있음
        """
        missing = self._find_missing_columns(where_cols, existing_indexes)
        if not missing:
            return None

        valid_indexes = [
            idx for idx in existing_indexes
            if idx.get("status", "").upper() != "UNUSABLE"
        ]

        if not valid_indexes:
            severity = "HIGH"
            reason = (
                f"테이블 {table}에 유효한 인덱스가 없습니다. "
                f"WHERE 절 컬럼 {missing}에 대해 Full Table Scan이 발생합니다."
            )
        elif not missing:
            # 이 분기는 위에서 이미 걸러지지만 방어적으로 유지
            return None
        else:
            severity = "MEDIUM"
            reason = (
                f"테이블 {table}의 WHERE 절 컬럼 {missing}이(가) "
                f"인덱스 선두 컬럼으로 등록되어 있지 않습니다. "
                f"Index Range Scan을 유도하려면 해당 컬럼을 선두로 하는 인덱스가 필요합니다."
            )

        ddl = self._generate_ddl(table, missing)

        return IndexAdvice(
            severity=severity,
            table_name=table,
            missing_columns=missing,
            suggested_ddl=ddl,
            reason=reason,
        )

    # ──────────────────────────────────────────────────────────────────────
    # 내부: DDL 생성
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _generate_ddl(table: str, columns: list[str]) -> str:
        """
        누락 인덱스에 대한 CREATE INDEX DDL을 생성합니다.

        인덱스명 규칙: IDX_{TABLE}_{COL1}[_{COL2}]
          - 컬럼이 3개 이상이면 앞 2개만 인덱스명에 포함 (너무 긴 이름 방지)
          - Oracle 최대 식별자 길이(30자)를 초과하면 자동 트런케이트
        """
        col_str = ", ".join(columns)
        name_suffix = "_".join(c[:10] for c in columns[:2])  # 최대 2컬럼, 각 10자
        raw_name = f"IDX_{table}_{name_suffix}"
        idx_name = raw_name[:30]  # Oracle 식별자 최대 30자
        return f"CREATE INDEX {idx_name} ON {table} ({col_str});"
