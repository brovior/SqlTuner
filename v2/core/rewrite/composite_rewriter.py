"""
복합 SQL 재작성기 — AST → Regex 자동 폴백
사용 흐름:
  1. AstRewriter.rewrite() 시도
  2. sqlglot 파싱 실패(ValueError/Exception) 시 RegexRewriter 로 폴백
  3. 사용된 엔진 이름을 RewriteResult.engine_used 에 기록
"""
from __future__ import annotations
from .base import SqlRewriter, RewriteResult
from .ast_rewriter import AstRewriter
from .regex_rewriter import RegexRewriter


class CompositeRewriter(SqlRewriter):
    """
    AST 엔진 우선, 파싱 실패 시 Regex 엔진으로 자동 폴백합니다.
    force_regex=True 로 생성하면 항상 Regex 엔진만 사용합니다.
    """

    def __init__(self, force_regex: bool = False):
        self._ast = AstRewriter()
        self._regex = RegexRewriter()
        self._force_regex = force_regex

    @property
    def engine_name(self) -> str:
        if self._force_regex:
            return self._regex.engine_name
        return f'Composite (AST → Regex 폴백)'

    def rewrite(self, sql: str) -> RewriteResult:
        if not self._force_regex:
            try:
                result = self._ast.rewrite(sql)
                return result
            except Exception:
                result = self._regex.rewrite(sql)
                result.engine_used = self._regex.engine_name + ' (폴백)'
                return result

        return self._regex.rewrite(sql)
