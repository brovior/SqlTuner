"""
Oracle DB 연결 및 SQL Plan 조회 모듈
python-oracledb Thick 모드 사용 (기존 Oracle 11 클라이언트 활용)
"""
try:
    import oracledb
    ORACLEDB_AVAILABLE = True
except ImportError:
    ORACLEDB_AVAILABLE = False
    oracledb = None  # type: ignore

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ConnectionInfo:
    tns_alias: str
    username: str
    password: str
    tns_filepath: str


@dataclass
class PlanRow:
    """EXPLAIN PLAN 한 행"""
    id: int
    parent_id: Optional[int]
    operation: str
    options: str
    object_name: str
    cost: Optional[int]
    cardinality: Optional[int]
    bytes: Optional[int]
    cpu_cost: Optional[int]
    io_cost: Optional[int]
    depth: int = 0
    children: list = field(default_factory=list)

    @property
    def full_operation(self) -> str:
        if self.options:
            return f"{self.operation} {self.options}"
        return self.operation


@dataclass
class SqlStats:
    """V$SQL 실행 통계"""
    sql_id: str
    executions: int
    elapsed_time_ms: float
    cpu_time_ms: float
    buffer_gets: int
    disk_reads: int
    rows_processed: int
    parse_calls: int


class OracleClient:
    def __init__(self):
        self._connection = None
        self._conn_info: Optional[ConnectionInfo] = None
        self._thick_initialized = False

    def init_thick_mode(self, lib_dir: str = None):
        """
        Oracle 클라이언트 라이브러리를 사용하는 Thick 모드 초기화.
        lib_dir 미지정 시 환경변수(ORACLE_HOME, PATH)에서 자동 탐색.
        """
        if not ORACLEDB_AVAILABLE:
            raise RuntimeError(
                "oracledb 패키지가 설치되어 있지 않습니다.\n"
                "install_online.bat 또는 install.bat을 실행하세요."
            )
        if self._thick_initialized:
            return
        try:
            if lib_dir:
                oracledb.init_oracle_client(lib_dir=lib_dir)
            else:
                oracledb.init_oracle_client()
            self._thick_initialized = True
        except Exception as e:
            raise RuntimeError(
                f"Oracle 클라이언트 초기화 실패: {e}\n"
                "Oracle Client가 설치되어 있고 PATH에 등록되어 있는지 확인하세요."
            )

    def connect(self, conn_info: ConnectionInfo) -> None:
        """TNS 별칭으로 Oracle DB에 연결합니다."""
        self.init_thick_mode()

        # tnsnames.ora 위치를 TNS_ADMIN으로 설정
        if conn_info.tns_filepath:
            tns_dir = os.path.dirname(conn_info.tns_filepath)
            os.environ['TNS_ADMIN'] = tns_dir

        try:
            self._connection = oracledb.connect(
                user=conn_info.username,
                password=conn_info.password,
                dsn=conn_info.tns_alias,
            )
            self._conn_info = conn_info
        except oracledb.Error as e:
            error_obj, = e.args
            raise ConnectionError(
                f"DB 연결 실패 [{conn_info.tns_alias}]\n"
                f"오류코드: {error_obj.code}\n"
                f"메시지: {error_obj.message}"
            )

    def disconnect(self):
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None
            self._conn_info = None

    @property
    def is_connected(self) -> bool:
        if not self._connection:
            return False
        try:
            self._connection.ping()
            return True
        except Exception:
            return False

    @property
    def current_connection_label(self) -> str:
        if self._conn_info:
            return f"{self._conn_info.tns_alias} / {self._conn_info.username}"
        return "미연결"

    def _ensure_connected(self):
        if not self.is_connected:
            raise RuntimeError("DB에 연결되어 있지 않습니다.")

    # ------------------------------------------------------------------
    # EXPLAIN PLAN
    # ------------------------------------------------------------------

    def explain_plan(self, sql: str) -> tuple[list[PlanRow], str]:
        """
        EXPLAIN PLAN을 1회만 실행하고 PlanRow 목록과 DBMS_XPLAN 텍스트를 함께 반환합니다.
        DB 부하를 줄이기 위해 EXPLAIN PLAN을 한 번만 수행합니다.
        실제 SQL을 실행하지 않으므로 안전합니다.
        """
        self._ensure_connected()
        statement_id = 'SQL_TUNER_PLAN'
        cursor = self._connection.cursor()

        try:
            # 기존 플랜 삭제
            cursor.execute(
                "DELETE FROM PLAN_TABLE WHERE STATEMENT_ID = :sid",
                sid=statement_id
            )

            # EXPLAIN PLAN 1회 실행
            cursor.execute(
                f"EXPLAIN PLAN SET STATEMENT_ID = '{statement_id}' FOR {sql}"
            )

            # 1) PLAN_TABLE에서 PlanRow 조회
            cursor.execute("""
                SELECT
                    ID,
                    PARENT_ID,
                    OPERATION,
                    OPTIONS,
                    OBJECT_NAME,
                    COST,
                    CARDINALITY,
                    BYTES,
                    CPU_COST,
                    IO_COST,
                    DEPTH
                FROM PLAN_TABLE
                WHERE STATEMENT_ID = :sid
                ORDER BY ID
            """, sid=statement_id)

            rows = []
            for row in cursor.fetchall():
                rows.append(PlanRow(
                    id=row[0],
                    parent_id=row[1],
                    operation=row[2] or '',
                    options=row[3] or '',
                    object_name=row[4] or '',
                    cost=row[5],
                    cardinality=row[6],
                    bytes=row[7],
                    cpu_cost=row[8],
                    io_cost=row[9],
                    depth=row[10] or 0,
                ))

            # 2) 같은 statement_id로 DBMS_XPLAN 텍스트 조회 (추가 EXPLAIN PLAN 불필요)
            cursor.execute("""
                SELECT PLAN_TABLE_OUTPUT
                FROM TABLE(DBMS_XPLAN.DISPLAY(
                    'PLAN_TABLE', :sid, 'ALL'
                ))
            """, sid=statement_id)
            xplan_lines = [row[0] for row in cursor.fetchall()]

            self._connection.rollback()
            return rows, '\n'.join(xplan_lines)

        except oracledb.Error as e:
            self._connection.rollback()
            error_obj, = e.args
            raise ValueError(
                f"EXPLAIN PLAN 실행 오류\n"
                f"오류코드: {error_obj.code}\n"
                f"메시지: {error_obj.message}"
            )
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # V$SQL 실행 통계 (실제 실행 이력)
    # ------------------------------------------------------------------

    def get_sql_stats(self, sql_keyword: str) -> list[SqlStats]:
        """
        V$SQL에서 SQL 실행 통계를 조회합니다.
        sql_keyword: SQL 텍스트의 일부 (첫 80자 권장)
        """
        self._ensure_connected()
        cursor = self._connection.cursor()
        keyword = '%' + sql_keyword.strip()[:80] + '%'

        try:
            cursor.execute("""
                SELECT
                    SQL_ID,
                    EXECUTIONS,
                    ELAPSED_TIME / 1000 AS ELAPSED_MS,
                    CPU_TIME / 1000 AS CPU_MS,
                    BUFFER_GETS,
                    DISK_READS,
                    ROWS_PROCESSED,
                    PARSE_CALLS
                FROM V$SQL
                WHERE SQL_TEXT LIKE :kw
                  AND ROWNUM <= 10
                ORDER BY ELAPSED_TIME DESC
            """, kw=keyword)

            stats = []
            for row in cursor.fetchall():
                stats.append(SqlStats(
                    sql_id=row[0] or '',
                    executions=row[1] or 0,
                    elapsed_time_ms=row[2] or 0,
                    cpu_time_ms=row[3] or 0,
                    buffer_gets=row[4] or 0,
                    disk_reads=row[5] or 0,
                    rows_processed=row[6] or 0,
                    parse_calls=row[7] or 0,
                ))
            return stats

        except oracledb.Error:
            # V$SQL 권한 없으면 빈 목록 반환
            return []
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # 인덱스 정보 조회
    # ------------------------------------------------------------------

    def get_table_indexes(self, table_name: str, owner: str = None) -> list[dict]:
        """테이블의 인덱스 목록을 조회합니다."""
        self._ensure_connected()
        cursor = self._connection.cursor()

        params = {'tname': table_name.upper()}
        owner_filter = "AND AI.TABLE_OWNER = :owner" if owner else ""
        if owner:
            params['owner'] = owner.upper()
        try:
            cursor.execute(f"""
                SELECT
                    AI.INDEX_NAME,
                    AI.INDEX_TYPE,
                    AI.UNIQUENESS,
                    AI.STATUS,
                    LISTAGG(AIC.COLUMN_NAME, ', ')
                        WITHIN GROUP (ORDER BY AIC.COLUMN_POSITION) AS COLUMNS
                FROM ALL_INDEXES AI
                JOIN ALL_IND_COLUMNS AIC
                  ON AI.INDEX_NAME = AIC.INDEX_NAME
                 AND AI.TABLE_OWNER = AIC.TABLE_OWNER
                WHERE AI.TABLE_NAME = :tname
                  {owner_filter}
                GROUP BY AI.INDEX_NAME, AI.INDEX_TYPE, AI.UNIQUENESS, AI.STATUS
                ORDER BY AI.INDEX_NAME
            """, **params)

            indexes = []
            for row in cursor.fetchall():
                indexes.append({
                    'index_name': row[0],
                    'index_type': row[1],
                    'uniqueness': row[2],
                    'status': row[3],
                    'columns': row[4],
                })
            return indexes

        except oracledb.Error:
            return []
        finally:
            cursor.close()

    def get_table_stats(self, table_name: str, owner: str = None) -> dict:
        """테이블 통계 정보를 조회합니다."""
        self._ensure_connected()
        cursor = self._connection.cursor()
        params = {'tname': table_name.upper()}
        owner_filter = "AND OWNER = :owner" if owner else ""
        if owner:
            params['owner'] = owner.upper()

        try:
            cursor.execute(f"""
                SELECT
                    NUM_ROWS,
                    BLOCKS,
                    AVG_ROW_LEN,
                    LAST_ANALYZED
                FROM ALL_TABLES
                WHERE TABLE_NAME = :tname
                  {owner_filter}
                  AND ROWNUM = 1
            """, **params)
            row = cursor.fetchone()
            if row:
                return {
                    'num_rows': row[0],
                    'blocks': row[1],
                    'avg_row_len': row[2],
                    'last_analyzed': str(row[3]) if row[3] else '미수집',
                }
            return {}
        except oracledb.Error:
            return {}
        finally:
            cursor.close()
