"""
SQL 유틸리티

공통 SQL 조작 함수를 제공합니다.
"""
from __future__ import annotations

import re


def inject_hint(sql: str, hint: str) -> str:
    """
    SELECT 문에 Oracle 힌트를 주입합니다.

    규칙:
      ① SELECT + 기존 힌트 블록 없음  → SELECT /*+ hint */
      ② SELECT + 기존 힌트 블록 있음  → SELECT /*+ 기존힌트 hint */
      ③ 앞뒤 공백/개행은 strip 후 처리
      ④ SELECT / WITH 이외 구문은 원본 그대로 반환

    Args:
        sql:  원본 SQL 문자열
        hint: 주입할 힌트 텍스트 (예: 'GATHER_PLAN_STATISTICS')

    Returns:
        힌트가 주입된 SQL 문자열
    """
    stripped = sql.strip()

    upper = stripped.upper()
    if not (upper.startswith('SELECT') or upper.startswith('WITH')):
        return sql

    # SELECT 키워드 직후 위치를 찾는다 (대소문자 무관)
    m_select = re.match(r'(SELECT)', stripped, re.IGNORECASE)
    if not m_select:
        return sql

    after_select = stripped[m_select.end():]   # SELECT 다음 문자열

    # 기존 힌트 블록 /*+ ... */ 이 SELECT 바로 뒤(공백 허용)에 있는지 확인
    m_hint = re.match(r'(\s*/\*\+)(.*?)(\*/)', after_select, re.DOTALL)
    if m_hint:
        # ② 기존 힌트 블록 안에 추가
        existing_body = m_hint.group(2).rstrip()
        new_block = f'{m_hint.group(1)}{existing_body} {hint}{m_hint.group(3)}'
        return stripped[:m_select.end()] + new_block + after_select[m_hint.end():]

    # ① 힌트 블록 없음 — SELECT 직후에 새 블록 삽입
    return stripped[:m_select.end()] + f' /*+ {hint} */' + after_select
