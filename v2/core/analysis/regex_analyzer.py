"""
정규식 기반 SQL 안티패턴 분석기
SqlAnalyzer 인터페이스를 구현합니다.

기존 tuning_rules.SqlTextAnalyzer 를 SqlAnalyzer ABC 상속으로 재작성.
sqlglot 파싱이 실패한 경우 AstAnalyzer 가 이 클래스로 폴백합니다.

감지 규칙 (10가지):
  HIGH   - UPDATE/DELETE WHERE 절 없음
  MEDIUM - WHERE 절 컬럼에 함수 적용 (인덱스 무효화)
  MEDIUM - 묵시적 형변환 의심 (= '숫자')
  MEDIUM - NOT IN 서브쿼리 NULL 위험
  MEDIUM - LIKE '%값' 앞 와일드카드
  MEDIUM - SELECT 절 스칼라 서브쿼리 3개 이상
  LOW    - SELECT * 사용
  LOW    - WHERE 절 OR 조건 3개 이상
  INFO   - DISTINCT + JOIN 조합
  INFO   - UNION (UNION ALL 고려)
"""
from __future__ import annotations
import re
from .base import SqlAnalyzer, SqlIssue


class RegexAnalyzer(SqlAnalyzer):
    """정규식 기반 SQL 분석기 (AstAnalyzer 파싱 실패 시 폴백)"""

    @property
    def engine_name(self) -> str:
        return '정규식 (Regex)'

    def analyze(self, sql: str) -> list[SqlIssue]:
        issues: list[SqlIssue] = []
        sql_upper = sql.upper()

        issues += self._check_missing_where(sql_upper)
        issues += self._check_function_on_column(sql)
        issues += self._check_implicit_conversion(sql)
        issues += self._check_not_in_null(sql_upper)
        issues += self._check_like_leading_wildcard(sql_upper)
        issues += self._check_scalar_subquery(sql_upper)
        issues += self._check_select_star(sql_upper)
        issues += self._check_or_condition(sql_upper)
        issues += self._check_distinct_join(sql_upper)
        issues += self._check_union_vs_union_all(sql_upper)

        return self.sort_issues(issues)

    # ------------------------------------------------------------------
    # 규칙 구현
    # ------------------------------------------------------------------

    def _check_missing_where(self, sql: str) -> list[SqlIssue]:
        """UPDATE/DELETE 문에 WHERE 절 없음 경고"""
        m = re.match(r'\s*(UPDATE|DELETE)\b', sql, re.IGNORECASE)
        has_where = bool(re.search(r'\bWHERE\b', sql, re.IGNORECASE))
        if m and not has_where:
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
                    f"반드시 WHERE 조건을 추가하여 대상 행을 한정하세요.\n"
                    "테스트 전 SELECT로 영향 행 수를 먼저 확인하는 것을 권장합니다."
                ),
            )]
        return []

    def _check_function_on_column(self, sql: str) -> list[SqlIssue]:
        """WHERE 절 컬럼에 함수 적용 감지 → 인덱스 무효화"""
        where_match = re.search(r'\bWHERE\b(.*)', sql, re.IGNORECASE | re.DOTALL)
        if not where_match:
            return []
        where_part = where_match.group(1)

        func_patterns = [
            (r'\bTO_CHAR\s*\(', 'TO_CHAR'),
            (r'\bTO_DATE\s*\(', 'TO_DATE'),
            (r'\bTRUNC\s*\(', 'TRUNC'),
            (r'\bSUBSTR\s*\(', 'SUBSTR'),
            (r'\bUPPER\s*\(', 'UPPER'),
            (r'\bLOWER\s*\(', 'LOWER'),
            (r'\bNVL\s*\(', 'NVL'),
            (r'\bTO_NUMBER\s*\(', 'TO_NUMBER'),
            (r'\bTRIM\s*\(', 'TRIM'),
            (r'\bLTRIM\s*\(', 'LTRIM'),
            (r'\bRTRIM\s*\(', 'RTRIM'),
        ]
        found_funcs = []
        for pattern, fname in func_patterns:
            if re.search(pattern, where_part, re.IGNORECASE):
                found_funcs.append(fname)

        if found_funcs:
            funcs_str = ', '.join(found_funcs)
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

    def _check_implicit_conversion(self, sql: str) -> list[SqlIssue]:
        """묵시적 형변환 패턴 감지 (숫자 컬럼 = '숫자문자열')"""
        if re.search(r"=\s*'[0-9]+'", sql, re.IGNORECASE):
            return [SqlIssue(
                severity='MEDIUM',
                category='묵시적 형변환',
                title='묵시적 형변환 의심',
                description=(
                    "숫자형 컬럼에 문자열('숫자')로 비교하면 묵시적 형변환이 발생합니다.\n"
                    "Oracle은 자동으로 TO_NUMBER 변환을 수행하지만\n"
                    "이 과정에서 인덱스가 무효화될 수 있습니다."
                ),
                suggestion=(
                    "컬럼의 데이터 타입에 맞는 리터럴을 사용하세요.\n"
                    "숫자 컬럼: WHERE NUM_COL = 12345  (따옴표 없이)\n"
                    "문자 컬럼: WHERE CHR_COL = '12345'  (따옴표 있게)"
                ),
            )]
        return []

    def _check_not_in_null(self, sql: str) -> list[SqlIssue]:
        """NOT IN 서브쿼리에 NULL 가능성 경고"""
        if re.search(r'\bNOT\s+IN\s*\(?\s*SELECT', sql, re.IGNORECASE):
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

    def _check_like_leading_wildcard(self, sql: str) -> list[SqlIssue]:
        """LIKE '%값' 앞 와일드카드 사용 감지"""
        if re.search(r"LIKE\s+'%[^%]", sql, re.IGNORECASE):
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

    def _check_scalar_subquery(self, sql: str) -> list[SqlIssue]:
        """SELECT 절 스칼라 서브쿼리 과다 사용"""
        # FROM 으로 분리하면 서브쿼리 내부 FROM 에 걸릴 수 있으므로
        # SQL 전체에서 중첩 SELECT 수를 카운트한다 (WHERE 서브쿼리 포함 허용)
        count = len(re.findall(r'\(\s*SELECT\b', sql, re.IGNORECASE))
        if count >= 3:
            return [SqlIssue(
                severity='MEDIUM',
                category='스칼라 서브쿼리',
                title=f'SELECT 절 스칼라 서브쿼리 {count}개',
                description=(
                    f"SELECT 절에 스칼라 서브쿼리가 {count}개 있습니다.\n"
                    "스칼라 서브쿼리는 행마다 실행되므로 대용량에서 매우 느립니다.\n"
                    "내부적으로 캐싱되지만 조건 값 다양성이 높으면 효과가 없습니다."
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

    def _check_select_star(self, sql: str) -> list[SqlIssue]:
        """SELECT * 사용 감지"""
        if re.search(r'SELECT\s+\*', sql, re.IGNORECASE):
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

    def _check_or_condition(self, sql: str) -> list[SqlIssue]:
        """WHERE 절 OR 조건 과다 사용"""
        where_match = re.search(
            r'\bWHERE\b(.*?)(?:\bGROUP\b|\bORDER\b|\bHAVING\b|$)',
            sql, re.IGNORECASE | re.DOTALL
        )
        if not where_match:
            return []
        where_part = where_match.group(1)
        or_count = len(re.findall(r'\bOR\b', where_part, re.IGNORECASE))

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

    def _check_distinct_join(self, sql: str) -> list[SqlIssue]:
        """DISTINCT와 JOIN이 함께 사용될 때 경고"""
        has_distinct = bool(re.search(r'\bSELECT\s+DISTINCT\b', sql, re.IGNORECASE))
        has_join = bool(re.search(r'\bJOIN\b', sql, re.IGNORECASE))
        if has_distinct and has_join:
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

    def _check_union_vs_union_all(self, sql: str) -> list[SqlIssue]:
        """UNION 사용 시 UNION ALL 고려 제안"""
        has_union = bool(re.search(r'\bUNION\b(?!\s+ALL)', sql, re.IGNORECASE))
        if has_union:
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
