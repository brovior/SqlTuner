"""
SQL 재작성기 공통 인터페이스 및 데이터 타입
모든 재작성기 구현체(AstRewriter, RegexRewriter, CompositeRewriter)는
SqlRewriter를 상속하고 rewrite() 를 구현합니다.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RewriteResult:
    """SQL 재작성 결과"""
    original_sql: str
    rewritten_sql: str
    changes: list[str] = field(default_factory=list)
    engine_used: str = ''  # 실제로 사용된 엔진 이름 (AST / Regex)

    @property
    def has_changes(self) -> bool:
        """원본과 재작성된 SQL 이 다른지 여부"""
        return bool(self.changes)

    @property
    def change_summary(self) -> str:
        """변경 사항을 줄글로 반환 (UI 표시용)"""
        if not self.changes:
            return '변환할 패턴이 없습니다.'
        return '\n'.join(f'• {c}' for c in self.changes)


class SqlRewriter(ABC):
    """SQL 자동 재작성기 인터페이스"""

    @abstractmethod
    def rewrite(self, sql: str) -> RewriteResult:
        """
        SQL 문자열을 받아 안티패턴을 자동 변환한 결과를 반환합니다.
        변환이 없어도 RewriteResult(original_sql=sql, rewritten_sql=sql, changes=[])
        형태로 반환합니다.
        """
        ...

    @property
    def engine_name(self) -> str:
        """재작성 엔진 이름 (UI 표시용)"""
        return self.__class__.__name__
