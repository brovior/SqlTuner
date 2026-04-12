"""
정규식 기반 SQL 자동 재작성기
SqlRewriter 인터페이스를 구현합니다.

변환 규칙:
  1. 동일 컬럼 OR 조건  →  IN 절
  2. NOT IN (SELECT ...)  →  NOT EXISTS
  3. UNION  →  UNION ALL
"""
from __future__ import annotations
import re
from .base import SqlRewriter, RewriteResult


class RegexRewriter(SqlRewriter):

    @property
    def engine_name(self) -> str:
        return '정규식 (Regex)'

    def rewrite(self, sql: str) -> RewriteResult:
        result = sql
        all_changes: list[str] = []

        result, c = self._or_to_in(result)
        all_changes.extend(c)

        result, c = self._not_in_to_not_exists(result)
        all_changes.extend(c)

        result, c = self._union_to_union_all(result)
        all_changes.extend(c)

        return RewriteResult(
            original_sql=sql,
            rewritten_sql=result,
            changes=all_changes,
            engine_used=self.engine_name,
        )

    # ------------------------------------------------------------------

    def _or_to_in(self, sql: str) -> tuple[str, list[str]]:
        """col = 'A' OR col = 'B' OR col = 'C'  →  col IN ('A', 'B', 'C')"""
        changes: list[str] = []
        val = r"(?:'[^']*'|[\d.]+)"
        pattern = re.compile(
            r'(\b\w+\b)\s*=\s*' + val +
            r'(?:\s+OR\s+\1\s*=\s*' + val + r')+',
            re.IGNORECASE,
        )

        def replace(m: re.Match) -> str:
            full = m.group(0)
            col = m.group(1)
            vals = re.findall(r'=\s*(' + val + r')', full)
            changes.append(f'OR 조건 → IN 변환 ({col})')
            return f'{col} IN ({", ".join(vals)})'

        return pattern.sub(replace, sql), changes

    def _not_in_to_not_exists(self, sql: str) -> tuple[str, list[str]]:
        """col NOT IN (SELECT col2 FROM tbl [alias] [WHERE ...])  →  NOT EXISTS"""
        changes: list[str] = []
        pattern = re.compile(
            r'(\w+(?:\.\w+)?)\s+NOT\s+IN\s*\(\s*'
            r'SELECT\s+(\w+(?:\.\w+)?)\s+FROM\s+(\w+)(?:\s+(\w+))?'
            r'(\s+WHERE\s+[^)]+?)?\s*\)',
            re.IGNORECASE | re.DOTALL,
        )

        def replace(m: re.Match) -> str:
            outer_col   = m.group(1)
            inner_col   = m.group(2)
            table       = m.group(3)
            alias       = m.group(4)
            extra_where = m.group(5) or ''

            ref   = f'{table} {alias}' if alias else table
            conds = [f'{inner_col} = {outer_col}']
            if extra_where.strip():
                extra = re.sub(r'^\s*WHERE\s+', '', extra_where.strip(), flags=re.IGNORECASE)
                conds.append(extra)

            changes.append('NOT IN → NOT EXISTS 변환 (NULL 안전성 향상)')
            return (
                f'NOT EXISTS (\n'
                f'    SELECT 1 FROM {ref}\n'
                f'    WHERE {" AND ".join(conds)}\n'
                f')'
            )

        return pattern.sub(replace, sql), changes

    def _union_to_union_all(self, sql: str) -> tuple[str, list[str]]:
        """UNION  →  UNION ALL"""
        changes: list[str] = []
        pattern = re.compile(r'\bUNION\b(?!\s+ALL)', re.IGNORECASE)
        if pattern.search(sql):
            changes.append('UNION → UNION ALL 변환 (⚠ 결과에 중복이 없는 경우에만 적용)')
            return pattern.sub('UNION ALL', sql), changes
        return sql, changes
