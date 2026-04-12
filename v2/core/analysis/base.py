"""
SQL 분석기 공통 인터페이스 및 데이터 타입
모든 분석기 구현체(AstAnalyzer, RegexAnalyzer, CompositeAnalyzer)는
SqlAnalyzer를 상속하고 analyze() 를 구현합니다.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class SqlIssue:
    """SQL 안티패턴 감지 결과"""
    severity: str    # HIGH / MEDIUM / LOW / INFO
    category: str    # 문제 분류 (예: 'Full Table Scan', 'NOT IN NULL 위험')
    title: str       # 짧은 제목 (UI 목록에 표시)
    description: str # 상세 설명 (왜 문제인가)
    suggestion: str  # 개선 제안 (어떻게 고치는가)
    sample_sql: str = ''  # 개선 예시 SQL (선택)


class SqlAnalyzer(ABC):
    """SQL 안티패턴 감지기 인터페이스"""

    @abstractmethod
    def analyze(self, sql: str) -> list[SqlIssue]:
        """
        SQL 문자열을 분석하여 감지된 이슈 목록을 반환합니다.
        반환값은 severity 내림차순(HIGH → INFO) 으로 정렬되어야 합니다.
        """
        ...

    @property
    def engine_name(self) -> str:
        """분석 엔진 이름 (UI 표시용)"""
        return self.__class__.__name__

    @staticmethod
    def sort_issues(issues: list[SqlIssue]) -> list[SqlIssue]:
        """이슈를 severity 순서(HIGH→MEDIUM→LOW→INFO)로 정렬합니다."""
        _ORDER = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2, 'INFO': 3}
        return sorted(issues, key=lambda x: _ORDER.get(x.severity, 99))

    @staticmethod
    def deduplicate(issues: list[SqlIssue]) -> list[SqlIssue]:
        """동일한 (category, title) 쌍의 중복 이슈를 제거합니다."""
        seen: set[tuple[str, str]] = set()
        result: list[SqlIssue] = []
        for issue in issues:
            key = (issue.category, issue.title)
            if key not in seen:
                seen.add(key)
                result.append(issue)
        return result
