"""
OracleClient – Index Advisor 메서드 단위 테스트

get_tables_from_sql : DB 불필요, sqlglot AST 파싱만 사용
get_table_indexes   : DB 연결 필요 → unittest.mock 으로 커서를 대체
"""
import pytest
from unittest.mock import MagicMock, patch
from v2.core.db.oracle_client import OracleClient


@pytest.fixture
def client():
    """DB 연결 없이 OracleClient 인스턴스만 생성"""
    return OracleClient()


# ================================================================== #
#  get_tables_from_sql – DB 불필요                                     #
# ================================================================== #

class TestGetTablesFromSql:

    def test_single_table(self, client):
        """단순 FROM 절 — 테이블 1개"""
        result = client.get_tables_from_sql("SELECT * FROM orders")
        assert result == ["ORDERS"]

    def test_join_two_tables(self, client):
        """JOIN 포함 — 테이블 2개, 출현 순서 유지"""
        sql = "SELECT * FROM orders o JOIN order_items oi ON o.id = oi.order_id"
        result = client.get_tables_from_sql(sql)
        assert result == ["ORDERS", "ORDER_ITEMS"]

    def test_multiple_joins(self, client):
        """JOIN 3개 — 순서대로 반환"""
        sql = """
            SELECT *
            FROM orders o
            JOIN customers c ON o.customer_id = c.id
            JOIN order_items oi ON o.id = oi.order_id
        """
        result = client.get_tables_from_sql(sql)
        assert result == ["ORDERS", "CUSTOMERS", "ORDER_ITEMS"]

    def test_subquery_in_where(self, client):
        """WHERE 절 서브쿼리 — 안쪽 테이블도 반환"""
        sql = "SELECT * FROM orders WHERE id IN (SELECT order_id FROM order_items)"
        result = client.get_tables_from_sql(sql)
        assert "ORDERS" in result
        assert "ORDER_ITEMS" in result

    def test_duplicate_table_deduped(self, client):
        """같은 테이블 두 번 등장 — 중복 제거"""
        sql = """
            SELECT * FROM emp e1
            JOIN emp e2 ON e1.manager_id = e2.id
        """
        result = client.get_tables_from_sql(sql)
        assert result.count("EMP") == 1

    def test_table_name_uppercased(self, client):
        """소문자 테이블명 → 대문자로 반환"""
        result = client.get_tables_from_sql("SELECT * FROM employees")
        assert result == ["EMPLOYEES"]

    def test_schema_qualified_table(self, client):
        """스키마 한정 테이블명 (hr.employees) — 테이블명만 반환"""
        result = client.get_tables_from_sql("SELECT * FROM hr.employees")
        assert "EMPLOYEES" in result

    def test_invalid_sql_returns_empty(self, client):
        """파싱 불가 텍스트 → 빈 리스트 반환 (예외 없음)"""
        result = client.get_tables_from_sql("이건 SQL이 아닙니다 !!!@@##")
        assert result == []

    def test_empty_string_returns_empty(self, client):
        """빈 문자열 → 빈 리스트"""
        result = client.get_tables_from_sql("")
        assert result == []

    def test_union_query(self, client):
        """UNION — 양쪽 테이블 모두 반환"""
        sql = """
            SELECT ename FROM emp WHERE deptno = 10
            UNION ALL
            SELECT ename FROM dept WHERE deptno = 20
        """
        result = client.get_tables_from_sql(sql)
        assert "EMP" in result
        assert "DEPT" in result


# ================================================================== #
#  get_table_indexes – DB mock                                         #
# ================================================================== #

class TestGetTableIndexes:

    def _make_client_with_mock_cursor(self, rows):
        """
        _ensure_connected 와 cursor 를 mock 으로 대체한 OracleClient 반환.

        rows : cursor.fetchall() 이 반환할 리스트
               각 원소 형식: (INDEX_NAME, UNIQUENESS, COLUMN_NAME, COLUMN_POSITION, STATUS)
        """
        client = OracleClient()
        mock_cursor = MagicMock()
        mock_cursor.fetchall.return_value = rows
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        client._connection = mock_conn
        client._ensure_connected = MagicMock()  # 연결 체크 우회
        return client

    def test_single_column_unique_index(self):
        """단일 컬럼 UNIQUE 인덱스"""
        rows = [("PK_ORDERS", "UNIQUE", "ORDER_ID", 1, "VALID")]
        client = self._make_client_with_mock_cursor(rows)
        result = client.get_table_indexes("orders")

        assert len(result) == 1
        idx = result[0]
        assert idx["index_name"] == "PK_ORDERS"
        assert idx["uniqueness"] == "UNIQUE"
        assert idx["columns"] == ["ORDER_ID"]
        assert idx["status"] == "VALID"

    def test_composite_index_column_order(self):
        """복합 인덱스 — COLUMN_POSITION 순서로 columns 구성"""
        rows = [
            ("IDX_ORDERS_COMP", "NONUNIQUE", "CUSTOMER_ID",  1, "VALID"),
            ("IDX_ORDERS_COMP", "NONUNIQUE", "ORDER_DATE",   2, "VALID"),
        ]
        client = self._make_client_with_mock_cursor(rows)
        result = client.get_table_indexes("orders")

        assert len(result) == 1
        assert result[0]["columns"] == ["CUSTOMER_ID", "ORDER_DATE"]

    def test_multiple_indexes(self):
        """인덱스 2개 — 각각 독립된 dict"""
        rows = [
            ("PK_ORDERS",      "UNIQUE",    "ORDER_ID",    1, "VALID"),
            ("IDX_CUST",       "NONUNIQUE", "CUSTOMER_ID", 1, "VALID"),
        ]
        client = self._make_client_with_mock_cursor(rows)
        result = client.get_table_indexes("orders")

        assert len(result) == 2
        names = [r["index_name"] for r in result]
        assert "PK_ORDERS" in names
        assert "IDX_CUST" in names

    def test_unusable_index_status(self):
        """UNUSABLE 상태 인덱스도 그대로 반환"""
        rows = [("IDX_OLD", "NONUNIQUE", "COL1", 1, "UNUSABLE")]
        client = self._make_client_with_mock_cursor(rows)
        result = client.get_table_indexes("some_table")

        assert result[0]["status"] == "UNUSABLE"

    def test_no_indexes_returns_empty(self):
        """인덱스 없는 테이블 → 빈 리스트"""
        client = self._make_client_with_mock_cursor([])
        result = client.get_table_indexes("no_index_table")
        assert result == []

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

        result = client.get_table_indexes("broken_table")
        assert result == []

    def test_schema_param_passed(self):
        """schema 파라미터 전달 시 쿼리에 포함 여부 확인"""
        rows = [("PK_EMP", "UNIQUE", "EMP_ID", 1, "VALID")]
        client = self._make_client_with_mock_cursor(rows)
        result = client.get_table_indexes("emp", schema="hr")

        # schema 지정해도 결과 구조는 동일
        assert result[0]["index_name"] == "PK_EMP"
        # execute 호출 시 schema 바인드 변수가 전달됐는지 확인
        call_kwargs = client._connection.cursor().execute.call_args
        assert "hr" in str(call_kwargs).upper() or "HR" in str(call_kwargs)
