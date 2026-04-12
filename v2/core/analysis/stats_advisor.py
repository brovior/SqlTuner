"""
StatsAdvisor – 테이블 통계 상태 분석기

흐름:
  1. OracleClient.get_tables_from_sql()  → SQL에서 테이블명 추출
  2. OracleClient.get_table_stats()      → 테이블별 통계 메타데이터 조회
  3. _evaluate()                         → 경고 기준 평가 → StatsAdvice 생성
  4. _generate_sql()                     → DBMS_STATS 수집 스크립트 자동 생성

경고 우선순위 (같은 테이블에 복수 조건 충족 시 가장 높은 심각도만 발행):
  HIGH   – 통계 미수집 / 30일 이상 경과 / Oracle STALE_STATS 판정
  MEDIUM – 7일 초과 30일 이하 경과

외부 의존: OracleClient (DB 조회)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from v2.core.db.oracle_client import OracleClient


# ──────────────────────────────────────────────────────────────────────────────
# 데이터 클래스
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TableStatsInfo:
    """테이블 통계 현황 스냅샷."""
    table_name: str
    num_rows: int | None
    last_analyzed: datetime | None
    days_since_analyzed: int | None
    stale_stats: bool


@dataclass
class StatsAdvice:
    """통계 문제에 대한 개선 제안 하나."""
    severity: str        # "HIGH" | "MEDIUM"
    table_name: str
    reason: str          # 사람이 읽을 수 있는 이유 설명
    suggested_sql: str   # DBMS_STATS 수집 스크립트


# ──────────────────────────────────────────────────────────────────────────────
# 심각도 순서 (정렬용)
# ──────────────────────────────────────────────────────────────────────────────

_SEV_ORDER: dict[str, int] = {"HIGH": 0, "MEDIUM": 1}


# ──────────────────────────────────────────────────────────────────────────────
# 메인 클래스
# ──────────────────────────────────────────────────────────────────────────────

class StatsAdvisor:
    """
    SQL 텍스트와 DB 통계 메타데이터를 결합하여
    통계 문제를 감지하고 DBMS_STATS 수집 스크립트를 제안합니다.
    """

    def __init__(self, client: "OracleClient") -> None:
        self._client = client

    # ──────────────────────────────────────────────────────────────────────
    # Public API
    # ──────────────────────────────────────────────────────────────────────

    def advise(self, sql: str) -> tuple[list[TableStatsInfo], list[StatsAdvice]]:
        """
        SQL을 분석하여 테이블 통계 현황과 개선 제안을 반환합니다.

        Parameters
        ----------
        sql : str
            분석할 SQL 텍스트

        Returns
        -------
        (stats_info_list, advice_list)
            stats_info_list : SQL에 등장하는 모든 테이블의 통계 현황
            advice_list     : 통계 이상 감지 시 개선 제안 (심각도 높은 순)
        """
        if not sql or not sql.strip():
            return [], []

        # 1. SQL에서 테이블 추출
        tables: list[str] = self._client.get_tables_from_sql(sql)
        if not tables:
            return [], []

        stats_info_list: list[TableStatsInfo] = []
        advice_list: list[StatsAdvice] = []

        for table in tables:
            # 2. 테이블 통계 조회
            raw = self._client.get_table_stats(table)
            if raw is None:
                # 테이블이 DB에 없거나 조회 실패 → 스킵
                continue

            info = TableStatsInfo(
                table_name=raw["table_name"],
                num_rows=raw["num_rows"],
                last_analyzed=raw["last_analyzed"],
                days_since_analyzed=raw["days_since_analyzed"],
                stale_stats=raw["stale_stats"],
            )
            stats_info_list.append(info)

            # 3. 경고 기준 평가 → 제안 생성
            advice = self._evaluate(info)
            if advice:
                advice_list.append(advice)

        # 심각도 순 정렬 (HIGH → MEDIUM)
        advice_list.sort(key=lambda a: _SEV_ORDER.get(a.severity, 9))

        return stats_info_list, advice_list

    # ──────────────────────────────────────────────────────────────────────
    # 내부: 경고 기준 평가
    # ──────────────────────────────────────────────────────────────────────

    def _evaluate(self, info: TableStatsInfo) -> StatsAdvice | None:
        """
        TableStatsInfo 하나를 받아 경고 기준을 평가합니다.

        복수 조건이 동시에 충족될 경우 가장 높은 심각도(HIGH) 하나만 발행합니다.
        조건 우선순위:
          1. last_analyzed IS NULL           → HIGH "통계 미수집"
          2. stale_stats = True              → HIGH "통계 오래됨 (Oracle 판정)"
          3. days_since_analyzed > 30        → HIGH "통계 30일 이상 경과"
          4. days_since_analyzed > 7         → MEDIUM "통계 7일 이상 경과"
        """
        table = info.table_name

        # 조건 1: 통계 미수집
        if info.last_analyzed is None:
            return StatsAdvice(
                severity="HIGH",
                table_name=table,
                reason=f"[{table}] 통계 미수집: 통계가 한 번도 수집되지 않았습니다. 옵티마이저가 기본값(부정확한 통계)으로 실행 계획을 수립합니다.",
                suggested_sql=self._generate_sql(table),
            )

        # 조건 2: Oracle STALE_STATS 판정
        if info.stale_stats:
            return StatsAdvice(
                severity="HIGH",
                table_name=table,
                reason=f"[{table}] Oracle이 통계를 오래된 것으로 판정했습니다 (STALE_STATS=YES). 데이터 변경량이 10% 임계값을 초과한 상태입니다.",
                suggested_sql=self._generate_sql(table),
            )

        days = info.days_since_analyzed

        # 조건 3: 30일 이상 경과
        if days is not None and days > 30:
            return StatsAdvice(
                severity="HIGH",
                table_name=table,
                reason=f"[{table}] 마지막 통계 수집 후 {days}일이 경과했습니다 (기준: 30일). 실행 계획이 현재 데이터 분포를 반영하지 못할 수 있습니다.",
                suggested_sql=self._generate_sql(table),
            )

        # 조건 4: 7일 초과 경과
        if days is not None and days > 7:
            return StatsAdvice(
                severity="MEDIUM",
                table_name=table,
                reason=f"[{table}] 마지막 통계 수집 후 {days}일이 경과했습니다 (기준: 7일). 데이터 변경이 많은 테이블이라면 통계 재수집을 권장합니다.",
                suggested_sql=self._generate_sql(table),
            )

        return None

    # ──────────────────────────────────────────────────────────────────────
    # 내부: DBMS_STATS 스크립트 생성
    # ──────────────────────────────────────────────────────────────────────

    @staticmethod
    def _generate_sql(table: str) -> str:
        """
        DBMS_STATS.GATHER_TABLE_STATS 호출 스크립트를 생성합니다.

        OWNNAME => USER 로 현재 세션 스키마를 자동 사용합니다.
        CASCADE => TRUE 로 인덱스 통계도 함께 수집합니다.
        """
        return (
            f"EXEC DBMS_STATS.GATHER_TABLE_STATS(\n"
            f"    OWNNAME => USER,\n"
            f"    TABNAME => '{table}',\n"
            f"    CASCADE => TRUE\n"
            f");"
        )
