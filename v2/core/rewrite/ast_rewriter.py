"""
sqlglot AST 기반 SQL 자동 재작성기
SqlRewriter 인터페이스를 구현합니다.

RegexRewriter 대비 장점:
  - 주석/문자열 내부 패턴을 건드리지 않음
  - 출력 SQL 이 pretty-print 로 자동 정형화됨
  - 중첩 구조도 정확하게 처리

변환 규칙:
  1. OR col=A OR col=B  →  col IN (A, B)
  2. col NOT IN (SELECT ...)  →  NOT EXISTS (SELECT 1 ...)
  3. UNION  →  UNION ALL
  4. SELECT 절 스칼라 서브쿼리  →  LEFT JOIN (단순 형태만, 복잡하면 경고)

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

        tree, c = self._scalar_subquery_to_left_join(tree)
        all_changes.extend(c)

        tree, c = self._in_subquery_to_join(tree)
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

    # ── 스칼라 서브쿼리 → LEFT JOIN ───────────────

    def _scalar_subquery_to_left_join(self, tree) -> tuple:
        """
        SELECT 절 내 스칼라 서브쿼리를 LEFT JOIN 으로 변환합니다.

        단순 서브쿼리 조건 (모두 충족해야 변환):
          - 최상위 SELECT 에 있는 스칼라 서브쿼리
          - 서브쿼리: SELECT 단일 컬럼, FROM 단일 테이블, WHERE 단일 EQ 조인 조건
          - 집계함수 · DISTINCT · GROUP BY · HAVING · ORDER BY · LIMIT 없음
          - EQ 조건 양쪽 컬럼에 테이블 한정자가 있어 inner/outer 를 구분할 수 있음

        복잡한 서브쿼리는 변환하지 않고 경고 change 만 추가합니다.
        """
        changes: list[str] = []

        # 최상위 SELECT 에서만 동작
        if not isinstance(tree, exp.Select):
            return tree, changes

        new_exprs = [e.copy() for e in tree.expressions]
        new_joins: list = []
        any_converted = False
        warn_added = False

        for idx, expr in enumerate(new_exprs):
            alias_str: str | None = None
            subq: exp.Subquery | None = None

            if isinstance(expr, exp.Alias) and isinstance(expr.this, exp.Subquery):
                alias_str = expr.alias
                subq = expr.this
            elif isinstance(expr, exp.Subquery):
                subq = expr

            if subq is None:
                continue

            info = self._analyze_scalar_subquery(subq.this)

            if info is None:
                # 복잡한 서브쿼리 → 경고만 (중복 방지: 첫 번째만)
                if not warn_added:
                    changes.append(
                        '스칼라 서브쿼리 경고: '
                        '복잡한 서브쿼리는 자동 변환 불가 — LEFT JOIN 으로 직접 변경 검토 필요'
                    )
                    warn_added = True
                continue

            join_table, join_cond, selected_col = info
            display = join_table.alias or join_table.name or '?'

            # SELECT 절 표현식 교체: 서브쿼리 → 내부 컬럼 (+ 외부 alias 유지)
            inner_col = (
                selected_col.this
                if isinstance(selected_col, exp.Alias)
                else selected_col
            )
            new_exprs[idx] = (
                exp.alias_(inner_col.copy(), alias_str)
                if alias_str
                else inner_col.copy()
            )

            new_joins.append(
                exp.Join(this=join_table.copy(), on=join_cond.copy(), side='LEFT')
            )
            changes.append(f'스칼라 서브쿼리 → LEFT JOIN 변환: {display}')
            any_converted = True

        if not any_converted and not warn_added:
            return tree, []

        if any_converted:
            new_tree = tree.copy()
            new_tree.set('expressions', new_exprs)
            existing = list(new_tree.args.get('joins') or [])
            new_tree.set('joins', existing + new_joins)
            return new_tree, changes

        return tree, changes

    @staticmethod
    def _analyze_scalar_subquery(inner_sel) -> tuple | None:
        """
        스칼라 서브쿼리 분석 — LEFT JOIN 변환 가능 여부 판단.

        반환값: (join_table: exp.Table, join_cond: exp.EQ, selected_col: exp.Expression)
                 변환 불가 시 None
        """
        if not isinstance(inner_sel, exp.Select):
            return None

        # ① 단일 SELECT 표현식 (집계 없음, * 없음)
        exprs = inner_sel.expressions
        if len(exprs) != 1:
            return None
        selected = exprs[0]
        if isinstance(selected, exp.Star):
            return None
        if selected.find(exp.AggFunc):
            return None

        # ② 복잡도 차단 (DISTINCT / GROUP BY / HAVING / ORDER BY / LIMIT)
        for key in ('distinct', 'group', 'having', 'order', 'limit'):
            if inner_sel.args.get(key):
                return None

        # ③ 단일 FROM 테이블 (서브조인 없음)
        from_node = inner_sel.find(exp.From)
        if not from_node:
            return None
        if inner_sel.args.get('joins'):
            return None

        join_table = from_node.this
        if not isinstance(join_table, exp.Table):
            return None

        # inner 테이블 한정자 (alias 우선)
        inner_q = (join_table.alias or join_table.name or '').upper()
        if not inner_q:
            return None

        # ④ WHERE 절: 단일 EQ, 양쪽 모두 Column
        where = inner_sel.find(exp.Where)
        if not where:
            return None
        eq = where.this
        if not isinstance(eq, exp.EQ):
            return None
        left, right = eq.left, eq.right
        if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
            return None

        # ⑤ inner/outer 컬럼 구분 (table 한정자 필수)
        left_q = (left.table or '').upper()
        right_q = (right.table or '').upper()
        left_inner = (left_q == inner_q)
        right_inner = (right_q == inner_q)

        # 양쪽이 같거나 모두 한정자 없으면 판단 불가
        if left_inner == right_inner:
            return None

        return join_table, eq, selected

    # ── IN 서브쿼리 → JOIN ────────────────────────

    def _in_subquery_to_join(self, tree) -> tuple:
        """
        WHERE col IN (SELECT col FROM tbl [WHERE cond])  →  JOIN tbl ON outer_col = inner_col

        단순 서브쿼리 조건 (모두 충족해야 변환):
          - SELECT 단일 컬럼, FROM 단일 테이블
          - GROUP BY / HAVING / DISTINCT 없음
          - NOT IN 은 대상 아님 (_not_in_to_not_exists 에서 처리)

        복잡한 경우 → 변환 없이 경고 change 추가.
        SELECT * 는 outer_table.* 로 자동 한정.
        """
        changes: list[str] = []

        if not isinstance(tree, exp.Select):
            return tree, changes

        where = tree.find(exp.Where)
        if not where:
            return tree, changes

        # NOT IN 제외: In 노드의 부모가 Not 이면 스킵
        in_node: exp.In | None = None
        for node in where.walk():
            if (isinstance(node, exp.In)
                    and node.args.get('query') is not None
                    and not isinstance(node.parent, exp.Not)):
                in_node = node
                break

        if in_node is None:
            return tree, changes

        inner_sel = in_node.args['query'].this
        info = self._analyze_in_subquery(inner_sel)

        if info is None:
            changes.append(
                '[IN 서브쿼리 감지] MEDIUM | SUBQUERY_TO_JOIN — '
                'JOIN 변환 검토 권장 (복잡한 서브쿼리로 자동 변환 불가)'
            )
            return tree, changes

        join_table, inner_col, inner_where_cond = info
        outer_col = in_node.this  # WHERE 좌변 컬럼 (e.g. A.ID)

        # ── JOIN ON 조건: outer_col = inner_col ──────────────────
        # inner_col 에 table 한정자가 없으면 join_table 의 alias/name 으로 보완
        inner_col_expr = inner_col.copy()
        if isinstance(inner_col_expr, exp.Column) and not inner_col_expr.table:
            qualifier = join_table.alias or join_table.name
            if qualifier:
                inner_col_expr.set('table', exp.Identifier(this=qualifier))
        join_cond = exp.EQ(this=outer_col.copy(), expression=inner_col_expr)

        # ── 외부 WHERE 재구성: IN 조건 제거 + 내부 WHERE 병합 ────
        remaining = [
            c.copy() for c in self._flatten_and(where.this)
            if c is not in_node
        ]
        if inner_where_cond is not None:
            remaining.append(inner_where_cond.copy())

        # ── SELECT * → outer_table.* ────────────────────────────
        new_exprs = [e.copy() for e in tree.expressions]
        if (len(new_exprs) == 1 and isinstance(new_exprs[0], exp.Star)):
            outer_from = tree.find(exp.From)
            if outer_from and isinstance(outer_from.this, exp.Table):
                outer_tbl = outer_from.this
                qual = outer_tbl.alias or outer_tbl.name
                if qual:
                    new_exprs = [
                        exp.Column(
                            this=exp.Star(),
                            table=exp.Identifier(this=qual),
                        )
                    ]

        # ── 새 트리 조립 ─────────────────────────────────────────
        new_tree = tree.copy()
        new_tree.set('expressions', new_exprs)

        existing_joins = list(new_tree.args.get('joins') or [])
        new_tree.set('joins', existing_joins + [
            exp.Join(this=join_table.copy(), on=join_cond)
        ])

        if remaining:
            new_where = remaining[0]
            for cond in remaining[1:]:
                new_where = exp.And(this=new_where, expression=cond)
            new_tree.set('where', exp.Where(this=new_where))
        else:
            new_tree.set('where', None)

        display = join_table.alias or join_table.name or '?'
        changes.append(f'IN 서브쿼리 → JOIN 변환: {display}')
        return new_tree, changes

    @staticmethod
    def _analyze_in_subquery(inner_sel) -> tuple | None:
        """
        IN 서브쿼리 분석 — JOIN 변환 가능 여부 판단.

        반환값: (join_table: exp.Table, inner_col: exp.Column, inner_where_cond: exp.Expression | None)
                 변환 불가 시 None
        """
        if not isinstance(inner_sel, exp.Select):
            return None

        # ① 단일 SELECT 컬럼 (집계 없음, * 없음)
        if len(inner_sel.expressions) != 1:
            return None
        selected = inner_sel.expressions[0]
        if isinstance(selected, exp.Star):
            return None
        if selected.find(exp.AggFunc):
            return None

        # ② GROUP BY / HAVING / DISTINCT 차단
        for key in ('distinct', 'group', 'having'):
            if inner_sel.args.get(key):
                return None

        # ③ 단일 FROM 테이블 (서브조인 없음)
        from_node = inner_sel.find(exp.From)
        if not from_node:
            return None
        if inner_sel.args.get('joins'):
            return None
        join_table = from_node.this
        if not isinstance(join_table, exp.Table):
            return None

        # ④ 내부 WHERE (있으면 추출, 없어도 허용)
        inner_where = inner_sel.find(exp.Where)
        inner_cond = inner_where.this if inner_where else None

        # inner SELECT 의 컬럼 표현식 (단순 Column 또는 Alias 해제)
        inner_col = selected.this if isinstance(selected, exp.Alias) else selected

        return join_table, inner_col, inner_cond

    @staticmethod
    def _flatten_and(cond) -> list:
        """AND 트리를 평탄화하여 조건 리스트를 반환한다."""
        if isinstance(cond, exp.And):
            return AstRewriter._flatten_and(cond.left) + AstRewriter._flatten_and(cond.right)
        return [cond]
