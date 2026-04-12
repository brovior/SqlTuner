# SQL Tuner 레포지토리 분석 문서

> 작성일: 2026-04-11  
> 대상 브랜치: `20260410_03`  
> 목적: 새로운 SQL 튜닝 엔진 설계를 위한 기존 코드 재사용성·한계점 분석

---

## 1. 레포지토리 전체 구조 맵

```
SqlTuner/
├── main.py                     # 진입점 — QApplication 생성 및 MainWindow 실행
├── requirements.txt            # PyQt5, oracledb, sqlparse, sqlglot
├── SQL_Tuner.spec              # PyInstaller 단일 폴더 빌드 설정
├── CLAUDE.md                   # 프로젝트 안내서 (개발 환경, 파일 역할, 흐름)
│
├── core/                       # 핵심 비즈니스 로직 (UI 의존 없음)
│   ├── oracle_client.py        # DB 연결, EXPLAIN PLAN, V$SQL, 인덱스/통계 조회
│   ├── plan_analyzer.py        # 실행 계획 PlanRow → 트리 + 이슈 감지 (7가지 규칙)
│   ├── tuning_rules.py         # SQL 텍스트 정규식 분석 (10가지 안티패턴)
│   ├── sqlglot_analyzer.py     # SQL 텍스트 AST 분석 (sqlglot, 정규식 대안)
│   ├── sqlglot_rewriter.py     # SQL AST 기반 자동 재작성 (OR→IN, NOT IN→NOT EXISTS)
│   ├── sql_rewriter.py         # SQL 정규식 기반 자동 재작성 (sqlglot 대안)
│   ├── ai_provider.py          # AI 제공자 추상화 (Claude / OpenAI 호환 / Null)
│   ├── ai_tuner.py             # AI 기반 SQL 튜닝 (프롬프트 생성 + 응답 정제)
│   └── tns_parser.py           # tnsnames.ora 자동 탐색 및 파싱
│
├── ui/                         # PyQt5 화면 구성 (로직과 분리됨)
│   ├── main_window.py          # 메인 창 (SQL 편집기, 결과 탭 5개, 툴바)
│   ├── connection_dialog.py    # DB 연결 설정 다이얼로그
│   └── ai_settings_dialog.py  # AI 제공자 설정 다이얼로그
│
└── *.bat                       # Windows 편의 스크립트 (설치, 실행, 빌드)
```

---

## 2. 핵심 기능 요약

### 2-1. DB 연결 흐름

`OracleClient.connect()` 는 **Thick → Thin 모드 자동 폴백** 방식으로 동작한다.

1. `oracledb.init_oracle_client()` 로 Thick 모드 초기화 시도
2. 실패(DPI-1047, 아키텍처 불일치 등)하면 Thin 모드로 재시도
3. 연결 성공 시 `_thin_mode` 플래그로 모드를 추적

연결 정보(`ConnectionInfo`)는 tnsnames.ora 파일을 통해 TNS 별칭으로 연결하며, `TNS_ADMIN` 환경변수를 자동 설정한다.

### 2-2. 실행 계획 분석 파이프라인

```
SQL 입력
  → OracleClient.explain_plan()
      ├─ DELETE FROM PLAN_TABLE (이전 플랜 제거)
      ├─ EXPLAIN PLAN FOR <sql>
      ├─ SELECT FROM PLAN_TABLE → list[PlanRow]
      └─ DBMS_XPLAN.DISPLAY → 텍스트
  → PlanAnalyzer(plan_rows)
      ├─ build_tree() : parent_id 기반 트리 구성
      └─ analyze() : 7가지 규칙 검사 → list[PlanIssue]
  → SqlTextAnalyzer / SqlglotAnalyzer
      └─ analyze(sql) : 10가지 안티패턴 → list[SqlIssue]
```

모든 분석은 `PlanWorker(QThread)` 에서 백그라운드 실행되어 UI가 멈추지 않는다.

### 2-3. SQL 재작성 엔진 (2종)

| 엔진 | 클래스 | 방식 | 특징 |
|------|--------|------|------|
| 정규식 | `RuleBasedRewriter` | regex substitution | 빠르나 주석·문자열 오탐 가능 |
| AST | `SqlglotRewriter` | sqlglot AST 변환 | 정확, 파싱 실패 시 regex로 폴백 |

공통 변환 규칙:
- `col='A' OR col='B'` → `col IN ('A','B')`
- `col NOT IN (SELECT ...)` → `NOT EXISTS (...)`
- `UNION` → `UNION ALL`

사용자가 툴바의 콤보박스에서 엔진을 선택할 수 있다.

### 2-4. AI 튜닝

`AiSqlTuner.tune(sql, issues)` 가 SQL + 감지된 이슈를 프롬프트로 조합해 AI에 전달한다.

```
[시스템 프롬프트]  Oracle SQL 튜닝 전문가. SQL만 반환. 마크다운 금지.
[사용자 프롬프트]  원본 SQL + 감지된 이슈 목록
                  → 최적화된 SQL (--주석 포함)
```

AI 응답에서 마크다운 코드 펜스(` ```sql ... ``` `)를 제거하고 순수 SQL만 반환한다.

AI 제공자는 `AIProvider` 추상 클래스를 통해 교체 가능:
- `ClaudeProvider` : Anthropic API (`anthropic` 패키지)
- `OpenAICompatibleProvider` : OpenAI 호환 API (`openai` 패키지) — Ollama, 사내 LLM, Azure 등
- `NullProvider` : AI 기능 비활성화 시 사용

---

## 3. 재사용 가능한 모듈 분류

### 3-1. 그대로 재사용 (수정 불필요)

| 파일 | 재사용 이유 |
|------|------------|
| `core/oracle_client.py` | DB 연결, EXPLAIN PLAN, V$SQL, 인덱스/통계 조회까지 완전하게 구현됨. Thick/Thin 폴백 포함. |
| `core/plan_analyzer.py` | PlanRow → 트리 + 이슈 감지 로직이 잘 분리되어 있음. 7개 규칙 모두 독립적으로 동작. |
| `core/tns_parser.py` | TNS_ADMIN → ORACLE_HOME → 일반 경로 탐색 순서가 현장 환경에 맞게 구현됨. |
| `core/ai_provider.py` | 추상화가 잘 되어 있음. `create_provider(config)` 팩토리로 제공자 교체가 단순함. |
| `core/ai_tuner.py` | 프롬프트 설계·응답 정제 로직이 단순하고 재사용 가능. |
| `core/sql_rewriter.py` | 정규식 재작성기. 단순한 케이스에서는 충분히 빠르고 안정적. |
| `core/sqlglot_rewriter.py` | AST 재작성기. 구조적으로 정확. 폴백 로직 포함. |
| `ui/connection_dialog.py` | DB 연결 다이얼로그. QSettings 기반 저장/복원 완성됨. |
| `ui/ai_settings_dialog.py` | AI 설정 다이얼로그. 제공자별 힌트, 연결 테스트 버튼 포함. |

### 3-2. 수정 후 재사용 (개선 필요)

| 파일 | 현재 한계 | 개선 방향 |
|------|----------|----------|
| `core/tuning_rules.py` | 정규식 기반이라 주석·문자열 내부 오탐 가능. `SqlglotAnalyzer`와 인터페이스만 공유하고 내용이 중복됨. | `SqlglotAnalyzer`를 기본으로 하고 regex를 폴백으로 전환. 또는 두 클래스를 하나의 `SqlAnalyzer` 인터페이스 아래로 통합. |
| `core/sqlglot_analyzer.py` | `_check_function_on_where_col` 이 `exp.Anonymous` 만 검사하여 `TRUNC`, `NVL` 등 일부 함수를 놓칠 수 있음. `_check_implicit_conversion` 은 여전히 regex에 의존함. | 함수 감지 범위 확대. 묵시적 형변환도 AST 레벨에서 감지 시도. |
| `ui/main_window.py` | 약 800줄짜리 단일 파일. UI 구성·이벤트 핸들러·데이터 표시·AI 호출이 모두 섞여 있음. | 역할별로 분리: 툴바 빌더, 탭 빌더, 이벤트 핸들러를 별도 헬퍼 클래스로 추출. |

### 3-3. 참고만 하고 버릴 모듈

| 파일 | 이유 |
|------|------|
| `*.bat` | 개발 편의용. 새 아키텍처에서 필요하면 그대로 유지하되 로직 변경은 불필요. |
| `SQL_Tuner.spec` | PyInstaller 설정. 파일 목록이 바뀌면 수정만 하면 됨. |

---

## 4. 기존 코드의 한계점

### 4-1. 분석 정확도

| 한계 | 상세 |
|------|------|
| **정규식 오탐** | `tuning_rules.py` 는 주석(`-- WHERE UPPER(...)`) 또는 문자열 리터럴 안의 패턴을 실제 안티패턴으로 잘못 감지할 수 있음. |
| **스키마 정보 부재** | 묵시적 형변환 감지는 컬럼의 실제 데이터 타입을 모르기 때문에 `= '숫자'` 패턴만 보고 경고함. 거짓 양성 가능. |
| **단일 SQL 가정** | 다중 SQL(세미콜론 구분), PL/SQL 블록, CTE를 포함한 복잡한 SQL에서 분석이 부정확할 수 있음. |

### 4-2. 아키텍처

| 한계 | 상세 |
|------|------|
| **모놀리식 UI** | `main_window.py` 가 UI·비즈니스 로직을 함께 담고 있어 단위 테스트가 불가능하고 유지보수가 어렵다. |
| **설정 저장 방식** | `config.ini` 에 base64 인코딩으로 비밀번호를 저장함. 보안 수준이 낮고, Tab 키 실수 입력이 저장되는 문제가 있었음 (ORA-01017 원인). |
| **엔진 선택 상태 비지속** | 분석 엔진(정규식/AST) 선택이 앱 재시작 시 초기화됨. QSettings에 저장해야 함. |
| **테스트 커버리지 없음** | 단위 테스트, 통합 테스트 파일이 전혀 없음. 회귀 검증 불가. |

### 4-3. AI 튜닝

| 한계 | 상세 |
|------|------|
| **모델 품질 의존** | 소형 로컬 모델(Ollama qwen2.5-coder:7b 등)은 프롬프트를 무시하고 마크다운을 출력하거나 설명을 추가하는 경우가 있음. `_clean_output` 으로 일부만 처리됨. |
| **결과 검증 없음** | AI가 반환한 SQL이 원본과 동일한 결과를 내는지 검증하는 파이프라인이 없음. |
| **스트리밍 미지원** | 응답 전체가 도착할 때까지 UI가 "AI 튜닝 중..." 상태로 대기함. 스트리밍 API 활용 시 UX 개선 가능. |

---

## 5. 새 아키텍처 개선 포인트

### 5-1. 레이어 분리 (우선순위 높음)

```
현재:                          개선 후:
main_window.py (모든 것)        ├─ core/           # UI 의존 없는 순수 로직
                                │   ├─ analyzer/   # 분석기 인터페이스 + 구현체
                                │   ├─ rewriter/   # 재작성기 인터페이스 + 구현체
                                │   └─ ai/         # AI 튜너 + 제공자
                                └─ ui/
                                    ├─ main_window.py   # 껍데기만
                                    ├─ widgets/         # 탭별 위젯
                                    └─ workers/         # QThread 워커들
```

### 5-2. 분석기 통합 인터페이스

```python
class SqlAnalyzer(ABC):
    def analyze(self, sql: str) -> list[SqlIssue]: ...

# 구현체
SqlglotAnalyzer  : 기본 (AST 기반, 정확)
SqlTextAnalyzer  : 폴백 (정규식 기반)
CompositeAnalyzer: 두 결과를 병합·중복 제거
```

### 5-3. 설정 보안 강화

- OS 키체인(Windows Credential Manager) 또는 환경변수로 비밀번호 저장 이관
- 입력값 trim 처리를 저장 시점이 아닌 읽기 시점에도 적용

### 5-4. 테스트 추가

```
tests/
├── test_plan_analyzer.py    # PlanRow fixture 기반 단위 테스트
├── test_sql_analyzer.py     # SQL 텍스트 → 이슈 감지 단위 테스트
├── test_sql_rewriter.py     # 재작성 전후 SQL 비교
└── test_oracle_client.py    # 실제 DB 또는 Mock 기반 통합 테스트
```

---

## 6. 권장 마이그레이션 순서

| 단계 | 작업 | 비고 |
|------|------|------|
| 1 | `core/` 모듈 단위 테스트 추가 | 리팩토링 전 회귀 방지망 확보 |
| 2 | `SqlAnalyzer` 인터페이스 통합 | `tuning_rules.py` + `sqlglot_analyzer.py` 정리 |
| 3 | `main_window.py` 탭별 위젯 분리 | `PlanTreeTab`, `SuggestionsTab`, `RewriteTab` 등 |
| 4 | QThread 워커 분리 | `workers/` 폴더로 추출 |
| 5 | 설정 저장 방식 개선 | 비밀번호 보안 강화 |
| 6 | AI 응답 검증 파이프라인 | AI SQL → EXPLAIN PLAN 재실행으로 유효성 확인 |

---

## 부록: 주요 데이터 타입 관계도

```
PlanRow          ← oracle_client.py 반환 → PlanAnalyzer  → PlanIssue
SqlIssue         ← tuning_rules / sqlglot_analyzer       → UI 표시
RewriteResult    ← sql_rewriter / sqlglot_rewriter       → UI 표시
AIProviderConfig → create_provider() → AIProvider → AiSqlTuner → str (튜닝된 SQL)
```

`PlanIssue` 와 `SqlIssue` 는 현재 **별개의 dataclass** 이지만 필드 구조(`severity`, `category`, `title`, `description`, `suggestion`, `sample_sql`)가 동일하므로 통합을 검토할 수 있다.
