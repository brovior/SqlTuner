"""
EXPLAIN PLAN 및 실제 실행 계획(DISPLAY_CURSOR) 조회 모듈
ORA-00938 등 회사 환경 이슈 디버깅 대상 코드를 분리
"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from .models import PlanRow


class PlanExecutor:
    """
    EXPLAIN PLAN / GATHER_PLAN_STATISTICS 실행을 담당합니다.
    OracleClient.connect() 후 connection 객체를 받아 생성됩니다.
    """

    def __init__(self, connection, oracledb_module):
        self._connection = connection
        self._oracledb = oracledb_module
        # explain_plan() 호출 직전에 저장하는 V$MYSTAT 스냅샷 (리소스 분석 3순위 폴백용)
        self._pre_analysis_mystat: dict[str, int] = {}

    @property
    def pre_analysis_mystat(self) -> dict[str, int]:
        return self._pre_analysis_mystat

    # ------------------------------------------------------------------
    # 내부 유틸
    # ------------------------------------------------------------------

    def snapshot_mystat(self) -> dict[str, int]:
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

        m = re.match(r'(\s*/\*\+)(.*?)(\*/)', after_select, re.DOTALL)
        if m:
            new_block = m.group(1) + m.group(2) + ' GATHER_PLAN_STATISTICS ' + m.group(3)
            return sql[:target_pos + 6] + new_block + after_select[m.end():]

        return sql[:target_pos + 6] + ' /*+ GATHER_PLAN_STATISTICS */' + after_select

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
        # V$MYSTAT 3순위 폴백을 위해 분석 직전 세션 통계 스냅샷 저장
        self._pre_analysis_mystat = self.snapshot_mystat()
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
            cursor.execute(f"""
                SELECT PLAN_TABLE_OUTPUT
                FROM TABLE(DBMS_XPLAN.DISPLAY(
                    'PLAN_TABLE', '{statement_id}', 'ALL'
                ))
            """)
            xplan_lines = [row[0] for row in cursor.fetchall()]

            self._connection.rollback()
            return rows, '\n'.join(xplan_lines)

        except self._oracledb.Error as e:
            self._connection.rollback()
            error_obj, = e.args
            code = error_obj.code
            message = error_obj.message

            # ORA-00938: 함수의 인수가 충분하지 않습니다
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
    # 실제 실행 계획 (DISPLAY_CURSOR)
    # ------------------------------------------------------------------

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
          2'. V$SQL 권한 없으면 V$SESSION.PREV_SQL_ID 조회 (폴백)
          3. DISPLAY_CURSOR(sql_id)로 명시 지정

        Returns: (hint_sql_id, cursor_plan_text)
        """
        normalized = sql.strip().upper()
        if not normalized.startswith('SELECT') and not normalized.startswith('WITH'):
            return ('', '(실제 플랜: SELECT / WITH 문만 지원합니다)')

        import uuid
        hint_sql = self._inject_gather_stats_hint(sql)

        tag = uuid.uuid4().hex[:12]
        tagged_sql = f'/* SQLT:{tag} */ {hint_sql}'

        # Step 1: 태그된 힌트 SQL 실행
        exec_cursor = self._connection.cursor()
        try:
            if bind_vars:
                exec_cursor.execute(tagged_sql, bind_vars)
            else:
                exec_cursor.execute(tagged_sql)
            exec_cursor.arraysize = 1000
            exec_cursor.fetchall()
        except Exception as e:
            exec_cursor.close()
            return ('', f'[실제 플랜 내부 실행 오류]\n{e}')
        exec_cursor.close()

        # Step 2: sql_id / child_number 조회
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
                pass

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
        조회 실패 시 빈 문자열 반환.
        """
        cursor = self._connection.cursor()
        try:
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
