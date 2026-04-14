# SQL Tuner v2 - 아키텍처 및 모듈 상세 설명

---

## v2/core/db/oracle_client.py

Oracle DB와 실제로 통신하는 모듈.

- `OracleClient` 클래스가 핵심
- `connect()` : Thick 모드 우선 시도 → 실패 시 Thin 모드 자동 전환
- `explain_plan(sql, bind_vars)` : EXPLAIN PLAN 실행 후 PlanRow 목록 + DBMS_XPLAN 텍스트 반환
  - `bind_vars` 전달 시 oracledb 네이티브 바인드로 전달 (문자열 치환 없음)
- `execute_sql(sql, max_rows, bind_vars)` : SELECT 실행, 바인드 변수 지원
- `get_sql_stats()` : V$SQL에서 실행 이력 조회
- `get_resource_analysis(sql_keyword)` : 리소스 분석 (3단계 폴백)
  1. V$SESSION_WAIT — 실시간 Wait Event (권한 필요)
  2. V$SQL 통계 — DISK_READS / BUFFER_GETS 등 (V$SQL 권한 + 이전 실행 이력 필요)
  3. V$MYSTAT 차이 — explain_plan() 전후 세션 통계 차이 (항상 사용 가능)
- `get_table_indexes()`, `get_table_stats()` : 인덱스/통계 조회
- `ResourceMetric` 데이터클래스 : name, category, raw_value, display_value, severity, suggestion
- `ResourceAnalysis` 데이터클래스 : method(조회방법 레이블), metrics(list[ResourceMetric]), error_chain

---

## v2/core/db/plan_analyzer.py

가져온 실행 계획에서 성능 문제를 찾는 모듈.

감지하는 문제 7가지:

| 문제 | 심각도 |
|------|--------|
| Full Table Scan | HIGH |
| Cartesian Join | HIGH |
| SORT DISK 사용 | HIGH |
| Index Full Scan | MEDIUM |
| 비용 집중 노드 | INFO |
| 대용량 Nested Loop | MEDIUM |
| 테이블 통계 없음 | MEDIUM |

---

## v2/core/db/tns_parser.py

`tnsnames.ora` 파일을 자동으로 찾아 TNS 별칭 목록을 반환.
- 탐색 순서: 환경변수 `TNS_ADMIN` → `ORACLE_HOME` → 일반 설치 경로

---

## v2/core/analysis/

SQL 텍스트를 정적 분석하여 나쁜 패턴을 찾는 모듈 묶음.

| 파일 | 역할 |
|------|------|
| `base.py` | `SqlIssue` 데이터클래스, `SqlAnalyzer` 인터페이스 |
| `ast_analyzer.py` | sqlglot AST 기반 정밀 분석 (구문 트리 탐색) |
| `regex_analyzer.py` | 정규식 기반 패턴 감지 (빠르고 간단한 규칙) |
| `composite_analyzer.py` | AST + 정규식 두 분석기를 순서대로 실행, 중복 제거 |

감지하는 SQL 안티패턴 예시:

| 패턴 | 심각도 |
|------|--------|
| `UPDATE/DELETE` WHERE 절 없음 | HIGH |
| `WHERE 컬럼함수()` (인덱스 무효화) | MEDIUM |
| 묵시적 형변환 | MEDIUM |
| `NOT IN` 서브쿼리 NULL 위험 | MEDIUM |
| `LIKE '%값'` 앞 와일드카드 | MEDIUM |
| 스칼라 서브쿼리 3개 이상 | MEDIUM |
| `SELECT *` | LOW |
| OR 조건 3개 이상 | LOW |
| DISTINCT + JOIN | INFO |
| UNION (UNION ALL 권장) | INFO |

---

## v2/core/rewrite/

SQL을 자동으로 개선된 형태로 재작성하는 모듈 묶음.

| 파일 | 역할 |
|------|------|
| `base.py` | `SqlRewriter` 인터페이스 |
| `ast_rewriter.py` | sqlglot AST 기반 구조적 재작성 |
| `regex_rewriter.py` | 정규식 기반 간단한 패턴 치환 |
| `composite_rewriter.py` | 두 재작성기 조합 실행 |

---

## v2/core/ai/

AI API를 활용해 추가 튜닝 제안을 생성하는 모듈.

| 파일 | 역할 |
|------|------|
| `ai_provider.py` | AI 공급자 설정 (`AIProviderConfig`), 공급자별 API 호출 |
| `ai_tuner.py` | 분석 결과 + SQL을 AI에 전송, 튜닝 제안 텍스트 수신 |

---

## v2/core/pipeline/validation.py

원본 SQL과 튜닝 SQL을 비교하는 검증 파이프라인.

### ValidationResult 데이터클래스

| 필드 | 타입 | 설명 |
|------|------|------|
| `is_valid` | bool | EXPLAIN PLAN 성공 여부 |
| `error_message` | str | 실패 시 오류 메시지 |
| `original_cost` | int\|None | 원본 SQL 루트 노드 Cost |
| `tuned_cost` | int\|None | 튜닝 SQL 루트 노드 Cost |
| `cost_delta_pct` | float\|None | Cost 변화율 (음수=감소=개선) |
| `original_issues` | list[PlanIssue] | 원본 SQL 이슈 목록 |
| `tuned_issues` | list[PlanIssue] | 튜닝 SQL 이슈 목록 |
| `resolved_issues` | list[PlanIssue] | 원본에만 있던 이슈 (해소됨) |
| `new_issues` | list[PlanIssue] | 튜닝 후 새로 생긴 이슈 |
| `row_count_match` | bool\|None | 결과 행 수 일치 여부 (None=미검증) |
| `original_elapsed_ms` | float\|None | 원본 실행시간 (measure_time=True 시) |
| `tuned_elapsed_ms` | float\|None | 튜닝 실행시간 (measure_time=True 시) |
| `elapsed_delta_pct` | float\|None | 실행시간 변화율 |
| `original_xplan` | str | 원본 DBMS_XPLAN 텍스트 |
| `tuned_xplan` | str | 튜닝 DBMS_XPLAN 텍스트 |
| `verdict` | str | **자동 판정** — APPROVE / REVIEW / REJECT (`__post_init__` 자동 계산) |
| `verdict_reasons` | list[str] | 판정 근거 문자열 목록 |

### 자동 판정 규칙 (`_compute_auto_verdict`)

| 판정 | 조건 |
|------|------|
| **REJECT** | `is_valid=False` OR `row_count_match=False` OR `cost_delta_pct > 10` OR `new_issues` 존재 |
| **APPROVE** | 위 조건 없음 AND `cost_delta_pct ≤ -10` AND `resolved_issues ≥ 1` |
| **REVIEW** | REJECT도 APPROVE도 아닌 경우 |

### 주요 프로퍼티

- `quality_verdict` : 세분화 품질 레이블 (INVALID / IMPROVED / WARNING / REGRESSED / NEUTRAL)
- `verdict_label` : 판정 한국어 레이블 (UI 표시용)
- `cost_summary` : Cost 비교 한 줄 요약 문자열
- `elapsed_summary` : 실행시간 비교 한 줄 요약 문자열

### TuningValidator

```python
TuningValidator(client).validate(original_sql, tuned_sql, measure_time=False)
```

- SQL 전처리: 세미콜론 제거 + 앞뒤 공백 제거
- `measure_time=True`: `execute_sql()` 호출로 실제 실행시간 측정 (SELECT/WITH 전용)
- DB 미연결 시 즉시 `is_valid=False` 반환

---

## v2/core/report/tuning_report.py

튜닝 결과를 단독 열람 가능한 HTML 파일로 내보내는 모듈.

- `TuningReporter.generate_html(original_sql, tuned_sql, result)` → str
- `TuningReporter.save_html(path, original_sql, tuned_sql, result)` → None
- 외부 CSS/JS 의존 없음 — 인라인 스타일로 완전한 단일 파일 생성

### 리포트 섹션 구성

| 섹션 | 내용 |
|------|------|
| 요약 | 판정 배지(APPROVE/REVIEW/REJECT) + 원본/튜닝 SQL 나란히 표시 |
| 성능 비교 | Cost 원본 vs 튜닝 vs 변화율 / 실행시간(측정 시) / Row Count(검증 시) |
| 이슈 분석 | 해소된 이슈(초록) / 신규 이슈(빨강) |
| 판정 근거 | `verdict_reasons` 목록 |

---

## v2/ui/main_window.py

메인 화면. 탭 구성:

| 탭 | 내용 |
|----|------|
| Plan Tree | 실행 계획 계층 트리 (FTS → 빨간색 강조) |
| DBMS_XPLAN | Oracle 텍스트 형식 플랜 |
| 실제 플랜 | DISPLAY_CURSOR로 조회한 실제 실행 플랜 |
| 튜닝 제안 | 감지된 이슈 목록 + 개선 방법 (리소스 HIGH 항목 포함) |
| 리소스 분석 | V$SESSION_WAIT → V$SQL → V$MYSTAT 순 폴백. 탭 상단에 조회 방법 표시 |
| V$SQL 통계 | 실행 이력 (횟수, 소요 시간, I/O) |
| 실행 결과 | SQL 직접 실행 결과 |
| 튜닝된 SQL | 재작성된 SQL + AI 튜닝 제안 |

분석/실행은 백그라운드 워커(`workers/`)에서 실행되므로 UI가 멈추지 않는다.

---

## v2/ui/dialogs/

| 파일 | 역할 |
|------|------|
| `connection_dialog.py` | DB 연결 정보 입력 창. 마지막 값을 QSettings로 기억 |
| `ai_settings_dialog.py` | AI 공급자 선택, API 키 설정 |
| `bind_vars_dialog.py` | SQL의 `:변수명` 감지 + 값 입력 폼 표시 |

---

## v2/ui/widgets/

| 파일 | 역할 |
|------|------|
| `sql_editor.py` | SQL 입력 텍스트 에디터 |
| `plan_tree_tab.py` | Plan Tree 탭 |
| `xplan_tab.py` | DBMS_XPLAN 텍스트 탭 |
| `issues_tab.py` | 튜닝 제안 탭 |
| `wait_event_tab.py` | 리소스 분석 탭 (ResourceAnalysis 표시, 조회방법 레이블, 3단계 폴백 원인 표시) |
| `rewrite_tab.py` | 재작성 SQL + AI 튜닝 + 검증 탭. 실행시간 측정 체크박스, 리포트 저장 버튼 포함 |
| `stats_tab.py` | V$SQL 통계 탭 |
| `result_tab.py` | SQL 실행 결과 탭 |

---

## v2/ui/workers/

| 파일 | 역할 |
|------|------|
| `plan_worker.py` | EXPLAIN PLAN + 이슈 분석 + 리소스 분석(3단계 폴백) 백그라운드 실행 |
| `execute_worker.py` | SQL 직접 실행 백그라운드 실행 |
| `validate_worker.py` | `TuningValidator.validate()` 백그라운드 실행. `measure_time` 옵션 전달 |
| `ai_tune_worker.py` | AI 튜닝 요청 백그라운드 실행 |

---

## v2/tests/

| 파일 | 대상 |
|------|------|
| `test_ast_analyzer.py` | `core/analysis/ast_analyzer.py` |
| `test_ast_rewriter.py` | `core/rewrite/ast_rewriter.py` |
| `test_plan_analyzer.py` | `core/db/plan_analyzer.py` |
| `test_regex_analyzer.py` | `core/analysis/regex_analyzer.py` |
| `test_regex_rewriter.py` | `core/rewrite/regex_rewriter.py` |
| `test_tuning_validator.py` | `core/pipeline/validation.py` — 전처리, Cost 비교, 자동 판정(APPROVE/REVIEW/REJECT), 실행시간 |
| `test_tuning_report.py` | `core/report/tuning_report.py` — HTML 생성, 필수 섹션, 조건부 행, 파일 저장 |
