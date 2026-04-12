# 실제 플랜(DISPLAY_CURSOR) 관련 코드 위치 정리

> 조사 일자: 2026-04-12  
> 수정 없이 현황 파악만 목적

---

## 파일별 관련 코드 위치

---

### 1. `v2/core/db/oracle_client.py`

| 메서드/블록 | 시작 라인 | 설명 |
|---|---|---|
| `_inject_gather_stats_hint(sql)` | 266 | GATHER_PLAN_STATISTICS 힌트를 SQL에 주입하는 정적 메서드 |
| `get_cursor_plan(sql_id)` | 313 | sql_id를 직접 지정해 DISPLAY_CURSOR 조회 (구형 단순 버전) |
| `execute_with_gather_stats(sql, bind_vars)` | 794 | 힌트 주입 → 내부 실행 → V$SQL에서 sql_id 조회 → DISPLAY_CURSOR 호출. 실제 플랜 탭 표시 전용 |

**`execute_with_gather_stats` 내부 단계별 위치:**

| 단계 | 라인 | 내용 |
|---|---|---|
| Step 1: 힌트 SQL 실행 | 826~837 | UUID 태그 주석 삽입 후 tagged_sql 실행 |
| Step 2: V$SQL에서 sql_id 조회 | 839~860 | 태그로 V$SQL 검색, sql_id / child_number 취득 |
| Step 3: DISPLAY_CURSOR 호출 | 862~900 | sql_id 지정 DISPLAY_CURSOR 또는 NULL 폴백 |

---

### 2. `v2/ui/workers/cursor_plan_worker.py`

| 클래스/메서드 | 시작 라인 | 설명 |
|---|---|---|
| `CursorPlanWorker(QThread)` | 17 | 실제 플랜 조회 전용 백그라운드 워커 클래스 |
| `CursorPlanWorker.__init__` | 20 | client, sql, bind_vars 수신 |
| `CursorPlanWorker.run` | 31 | `execute_with_gather_stats` 호출 → `finished` 시그널 발신 |

---

### 3. `v2/ui/widgets/cursor_plan_tab.py`

| 클래스/함수 | 시작 라인 | 설명 |
|---|---|---|
| `_make_pane(title, placeholder)` | 26 | 레이블 + QPlainTextEdit 패널 생성 헬퍼 |
| `CursorPlanTab(QWidget)` | 47 | 예상 플랜(좌) / 실제 플랜(우) 비교 탭 위젯 |
| `CursorPlanTab._build_ui` | 54 | QSplitter로 좌우 분할 UI 구성. 실제 플랜 패널 제목: `'실제 플랜  (DBMS_XPLAN.DISPLAY_CURSOR)'` (65번 라인) |
| `CursorPlanTab.set_estimated` | 76 | 예상 플랜(EXPLAIN PLAN) 텍스트 설정 |
| `CursorPlanTab.populate_actual` | 80 | 실제 플랜(DISPLAY_CURSOR) 텍스트 설정 |
| `CursorPlanTab.clear` | 84 | 좌우 패널 초기화 |

---

### 4. `v2/ui/main_window.py`

| 메서드/코드 블록 | 라인 | 설명 |
|---|---|---|
| `CursorPlanWorker` import | 36 | |
| `CursorPlanTab` import | 44 | |
| `self._cursor_plan_worker` 멤버 선언 | 62 | `None`으로 초기화 |
| `self._cursor_plan_tab = CursorPlanTab()` 생성 | 126 | |
| 탭 추가 `'실제 플랜'` | 140 | `self._tabs.addTab(self._cursor_plan_tab, '실제 플랜')` |
| `_clear_results` — `cursor_plan_tab.clear()` 호출 | 334 | 분석 시작 시 탭 초기화 |
| `_on_analysis_done` — `set_estimated` 호출 | 354 | 분석 완료 후 예상 플랜 텍스트 세팅 |
| `_on_analysis_done` — `_fetch_actual_plan` 호출 | 397 | 분석 완료 직후 실제 플랜 비동기 조회 시작 |
| `_on_execute_done` — `_fetch_actual_plan` 호출 | 453 | SQL 직접 실행 완료 후 실제 플랜 비동기 조회 시작 |
| `_fetch_actual_plan(sql, bind_vars)` | 459 | `CursorPlanWorker` 생성 및 시작. `finished` 시그널을 `populate_actual`에 연결 |

---

## 흐름 요약

```
[분석 실행 or SQL 직접 실행]
        │
        ▼
main_window._fetch_actual_plan()          ← L459
        │
        ▼
CursorPlanWorker.run()                    ← cursor_plan_worker.py L31
        │
        ▼
OracleClient.execute_with_gather_stats()  ← oracle_client.py L794
  ├─ _inject_gather_stats_hint()          ← oracle_client.py L266
  ├─ Step1: 힌트 SQL 실행                  ← oracle_client.py L826
  ├─ Step2: V$SQL → sql_id 조회           ← oracle_client.py L839
  └─ Step3: DISPLAY_CURSOR 호출           ← oracle_client.py L862
        │
        ▼
CursorPlanTab.populate_actual()           ← cursor_plan_tab.py L80
```

---

## 참고: `get_cursor_plan` 구형 메서드

- 위치: `oracle_client.py` L313
- 현재 `CursorPlanWorker`에서는 **사용하지 않음** (execute_with_gather_stats 사용)
- sql_id를 직접 전달받아 단순 DISPLAY_CURSOR 조회만 수행
- 외부 호출 여부 추가 확인 필요
