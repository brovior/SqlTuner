"""
StatsAdvisor 단위 테스트

advise() 전체 흐름을 OracleClient mock 으로 검증합니다.
DB 연결 없이 순수 로직만 테스트합니다.
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock

from v2.core.analysis.stats_advisor import StatsAdvisor, TableStatsInfo, StatsAdvice


# ──────────────────────────────────────────────────────────────────────────────
# 공용 헬퍼
# ──────────────────────────────────────────────────────────────────────────────

def _make_advisor(
    tables: list[str],
    stats_map: dict[str, dict | None],
) -> StatsAdvisor:
    """
    OracleClient 를 mock 으로 대체한 StatsAdvisor 반환.

    tables    : get_tables_from_sql() 반환값
    stats_map : {table_name: get_table_stats() 반환 dict (또는 None)}
    """
    client = MagicMock()
    client.get_tables_from_sql.return_value = tables
    client.get_table_stats.side_effect = lambda t, **kw: stats_map.get(t.upper())
    return StatsAdvisor(client)


def _raw(
    table: str,
    last_analyzed: datetime | None,
    days: int | None,
    stale: bool,
    num_rows: int | None = 1000,
) -> dict:
    """get_table_stats() 반환 dict 생성 헬퍼."""
    return {
        "table_name": table,
        "num_rows": num_rows,
        "blocks": 10,
        "last_analyzed": last_analyzed,
        "days_since_analyzed": days,
        "stale_stats": stale,
    }


_NOW = datetime(2026, 4, 13)  # 테스트 기준일 (고정)


# ──────────────────────────────────────────────────────────────────────────────
# 1. 통계 미수집
# ──────────────────────────────────────────────────────────────────────────────

class TestNoStats:

    def test_severity_is_high(self):
        """last_analyzed=None → severity HIGH"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", None, None, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert len(advices) == 1
        assert advices[0].severity == "HIGH"

    def test_reason_contains_keyword(self):
        """reason 에 '미수집' 포함"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", None, None, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert "미수집" in advices[0].reason

    def test_suggested_sql_contains_table(self):
        """suggested_sql 에 테이블명 포함"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", None, None, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert "ORDERS" in advices[0].suggested_sql

    def test_suggested_sql_contains_dbms_stats(self):
        """suggested_sql 에 DBMS_STATS 포함"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", None, None, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert "DBMS_STATS" in advices[0].suggested_sql


# ──────────────────────────────────────────────────────────────────────────────
# 2. Oracle STALE_STATS 판정
# ──────────────────────────────────────────────────────────────────────────────

class TestStaleStats:

    def test_severity_is_high(self):
        """stale_stats=True → severity HIGH"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 4, 10), 3, True)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert advices[0].severity == "HIGH"

    def test_reason_contains_stale_keyword(self):
        """reason 에 'STALE_STATS' 포함"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 4, 10), 3, True)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert "STALE_STATS" in advices[0].reason

    def test_stale_beats_recent_days(self):
        """days=3 (7일 이하) 이어도 stale_stats=True 면 HIGH"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 4, 10), 3, True)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert advices[0].severity == "HIGH"


# ──────────────────────────────────────────────────────────────────────────────
# 3. 30일 초과 경과
# ──────────────────────────────────────────────────────────────────────────────

class TestOver30Days:

    def test_severity_is_high(self):
        """days=31 → severity HIGH"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 3, 1), 31, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert advices[0].severity == "HIGH"

    def test_reason_contains_days(self):
        """reason 에 경과일 숫자 포함"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 3, 1), 31, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert "31" in advices[0].reason

    def test_exactly_30_days_is_medium_not_high(self):
        """days=30 (30 초과 아님) → HIGH 아닌 MEDIUM 발행"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 3, 14), 30, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert len(advices) == 1
        assert advices[0].severity == "MEDIUM"

    def test_31_days_is_high_not_medium(self):
        """days=31 → HIGH (MEDIUM 이 아님)"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 3, 1), 31, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert advices[0].severity != "MEDIUM"


# ──────────────────────────────────────────────────────────────────────────────
# 4. 7일 초과 경과
# ──────────────────────────────────────────────────────────────────────────────

class TestOver7Days:

    def test_severity_is_medium(self):
        """days=8 → severity MEDIUM"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 4, 5), 8, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert advices[0].severity == "MEDIUM"

    def test_reason_contains_days(self):
        """reason 에 경과일 숫자 포함"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 4, 5), 8, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert "8" in advices[0].reason

    def test_exactly_7_days_no_advice(self):
        """days=7 (초과 아님) → advice 없음"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 4, 6), 7, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert advices == []


# ──────────────────────────────────────────────────────────────────────────────
# 5. 정상 케이스 (경고 없음)
# ──────────────────────────────────────────────────────────────────────────────

class TestNoAdvice:

    def test_fresh_stats_no_advice(self):
        """days=3, stale_stats=False → advice 없음"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 4, 10), 3, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert advices == []

    def test_stats_info_returned_even_without_advice(self):
        """경고 없어도 TableStatsInfo 는 반환"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 4, 10), 3, False)},
        )
        infos, advices = advisor.advise("SELECT * FROM orders")
        assert len(infos) == 1
        assert infos[0].table_name == "ORDERS"
        assert advices == []


# ──────────────────────────────────────────────────────────────────────────────
# 6. 복수 조건 중복 방지
# ──────────────────────────────────────────────────────────────────────────────

class TestDuplicatePrevention:

    def test_stale_and_over_30_days_one_advice_only(self):
        """stale_stats=True + days=35 → HIGH advice 1개만 발행"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 3, 1), 35, True)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert len(advices) == 1
        assert advices[0].severity == "HIGH"

    def test_no_stats_and_stale_one_advice_only(self):
        """last_analyzed=None + stale_stats=True → HIGH advice 1개만 (미수집 우선)"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", None, None, True)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert len(advices) == 1
        assert "미수집" in advices[0].reason

    def test_no_stats_has_highest_priority(self):
        """미수집 조건이 다른 모든 조건보다 우선"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", None, None, True)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        # stale_stats reason 이 아닌 미수집 reason 이어야 함
        assert "STALE_STATS" not in advices[0].reason


# ──────────────────────────────────────────────────────────────────────────────
# 7. 빈 SQL / 빈 테이블
# ──────────────────────────────────────────────────────────────────────────────

class TestEdgeCases:

    def test_empty_sql_returns_empty(self):
        """빈 문자열 → ([], [])"""
        advisor = _make_advisor(tables=[], stats_map={})
        infos, advices = advisor.advise("")
        assert infos == [] and advices == []

    def test_whitespace_sql_returns_empty(self):
        """공백만 있는 SQL → ([], [])"""
        advisor = _make_advisor(tables=[], stats_map={})
        infos, advices = advisor.advise("   \n\t  ")
        assert infos == [] and advices == []

    def test_no_tables_extracted_returns_empty(self):
        """테이블 추출 결과 없음 → ([], [])"""
        advisor = _make_advisor(tables=[], stats_map={})
        infos, advices = advisor.advise("SELECT 1 FROM DUAL")
        assert infos == [] and advices == []


# ──────────────────────────────────────────────────────────────────────────────
# 8. 테이블 조회 실패 (get_table_stats → None)
# ──────────────────────────────────────────────────────────────────────────────

class TestTableStatsFails:

    def test_none_result_excluded_from_infos(self):
        """get_table_stats가 None 반환 → stats_info_list 에 포함 안 됨"""
        advisor = _make_advisor(
            tables=["GHOST_TABLE"],
            stats_map={"GHOST_TABLE": None},
        )
        infos, advices = advisor.advise("SELECT * FROM ghost_table")
        assert infos == []
        assert advices == []

    def test_partial_none_only_valid_returned(self):
        """테이블 2개 중 1개만 None → 유효한 1개만 infos 에 포함"""
        advisor = _make_advisor(
            tables=["ORDERS", "GHOST"],
            stats_map={
                "ORDERS": _raw("ORDERS", datetime(2026, 4, 10), 3, False),
                "GHOST":  None,
            },
        )
        infos, advices = advisor.advise("SELECT * FROM orders JOIN ghost ON 1=1")
        assert len(infos) == 1
        assert infos[0].table_name == "ORDERS"


# ──────────────────────────────────────────────────────────────────────────────
# 9. 정렬 순서 검증
# ──────────────────────────────────────────────────────────────────────────────

class TestSortOrder:

    def test_high_before_medium(self):
        """복수 테이블: HIGH advice 가 MEDIUM 보다 앞에 위치"""
        advisor = _make_advisor(
            tables=["A", "B"],
            stats_map={
                "A": _raw("A", datetime(2026, 4, 5), 8,  False),   # MEDIUM
                "B": _raw("B", datetime(2026, 3, 1), 35, False),   # HIGH
            },
        )
        _, advices = advisor.advise("SELECT * FROM a JOIN b ON 1=1")
        assert len(advices) == 2
        assert advices[0].severity == "HIGH"
        assert advices[1].severity == "MEDIUM"

    def test_all_high_all_returned(self):
        """모두 HIGH 인 경우 전부 반환"""
        advisor = _make_advisor(
            tables=["A", "B"],
            stats_map={
                "A": _raw("A", None,                None, False),   # HIGH: 미수집
                "B": _raw("B", datetime(2026, 3, 1), 35, False),    # HIGH: 30일 초과
            },
        )
        _, advices = advisor.advise("SELECT * FROM a JOIN b ON 1=1")
        assert len(advices) == 2
        assert all(a.severity == "HIGH" for a in advices)


# ──────────────────────────────────────────────────────────────────────────────
# 10. TableStatsInfo 필드 완전성
# ──────────────────────────────────────────────────────────────────────────────

class TestTableStatsInfoFields:

    def test_all_fields_populated(self):
        """TableStatsInfo 5개 필드 모두 올바르게 채워짐"""
        la = datetime(2026, 4, 10)
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", la, 3, False, num_rows=5000)},
        )
        infos, _ = advisor.advise("SELECT * FROM orders")
        info = infos[0]

        assert info.table_name == "ORDERS"
        assert info.num_rows == 5000
        assert info.last_analyzed == la
        assert info.days_since_analyzed == 3
        assert info.stale_stats is False

    def test_none_fields_preserved(self):
        """통계 미수집 시 num_rows=None, days=None 그대로 유지"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", None, None, False, num_rows=None)},
        )
        infos, _ = advisor.advise("SELECT * FROM orders")
        info = infos[0]

        assert info.last_analyzed is None
        assert info.days_since_analyzed is None
        assert info.num_rows is None


# ──────────────────────────────────────────────────────────────────────────────
# 11. suggested_sql 스크립트 형식 검증 (STEP 6-3)
# ──────────────────────────────────────────────────────────────────────────────

class TestSuggestedSqlFormat:

    def test_suggested_sql_uses_user_keyword(self):
        """suggested_sql 에 OWNNAME => USER (따옴표 없음) 포함"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", None, None, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        sql = advices[0].suggested_sql
        # USER 는 Oracle 키워드 — 따옴표 없이 포함되어야 함
        assert 'USER' in sql
        # 'SYSTEM' 고정값이 들어가면 안 됨
        assert "'SYSTEM'" not in sql

    def test_suggested_sql_uses_dbms_stats(self):
        """suggested_sql 에 DBMS_STATS.GATHER_TABLE_STATS 포함"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", None, None, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert "DBMS_STATS.GATHER_TABLE_STATS" in advices[0].suggested_sql

    def test_suggested_sql_cascade_true(self):
        """suggested_sql 에 CASCADE => TRUE 포함 (인덱스 통계 함께 수집)"""
        advisor = _make_advisor(
            tables=["ORDERS"],
            stats_map={"ORDERS": _raw("ORDERS", datetime(2026, 3, 1), 35, False)},
        )
        _, advices = advisor.advise("SELECT * FROM orders")
        assert "CASCADE" in advices[0].suggested_sql
        assert "TRUE" in advices[0].suggested_sql

    def test_suggested_sql_contains_exact_table_name(self):
        """suggested_sql 테이블명이 대문자로 정확히 포함"""
        advisor = _make_advisor(
            tables=["MY_ORDERS"],
            stats_map={"MY_ORDERS": _raw("MY_ORDERS", None, None, False)},
        )
        _, advices = advisor.advise("SELECT * FROM my_orders")
        assert "MY_ORDERS" in advices[0].suggested_sql
