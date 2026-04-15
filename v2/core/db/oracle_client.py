"""
Oracle DB 연결 및 SQL Plan 조회 모듈
python-oracledb Thick 모드 사용 (기존 Oracle 11 클라이언트 활용)
"""
try:
    import oracledb
    ORACLEDB_AVAILABLE = True
    _ORACLEDB_IMPORT_ERROR: str | None = None
except Exception as _e:
    ORACLEDB_AVAILABLE = False
    _ORACLEDB_IMPORT_ERROR = f'{type(_e).__name__}: {_e}'
    oracledb = None  # type: ignore

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
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


# Wait Class → 심각도 매핑
_WAIT_CLASS_SEVERITY: dict[str, str] = {
    'User I/O':    'HIGH',
    'Concurrency': 'HIGH',
    'System I/O':  'MEDIUM',
    'Application': 'MEDIUM',
    'Network':     'LOW',
    'Commit':      'LOW',
    'Other':       'INFO',
    'Idle':        'INFO',
}

# Wait Class → 개선 제안
_WAIT_CLASS_SUGGESTION: dict[str, str] = {
    'User I/O': (
        '물리적 I/O 병목입니다. 인덱스 추가·재구성으로 Full Table Scan을 줄이세요. '
        'BUFFER_GETS 대비 DISK_READS 비율이 높다면 DB Buffer Cache 크기를 검토하세요.'
    ),
    'Concurrency': (
        '락(Lock) 또는 래치(Latch) 경합이 발생하고 있습니다. '
        '트랜잭션 범위를 줄이거나 커밋 주기를 단축하세요. '
        'V$LOCK, V$SESSION을 조회해 블로킹 세션을 확인하세요.'
    ),
    'System I/O': (
        'Redo 로그 또는 컨트롤 파일 I/O가 발생하고 있습니다. '
        'Redo Log 파일 크기·개수를 늘리거나 빠른 디스크로 이동을 검토하세요.'
    ),
    'Application': (
        '애플리케이션 수준의 대기(예: 락 대기)가 발생하고 있습니다. '
        '트랜잭션 설계 및 커밋 주기를 검토하세요.'
    ),
}


@dataclass
class ResourceMetric:
    """리소스 분석 결과 항목 하나 (V$SESSION_WAIT / V$SQL / V$MYSTAT 공통)"""
    name: str           # 항목명 (예: 'db file sequential read', 'DISK_READS')
    category: str       # 분류 (예: 'Wait Event', 'I/O 통계', '세션 통계')
    raw_value: int      # 비교용 숫자값
    display_value: str  # 화면 표시용 문자열
    severity: str       # HIGH / MEDIUM / LOW / INFO
    suggestion: str     # 개선 제안 (없으면 '')


@dataclass
class ResourceAnalysis:
    """리소스 분석 결과 전체 (조회 방법 레이블 + 항목 목록 + 폴백 원인)"""
    method: str                             # 조회 방법 레이블
    metrics: list = field(default_factory=list)        # list[ResourceMetric]
    error_chain: list = field(default_factory=list)    # 상위 방법 실패 메시지 list[str]


class OracleClient:
    def __init__(self):
        self._connection = None
        self._conn_info: Optional[ConnectionInfo] = None
        self._thick_initialized = False
        self._thin_mode = False   # True면 Thin 모드로 연결된 상태
        # explain_plan() 호출 직전에 저장하는 V$MYSTAT 스냅샷 (3순위 폴백용)
        self._pre_analysis_mystat: dict[str, int] = {}

    @property
    def connection_mode(self) -> str:
        """현재 연결 모드 반환 (Thick / Thin / 미연결)"""
        if not self.is_connected:
            return '미연결'
        return 'Thin' if self._thin_mode else 'Thick'

    def _try_init_thick_mode(self) -> str | None:
        """
        Thick 모드 초기화를 시도합니다.
        성공하면 None, 실패하면 오류 메시지를 반환합니다.
        """
        if self._thick_initialized:
            return None
        try:
            oracledb.init_oracle_client()
            self._thick_initialized = True
            return None
        except Exception as e:
            return str(e)

    def connect(self, conn_info: ConnectionInfo) -> None:
        """
        TNS 별칭으로 Oracle DB에 연결합니다.
        Thick 모드(64bit Oracle Client)를 먼저 시도하고,
        DPI-1047(아키텍처 불일치) 등 실패 시 Thin 모드로 자동 전환합니다.
        """
        if not ORACLEDB_AVAILABLE:
            detail = f'\n\n[import 오류] {_ORACLEDB_IMPORT_ERROR}' if _ORACLEDB_IMPORT_ERROR else ''
            raise RuntimeError(
                f"oracledb 패키지를 로드할 수 없습니다.{detail}"
            )

        # tnsnames.ora 위치를 TNS_ADMIN으로 설정
        tns_dir = None
        if conn_info.tns_filepath:
            tns_dir = os.path.dirname(conn_info.tns_filepath)
            os.environ['TNS_ADMIN'] = tns_dir

        # 1차: Thick 모드 시도
        thick_error = self._try_init_thick_mode()
        if thick_error is None:
            try:
                self._connection = oracledb.connect(
                    user=conn_info.username,
                    password=conn_info.password,
                    dsn=conn_info.tns_alias,
                )
                self._conn_info = conn_info
                self._thin_mode = False
                return
            except oracledb.Error as e:
                error_obj, = e.args
                raise ConnectionError(
                    f"DB 연결 실패 [{conn_info.tns_alias}]\n"
                    f"오류코드: {error_obj.code}\n"
                    f"메시지: {error_obj.message}"
                )

        # 2차: Thick 초기화 실패 시 Thin 모드로 폴백
        # (DPI-1047: 32bit/64bit 불일치, Oracle Client 미설치 등)
        try:
            self._connection = oracledb.connect(
                user=conn_info.username,
                password=conn_info.password,
                dsn=conn_info.tns_alias,
                config_dir=tns_dir,   # tnsnames.ora 경로 직접 전달
            )
            self._conn_info = conn_info
            self._thin_mode = True
        except oracledb.Error as e:
            error_obj, = e.args
            raise ConnectionError(
                f"DB 연결 실패 [{conn_info.tns_alias}]\n"
                f"오류코드: {error_obj.code}\n"
                f"메시지: {error_obj.message}\n\n"
                f"[Thick 모드 오류] {thick_error}"
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

    def get_db_version(self) -> tuple[str, str]:
        """
        Oracle DB 버전을 반환합니다.
        반환값: (short_version, full_banner)
          short_version 예시: "Oracle 19c", "Oracle 21c", "Oracle 11g"
          full_banner   예시: "Oracle Database 19c Enterprise Edition Release 19.0.0.0.0 - Production"
        """
        self._ensure_connected()
        cursor = self._connection.cursor()
        try:
            cursor.execute("SELECT BANNER FROM V$VERSION WHERE ROWNUM = 1")
            row = cursor.fetchone()
            banner = row[0] if row else ''
            short = self._parse_version_short(banner)
            return short, banner
        finally:
            cursor.close()

    @staticmethod
    def _parse_version_short(banner: str) -> str:
        """
        BANNER 문자열에서 "Oracle 19c" 형식의 짧은 버전명을 추출합니다.
        예: "Oracle Database 19c Enterprise Edition ..." → "Oracle 19c"
        """
        import re
        m = re.search(r'Oracle\s+(?:Database\s+)?(\d+)([cg])', banner, re.IGNORECASE)
        if m:
            return f"Oracle {m.group(1)}{m.group(2).lower()}"
        # 버전 번호만 추출 (예: Release 11.2.0.4.0)
        m2 = re.search(r'Release\s+(\d+\.\d+)', banner)
        if m2:
            return f"Oracle {m2.group(1)}"
        return 'Oracle (버전 미상)'

    @staticmethod
    def _inject_gather_stats_hint(sql: str) -> str:
        """
        SQL의 메인 SELECT에 GATHER_PLAN_STATISTICS 힌트를 주입합니다.
        ALTER SESSION 권한 없이 row source 통계(A-Rows, Buffers, Reads)를 수집합니다.

        - 일반 SELECT: SELECT 바로 뒤에 삽입
        - WITH 구문:   최상위(depth=0) SELECT(메인 쿼리)에 삽입
        - 기존 힌트 블록이 있으면 그 안에 추가
        - SELECT를 찾지 못하면 원본 반환
        """
        import re

        # 최상위(depth=0) 첫 번째 SELECT 위치 탐색
        depth = 0
        target_pos = -1
        n = len(sql)
        upper = sql.upper()
        i = 0
        while i < n:
            ch = sql[i]
            if ch == '(':
                depth += 1
            elif ch == ')':
                depth -= 1
            elif depth == 0 and upper[i:i+6] == 'SELECT':
                before_ok = i == 0 or not (sql[i-1].isalnum() or sql[i-1] == '_')
                after_ok  = i + 6 >= n or not (sql[i+6].isalnum() or sql[i+6] == '_')
                if before_ok and after_ok:
                    target_pos = i
                    break
            i += 1

        if target_pos == -1:
            return sql

        after_select = sql[target_pos + 6:]

        # 기존 힌트 블록(/*+ ... */)이 있으면 기존 힌트 뒤에 추가
        # 예: SELECT /*+ NO_MERGE */ → SELECT /*+ NO_MERGE GATHER_PLAN_STATISTICS */
        m = re.match(r'(\s*/\*\+)(.*?)(\*/)', after_select, re.DOTALL)
        if m:
            new_block = m.group(1) + m.group(2) + ' GATHER_PLAN_STATISTICS ' + m.group(3)
            return sql[:target_pos + 6] + new_block + after_select[m.end():]

        # 없으면 힌트 블록 새로 삽입
        return sql[:target_pos + 6] + ' /*+ GATHER_PLAN_STATISTICS */' + after_select

    def get_current_user_schema(self) -> tuple[str, str]:
        """
        현재 세션의 로그인 유저와 현재 스키마를 반환합니다.
        반환값: (user, current_schema)
        """
        self._ensure_connected()
        cursor = self._connection.cursor()
        try:
            cursor.execute(
                "SELECT USER, SYS_CONTEXT('USERENV','CURRENT_SCHEMA') FROM DUAL"
            )
            row = cursor.fetchone()
            return (row[0] or '', row[1] or '')
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # EXPLAIN PLAN
    # ------------------------------------------------------------------

    def explain_plan(
        self, sql: str, bind_vars: dict | None = None
    ) -> tuple[list[PlanRow], str]:
        """
        EXPLAIN PLAN을 1회만 실행하고 PlanRow 목록과 DBMS_XPLAN 텍스트를 함께 반환합니다.
        DB 부하를 줄이기 위해 EXPLAIN PLAN을 한 번만 수행합니다.
        실제 SQL을 실행하지 않으므로 안전합니다.

        bind_vars: SQL의 :변수명에 대응하는 값 딕셔너리.
                   oracledb 네이티브 바인드로 전달되며 문자열 치환은 하지 않습니다.
        """
        self._ensure_connected()
        # V$MYSTAT 3순위 폴백을 위해 분석 직전 세션 통계 스냅샷 저장
        self._pre_analysis_mystat = self._snapshot_mystat()
        statement_id = 'SQL_TUNER_PLAN'

        # SQL 전처리: 세미콜론 제거 + 앞뒤 공백 제거
        # 세미콜론이 붙으면 EXPLAIN PLAN 구문이 깨져 ORA-00911 또는 ORA-00938 발생 가능
        sql = sql.strip().rstrip(';').strip()

        cursor = self._connection.cursor()

        try:
            # 기존 플랜 삭제
            # ※ statement_id 는 내부 고정 상수이므로 f-string 삽입 (바인드 변수 ORA-00938 방지)
            cursor.execute(
                f"DELETE FROM PLAN_TABLE WHERE STATEMENT_ID = '{statement_id}'"
            )

            # EXPLAIN PLAN 1회 실행 (바인드 변수 있으면 네이티브 바인드로 전달)
            plan_sql = f"EXPLAIN PLAN SET STATEMENT_ID = '{statement_id}' FOR {sql}"
            if bind_vars:
                cursor.execute(plan_sql, bind_vars)
            else:
                cursor.execute(plan_sql)

            # 1) PLAN_TABLE에서 PlanRow 조회
            # ※ statement_id 는 내부 고정 상수이므로 f-string 삽입 (바인드 변수 ORA-00938 방지)
            cursor.execute(f"""
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
                WHERE STATEMENT_ID = '{statement_id}'
                ORDER BY ID
            """)

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
            # ※ TABLE(pipelined_func(:bind)) 구문은 일부 Oracle 버전에서 ORA-00938 발생 →
            #   statement_id 는 내부 고정 상수이므로 f-string으로 직접 삽입
            cursor.execute(f"""
                SELECT PLAN_TABLE_OUTPUT
                FROM TABLE(DBMS_XPLAN.DISPLAY(
                    'PLAN_TABLE', '{statement_id}', 'ALL'
                ))
            """)
            xplan_lines = [row[0] for row in cursor.fetchall()]

            self._connection.rollback()
            return rows, '\n'.join(xplan_lines)

        except oracledb.Error as e:
            self._connection.rollback()
            error_obj, = e.args
            code = error_obj.code
            message = error_obj.message

            # ORA-00938: 함수의 인수가 충분하지 않습니다
            # → SQL 또는 참조 뷰/객체에 인수가 누락된 함수 호출이 있을 때 발생
            if code == 938:
                hint = (
                    "\n\n[원인 안내]\n"
                    "SQL 또는 참조하는 뷰/함수에 인수가 부족한 함수 호출이 포함되어 있습니다.\n"
                    "예) NVL(col) → NVL(col, 0) / DECODE(col) → DECODE(col, ...) \n"
                    "SQL Developer 에서 직접 실행하여 오류 위치를 확인하세요."
                )
                raise ValueError(
                    f"EXPLAIN PLAN 실행 오류\n"
                    f"오류코드: {code}\n"
                    f"메시지: {message}{hint}"
                )

            raise ValueError(
                f"EXPLAIN PLAN 실행 오류\n"
                f"오류코드: {code}\n"
                f"메시지: {message}"
            )
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # V$SQL 실행 통계 (실제 실행 이력)
    # ------------------------------------------------------------------

    def get_sql_stats(
        self, sql_keyword: str, sql_id: str = ''
    ) -> list[SqlStats]:
        """
        V$SQL에서 SQL 실행 통계를 조회합니다.
        sql_id가 있으면 SQL_ID로 정확히 조회합니다 (힌트 주입 등 텍스트 변형 대응).
        sql_id가 없으면 sql_keyword LIKE 매칭으로 폴백합니다.
        """
        self._ensure_connected()
        cursor = self._connection.cursor()

        try:
            if sql_id:
                cursor.execute("""
                    SELECT SQL_ID, EXECUTIONS,
                           ELAPSED_TIME / 1000 AS ELAPSED_MS,
                           CPU_TIME / 1000 AS CPU_MS,
                           BUFFER_GETS, DISK_READS,
                           ROWS_PROCESSED, PARSE_CALLS
                    FROM V$SQL
                    WHERE SQL_ID = :sid
                    ORDER BY ELAPSED_TIME DESC
                """, sid=sql_id)
            else:
                keyword = '%' + sql_keyword.strip()[:80] + '%'
                cursor.execute("""
                    SELECT SQL_ID, EXECUTIONS,
                           ELAPSED_TIME / 1000 AS ELAPSED_MS,
                           CPU_TIME / 1000 AS CPU_MS,
                           BUFFER_GETS, DISK_READS,
                           ROWS_PROCESSED, PARSE_CALLS
                    FROM (
                        SELECT SQL_ID, EXECUTIONS, ELAPSED_TIME, CPU_TIME,
                               BUFFER_GETS, DISK_READS, ROWS_PROCESSED, PARSE_CALLS
                        FROM V$SQL
                        WHERE SQL_TEXT LIKE :kw
                          AND SQL_TEXT NOT LIKE 'EXPLAIN PLAN%'
                        ORDER BY ELAPSED_TIME DESC
                    )
                    WHERE ROWNUM <= 10
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

        except oracledb.Error as e:
            error_obj, = e.args
            raise ValueError(
                f"V$SQL 조회 오류 (권한이 없거나 뷰에 접근할 수 없습니다)\n"
                f"오류코드: {error_obj.code}\n"
                f"메시지: {error_obj.message}"
            )
        finally:
            cursor.close()

    # ------------------------------------------------------------------
    # 리소스 분석 (3단계 폴백)
    # ------------------------------------------------------------------

    def get_resource_analysis(self, sql_keyword: str = '') -> 'ResourceAnalysis':
        """
        SQL 실행 리소스를 아래 우선순위로 조회하여 ResourceAnalysis를 반환합니다.

          1순위: V$SESSION_WAIT  — 실시간 세션 대기 이벤트 (권한 필요)
          2순위: V$SQL 통계      — 실행 이력의 I/O·시간 통계 (sql_keyword 필요, V$SQL 권한 필요)
          3순위: V$MYSTAT 차이   — explain_plan() 전후 세션 통계 차이 (항상 가능)

        self._pre_analysis_mystat 는 explain_plan() 호출 시 자동으로 저장됩니다.
        """
        self._ensure_connected()
        errors: list[str] = []

        # 1순위: V$SESSION_WAIT
        try:
            metrics = self._get_session_wait_metrics()
            return ResourceAnalysis(method='V$SESSION_WAIT 기준', metrics=metrics)
        except Exception as e:
            errors.append(f'V$SESSION_WAIT 조회 실패: {e}')

        # 2순위: V$SQL 통계
        if sql_keyword.strip():
            try:
                metrics = self._get_vsql_resource_metrics(sql_keyword)
                return ResourceAnalysis(
                    method='V$SQL 통계 기준', metrics=metrics, error_chain=errors
                )
            except Exception as e:
                errors.append(f'V$SQL 조회 실패: {e}')

        # 3순위: V$MYSTAT 전후 차이
        try:
            metrics = self._get_mystat_diff_metrics()
            return ResourceAnalysis(
                method='V$MYSTAT 차이 기준', metrics=metrics, error_chain=errors
            )
        except Exception as e:
            errors.append(f'V$MYSTAT 조회 실패: {e}')

        return ResourceAnalysis(method='조회 불가', metrics=[], error_chain=errors)

    def _snapshot_mystat(self) -> dict[str, int]:
        """V$MYSTAT 현재값 스냅샷을 {stat_name: value} 딕셔너리로 반환한다."""
        if not self._connection:
            return {}
        cursor = self._connection.cursor()
        try:
            cursor.execute("""
                SELECT n.NAME, s.VALUE
                FROM V$MYSTAT s
                JOIN V$STATNAME n ON s.STATISTIC# = n.STATISTIC#
                WHERE n.NAME IN (
                    'physical reads',
                    'session logical reads',
                    'redo size'
                )
            """)
            return {row[0]: (row[1] or 0) for row in cursor.fetchall()}
        except Exception:
            return {}
        finally:
            cursor.close()

    def _get_session_wait_metrics(self) -> list['ResourceMetric']:
        """V$SESSION_WAIT에서 현재 세션의 Wait Event 통계를 조회한다."""
        cursor = self._connection.cursor()
        try:
            cursor.execute("""
                SELECT EVENT, WAIT_CLASS, TOTAL_WAITS, TIME_WAITED
                FROM V$SESSION_WAIT
                WHERE SID = (SELECT SID FROM V$MYSTAT WHERE ROWNUM = 1)
                  AND TOTAL_WAITS > 0
                ORDER BY TIME_WAITED DESC
            """)
            results = []
            for row in cursor.fetchall():
                wait_class = row[1] or 'Other'
                total_waits = row[2] or 0
                time_waited = row[3] or 0
                severity = _WAIT_CLASS_SEVERITY.get(wait_class, 'INFO')
                results.append(ResourceMetric(
                    name=row[0] or '',
                    category=wait_class,
                    raw_value=time_waited,
                    display_value=f'{total_waits:,}회  /  {time_waited:,} cs',
                    severity=severity,
                    suggestion=_WAIT_CLASS_SUGGESTION.get(wait_class, ''),
                ))
            return results
        except oracledb.Error as e:
            error_obj, = e.args
            raise PermissionError(
                f"V$SESSION_WAIT 조회 권한이 없습니다 (ORA-{error_obj.code:05d}).\n"
                f"DBA에게 'GRANT SELECT ON V$SESSION_WAIT TO <user>' 권한을 요청하세요."
            )
        finally:
            cursor.close()

    def _get_vsql_resource_metrics(self, sql_keyword: str) -> list['ResourceMetric']:
        """V$SQL에서 가장 최근 실행 통계를 조회한다."""
        keyword = '%' + sql_keyword.strip()[:80] + '%'
        cursor = self._connection.cursor()
        try:
            cursor.execute("""
                SELECT BUFFER_GETS, DISK_READS,
                       ELAPSED_TIME / 1000 AS ELAPSED_MS,
                       CPU_TIME / 1000 AS CPU_MS,
                       ROWS_PROCESSED
                FROM (
                    SELECT BUFFER_GETS, DISK_READS, ELAPSED_TIME,
                           CPU_TIME, ROWS_PROCESSED
                    FROM V$SQL
                    WHERE SQL_TEXT LIKE :kw
                      AND SQL_TEXT NOT LIKE 'EXPLAIN PLAN%'
                    ORDER BY ELAPSED_TIME DESC
                )
                WHERE ROWNUM = 1
            """, kw=keyword)
            row = cursor.fetchone()
            if not row:
                raise ValueError('V$SQL에서 해당 SQL의 실행 이력을 찾을 수 없습니다')

            buffer_gets    = row[0] or 0
            disk_reads     = row[1] or 0
            elapsed_ms     = row[2] or 0.0
            cpu_ms         = row[3] or 0.0
            rows_processed = row[4] or 0

            if disk_reads > 1000:
                disk_sev = 'HIGH'
                disk_sugg = '물리적 디스크 읽기가 매우 많습니다. 인덱스를 추가하거나 Buffer Cache 크기를 검토하세요.'
            elif disk_reads > 100:
                disk_sev = 'MEDIUM'
                disk_sugg = '디스크 읽기가 다소 발생합니다. 인덱스 효율을 확인하세요.'
            else:
                disk_sev = 'LOW'
                disk_sugg = ''

            buf_sev  = 'MEDIUM' if buffer_gets > 100_000 else 'INFO'
            buf_sugg = '논리적 읽기가 매우 많습니다. 인덱스 효율을 높이거나 결과셋을 줄이세요.' if buf_sev == 'MEDIUM' else ''

            return [
                ResourceMetric('DISK_READS',     'I/O 통계',
                               disk_reads,    f'{disk_reads:,}',
                               disk_sev,  disk_sugg),
                ResourceMetric('BUFFER_GETS',    'I/O 통계',
                               buffer_gets,   f'{buffer_gets:,}',
                               buf_sev,   buf_sugg),
                ResourceMetric('ELAPSED_TIME',   '실행 시간',
                               int(elapsed_ms), f'{elapsed_ms:,.1f} ms',
                               'INFO', ''),
                ResourceMetric('CPU_TIME',        '실행 시간',
                               int(cpu_ms),     f'{cpu_ms:,.1f} ms',
                               'INFO', ''),
                ResourceMetric('ROWS_PROCESSED', '실행 결과',
                               rows_processed,  f'{rows_processed:,}',
                               'INFO', ''),
            ]
        except oracledb.Error as e:
            error_obj, = e.args
            raise ValueError(f'V$SQL 조회 실패 (ORA-{error_obj.code:05d})')
        finally:
            cursor.close()

    def _get_mystat_diff_metrics(self) -> list['ResourceMetric']:
        """explain_plan() 전후의 V$MYSTAT 차이로 세션 I/O 통계를 반환한다."""
        after = self._snapshot_mystat()
        if not after:
            raise RuntimeError('V$MYSTAT 조회에 실패했습니다')

        pre = self._pre_analysis_mystat or {}

        stat_cfg = {
            'physical reads': {
                'category': '세션 통계',
                'hi': 1000, 'med': 100,
                'sugg_hi':  '물리적 디스크 읽기가 많습니다. 인덱스 추가 또는 Buffer Cache 확장을 검토하세요.',
                'sugg_med': '디스크 읽기가 다소 발생합니다. 인덱스 효율을 확인하세요.',
            },
            'session logical reads': {
                'category': '세션 통계',
                'hi': 100_000, 'med': 10_000,
                'sugg_hi':  '논리적 읽기가 매우 많습니다. 실행 계획 및 인덱스를 검토하세요.',
                'sugg_med': '논리적 읽기가 다소 많습니다.',
            },
            'redo size': {
                'category': '세션 통계',
                'hi': 1_000_000, 'med': 100_000,
                'sugg_hi':  'Redo 생성량이 많습니다. DML 배치 최적화를 검토하세요.',
                'sugg_med': '',
            },
        }

        metrics = []
        for stat_name, cfg in stat_cfg.items():
            delta = max(0, after.get(stat_name, 0) - pre.get(stat_name, 0))
            if delta > cfg['hi']:
                sev, sugg = 'HIGH',   cfg['sugg_hi']
            elif delta > cfg['med']:
                sev, sugg = 'MEDIUM', cfg['sugg_med']
            else:
                sev, sugg = 'INFO',   ''
            metrics.append(ResourceMetric(
                name=stat_name,
                category=cfg['category'],
                raw_value=delta,
                display_value=f'{delta:,}',
                severity=sev,
                suggestion=sugg,
            ))
        return metrics

    # ------------------------------------------------------------------
    # SQL 직접 실행
    # ------------------------------------------------------------------

    def execute_sql(
        self, sql: str, max_rows: int = 500, bind_vars: dict | None = None
    ) -> tuple[list[str], list[tuple], float]:
        """
        SELECT SQL을 직접 실행하고 결과를 반환합니다.
        SELECT 가 아닌 문장은 거부합니다.

        bind_vars: SQL의 :변수명에 대응하는 값 딕셔너리.
                   oracledb 네이티브 바인드로 전달됩니다.
        반환값: (컬럼명 리스트, 행 리스트, 소요시간_ms, sql_id)
        """
        self._ensure_connected()

        normalized = sql.strip().upper()
        if not normalized.startswith('SELECT') and not normalized.startswith('WITH'):
            raise ValueError(
                "실제 실행 모드는 SELECT / WITH 문만 지원합니다.\n"
                "UPDATE · DELETE · INSERT · DDL 등은 실행할 수 없습니다."
            )

        import time
        cursor = self._connection.cursor()
        try:
            t0 = time.perf_counter()
            if bind_vars:
                cursor.execute(sql, bind_vars)
            else:
                cursor.execute(sql)
            columns = [desc[0] for desc in cursor.description]
            rows = cursor.fetchmany(max_rows)
            elapsed_ms = (time.perf_counter() - t0) * 1000

            # 원본 SQL 기준 SQL_ID 조회 (V$SQL 통계 탭에서 사용)
            sql_id = self._get_last_sql_id(sql)

            return columns, rows, elapsed_ms, sql_id
        except oracledb.Error as e:
            error_obj, = e.args
            raise ValueError(
                f"SQL 실행 오류\n"
                f"오류코드: {error_obj.code}\n"
                f"메시지: {error_obj.message}"
            )
        finally:
            cursor.close()

    def execute_with_gather_stats(
        self, sql: str, bind_vars: dict | None = None
    ) -> tuple[str, str]:
        """
        GATHER_PLAN_STATISTICS 힌트를 주입하여 내부 실행 후 DISPLAY_CURSOR 텍스트를 반환합니다.
        실제 플랜 탭 표시 전용이며 결과 행은 버립니다.
        SELECT / WITH 문만 처리하며, 그 외는 안내 문자열을 반환합니다.

        방식:
          1. 힌트 SQL에 UUID 기반 유일 태그 주석을 추가
          2. 실행 후 UUID 태그로 V$SQL에서 sql_id를 정확히 조회 (1순위)
             → python-oracledb statement cache 영향 없음 (UUID로 매번 유일한 SQL 텍스트)
          2'. V$SQL 권한 없으면 V$SESSION.PREV_SQL_ID 조회 (폴백)
          3. DISPLAY_CURSOR(sql_id)로 명시 지정

        Returns: (hint_sql_id, cursor_plan_text)
        """
        self._ensure_connected()

        normalized = sql.strip().upper()
        if not normalized.startswith('SELECT') and not normalized.startswith('WITH'):
            return ('', '(실제 플랜: SELECT / WITH 문만 지원합니다)')

        import uuid
        hint_sql = self._inject_gather_stats_hint(sql)

        # V$SQL에서 이 실행을 유일하게 식별하기 위한 태그 주석 삽입
        # V$SQL.SQL_TEXT는 최대 1000자 → 태그를 SQL 앞에 붙여 항상 포함되도록 함
        tag = uuid.uuid4().hex[:12]           # 예: 'a1b2c3d4e5f6'
        tagged_sql = f'/* SQLT:{tag} */ {hint_sql}'

        # Step 1: 태그된 힌트 SQL 실행
        exec_cursor = self._connection.cursor()
        try:
            if bind_vars:
                exec_cursor.execute(tagged_sql, bind_vars)
            else:
                exec_cursor.execute(tagged_sql)
            exec_cursor.arraysize = 1000      # 청크 크기 제한 (메모리 부하 방지)
            exec_cursor.fetchall()            # 전체 fetch → 모든 plan node 통계 확정
        except Exception as e:
            exec_cursor.close()
            return ('', f'[실제 플랜 내부 실행 오류]\n{e}')
        exec_cursor.close()

        # Step 2: sql_id / child_number 조회
        # 1순위: UUID 태그로 V$SQL 텍스트 검색 (statement cache 영향 없음 — UUID로 유일)
        # 폴백: V$SQL 권한 없으면 V$SESSION.PREV_SQL_ID 조회
        hint_sql_id = ''
        hint_child_no = 0
        try:
            id_cursor = self._connection.cursor()
            id_cursor.execute("""
                SELECT SQL_ID, CHILD_NUMBER
                FROM (
                    SELECT SQL_ID, CHILD_NUMBER
                    FROM V$SQL
                    WHERE SQL_TEXT LIKE :kw
                    ORDER BY LAST_ACTIVE_TIME DESC
                )
                WHERE ROWNUM = 1
            """, kw=f'%SQLT:{tag}%')
            row = id_cursor.fetchone()
            id_cursor.close()
            if row:
                hint_sql_id = row[0] or ''
                hint_child_no = row[1] or 0
        except Exception:
            # V$SQL 권한 없음 → V$SESSION.PREV_SQL_ID 조회 (폴백)
            try:
                id_cursor = self._connection.cursor()
                id_cursor.execute("""
                    SELECT PREV_SQL_ID, PREV_CHILD_NUMBER
                    FROM V$SESSION
                    WHERE SID = SYS_CONTEXT('USERENV', 'SID')
                """)
                row = id_cursor.fetchone()
                id_cursor.close()
                if row:
                    hint_sql_id = row[0] or ''
                    hint_child_no = row[1] or 0
            except Exception:
                pass  # 두 방법 모두 실패 시 DISPLAY_CURSOR(NULL) 폴백

        # Step 3: sql_id로 DISPLAY_CURSOR 명시 호출
        plan_cursor = self._connection.cursor()
        try:
            if hint_sql_id:
                plan_cursor.execute(
                    "SELECT * FROM TABLE("
                    "DBMS_XPLAN.DISPLAY_CURSOR(:sid, :child, 'ALLSTATS LAST'))",
                    sid=hint_sql_id,
                    child=hint_child_no,
                )
            else:
                # sql_id를 못 찾은 경우만 NULL 폴백
                plan_cursor.execute(
                    "SELECT * FROM TABLE("
                    "DBMS_XPLAN.DISPLAY_CURSOR(NULL, NULL, 'ALLSTATS LAST'))"
                )
            lines = [row[0] for row in plan_cursor.fetchall()]
            if not lines:
                plan_text = (
                    '(실제 실행 계획 없음 — SQL이 공유 풀에서 제거되었거나 '
                    'GATHER_PLAN_STATISTICS 통계가 수집되지 않았습니다)'
                )
            else:
                plan_text = '\n'.join(lines)
        except Exception as e:
            msg = str(e)
            if 'ORA-00942' in msg or 'insufficient privilege' in msg.lower():
                plan_text = (
                    '[권한 없음] DISPLAY_CURSOR를 조회하려면 아래 권한이 필요합니다.\n'
                    '  GRANT SELECT ON V_$SQL TO <계정>;\n'
                    '  GRANT SELECT ON V_$SQL_PLAN_STATISTICS_ALL TO <계정>;\n\n'
                    f'원본 오류: {msg}'
                )
            else:
                plan_text = f'[DISPLAY_CURSOR 오류]\n{msg}'
        finally:
            plan_cursor.close()

        return (hint_sql_id, plan_text)

    def _get_last_sql_id(self, sql_text: str) -> str:
        """
        방금 실행한 SQL의 SQL_ID를 V$SQL에서 조회합니다.
        힌트 주입 등으로 텍스트가 달라진 경우에도 정확히 찾아냅니다.
        조회 실패 시 빈 문자열 반환.

        - FETCH FIRST 대신 ROWNUM 사용 (Oracle 11g 호환)
        - EXPLAIN PLAN 래퍼 명시적 제외
        """
        cursor = self._connection.cursor()
        try:
            # SQL_TEXT는 최대 1000자만 저장되므로 앞 200자로 매칭
            prefix = sql_text.strip()[:200]
            cursor.execute("""
                SELECT SQL_ID
                FROM (
                    SELECT SQL_ID
                    FROM V$SQL
                    WHERE SQL_TEXT LIKE :kw
                      AND SQL_TEXT NOT LIKE 'EXPLAIN PLAN%'
                    ORDER BY LAST_ACTIVE_TIME DESC
                )
                WHERE ROWNUM = 1
            """, kw=prefix + '%')
            row = cursor.fetchone()
            return row[0] if row else ''
        except Exception:
            return ''
        finally:
            cursor.close()

    def get_table_stats(self, table_name: str, schema: str = None) -> dict | None:
        """
        테이블 통계 정보를 조회합니다.

        Parameters
        ----------
        table_name : str
            조회할 테이블명 (대소문자 무관)
        schema : str, optional
            테이블 소유자(스키마). None 이면 ALL_TABLES 에서 검색.

        Returns
        -------
        dict | None
            {
              "table_name": str,
              "num_rows": int | None,
              "blocks": int | None,
              "last_analyzed": datetime | None,
              "stale_stats": bool,          # STALE_STATS = 'YES'
              "days_since_analyzed": int | None
            }
            통계 행이 없으면 None 반환.
        """
        self._ensure_connected()
        cursor = self._connection.cursor()

        params: dict = {'tname': table_name.upper()}
        owner_filter = "AND OWNER = :schema" if schema else ""
        if schema:
            params['schema'] = schema.upper()

        try:
            cursor.execute(f"""
                SELECT
                    TABLE_NAME,
                    NUM_ROWS,
                    BLOCKS,
                    LAST_ANALYZED,
                    STALE_STATS
                FROM ALL_TABLES
                WHERE TABLE_NAME = :tname
                  {owner_filter}
                FETCH FIRST 1 ROWS ONLY
            """, **params)
            row = cursor.fetchone()
        except oracledb.Error:
            return None
        finally:
            cursor.close()

        if row is None:
            return None

        tbl_name, num_rows, blocks, last_analyzed, stale_stats_raw = row
        stale_stats: bool = (stale_stats_raw == 'YES')

        days_since: int | None = None
        if last_analyzed is not None:
            if isinstance(last_analyzed, datetime):
                la = last_analyzed
            else:
                la = datetime(
                    last_analyzed.year, last_analyzed.month, last_analyzed.day
                )
            days_since = (datetime.now() - la.replace(tzinfo=None)).days

        return {
            "table_name": tbl_name,
            "num_rows": num_rows,
            "blocks": blocks,
            "last_analyzed": last_analyzed,
            "stale_stats": stale_stats,
            "days_since_analyzed": days_since,
        }

    # ------------------------------------------------------------------ #
    #  STEP 5 – Index Advisor 지원 메서드                                   #
    # ------------------------------------------------------------------ #

    def get_table_indexes(self, table_name: str, schema: str = None) -> list[dict]:
        """
        테이블의 인덱스 목록과 컬럼 정보를 조회합니다.

        Parameters
        ----------
        table_name : str
            조회할 테이블명 (대소문자 무관)
        schema : str, optional
            테이블 소유자(스키마). None 이면 ALL_INDEXES 에서 검색.

        Returns
        -------
        list[dict]
            [
              {
                "index_name": "PK_ORDERS",
                "uniqueness": "UNIQUE",   # "UNIQUE" | "NONUNIQUE"
                "columns": ["ORDER_ID"],  # 컬럼 포지션 순서
                "status": "VALID"         # "VALID" | "UNUSABLE" | ...
              }, ...
            ]
        """
        self._ensure_connected()
        cursor = self._connection.cursor()

        params: dict = {'tname': table_name.upper()}
        owner_filter = "AND ai.OWNER = :schema" if schema else ""
        if schema:
            params['schema'] = schema.upper()

        try:
            cursor.execute(f"""
                SELECT
                    ai.INDEX_NAME,
                    ai.UNIQUENESS,
                    aic.COLUMN_NAME,
                    aic.COLUMN_POSITION,
                    ai.STATUS
                FROM ALL_INDEXES ai
                JOIN ALL_IND_COLUMNS aic
                  ON aic.INDEX_NAME  = ai.INDEX_NAME
                 AND aic.TABLE_OWNER = ai.OWNER
                 AND aic.TABLE_NAME  = ai.TABLE_NAME
                WHERE ai.TABLE_NAME = :tname
                  {owner_filter}
                ORDER BY ai.INDEX_NAME, aic.COLUMN_POSITION
            """, **params)

            rows = cursor.fetchall()
        except oracledb.Error:
            return []
        finally:
            cursor.close()

        # 인덱스별로 컬럼 목록을 집계
        index_map: dict[str, dict] = {}
        for index_name, uniqueness, col_name, _col_pos, status in rows:
            if index_name not in index_map:
                index_map[index_name] = {
                    "index_name": index_name,
                    "uniqueness": uniqueness,
                    "columns": [],
                    "status": status,
                }
            index_map[index_name]["columns"].append(col_name)

        return list(index_map.values())

    def get_column_stats(self, table_name: str, schema: str = None) -> list[dict]:
        """
        테이블의 컬럼별 통계 정보를 조회합니다.

        Parameters
        ----------
        table_name : str
            조회할 테이블명 (대소문자 무관)
        schema : str, optional
            테이블 소유자(스키마). None 이면 ALL_TAB_COLUMNS 에서 검색.

        Returns
        -------
        list[dict]
            [
              {
                "column_name": str,
                "num_distinct": int | None,
                "num_nulls": int | None,
                "density": float | None,
                "last_analyzed": datetime | None
              }, ...
            ]
            컬럼 순서(COLUMN_ID) 기준 정렬.
        """
        self._ensure_connected()
        cursor = self._connection.cursor()

        params: dict = {'tname': table_name.upper()}
        owner_filter = "AND OWNER = :schema" if schema else ""
        if schema:
            params['schema'] = schema.upper()

        try:
            cursor.execute(f"""
                SELECT
                    COLUMN_NAME,
                    NUM_DISTINCT,
                    NUM_NULLS,
                    DENSITY,
                    LAST_ANALYZED
                FROM ALL_TAB_COLUMNS
                WHERE TABLE_NAME = :tname
                  {owner_filter}
                ORDER BY COLUMN_ID
            """, **params)
            rows = cursor.fetchall()
        except oracledb.Error:
            return []
        finally:
            cursor.close()

        result: list[dict] = []
        for col_name, num_distinct, num_nulls, density, last_analyzed in rows:
            result.append({
                "column_name": col_name,
                "num_distinct": num_distinct,
                "num_nulls": num_nulls,
                "density": float(density) if density is not None else None,
                "last_analyzed": last_analyzed,
            })
        return result

    def get_tables_from_sql(self, sql: str) -> list[str]:
        """
        SQL 텍스트에서 FROM / JOIN 절에 사용된 테이블명을 추출합니다.

        sqlglot AST 파싱을 사용하며, 파싱 실패 시 빈 리스트를 반환합니다.

        Parameters
        ----------
        sql : str
            분석할 SQL 텍스트

        Returns
        -------
        list[str]
            대문자 테이블명 목록 (중복 제거, 서브쿼리 인라인 뷰 별칭 제외)
        """
        try:
            import sqlglot
            from sqlglot import exp
        except ImportError:
            return []

        tables: list[str] = []
        try:
            statements = sqlglot.parse(sql, error_level=sqlglot.ErrorLevel.IGNORE)
            for statement in statements:
                if statement is None:
                    continue
                for table_node in statement.find_all(exp.Table):
                    # 서브쿼리(인라인 뷰)가 아닌 실제 테이블만 수집
                    if isinstance(table_node.parent, exp.Subquery):
                        continue
                    name = table_node.name
                    if name:
                        tables.append(name.upper())
        except Exception:
            return []

        # 순서 유지하면서 중복 제거
        seen: set[str] = set()
        result: list[str] = []
        for t in tables:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result

    # ------------------------------------------------------------------ #
    #  STEP 6 – 통계 수집 권한 확인 / DBMS_STATS 실행                        #
    # ------------------------------------------------------------------ #

    def check_stats_privilege(self) -> bool:
        """
        현재 세션이 DBMS_STATS를 직접 실행할 수 있는 권한을 보유하는지 확인합니다.

        SESSION_PRIVS에서 ANALYZE ANY 또는 DBA 권한이 있으면 True를 반환합니다.
        조회 실패(권한 뷰 접근 불가 등) 시 안전하게 False를 반환합니다.
        """
        self._ensure_connected()
        cursor = self._connection.cursor()
        try:
            cursor.execute("""
                SELECT COUNT(*)
                FROM SESSION_PRIVS
                WHERE PRIVILEGE IN ('ANALYZE ANY', 'DBA')
            """)
            row = cursor.fetchone()
            return (row[0] or 0) > 0
        except Exception:
            return False
        finally:
            cursor.close()

    def execute_stats_collection(self, table_names: list) -> tuple:
        """
        테이블 목록에 대해 DBMS_STATS.GATHER_TABLE_STATS를 순차적으로 실행합니다.

        OWNNAME에 USER Oracle 함수를 사용하여 현재 세션의 스키마 기준으로 수집합니다.
        CASCADE => TRUE 로 인덱스 통계도 함께 수집합니다.

        Returns
        -------
        (success: bool, message: str)
        """
        self._ensure_connected()
        if not table_names:
            return False, '수집 대상 테이블이 없습니다.'

        cursor = self._connection.cursor()
        try:
            for table_name in table_names:
                cursor.execute(
                    f"BEGIN DBMS_STATS.GATHER_TABLE_STATS("
                    f"OWNNAME => USER, "
                    f"TABNAME => '{table_name.upper()}', "
                    f"CASCADE => TRUE); END;"
                )
            self._connection.commit()
            return True, f'{len(table_names)}개 테이블 통계 수집 완료'
        except oracledb.Error as e:
            error_obj, = e.args
            return False, f'통계 수집 실패 (ORA-{error_obj.code:05d}): {error_obj.message}'
        except Exception as e:
            return False, str(e)
        finally:
            cursor.close()
