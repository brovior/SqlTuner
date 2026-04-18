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
from datetime import datetime
from typing import Optional

from .models import (
    ConnectionInfo,
    PlanRow,
    SqlStats,
    ResourceMetric,
    ResourceAnalysis,
    WAIT_CLASS_SEVERITY,
    WAIT_CLASS_SUGGESTION,
)
from .plan_executor import PlanExecutor

# 기존 import 경로 호환성 유지 (다른 파일 수정 불필요)
__all__ = [
    'ORACLEDB_AVAILABLE', '_ORACLEDB_IMPORT_ERROR',
    'ConnectionInfo', 'PlanRow', 'SqlStats',
    'ResourceMetric', 'ResourceAnalysis',
    'OracleClient',
]


class OracleClient:
    def __init__(self):
        self._connection = None
        self._conn_info: Optional[ConnectionInfo] = None
        self._thick_initialized = False
        self._thin_mode = False
        self._plan_executor: Optional[PlanExecutor] = None

    @property
    def connection_mode(self) -> str:
        if not self.is_connected:
            return '미연결'
        return 'Thin' if self._thin_mode else 'Thick'

    def _try_init_thick_mode(self) -> str | None:
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
        Thick 모드를 먼저 시도하고, 실패 시 Thin 모드로 자동 전환합니다.
        """
        if not ORACLEDB_AVAILABLE:
            detail = f'\n\n[import 오류] {_ORACLEDB_IMPORT_ERROR}' if _ORACLEDB_IMPORT_ERROR else ''
            raise RuntimeError(f"oracledb 패키지를 로드할 수 없습니다.{detail}")

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
                self._plan_executor = PlanExecutor(self._connection, oracledb)
                return
            except oracledb.Error as e:
                error_obj, = e.args
                raise ConnectionError(
                    f"DB 연결 실패 [{conn_info.tns_alias}]\n"
                    f"오류코드: {error_obj.code}\n"
                    f"메시지: {error_obj.message}"
                )

        # 2차: Thin 모드 폴백 (DPI-1047: 32bit/64bit 불일치, Oracle Client 미설치 등)
        try:
            self._connection = oracledb.connect(
                user=conn_info.username,
                password=conn_info.password,
                dsn=conn_info.tns_alias,
                config_dir=tns_dir,
            )
            self._conn_info = conn_info
            self._thin_mode = True
            self._plan_executor = PlanExecutor(self._connection, oracledb)
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
            self._plan_executor = None

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
    # DB 버전 / 스키마
    # ------------------------------------------------------------------

    def get_db_version(self) -> tuple[str, str]:
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
        import re
        m = re.search(r'Oracle\s+(?:Database\s+)?(\d+)([cg])', banner, re.IGNORECASE)
        if m:
            return f"Oracle {m.group(1)}{m.group(2).lower()}"
        m2 = re.search(r'Release\s+(\d+\.\d+)', banner)
        if m2:
            return f"Oracle {m2.group(1)}"
        return 'Oracle (버전 미상)'

    def get_current_user_schema(self) -> tuple[str, str]:
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
    # EXPLAIN PLAN (PlanExecutor에 위임)
    # ------------------------------------------------------------------

    def explain_plan(
        self, sql: str, bind_vars: dict | None = None
    ) -> tuple[list[PlanRow], str]:
        self._ensure_connected()
        return self._plan_executor.explain_plan(sql, bind_vars)

    def execute_with_gather_stats(
        self, sql: str, bind_vars: dict | None = None
    ) -> tuple[str, str]:
        self._ensure_connected()
        return self._plan_executor.execute_with_gather_stats(sql, bind_vars)

    # ------------------------------------------------------------------
    # V$SQL 실행 통계
    # ------------------------------------------------------------------

    def get_sql_stats(
        self, sql_keyword: str, sql_id: str = ''
    ) -> list[SqlStats]:
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

    def get_resource_analysis(self, sql_keyword: str = '') -> ResourceAnalysis:
        """
        SQL 실행 리소스를 아래 우선순위로 조회하여 ResourceAnalysis를 반환합니다.

          1순위: V$SESSION_WAIT  — 실시간 세션 대기 이벤트
          2순위: V$SQL 통계      — 실행 이력의 I/O·시간 통계
          3순위: V$MYSTAT 차이   — explain_plan() 전후 세션 통계 차이
        """
        self._ensure_connected()
        errors: list[str] = []

        try:
            metrics = self._get_session_wait_metrics()
            return ResourceAnalysis(method='V$SESSION_WAIT 기준', metrics=metrics)
        except Exception as e:
            errors.append(f'V$SESSION_WAIT 조회 실패: {e}')

        if sql_keyword.strip():
            try:
                metrics = self._get_vsql_resource_metrics(sql_keyword)
                return ResourceAnalysis(method='V$SQL 통계 기준', metrics=metrics, error_chain=errors)
            except Exception as e:
                errors.append(f'V$SQL 조회 실패: {e}')

        try:
            metrics = self._get_mystat_diff_metrics()
            return ResourceAnalysis(method='V$MYSTAT 차이 기준', metrics=metrics, error_chain=errors)
        except Exception as e:
            errors.append(f'V$MYSTAT 조회 실패: {e}')

        return ResourceAnalysis(method='조회 불가', metrics=[], error_chain=errors)

    def _get_session_wait_metrics(self) -> list[ResourceMetric]:
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
                severity = WAIT_CLASS_SEVERITY.get(wait_class, 'INFO')
                results.append(ResourceMetric(
                    name=row[0] or '',
                    category=wait_class,
                    raw_value=time_waited,
                    display_value=f'{total_waits:,}회  /  {time_waited:,} cs',
                    severity=severity,
                    suggestion=WAIT_CLASS_SUGGESTION.get(wait_class, ''),
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

    def _get_vsql_resource_metrics(self, sql_keyword: str) -> list[ResourceMetric]:
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
                disk_sev  = 'HIGH'
                disk_sugg = '물리적 디스크 읽기가 매우 많습니다. 인덱스를 추가하거나 Buffer Cache 크기를 검토하세요.'
            elif disk_reads > 100:
                disk_sev  = 'MEDIUM'
                disk_sugg = '디스크 읽기가 다소 발생합니다. 인덱스 효율을 확인하세요.'
            else:
                disk_sev  = 'LOW'
                disk_sugg = ''

            buf_sev  = 'MEDIUM' if buffer_gets > 100_000 else 'INFO'
            buf_sugg = '논리적 읽기가 매우 많습니다. 인덱스 효율을 높이거나 결과셋을 줄이세요.' if buf_sev == 'MEDIUM' else ''

            return [
                ResourceMetric('DISK_READS',     'I/O 통계',  disk_reads,    f'{disk_reads:,}',       disk_sev,  disk_sugg),
                ResourceMetric('BUFFER_GETS',    'I/O 통계',  buffer_gets,   f'{buffer_gets:,}',      buf_sev,   buf_sugg),
                ResourceMetric('ELAPSED_TIME',   '실행 시간', int(elapsed_ms), f'{elapsed_ms:,.1f} ms', 'INFO', ''),
                ResourceMetric('CPU_TIME',       '실행 시간', int(cpu_ms),     f'{cpu_ms:,.1f} ms',     'INFO', ''),
                ResourceMetric('ROWS_PROCESSED', '실행 결과', rows_processed,  f'{rows_processed:,}',   'INFO', ''),
            ]
        except oracledb.Error as e:
            error_obj, = e.args
            raise ValueError(f'V$SQL 조회 실패 (ORA-{error_obj.code:05d})')
        finally:
            cursor.close()

    def _get_mystat_diff_metrics(self) -> list[ResourceMetric]:
        """explain_plan() 전후의 V$MYSTAT 차이로 세션 I/O 통계를 반환한다."""
        after = self._plan_executor.snapshot_mystat() if self._plan_executor else {}
        if not after:
            raise RuntimeError('V$MYSTAT 조회에 실패했습니다')

        pre = self._plan_executor.pre_analysis_mystat if self._plan_executor else {}

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

            sql_id = self._plan_executor._get_last_sql_id(sql) if self._plan_executor else ''

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

    # ------------------------------------------------------------------
    # 테이블 / 인덱스 / 컬럼 메타데이터
    # ------------------------------------------------------------------

    def get_table_stats(self, table_name: str, schema: str = None) -> dict | None:
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
                la = datetime(last_analyzed.year, last_analyzed.month, last_analyzed.day)
            days_since = (datetime.now() - la.replace(tzinfo=None)).days

        return {
            "table_name": tbl_name,
            "num_rows": num_rows,
            "blocks": blocks,
            "last_analyzed": last_analyzed,
            "stale_stats": stale_stats,
            "days_since_analyzed": days_since,
        }

    def get_table_indexes(self, table_name: str, schema: str = None) -> list[dict]:
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
                    if isinstance(table_node.parent, exp.Subquery):
                        continue
                    name = table_node.name
                    if name:
                        tables.append(name.upper())
        except Exception:
            return []

        seen: set[str] = set()
        result: list[str] = []
        for t in tables:
            if t not in seen:
                seen.add(t)
                result.append(t)
        return result

    # ------------------------------------------------------------------
    # 통계 수집
    # ------------------------------------------------------------------

    def check_stats_privilege(self) -> bool:
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
