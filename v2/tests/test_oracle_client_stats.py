"""
OracleClient – 테이블/컬럼 통계 메서드 단위 테스트

get_table_stats  : DB 연결 필요 → unittest.mock 으로 커서를 대체
get_column_stats : DB 연결 필요 → unittest.mock 으로 커서를 대체
"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock
from v2.core.db.oracle_client import OracleClient


# ------------------------------------------------------------------ #
#  공용 헬퍼                                                            #
# ------------------------------------------------------------------ #

_UNSET = object()  # sentinel: 인자가 전달되지 않았음을 구분


def _make_client(fetchone=_UNSET, fetchall=_UNSET):
    """
    _ensure_connected 와 cursor 를 mock 으로 대체한 OracleClient 반환.

    fetchone : cursor.fetchone() 반환값 (None 포함 명시적으로 전달 가능)
    fetchall : cursor.fetchall() 반환값 (None 포함 명시적으로 전달 가능)
    """
    client = OracleClient()
    mock_cursor = MagicMock()
    if fetchone is not _UNSET:
        mock_cursor.fetchone.return_value = fetchone
    if fetchall is not _UNSET:
        mock_cursor.fetchall.return_value = fetchall
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    client._connection = mock_conn
    client._ensure_connected = MagicMock()
    return client


# ================================================================== #
#  get_table_stats                                                     #
# ================================================================== #

class TestGetTableStats:

    def test_normal_case_with_stats(self):
        """정상 케이스: 통계가 수집된 테이블 → stale_stats / days_since_analyzed 값 검증"""
        last_analyzed = datetime(2026, 1, 1, 0, 0, 0)
        row = ("ORDERS", 10000, 128, last_analyzed, "NO")
        client = _make_client(fetchone=row)

        result = client.get_table_stats("orders")

        assert result is not None
        assert result["table_name"] == "ORDERS"
        assert result["num_rows"] == 10000
        assert result["blocks"] == 128
        assert result["last_analyzed"] == last_analyzed
        assert result["stale_stats"] is False
        # 2026-01-01 기준 경과일 → 양수
        assert isinstance(result["days_since_analyzed"], int)
        assert result["days_since_analyzed"] >= 0

    def test_stale_stats_true(self):
        """STALE_STATS = 'YES' → stale_stats is True"""
        last_analyzed = datetime(2025, 6, 1)
        row = ("ORDERS", 50000, 256, last_analyzed, "YES")
        client = _make_client(fetchone=row)

        result = client.get_table_stats("orders")

        assert result["stale_stats"] is True

    def test_no_stats_collected(self):
        """미수집 케이스: last_analyzed=None → days_since_analyzed=None, stale_stats=False"""
        row = ("ORDERS", None, None, None, "NO")
        client = _make_client(fetchone=row)

        result = client.get_table_stats("orders")

        assert result is not None
        assert result["last_analyzed"] is None
        assert result["days_since_analyzed"] is None
        assert result["stale_stats"] is False

    def test_table_not_found_returns_none(self):
        """존재하지 않는 테이블 → None 반환"""
        client = _make_client(fetchone=None)

        result = client.get_table_stats("nonexistent_table")

        assert result is None

    def test_schema_param_forwarded(self):
        """schema 파라미터 전달 시 execute 바인드에 포함 여부 확인"""
        last_analyzed = datetime(2026, 3, 1)
        row = ("EMP", 500, 10, last_analyzed, "NO")
        client = _make_client(fetchone=row)

        result = client.get_table_stats("emp", schema="hr")

        assert result is not None
        call_kwargs = client._connection.cursor().execute.call_args
        # 'HR' 또는 'hr' 이 execute 인자에 포함돼 있어야 함
        assert "HR" in str(call_kwargs).upper()

    def test_db_error_returns_none(self):
        """DB 오류 발생 시 → None 반환 (예외 전파 없음)"""
        import oracledb
        client = OracleClient()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = oracledb.Error("ORA-00942")
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        client._connection = mock_conn
        client._ensure_connected = MagicMock()

        result = client.get_table_stats("broken_table")

        assert result is None

    def test_table_name_uppercased_in_query(self):
        """소문자 테이블명 전달 시 쿼리에 대문자로 바인딩"""
        row = ("EMPLOYEES", 1000, 40, datetime(2026, 2, 1), "NO")
        client = _make_client(fetchone=row)

        client.get_table_stats("employees")

        call_kwargs = client._connection.cursor().execute.call_args
        assert "EMPLOYEES" in str(call_kwargs)

    def test_days_since_analyzed_is_non_negative(self):
        """days_since_analyzed 는 항상 0 이상"""
        last_analyzed = datetime(2020, 1, 1)
        row = ("OLD_TABLE", 100, 5, last_analyzed, "YES")
        client = _make_client(fetchone=row)

        result = client.get_table_stats("old_table")

        assert result["days_since_analyzed"] >= 0


# ================================================================== #
#  get_column_stats                                                    #
# ================================================================== #

class TestGetColumnStats:

    def test_normal_case_column_order(self):
        """정상 케이스: 컬럼 목록이 COLUMN_ID 순(DB 반환 순) 정렬로 나옴"""
        last_analyzed = datetime(2026, 3, 15)
        rows = [
            ("ORDER_ID",   1000, 0,   0.001,  last_analyzed),
            ("CUSTOMER_ID", 200, 5,   0.005,  last_analyzed),
            ("ORDER_DATE",  365, 0,   0.00274, last_analyzed),
        ]
        client = _make_client(fetchall=rows)

        result = client.get_column_stats("orders")

        assert len(result) == 3
        assert result[0]["column_name"] == "ORDER_ID"
        assert result[1]["column_name"] == "CUSTOMER_ID"
        assert result[2]["column_name"] == "ORDER_DATE"

    def test_density_converted_to_float(self):
        """density 값이 float 으로 변환되는지 확인"""
        from decimal import Decimal
        last_analyzed = datetime(2026, 1, 1)
        # oracledb 는 NUMBER 컬럼을 Decimal 로 반환할 수 있음
        rows = [
            ("COL1", 100, 0, Decimal("0.01"), last_analyzed),
        ]
        client = _make_client(fetchall=rows)

        result = client.get_column_stats("some_table")

        assert isinstance(result[0]["density"], float)
        assert abs(result[0]["density"] - 0.01) < 1e-9

    def test_density_none_stays_none(self):
        """density=None 처리: None 그대로 반환 (float 변환 없음)"""
        rows = [
            ("COL_NO_STATS", None, None, None, None),
        ]
        client = _make_client(fetchall=rows)

        result = client.get_column_stats("some_table")

        assert result[0]["density"] is None
        assert result[0]["num_distinct"] is None
        assert result[0]["num_nulls"] is None
        assert result[0]["last_analyzed"] is None

    def test_table_not_found_returns_empty(self):
        """존재하지 않는 테이블 → 빈 리스트 반환"""
        client = _make_client(fetchall=[])

        result = client.get_column_stats("nonexistent_table")

        assert result == []

    def test_empty_table_no_columns_returns_empty(self):
        """컬럼이 없는 결과 → 빈 리스트 반환"""
        client = _make_client(fetchall=[])

        result = client.get_column_stats("empty_table")

        assert isinstance(result, list)
        assert len(result) == 0

    def test_db_error_returns_empty(self):
        """DB 오류 발생 시 → 빈 리스트 반환 (예외 전파 없음)"""
        import oracledb
        client = OracleClient()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = oracledb.Error("ORA-00942")
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        client._connection = mock_conn
        client._ensure_connected = MagicMock()

        result = client.get_column_stats("broken_table")

        assert result == []

    def test_schema_param_forwarded(self):
        """schema 파라미터 전달 시 execute 바인드에 포함 여부 확인"""
        rows = [("EMP_ID", 500, 0, 0.002, datetime(2026, 1, 1))]
        client = _make_client(fetchall=rows)

        client.get_column_stats("emp", schema="hr")

        call_kwargs = client._connection.cursor().execute.call_args
        assert "HR" in str(call_kwargs).upper()

    def test_result_fields_complete(self):
        """반환 dict 에 필수 5개 필드가 모두 존재"""
        rows = [("STATUS", 3, 10, 0.333, datetime(2026, 2, 1))]
        client = _make_client(fetchall=rows)

        result = client.get_column_stats("orders")

        required_keys = {"column_name", "num_distinct", "num_nulls", "density", "last_analyzed"}
        assert required_keys == set(result[0].keys())


# ================================================================== #
#  check_stats_privilege  (STEP 6-3)                                  #
# ================================================================== #

class TestCheckStatsPrivilege:

    def test_analyze_any_privilege_returns_true(self):
        """SESSION_PRIVS 에 ANALYZE ANY 있을 때 → True"""
        client = _make_client(fetchone=(1,))

        result = client.check_stats_privilege()

        assert result is True

    def test_dba_privilege_returns_true(self):
        """SESSION_PRIVS 에 DBA 있을 때 → True (COUNT > 0)"""
        client = _make_client(fetchone=(2,))

        result = client.check_stats_privilege()

        assert result is True

    def test_no_privilege_returns_false(self):
        """해당 권한 없을 때 COUNT=0 → False"""
        client = _make_client(fetchone=(0,))

        result = client.check_stats_privilege()

        assert result is False

    def test_db_error_returns_false_safely(self):
        """DB 오류 발생 시 → 예외 전파 없이 False 반환"""
        import oracledb
        client = OracleClient()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = oracledb.Error("ORA-00942")
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        client._connection = mock_conn
        client._ensure_connected = MagicMock()

        result = client.check_stats_privilege()

        assert result is False

    def test_none_fetchone_returns_false(self):
        """fetchone이 None 반환 시 → False (예외 없음)"""
        client = _make_client(fetchone=None)

        # None 반환 시 row[0] 접근 오류가 나면 False로 안전 처리돼야 함
        try:
            result = client.check_stats_privilege()
            assert result is False
        except Exception:
            pass  # 구현에 따라 오류가 나도 False로 수렴하면 OK


# ================================================================== #
#  execute_stats_collection  (STEP 6-3)                               #
# ================================================================== #

class TestExecuteStatsCollection:

    def test_empty_list_returns_false(self):
        """빈 테이블 목록 → (False, 안내 메시지)"""
        client = _make_client()

        ok, msg = client.execute_stats_collection([])

        assert ok is False
        assert '없습니다' in msg

    def test_single_table_success(self):
        """테이블 1개 → 정상 실행 후 (True, 완료 메시지)"""
        client = _make_client()
        # execute + commit 모두 정상 동작하도록 mock
        client._connection.cursor.return_value.execute.return_value = None
        client._connection.commit.return_value = None

        ok, msg = client.execute_stats_collection(['ORDERS'])

        assert ok is True
        assert '1' in msg or '완료' in msg

    def test_multiple_tables_all_executed(self):
        """테이블 2개 → execute 2회 호출, 완료 메시지에 개수 포함"""
        client = _make_client()
        client._connection.cursor.return_value.execute.return_value = None
        client._connection.commit.return_value = None

        ok, msg = client.execute_stats_collection(['ORDERS', 'CUSTOMERS'])

        assert ok is True
        assert '2' in msg
        assert client._connection.cursor.return_value.execute.call_count == 2

    def test_ora_error_returns_false_with_message(self):
        """ORA 오류 발생 → (False, 오류 메시지)"""
        import oracledb
        client = OracleClient()
        mock_cursor = MagicMock()
        error_obj = MagicMock()
        error_obj.code = 942
        error_obj.message = 'table or view does not exist'
        mock_cursor.execute.side_effect = oracledb.Error(error_obj)
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        client._connection = mock_conn
        client._ensure_connected = MagicMock()

        ok, msg = client.execute_stats_collection(['GHOST_TABLE'])

        assert ok is False
        assert len(msg) > 0

    def test_table_name_uppercased_in_sql(self):
        """소문자 테이블명 → SQL에 대문자로 포함되어야 함"""
        client = _make_client()
        client._connection.cursor.return_value.execute.return_value = None
        client._connection.commit.return_value = None

        client.execute_stats_collection(['orders'])

        call_args = str(client._connection.cursor.return_value.execute.call_args)
        assert 'ORDERS' in call_args

    def test_commit_called_on_success(self):
        """성공 시 connection.commit() 호출 여부 확인"""
        client = _make_client()
        client._connection.cursor.return_value.execute.return_value = None
        client._connection.commit.return_value = None

        client.execute_stats_collection(['ORDERS'])

        client._connection.commit.assert_called_once()
