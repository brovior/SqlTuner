"""
sqlglot AST 기반 SQL 자동 재작성기
SqlRewriter 인터페이스를 구현합니다.

RegexRewriter 대비 장점:
  - 주석/문자열 내부 패턴을 건드리지 않음
  - 출력 SQL 이 pretty-print 로 자동 정형화됨
  - 중첩 구조도 정확하게 처리

파싱 실패 시 ValueError 를 raise → CompositeRewriter 가 폴백 처리.
"""
from __future__ import annotations
import sqlglot
from sqlglot import exp, ErrorLevel
from .base import SqlRewriter, RewriteResult


class AstRewriter(SqlRewriter):

    @property
    def engine_name(self) -> str:
        return 'AST (sqlglot)'

    def rewrite(self, sql: str) -> RewriteResult:
        """파싱 실패 시 ValueError raise → CompositeRewriter 가 폴백"""
        tree = sqlglot.parse_one(sql, dialect='oracle', error_level=ErrorLevel.RAISE)

        all_changes: list[str] = []

        tree, c = self._or_to_in(tree)
        all_changes.extend(c)

        tree, c = self._not_in_to_not_exists(tree)
        all_changes.extend(c)

        tree, c = self._union_to_union_all(tree)
        all_changes.extend(c)

        rewritten = tree.sql(dialect='oracle', pretty=True)
        return RewriteResult(
            original_sql=sql,
            rewritten_sql=rewritten,
            changes=all_changes,
            engine_used=self.engine_name,
        )

    # ── 헬퍼 ──────────────────────────────────────

    @staticmethod
    def _extract_col_vals(node) -> tuple:
        """
        EQ(col, literal) 또는 IN(col, [literals]) 노드에서
        (column_expr, [value_expr, ...]) 를 추출합니다.
        """
        if isinstance(node, exp.EQ):
            left, right = node.left, node.right
            if isinstance(left, exp.Column) and isinstance(right, exp.Literal):
                return left, [right]
            if isinstance(right, exp.Column) and isinstance(left, exp.Literal):
                return right, [left]
        elif isinstance(node, exp.In) and not node.args.get('query'):
            col = node.this
            if isinstance(col, exp.Column):
                return col, list(node.expressions)
        return None, None

    # ── 변환 규칙 ──────────────────────────────────

    def _or_to_in(self, tree) -> tuple:
        """col='A' OR col='B'  →  col IN ('A','B')  (bottom-up 연쇄 처리)"""
        changes: list[str] = []

        def transform(node):
            if not isinstance(node, exp.Or):
                return node
            left_col, left_vals = self._extract_col_vals(node.left)
            right_col, right_vals = self._extract_col_vals(node.right)
            if (left_col is not None and right_col is not None
                    and left_col.sql().upper() == right_col.sql().upper()):
                changes.append(f'OR 조건 → IN 변환 ({left_col.sql()})')
                return exp.In(
                    this=left_col.copy(),
                    expressions=[v.copy() for v in left_vals + right_vals],
                )
            return node

        return tree.transform(transform), changes

    def _not_in_to_not_exists(self, tree) -> tuple:
        """col NOT IN (SELECT col2 FROM tbl [WHERE ...])  →  NOT EXISTS (SELECT 1 ...)"""
        changes: list[str] = []

        def transform(node):
            if not isinstance(node, exp.Not):
                return node
            inner = node.this
            if not isinstance(inner, exp.In):
                return node
            subquery = inner.args.get('query')
            if subquery is None:
                return node

            outer_col = inner.this
            inner_select = subquery.this
            inner_cols = inner_select.expressions
            if not inner_cols:
                return node

            join_cond = exp.EQ(
                this=inner_cols[0].copy(),
                expression=outer_col.copy(),
            )
            existing_where = inner_select.args.get('where')
            if existing_where:
                new_cond = exp.And(
                    this=join_cond,
                    expression=existing_where.this.copy(),
                )
            else:
                new_cond = join_cond

            new_select = inner_select.copy()
            new_select.set('expressions', [exp.Literal.number(1)])
            new_select.set('where', exp.Where(this=new_cond))

            changes.append('NOT IN → NOT EXISTS 변환 (NULL 안전성 향상)')
            return exp.Not(this=exp.Exists(this=new_select))

        return tree.transform(transform), changes

    def _union_to_union_all(self, tree) -> tuple:
        """UNION  →  UNION ALL"""
        changes: list[str] = []

        def transform(node):
            if isinstance(node, exp.Union) and node.args.get('distinct', False):
                new_node = node.copy()
                new_node.set('distinct', False)
                changes.append('UNION → UNION ALL 변환 (⚠ 결과에 중복이 없는 경우에만 적용)')
                return new_node
            return node

        return tree.transform(transform), changes
