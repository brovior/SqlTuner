"""
HintAdvisor — 실행 계획 기반 Oracle 옵티마이저 힌트 자동 추천

plan_rows 와 index_infos 를 분석하여 다섯 가지 규칙으로 힌트를 생성합니다.

규칙:
  1. LEADING    : 조인 테이블 중 E-Rows 가장 작은 테이블을 드라이빙으로 제안
  2. USE_NL/USE_HASH : 드리븐 E-Rows < 1000 → NL, >= 10000 → HASH
  3. INDEX      : TABLE ACCESS FULL 인 테이블에 인덱스가 존재하면 INDEX 힌트 제안
  4. PUSH_PRED  : VIEW 오퍼레이션 바깥에 FILTER 조건 존재 → 외부 조건을 뷰 안으로 pushdown
  5. NO_MERGE   : VIEW Cost 가 전체 Cost 의 70% 이상 → 뷰 머지 방지, 내부 필터 우선 적용

sql 인수를 전달하면 full_hint 가 "원본 SQL에 힌트 삽입한 전체 SQL" 로 생성됩니다.
DB 연결이나 SQL 파싱이 필요 없는 순수 로직 클래스입니다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


# ──────────────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class HintSuggestion:
    """힌트 추천 하나"""
    hint: str        # 힌트 본문  예: "LEADING(DEPT EMP)"
    reason: str      # 추천 이유  예: "E-Rows 기준 드라이빙 순서 제안"
    full_hint: str   # 완전한 힌트 주석  예: "/*+ LEADING(DEPT EMP) */"


# ──────────────────────────────────────────────────────────────────────────────
# 메인 클래스
# ──────────────────────────────────────────────────────────────────────────────

# USE_NL / USE_HASH 경계값
_NL_THRESHOLD   = 1_000    # E-Rows < 이 값 → Nested Loop 적합
_HASH_THRESHOLD = 10_000   # E-Rows >= 이 값 → Hash Join 적합

# JOIN 연산 집합
_JOIN_OPS = frozenset({'NESTED LOOPS', 'HASH JOIN', 'MERGE JOIN'})

# NO_MERGE 임계값: VIEW Cost / 전체 Cost 가 이 비율 이상이면 추천
_NO_MERGE_RATIO = 0.70


class HintAdvisor:
    """
    실행 계획(plan_rows)과 인덱스 정보(index_infos)를 분석하여
    적용 가능한 Oracle 옵티마이저 힌트 목록을 반환합니다.
    """

    def advise(
        self,
        plan_rows,
        index_infos=None,
        sql: str = '',
    ) -> list[HintSuggestion]:
        """
        Parameters
        ----------
        plan_rows   : PlanRow 목록 (operation, options, object_name, cost, cardinality, parent_id 필드 필요)
        index_infos : IndexInfo 목록 (table_name, index_name 필드 필요), 없으면 []
        sql         : 원본 SQL (전달 시 full_hint 가 힌트 삽입 SQL 전체로 생성됨)

        Returns
        -------
        HintSuggestion 목록 (LEADING → USE_NL/HASH → INDEX → PUSH_PRED → NO_MERGE 순)
        """
        if not plan_rows:
            return []

        index_infos = index_infos or []
        suggestions: list[HintSuggestion] = []

        # TABLE ACCESS 행만 추려서 재사용
        table_rows = [
            r for r in plan_rows
            if getattr(r, 'operation', '') == 'TABLE ACCESS'
            and getattr(r, 'object_name', '')
        ]

        # ── 규칙 1: LEADING ──────────────────────────────────────────────
        leading = self._suggest_leading(table_rows)
        if leading:
            suggestions.append(leading)

        # ── 규칙 2: USE_NL / USE_HASH ────────────────────────────────────
        suggestions.extend(self._suggest_join_method(plan_rows, table_rows))

        # ── 규칙 3: INDEX ────────────────────────────────────────────────
        suggestions.extend(self._suggest_index(table_rows, index_infos))

        # ── 규칙 4·5: PUSH_PRED / NO_MERGE (인라인 뷰) ──────────────────
        suggestions.extend(self._suggest_inline_view(plan_rows, sql))

        return suggestions

    # ──────────────────────────────────────────────────────────────────────
    # 규칙 1: LEADING
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _suggest_leading(table_rows) -> HintSuggestion | None:
        """
        E-Rows 가 있는 TABLE ACCESS 행이 2개 이상일 때
        가장 작은 E-Rows 순서로 LEADING 힌트를 생성합니다.
        """
        with_card = [
            r for r in table_rows
            if getattr(r, 'cardinality', None) is not None
        ]
        if len(with_card) < 2:
            return None

        sorted_rows = sorted(with_card, key=lambda r: r.cardinality)
        tables = [r.object_name.upper() for r in sorted_rows]
        order_str = ' → '.join(tables)
        hint = f'LEADING({" ".join(tables)})'
        return HintSuggestion(
            hint=hint,
            reason=f'E-Rows 기준 드라이빙 순서 제안: {order_str}',
            full_hint=f'/*+ {hint} */',
        )

    # ──────────────────────────────────────────────────────────────────────
    # 규칙 2: USE_NL / USE_HASH
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _suggest_join_method(plan_rows, table_rows) -> list[HintSuggestion]:
        """
        JOIN 연산(NESTED LOOPS, HASH JOIN, MERGE JOIN)의 직접 자식인
        TABLE ACCESS 행에 대해 E-Rows 기준으로 NL / HASH 힌트를 생성합니다.

          E-Rows < 1_000  → USE_NL  (소규모 → 인덱스 NL 적합)
          E-Rows >= 10_000 → USE_HASH (대규모 → Hash 적합)
          그 사이         → 힌트 없음 (옵티마이저 자율)
        """
        id_map = {getattr(r, 'id', None): r for r in plan_rows}
        suggestions: list[HintSuggestion] = []

        for row in table_rows:
            card = getattr(row, 'cardinality', None)
            if card is None:
                continue

            parent = id_map.get(getattr(row, 'parent_id', None))
            if parent is None or getattr(parent, 'operation', '') not in _JOIN_OPS:
                continue

            table = row.object_name.upper()
            if card < _NL_THRESHOLD:
                hint = f'USE_NL({table})'
                suggestions.append(HintSuggestion(
                    hint=hint,
                    reason=f'{table} E-Rows={card:,} (소규모 — Nested Loop 적합)',
                    full_hint=f'/*+ {hint} */',
                ))
            elif card >= _HASH_THRESHOLD:
                hint = f'USE_HASH({table})'
                suggestions.append(HintSuggestion(
                    hint=hint,
                    reason=f'{table} E-Rows={card:,} (대규모 — Hash Join 적합)',
                    full_hint=f'/*+ {hint} */',
                ))

        return suggestions

    # ──────────────────────────────────────────────────────────────────────
    # 공통 헬퍼
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _build_full_hint(sql: str, hint: str) -> str:
        """
        sql 이 있으면 첫 번째 SELECT 뒤에 힌트를 삽입한 전체 SQL 을 반환합니다.
        sql 이 없으면 /*+ hint */ 형식만 반환합니다.
        """
        if sql and sql.strip():
            return re.sub(
                r'\bSELECT\b',
                f'SELECT /*+ {hint} */',
                sql,
                count=1,
                flags=re.IGNORECASE,
            )
        return f'/*+ {hint} */'

    # ──────────────────────────────────────────────────────────────────────
    # 규칙 3: INDEX
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _suggest_index(table_rows, index_infos) -> list[HintSuggestion]:
        """
        TABLE ACCESS FULL 이 발생한 테이블에 인덱스가 있으면
        INDEX(table_name index_name) 힌트를 생성합니다.
        """
        # 테이블명 → 인덱스 목록 매핑
        idx_map: dict[str, list] = {}
        for info in index_infos:
            tbl = getattr(info, 'table_name', '').upper()
            if tbl:
                idx_map.setdefault(tbl, []).append(info)

        suggestions: list[HintSuggestion] = []
        seen: set[str] = set()

        for row in table_rows:
            if getattr(row, 'options', '') != 'FULL':
                continue

            table = (getattr(row, 'object_name', '') or '').upper()
            if not table or table in seen:
                continue

            idxs = idx_map.get(table, [])
            if not idxs:
                continue

            seen.add(table)
            best = idxs[0]  # 첫 번째 인덱스를 우선 추천
            idx_name = getattr(best, 'index_name', '').upper()
            hint = f'INDEX({table} {idx_name})'
            suggestions.append(HintSuggestion(
                hint=hint,
                reason=(
                    f'{table} Full Table Scan 감지 — '
                    f'인덱스 {idx_name} 활용으로 Range Scan 유도 가능'
                ),
                full_hint=f'/*+ {hint} */',
            ))

        return suggestions

    # ──────────────────────────────────────────────────────────────────────
    # 규칙 4·5: PUSH_PRED / NO_MERGE (인라인 뷰)
    # ──────────────────────────────────────────────────────────────────────

    def _suggest_inline_view(self, plan_rows, sql: str) -> list[HintSuggestion]:
        """
        VIEW 오퍼레이션이 존재할 때 두 가지 힌트를 검토합니다.

        규칙 4 — PUSH_PRED:
          VIEW 행의 조상(ancestor) 중 FILTER 오퍼레이션이 있으면
          외부 조건이 뷰 안으로 pushdown 되지 않은 것이므로 PUSH_PRED 추천.

        규칙 5 — NO_MERGE:
          VIEW Cost / 전체 Cost(루트 행 기준) ≥ 70% 이면
          뷰 머지(view merging)로 옵티마이저가 잘못된 플랜을 선택할 수 있으므로
          NO_MERGE 추천.

        full_hint: sql 인수가 있으면 힌트 삽입 SQL 전체, 없으면 /*+ ... */ 만.
        """
        view_rows = [r for r in plan_rows if getattr(r, 'operation', '') == 'VIEW']
        if not view_rows:
            return []

        suggestions: list[HintSuggestion] = []
        id_map = {getattr(r, 'id', None): r for r in plan_rows}

        # 전체 비용: parent_id=None 인 루트 행 기준 (없으면 max cost)
        root = next(
            (r for r in plan_rows if getattr(r, 'parent_id', -1) is None),
            None,
        )
        total_cost = getattr(root, 'cost', None) or 0
        if not total_cost:
            total_cost = max(
                (getattr(r, 'cost', None) or 0 for r in plan_rows), default=0
            )

        for view_row in view_rows:
            alias = (getattr(view_row, 'object_name', '') or 'V').upper()
            view_cost = getattr(view_row, 'cost', None) or 0

            # ── 규칙 4: PUSH_PRED ─────────────────────────────────────────
            if self._has_filter_ancestor(view_row, id_map):
                hint = f'PUSH_PRED({alias})'
                suggestions.append(HintSuggestion(
                    hint=hint,
                    reason=(
                        f'VIEW({alias}) 바깥에 FILTER 조건 감지 — '
                        '외부 조건을 뷰 안으로 pushdown'
                    ),
                    full_hint=self._build_full_hint(sql, hint),
                ))

            # ── 규칙 5: NO_MERGE ──────────────────────────────────────────
            if total_cost > 0 and (view_cost / total_cost) >= _NO_MERGE_RATIO:
                ratio_pct = int(view_cost / total_cost * 100)
                hint = f'NO_MERGE({alias})'
                suggestions.append(HintSuggestion(
                    hint=hint,
                    reason=(
                        f'VIEW({alias}) Cost={view_cost:,} '
                        f'(전체 Cost의 {ratio_pct}%) — '
                        '뷰 머지 방지, 내부 필터 우선 적용'
                    ),
                    full_hint=self._build_full_hint(sql, hint),
                ))

        return suggestions

    @staticmethod
    def _has_filter_ancestor(row, id_map: dict) -> bool:
        """row 의 조상(ancestor) 중 FILTER 오퍼레이션이 있는지 확인합니다."""
        current = id_map.get(getattr(row, 'parent_id', None))
        while current is not None:
            if getattr(current, 'operation', '') == 'FILTER':
                return True
            current = id_map.get(getattr(current, 'parent_id', None))
        return False
