"""
sqlglot AST 기반 SQL 분석기 (개선판)
RegexAnalyzer 대비 개선 사항:
  1. 함수 감지 범위 확대
     - exp.Upper / exp.Lower / exp.Trim / exp.Substring 전용 노드 추가
     - exp.Anonymous 는 이름 기반으로 _INDEX_BREAKING_FUNCS 와 대조
  2. 묵시적 형변환 감지를 AST 레벨에서 수행 (3패턴)
     - P1: EQ(Column, Literal[string/숫자]) — 숫자 컬럼에 문자열 리터럴
     - P2: 형변환 함수(TO_NUMBER 등)가 WHERE 절 컬럼에 직접 적용
     - P3: Column || '' 연산으로 형변환 유도
     - 주석/문자열 리터럴 내부 오탐 없음
  3. 주석 또는 문자열 리터럴 내부의 키워드를 오탐하지 않음
  4. ROWNUM 페이징 안티패턴 (2종)
     - 이중 중첩 ROWNUM 페이징 (구식 Oracle 페이징)
     - ORDER BY 없는 ROWNUM <= N 단독 사용

파싱 실패 시 상위(CompositeAnalyzer)가 RegexAnalyzer 로 폴백합니다.
"""
from __future__ import annotations
import re
import sqlglot
from sqlglot import exp, ErrorLevel
from .base import SqlAnalyzer, SqlIssue

# 형변환 유발 함수 — _check_implicit_conversion(P2)에서 HIGH로 처리
# _check_function_on_where_col 과 중복 방지를 위해 별도 분리
_TYPE_CONVERSION_FUNCS: frozenset[str] = frozenset({
    'TO_NUMBER', 'TO_CHAR', 'TO_DATE', 'TO_TIMESTAMP',
})

# WHERE 절 컬럼에 적용되면 인덱스를 무효화하는 함수 이름 (대문자)
# 형변환 함수(_TYPE_CONVERSION_FUNCS)는 제외 — 중복 감지 방지
_INDEX_BREAKING_FUNCS: frozenset[str] = frozenset({
    'TRUNC', 'SUBSTR', 'UPPER', 'LOWER',
    'NVL', 'TRIM', 'LTRIM', 'RTRIM', 'NVL2',
    'DECODE', 'REPLACE', 'INSTR',
})

# sqlglot 전용 노드 → 함수 이름 매핑
_NODE_TO_FUNC: dict[type, str] = {
    exp.Upper:     'UPPER',
    exp.Lower:     'LOWER',
    exp.Trim:      'TRIM',
    exp.Substring: 'SUBSTR',
}


class AstAnalyzer(SqlAnalyzer):
    """sqlglot AST 기반 SQL 분석기"""

    @property
    def engine_name(self) -> str:
        return 'AST (sqlglot)'

    def analyze(self, sql: str) -> list[SqlIssue]:
        """파싱 실패 시 ValueError 를 raise → CompositeAnalyzer 가 폴백 처리"""
        tree = sqlglot.parse_one(sql, dialect='oracle', error_level=ErrorLevel.RAISE)

        issues: list[SqlIssue] = []
        issues += self._check_select_star(tree)
        issues += self._check_function_on_where_col(tree)
        issues += self._check_implicit_conversion(tree)
        issues += self._check_not_in_null(tree)
        issues += self._check_or_conditions(tree)
        issues += self._check_like_leading_wildcard(tree)
        issues += self._check_distinct_join(tree)
        issues += self._check_scalar_subquery(tree)
        issues += self._check_union_vs_union_all(tree)
        issues += self._check_missing_where(tree, sql)
        issues += self._check_rownum_nested_paging(tree)
        issues += self._check_rownum_no_order(tree)

        return self.sort_issues(issues)

    # ------------------------------------------------------------------
    # 개별 규칙
    # ------------------------------------------------------------------

    def _check_select_star(self, tree) -> list[SqlIssue]:
        if tree.find(exp.Star):
            return [SqlIssue(
                severity='LOW',
                category='SELECT *',
                title='SELECT * 사용',
                description=(
                    "SELECT *는 테이블의 모든 컬럼을 조회합니다.\n"
                    "불필요한 컬럼까지 네트워크/메모리로 전송되어 성능이 저하됩니다.\n"
                    "또한 컬럼 추가/변경 시 예상치 못한 오류가 발생할 수 있습니다."
                ),
                suggestion="필요한 컬럼만 명시적으로 지정하세요.\n예: SELECT COL1, COL2, COL3 FROM ...",
            )]
        return []

    def _check_function_on_where_col(self, tree) -> list[SqlIssue]:
        """
        WHERE 절 내부에서 컬럼에 인덱스 무효화 함수가 적용된 경우 감지.
        개선: exp.Upper / Lower / Trim / Substring 전용 노드 + Anonymous 이름 대조
        """
        where = tree.find(exp.Where)
        if not where:
            return []

        found: set[str] = set()
        for node in where.walk():
            fname = _NODE_TO_FUNC.get(type(node))
            if fname is None and isinstance(node, exp.Anonymous):
                candidate = (node.name or '').upper()
                if candidate in _INDEX_BREAKING_FUNCS:
                    fname = candidate
            if fname and node.find(exp.Column):
                found.add(fname)

        if found:
            funcs_str = ', '.join(sorted(found))
            return [SqlIssue(
                severity='MEDIUM',
                category='인덱스 무효화',
                title=f'WHERE 절 함수 사용: {funcs_str}',
                description=(
                    f"WHERE 절에서 컬럼에 함수({funcs_str})가 적용되면\n"
                    "해당 컬럼의 인덱스를 사용할 수 없게 됩니다.\n"
                    "이는 Full Table Scan의 원인이 됩니다."
                ),
                suggestion=(
                    "함수를 컬럼 대신 상수(비교값)에 적용하세요.\n\n"
                    "예시 (날짜 조건):\n"
                    "  나쁜 예: WHERE TO_CHAR(REG_DATE, 'YYYYMMDD') = '20240101'\n"
                    "  좋은 예: WHERE REG_DATE >= TO_DATE('20240101', 'YYYYMMDD')\n"
                    "           AND REG_DATE <  TO_DATE('20240102', 'YYYYMMDD')"
                ),
            )]
        return []

    def _check_implicit_conversion(self, tree) -> list[SqlIssue]:
        """
        AST 기반 묵시적 형변환 감지 — 3패턴.

        P1: Column = '숫자문자열'
            숫자형 컬럼에 문자열 리터럴로 비교 → Oracle 내부 TO_NUMBER 변환 유발
        P2: TypeConvFunc(Column) in WHERE
            TO_NUMBER / TO_CHAR / TO_DATE / TO_TIMESTAMP 가 컬럼에 직접 적용
            (_check_function_on_where_col 과 감지 대상 분리로 중복 없음)
        P3: Column || '' 비교
            숫자/날짜 컬럼을 || '' 연결로 강제 형변환 후 문자열과 비교
        """
        where = tree.find(exp.Where)
        if not where:
            return []

        issues: list[SqlIssue] = []

        # ── P1: Column = '숫자문자열' ──────────────────────────────────────
        p1_found = False
        for eq_node in where.find_all(exp.EQ):
            if p1_found:
                break
            for col_side, lit_side in [(eq_node.left, eq_node.right),
                                       (eq_node.right, eq_node.left)]:
                if (isinstance(col_side, exp.Column)
                        and isinstance(lit_side, exp.Literal)
                        and lit_side.is_string
                        and lit_side.this.isdigit()):
                    issues.append(SqlIssue(
                        severity='HIGH',
                        category='묵시적 형변환',
                        title='숫자 컬럼에 문자열 리터럴 비교',
                        description=(
                            "숫자형 컬럼에 문자열('숫자')로 비교하면 묵시적 형변환이 발생합니다.\n"
                            "Oracle은 내부적으로 TO_NUMBER 변환을 수행하며\n"
                            "이 과정에서 인덱스가 무효화될 수 있습니다."
                        ),
                        suggestion=(
                            "컬럼의 데이터 타입에 맞는 리터럴을 사용하세요.\n"
                            "숫자 컬럼: WHERE NUM_COL = 12345  (따옴표 없이)\n"
                            "문자 컬럼: WHERE CHR_COL = '12345'  (따옴표 있게)"
                        ),
                    ))
                    p1_found = True
                    break

        # ── P2: 형변환 함수(TO_NUMBER 등)가 컬럼에 직접 적용 ────────────────
        # sqlglot 은 TO_NUMBER 등을 exp.Anonymous 또는 전용 Func 서브클래스로 파싱.
        # exp.Anonymous → node.name 으로 이름 추출
        # 전용 Func 서브클래스 → node.sql() 앞부분으로 이름 추출 (폴백)
        found_conv: set[str] = set()
        for node in where.walk():
            fname = None
            if isinstance(node, (exp.Cast, exp.TryCast)):
                fname = 'CAST'
            elif isinstance(node, exp.Anonymous):
                candidate = (node.name or '').upper()
                if candidate in _TYPE_CONVERSION_FUNCS:
                    fname = candidate
            elif isinstance(node, exp.Func):
                try:
                    func_sql = node.sql(dialect='oracle').split('(')[0].strip().upper()
                    if func_sql in _TYPE_CONVERSION_FUNCS:
                        fname = func_sql
                except Exception:
                    pass
            if fname and node.find(exp.Column):
                found_conv.add(fname)

        if found_conv:
            funcs_str = ', '.join(sorted(found_conv))
            issues.append(SqlIssue(
                severity='HIGH',
                category='묵시적 형변환',
                title=f'WHERE 절 형변환 함수 적용: {funcs_str}',
                description=(
                    f"WHERE 절에서 컬럼에 형변환 함수({funcs_str})가 직접 적용되면\n"
                    "인덱스를 사용할 수 없고 묵시적 형변환이 발생합니다.\n"
                    "Full Table Scan의 주요 원인입니다."
                ),
                suggestion=(
                    "함수를 컬럼 대신 비교값(상수)에 적용하세요.\n\n"
                    "예시 (날짜 조건):\n"
                    "  나쁜 예: WHERE TO_CHAR(REG_DATE, 'YYYYMMDD') = '20240101'\n"
                    "  좋은 예: WHERE REG_DATE >= TO_DATE('20240101', 'YYYYMMDD')\n"
                    "           AND REG_DATE <  TO_DATE('20240102', 'YYYYMMDD')"
                ),
            ))

        # ── P3: Column || '' (문자열 연결로 형변환 유도) ─────────────────────
        for dpipe in where.find_all(exp.DPipe):
            left, right = dpipe.left, dpipe.right
            has_col = isinstance(left, exp.Column) or isinstance(right, exp.Column)
            has_empty = (
                (isinstance(right, exp.Literal) and right.is_string and right.this == '')
                or (isinstance(left, exp.Literal) and left.is_string and left.this == '')
            )
            if has_col and has_empty:
                issues.append(SqlIssue(
                    severity='HIGH',
                    category='묵시적 형변환',
                    title="문자열 연결 연산자(||)로 형변환 유도",
                    description=(
                        "SALARY || '' 패턴은 숫자/날짜 컬럼을 문자열로 강제 변환하여\n"
                        "인덱스를 무력화합니다.\n"
                        "비교 대상과의 타입 불일치로 추가 묵시적 형변환도 발생합니다."
                    ),
                    suggestion=(
                        "컬럼에 직접 비교하는 방식으로 변경하세요.\n"
                        "  나쁜 예: WHERE SALARY || '' = '5000'\n"
                        "  좋은 예: WHERE SALARY = 5000"
                    ),
                ))
                break

        return issues

    def _check_not_in_null(self, tree) -> list[SqlIssue]:
        """NOT IN (SELECT ...) — 서브쿼리 결과에 NULL 포함 시 전체 0건 위험"""
        for in_node in tree.find_all(exp.In):
            if in_node.args.get('query') is not None:
                if isinstance(in_node.parent, exp.Not):
                    return [SqlIssue(
                        severity='MEDIUM',
                        category='NOT IN NULL 위험',
                        title='NOT IN + 서브쿼리: NULL 위험',
                        description=(
                            "NOT IN 서브쿼리의 결과에 NULL이 하나라도 포함되면\n"
                            "전체 결과가 0건이 됩니다. (SQL NULL 비교 특성)\n"
                            "의도치 않은 결과를 초래할 수 있습니다."
                        ),
                        suggestion=(
                            "NOT EXISTS로 대체하거나 서브쿼리에 IS NOT NULL 조건을 추가하세요.\n\n"
                            "권장 방식 (NOT EXISTS):\n"
                            "  WHERE NOT EXISTS (\n"
                            "    SELECT 1 FROM 서브테이블\n"
                            "    WHERE 서브테이블.키 = 메인테이블.키\n"
                            "  )"
                        ),
                    )]
        return []

    def _check_or_conditions(self, tree) -> list[SqlIssue]:
        """WHERE 절 OR 조건 3개 이상"""
        where = tree.find(exp.Where)
        if not where:
            return []
        or_count = sum(1 for _ in where.find_all(exp.Or))
        if or_count >= 3:
            return [SqlIssue(
                severity='LOW',
                category='OR 조건',
                title=f'WHERE 절 OR 조건 {or_count}개',
                description=(
                    f"WHERE 절에 OR 조건이 {or_count}개 있습니다.\n"
                    "OR 조건이 많으면 인덱스 활용이 어렵고 실행 계획이 복잡해집니다."
                ),
                suggestion=(
                    "UNION ALL로 분리하거나 IN 절로 합치는 것을 검토하세요.\n\n"
                    "예시:\n"
                    "  나쁜 예: WHERE COL = 'A' OR COL = 'B' OR COL = 'C'\n"
                    "  좋은 예: WHERE COL IN ('A', 'B', 'C')"
                ),
            )]
        return []

    def _check_like_leading_wildcard(self, tree) -> list[SqlIssue]:
        """LIKE '%값' — 앞 와일드카드로 인한 인덱스 미사용"""
        for like in tree.find_all(exp.Like):
            pat = like.expression
            if isinstance(pat, exp.Literal) and pat.is_string:
                if pat.this.startswith('%'):
                    return [SqlIssue(
                        severity='MEDIUM',
                        category='LIKE 앞 와일드카드',
                        title="LIKE '%값' 앞 와일드카드 사용",
                        description=(
                            "LIKE '%값' 형태는 앞 와일드카드로 인해 인덱스를 사용할 수 없습니다.\n"
                            "Full Table Scan 또는 Index Full Scan이 발생합니다."
                        ),
                        suggestion=(
                            "가능하면 LIKE '값%' 형태(앞 고정)로 변경하세요.\n"
                            "앞 와일드카드가 필수라면 Function Based Index나\n"
                            "Oracle Text 인덱스를 고려하세요."
                        ),
                    )]
        return []

    def _check_distinct_join(self, tree) -> list[SqlIssue]:
        """DISTINCT + JOIN 조합 — 불필요한 정렬 연산 가능성"""
        if tree.find(exp.Distinct) and tree.find(exp.Join):
            return [SqlIssue(
                severity='INFO',
                category='DISTINCT + JOIN',
                title='DISTINCT + JOIN 조합',
                description=(
                    "DISTINCT와 JOIN을 함께 사용하면 JOIN으로 증가한 행을\n"
                    "DISTINCT로 다시 제거하는 불필요한 정렬/해시 연산이 발생합니다.\n"
                    "JOIN 조건이 올바른지 먼저 확인하세요."
                ),
                suggestion=(
                    "JOIN 조건을 검토하여 중복이 발생하는 원인을 파악하세요.\n"
                    "가능하면 EXISTS 서브쿼리로 대체하거나\n"
                    "1:1 관계가 보장된 경우 DISTINCT를 제거하세요."
                ),
            )]
        return []

    def _check_scalar_subquery(self, tree) -> list[SqlIssue]:
        """SELECT 절 스칼라 서브쿼리 3개 이상"""
        select = tree.find(exp.Select)
        if not select:
            return []
        count = sum(1 for expr in select.expressions if expr.find(exp.Subquery))
        if count >= 3:
            return [SqlIssue(
                severity='MEDIUM',
                category='스칼라 서브쿼리',
                title=f'SELECT 절 스칼라 서브쿼리 {count}개',
                description=(
                    f"SELECT 절에 스칼라 서브쿼리가 {count}개 있습니다.\n"
                    "스칼라 서브쿼리는 행마다 실행되므로 대용량에서 매우 느립니다."
                ),
                suggestion=(
                    "LEFT OUTER JOIN으로 변환하는 것을 검토하세요.\n\n"
                    "예시:\n"
                    "  나쁜 예: SELECT A.COL, (SELECT B.VAL FROM B WHERE B.ID = A.ID)\n"
                    "  좋은 예: SELECT A.COL, B.VAL\n"
                    "           FROM A LEFT JOIN B ON B.ID = A.ID"
                ),
            )]
        return []

    def _check_union_vs_union_all(self, tree) -> list[SqlIssue]:
        """UNION (중복 제거) 사용 시 UNION ALL 고려 제안"""
        for node in tree.find_all(exp.Union):
            if node.args.get('distinct', False):
                return [SqlIssue(
                    severity='INFO',
                    category='UNION vs UNION ALL',
                    title='UNION 사용 (UNION ALL 고려)',
                    description=(
                        "UNION은 중복 제거를 위해 추가적인 SORT/HASH 연산을 수행합니다.\n"
                        "결과 집합에 중복이 없다고 보장되면 UNION ALL이 더 빠릅니다."
                    ),
                    suggestion=(
                        "중복 데이터가 없다고 확인된 경우 UNION ALL로 변경하세요.\n"
                        "UNION ALL은 중복 제거 연산이 없어 성능이 향상됩니다."
                    ),
                )]
        return []

    def _check_missing_where(self, tree, sql: str) -> list[SqlIssue]:
        """UPDATE/DELETE 에 WHERE 절 없음"""
        m = re.match(r'\s*(UPDATE|DELETE)\b', sql, re.IGNORECASE)
        if m and not tree.find(exp.Where):
            op = m.group(1).upper()
            return [SqlIssue(
                severity='HIGH',
                category='전체 테이블 변경',
                title=f'{op} 문에 WHERE 절 없음',
                description=(
                    f"WHERE 절이 없는 {op} 문은 테이블의 모든 행을 변경합니다!\n"
                    "의도하지 않은 대량 데이터 변경이 발생할 수 있습니다."
                ),
                suggestion=(
                    "반드시 WHERE 조건을 추가하여 대상 행을 한정하세요.\n"
                    "테스트 전 SELECT로 영향 행 수를 먼저 확인하는 것을 권장합니다."
                ),
            )]
        return []

    @staticmethod
    def _where_contains_rownum(where_node) -> bool:
        """WHERE 절에 ROWNUM 컬럼이 있는지 확인한다."""
        return any(
            (col.name or '').upper() == 'ROWNUM'
            for col in where_node.find_all(exp.Column)
        )

    @staticmethod
    def _is_inside_subquery(node) -> bool:
        """노드가 Subquery(인라인 뷰) 안에 있는지 확인한다."""
        parent = node.parent
        while parent:
            if isinstance(parent, exp.Subquery):
                return True
            parent = parent.parent
        return False

    def _check_rownum_nested_paging(self, tree) -> list[SqlIssue]:
        """
        이중 중첩 ROWNUM 페이징 패턴 감지.

        Oracle 구식 페이징의 전형적인 형태:
          SELECT * FROM (
            SELECT A.*, ROWNUM RN FROM (...) A WHERE ROWNUM <= :end
          ) WHERE RN >= :start

        감지 기준:
          ① Subquery(인라인 뷰) 안쪽 WHERE 절에 ROWNUM 이 있고
          ② 그 Subquery 를 감싸는 바깥쪽 WHERE 절이 존재한다
        """
        rownum_in_subquery = False
        has_outer_where = False

        for where in tree.find_all(exp.Where):
            if self._where_contains_rownum(where):
                if self._is_inside_subquery(where):
                    rownum_in_subquery = True
            else:
                has_outer_where = True

        if rownum_in_subquery and has_outer_where:
            return [SqlIssue(
                severity='MEDIUM',
                category='PAGING',
                title='구식 ROWNUM 페이징 패턴',
                description=(
                    "SELECT * FROM (SELECT ..., ROWNUM RN FROM (...) WHERE ROWNUM <= :n)\n"
                    "WHERE RN >= :m 형태의 구식 Oracle 페이징입니다.\n"
                    "복잡한 중첩 구조로 성능 예측이 어렵고 유지보수가 힘듭니다."
                ),
                suggestion=(
                    "Oracle 12c 이상이면 OFFSET/FETCH NEXT를 사용하세요:\n"
                    "  SELECT * FROM ORDERS ORDER BY ORDER_DATE\n"
                    "  OFFSET :offset ROWS FETCH NEXT :n ROWS ONLY\n\n"
                    "또는 ROW_NUMBER() OVER() 방식:\n"
                    "  SELECT * FROM (\n"
                    "    SELECT A.*, ROW_NUMBER() OVER (ORDER BY ORDER_DATE) AS RN\n"
                    "    FROM ORDERS A\n"
                    "  ) WHERE RN BETWEEN :start AND :end"
                ),
            )]
        return []

    def _check_rownum_no_order(self, tree) -> list[SqlIssue]:
        """
        ORDER BY 없는 ROWNUM <= N 단독 사용 감지.

        WHERE ROWNUM <= N 조건이 있으나 ORDER BY 절이 없으면
        어떤 행이 반환될지 보장되지 않는다.

        감지 기준:
          ① Subquery 밖(최상위) WHERE 절에 ROWNUM 이 있고
          ② 쿼리 전체에 ORDER BY 가 없다
          (Subquery 안쪽 ROWNUM 은 _check_rownum_nested_paging 에서 처리)
        """
        for where in tree.find_all(exp.Where):
            if not self._where_contains_rownum(where):
                continue
            # 이 WHERE가 Subquery 밖에 있어야 한다
            if self._is_inside_subquery(where):
                continue
            # ORDER BY 가 없으면 경고
            if not tree.find(exp.Order):
                return [SqlIssue(
                    severity='MEDIUM',
                    category='PAGING',
                    title='ORDER BY 없는 ROWNUM 페이징',
                    description=(
                        "WHERE ROWNUM <= N 조건이 ORDER BY 없이 사용되었습니다.\n"
                        "ORDER BY가 없으면 어떤 행이 반환될지 보장되지 않습니다.\n"
                        "Oracle의 행 저장 순서는 실행마다 달라질 수 있습니다."
                    ),
                    suggestion=(
                        "ORDER BY를 추가하거나 ROW_NUMBER() OVER(ORDER BY ...) 방식을 사용하세요.\n\n"
                        "예시:\n"
                        "  나쁜 예: SELECT * FROM ORDERS WHERE ROWNUM <= 10\n"
                        "  좋은 예: SELECT * FROM (\n"
                        "             SELECT * FROM ORDERS ORDER BY ORDER_DATE\n"
                        "           ) WHERE ROWNUM <= 10"
                    ),
                )]
        return []
