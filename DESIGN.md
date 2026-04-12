# SQL Tuner v2 — 설계 문서

> 작성일: 2026-04-11  
> 기반: ANALYSIS.md 분석 결과  
> 원칙: 기존 파일 무수정 / `v2/` 디렉토리에 신규 구현

---

## 1. Reusable Assets (그대로 복사 또는 import)

아래 파일들은 기능이 완전하고 인터페이스도 안정적이므로 **파일 복사 또는 직접 import**로 재사용한다.  
단, 파일 위치가 `v2/` 하위로 바뀌므로 내부 import 경로만 조정.

| 기존 파일 | 복사 위치 | 수정 내용 |
|-----------|-----------|-----------|
| `core/oracle_client.py` | `v2/core/db/oracle_client.py` | import 경로 조정 없음 (독립 모듈) |
| `core/plan_analyzer.py` | `v2/core/db/plan_analyzer.py` | import: `oracle_client` 경로 조정 |
| `core/tns_parser.py` | `v2/core/db/tns_parser.py` | 수정 없음 |
| `core/ai_provider.py` | `v2/core/ai/ai_provider.py` | 수정 없음 |
| `core/ai_tuner.py` | `v2/core/ai/ai_tuner.py` | import 경로 조정 |
| `core/sql_rewriter.py` | `v2/core/rewrite/regex_rewriter.py` | 클래스명 유지, 모듈 위치만 이동 |
| `core/sqlglot_rewriter.py` | `v2/core/rewrite/ast_rewriter.py` | import 경로 조정 |
| `ui/connection_dialog.py` | `v2/ui/dialogs/connection_dialog.py` | import 경로 조정 |
| `ui/ai_settings_dialog.py` | `v2/ui/dialogs/ai_settings_dialog.py` | import 경로 조정 |

---

## 2. Rewrite Targets (새로 작성)

### 2-1. 분석기 통합 (`core/analysis/`)

**기존 문제:**
- `tuning_rules.py` (regex) + `sqlglot_analyzer.py` (AST) — 동일 기능, 중복 구현
- 두 클래스가 같은 `SqlIssue` 반환형을 쓰지만 공통 인터페이스가 없음
- `sqlglot_analyzer.py` 의 `_check_function_on_where_col` 이 `exp.Anonymous` 만 검사 → `TRUNC`, `NVL`, `TO_NUMBER` 미감지

**새 설계:**
```python
# v2/core/analysis/base.py
class SqlAnalyzer(ABC):
    def analyze(self, sql: str) -> list[SqlIssue]: ...

# v2/core/analysis/ast_analyzer.py  ← sqlglot_analyzer.py 개선판
class AstAnalyzer(SqlAnalyzer):
    """AST 기반. 함수 감지 범위 확대, 폴백 없음."""

# v2/core/analysis/regex_analyzer.py  ← tuning_rules.py 이름 변경
class RegexAnalyzer(SqlAnalyzer):
    """정규식 기반. AstAnalyzer 파싱 실패 시 폴백으로 사용."""

# v2/core/analysis/composite_analyzer.py  ← 신규
class CompositeAnalyzer(SqlAnalyzer):
    """AST 시도 → 실패 시 Regex 폴백. 결과 중복 제거."""
    def __init__(self, primary: SqlAnalyzer, fallback: SqlAnalyzer): ...
```

**AstAnalyzer 개선 사항:**
- `_check_function_on_where_col`: `exp.Anonymous` 외에 `exp.TryCast`, `exp.Cast`, `exp.Trim`, `exp.Nvl`, `exp.Substring` 등 sqlglot 전용 노드 타입도 포함
- `_check_implicit_conversion`: 정규식 대신 AST 에서 `exp.EQ(Column, Literal)` 패턴으로 숫자 리터럴이 문자열인지 확인

### 2-2. 검증 파이프라인 (`core/pipeline/`) ← 완전 신규

**목적:** AI 또는 규칙 기반으로 생성된 튜닝 SQL이 실제로 동작하고, 원본보다 나은지 검증

```python
# v2/core/pipeline/validation.py
@dataclass
class ValidationResult:
    is_valid: bool              # EXPLAIN PLAN 성공 여부
    error_message: str          # 실패 시 오류 메시지
    original_cost: int | None   # 원본 SQL 총 Cost
    tuned_cost: int | None      # 튜닝 SQL 총 Cost
    cost_delta_pct: float       # 비용 변화율 (음수 = 개선)
    original_issues: list       # 원본 PlanIssue 목록
    tuned_issues: list          # 튜닝 후 PlanIssue 목록
    resolved_issues: list       # 해소된 이슈 (원본에만 있는 것)
    new_issues: list            # 신규 이슈 (튜닝 후에만 생긴 것)

class TuningValidator:
    def __init__(self, client: OracleClient): ...

    def validate(self, original_sql: str, tuned_sql: str) -> ValidationResult:
        """
        1. tuned_sql 에 EXPLAIN PLAN 실행 → 파싱 오류 감지
        2. 원본 Cost vs 튜닝 Cost 비교
        3. PlanIssue 목록 비교 (해소된 이슈, 신규 이슈)
        4. ValidationResult 반환
        """
```

### 2-3. UI 분리 (`ui/`)

**기존 문제:** `main_window.py` 1개 파일이 약 800줄, 모든 역할 혼합

**새 설계:**
```
v2/ui/
├── main_window.py          # 조립만 담당 (200줄 이내 목표)
├── dialogs/
│   ├── connection_dialog.py
│   └── ai_settings_dialog.py
├── widgets/
│   ├── sql_editor.py       # SQL 입력 + 하이라이터 + 단축키
│   ├── plan_tree_tab.py    # Plan Tree 탭
│   ├── xplan_tab.py        # DBMS_XPLAN 탭
│   ├── issues_tab.py       # 튜닝 제안 탭
│   ├── stats_tab.py        # V$SQL 통계 탭
│   └── rewrite_tab.py      # 튜닝된 SQL 탭 (규칙 + AI + 검증 결과)
└── workers/
    ├── plan_worker.py      # 실행 계획 분석 QThread
    ├── ai_tune_worker.py   # AI 튜닝 QThread
    └── validate_worker.py  # 검증 파이프라인 QThread  ← 신규
```

---

## 3. New Architecture

### 3-1. 전체 폴더 구조

```
SqlTuner/
├── (기존 파일들 — 수정하지 않음)
│
└── v2/
    ├── main.py                         # 새 앱 진입점
    ├── requirements.txt                # 기존과 동일 + openai, anthropic
    │
    ├── core/
    │   ├── db/
    │   │   ├── __init__.py
    │   │   ├── oracle_client.py        # [복사] Thick/Thin 폴백 연결
    │   │   ├── plan_analyzer.py        # [복사] 실행 계획 이슈 감지
    │   │   └── tns_parser.py           # [복사] tnsnames.ora 탐색
    │   │
    │   ├── analysis/
    │   │   ├── __init__.py
    │   │   ├── base.py                 # [신규] SqlAnalyzer ABC + SqlIssue
    │   │   ├── ast_analyzer.py         # [개선] sqlglot 기반, 함수 감지 확장
    │   │   ├── regex_analyzer.py       # [복사] tuning_rules.py 이름 변경
    │   │   └── composite_analyzer.py   # [신규] AST→Regex 폴백 + 중복 제거
    │   │
    │   ├── rewrite/
    │   │   ├── __init__.py
    │   │   ├── base.py                 # [신규] SqlRewriter ABC + RewriteResult
    │   │   ├── ast_rewriter.py         # [복사] sqlglot_rewriter.py
    │   │   └── regex_rewriter.py       # [복사] sql_rewriter.py
    │   │
    │   ├── ai/
    │   │   ├── __init__.py
    │   │   ├── ai_provider.py          # [복사] AIProvider 추상화
    │   │   └── ai_tuner.py             # [복사] AiSqlTuner
    │   │
    │   └── pipeline/
    │       ├── __init__.py
    │       └── validation.py           # [신규] TuningValidator + ValidationResult
    │
    ├── ui/
    │   ├── main_window.py              # [재작성] 조립만, 200줄 목표
    │   ├── dialogs/
    │   │   ├── __init__.py
    │   │   ├── connection_dialog.py    # [복사] 경로 조정
    │   │   └── ai_settings_dialog.py  # [복사] 경로 조정
    │   ├── widgets/
    │   │   ├── __init__.py
    │   │   ├── sql_editor.py           # [신규] QPlainTextEdit + SqlHighlighter
    │   │   ├── plan_tree_tab.py        # [추출] _build_plan_tree_tab 분리
    │   │   ├── xplan_tab.py            # [추출] _build_xplan_tab 분리
    │   │   ├── issues_tab.py           # [추출] _build_issues_tab 분리
    │   │   ├── stats_tab.py            # [추출] _build_stats_tab 분리
    │   │   └── rewrite_tab.py          # [재작성] 규칙 + AI + 검증 결과 통합
    │   └── workers/
    │       ├── __init__.py
    │       ├── plan_worker.py          # [추출] PlanWorker QThread
    │       ├── ai_tune_worker.py       # [추출] AiTuneWorker QThread
    │       └── validate_worker.py      # [신규] ValidateWorker QThread
    │
    └── tests/
        ├── test_plan_analyzer.py
        ├── test_ast_analyzer.py
        ├── test_regex_analyzer.py
        ├── test_ast_rewriter.py
        └── test_regex_rewriter.py
```

### 3-2. 데이터 흐름 (새 파이프라인)

```
[사용자 SQL 입력]
       │
       ▼
  PlanWorker (QThread)
  ├─ OracleClient.explain_plan() → PlanRow[], xplan_text
  ├─ PlanAnalyzer.analyze()      → list[PlanIssue]
  └─ CompositeAnalyzer.analyze() → list[SqlIssue]
       │
       ▼
  결과 탭 표시 (Plan Tree / DBMS_XPLAN / 튜닝 제안)
       │
       ▼
  [규칙 기반 재작성] — 자동 실행
  CompositeRewriter.rewrite() → RewriteResult
  (AstRewriter → RegexRewriter 폴백)
       │
       ├─ rewrite_tab 에 즉시 표시
       │
       └─ [선택] 검증 버튼 클릭
              ValidateWorker (QThread)
              TuningValidator.validate(original, rewritten)
              → ValidationResult (비용 비교, 이슈 해소 현황)
              → rewrite_tab 하단에 검증 결과 표시

  [AI 튜닝 요청 버튼 클릭]
       │
       ▼
  AiTuneWorker (QThread)
  AiSqlTuner.tune(sql, issues) → ai_sql (str)
       │
       ├─ rewrite_tab AI 섹션에 표시
       │
       └─ [선택] AI SQL 검증 버튼 클릭
              ValidateWorker (QThread)
              TuningValidator.validate(original, ai_sql)
              → ValidationResult
              → rewrite_tab 하단에 검증 결과 표시
```

### 3-3. 핵심 인터페이스 정의

```python
# v2/core/analysis/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class SqlIssue:
    severity: str        # HIGH / MEDIUM / LOW / INFO
    category: str
    title: str
    description: str
    suggestion: str
    sample_sql: str = ''

class SqlAnalyzer(ABC):
    @abstractmethod
    def analyze(self, sql: str) -> list[SqlIssue]: ...

# v2/core/rewrite/base.py
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

@dataclass
class RewriteResult:
    original_sql: str
    rewritten_sql: str
    changes: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.changes)

class SqlRewriter(ABC):
    @abstractmethod
    def rewrite(self, sql: str) -> RewriteResult: ...
```

### 3-4. CompositeRewriter (신규 — 엔진 선택 대체)

기존에는 사용자가 콤보박스로 엔진을 선택했다. 새 설계에서는:
- **CompositeRewriter** 가 AST → Regex 순서로 자동 시도
- 사용자 선택지는 `강제 정규식 모드` 체크박스(선택 사항)로 단순화

```python
class CompositeRewriter(SqlRewriter):
    def __init__(self, force_regex: bool = False):
        self._ast = AstRewriter()
        self._regex = RegexRewriter()
        self._force_regex = force_regex

    def rewrite(self, sql: str) -> RewriteResult:
        if not self._force_regex:
            try:
                result = self._ast.rewrite(sql)
                result.changes.insert(0, '[AST 엔진]')
                return result
            except Exception:
                pass
        result = self._regex.rewrite(sql)
        result.changes.insert(0, '[정규식 엔진]')
        return result
```

---

## 4. Migration Plan

### Phase 1 — 골격 구성 (코어 복사 + 인터페이스 정의)

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 1.1 | `v2/` 디렉토리 생성 및 `__init__.py` 배치 | 폴더 구조 |
| 1.2 | `core/db/` 에 oracle_client, plan_analyzer, tns_parser 복사 | DB 레이어 완성 |
| 1.3 | `core/analysis/base.py` 작성 (SqlAnalyzer ABC + SqlIssue) | 분석기 인터페이스 |
| 1.4 | `core/rewrite/base.py` 작성 (SqlRewriter ABC + RewriteResult) | 재작성기 인터페이스 |
| 1.5 | `core/ai/` 에 ai_provider, ai_tuner 복사 | AI 레이어 완성 |

### Phase 2 — 분석기 구현

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 2.1 | `regex_analyzer.py` 작성 (tuning_rules.py + SqlAnalyzer 상속) | 정규식 분석기 |
| 2.2 | `ast_analyzer.py` 작성 (sqlglot_analyzer.py 개선판) | AST 분석기 |
| 2.3 | `composite_analyzer.py` 작성 | 자동 폴백 분석기 |
| 2.4 | `tests/test_ast_analyzer.py` 작성 | 분석기 단위 테스트 |

### Phase 3 — 재작성기 + 검증 파이프라인

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 3.1 | `ast_rewriter.py`, `regex_rewriter.py` 복사 및 base 상속 추가 | 재작성기 구현 |
| 3.2 | `CompositeRewriter` 구현 | 자동 폴백 재작성기 |
| 3.3 | `pipeline/validation.py` 구현 | TuningValidator |
| 3.4 | `tests/test_ast_rewriter.py`, `test_regex_rewriter.py` 작성 | 재작성기 단위 테스트 |

### Phase 4 — UI 분리 및 조립

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 4.1 | `workers/` 3개 파일 작성 | QThread 워커 |
| 4.2 | `widgets/sql_editor.py` 작성 | SQL 편집기 위젯 |
| 4.3 | `widgets/plan_tree_tab.py` 등 탭별 위젯 작성 | 탭 위젯 5개 |
| 4.4 | `widgets/rewrite_tab.py` 작성 (검증 결과 포함) | 튜닝된 SQL 탭 |
| 4.5 | `ui/main_window.py` 재작성 (조립만) | 메인 창 |
| 4.6 | `dialogs/` 복사 및 경로 조정 | 다이얼로그 2개 |

### Phase 5 — 마무리

| 순서 | 작업 | 산출물 |
|------|------|--------|
| 5.1 | `v2/main.py` 작성 | 새 진입점 |
| 5.2 | `v2/requirements.txt` 작성 | 의존성 목록 |
| 5.3 | QSettings 키를 `v2/` 네임스페이스로 분리 | 설정 충돌 방지 |
| 5.4 | 엔진 선택 상태 QSettings 저장 | 재시작 후에도 유지 |
| 5.5 | 전체 동작 테스트 (Docker Oracle + Ollama) | 검증 완료 |

---

## 5. Risks

### 5-1. 기술 위험

| 위험 | 영향도 | 대응 |
|------|--------|------|
| **sqlglot Oracle 방언 미지원 구문** | 중간 | AST 파싱 실패 시 Regex 폴백으로 자동 전환. 폴백 발생 로그를 UI에 표시. |
| **검증 파이프라인 권한 문제** | 중간 | EXPLAIN PLAN은 PLAN_TABLE 쓰기 권한 필요. 권한 없으면 검증 생략 후 경고만 표시. |
| **AI 응답 품질** | 높음 | 소형 Ollama 모델은 SQL 문법 오류 포함 응답 가능. 검증 파이프라인이 이를 감지하여 "검증 실패" 표시. AI SQL 을 자동 적용하지 않고 사용자 확인 후 복사 사용. |
| **32bit Python + 라이브러리 호환** | 낮음 | anthropic, openai, sqlglot 모두 32bit 지원 확인됨. PyInstaller 빌드 시 hidden imports 추가 필요. |

### 5-2. 아키텍처 위험

| 위험 | 영향도 | 대응 |
|------|--------|------|
| **PlanIssue vs SqlIssue 이중 타입** | 낮음 | 현재는 별도 dataclass 유지 (필드가 동일하지만 출처가 다름). 향후 단일 `Issue` 타입으로 통합 검토. |
| **ValidateWorker 중첩 실행** | 낮음 | 검증 버튼을 실행 중에는 비활성화하여 중복 실행 방지. |
| **설정 파일 공존 (`config.ini`)** | 낮음 | v2 는 `config_v2.ini` 로 분리하여 기존 설정과 충돌 없이 독립 운영. |

### 5-3. 운영 위험

| 위험 | 영향도 | 대응 |
|------|--------|------|
| **기존 .bat 스크립트 경로** | 낮음 | `run.bat` 에 `cd v2 && py -3.13-32 main.py` 로 분기 추가. 기존 main.py는 그대로 유지. |
| **PyInstaller 빌드 경로** | 낮음 | `SQL_Tuner.spec` 을 `v2/SQL_Tuner_v2.spec` 으로 별도 관리. |

---

## 부록 A: 파일별 작업 분류 요약

| 파일 | 작업 | 새 위치 |
|------|------|---------|
| `core/oracle_client.py` | 복사 | `v2/core/db/oracle_client.py` |
| `core/plan_analyzer.py` | 복사 | `v2/core/db/plan_analyzer.py` |
| `core/tns_parser.py` | 복사 | `v2/core/db/tns_parser.py` |
| `core/tuning_rules.py` | 재작성 → `regex_analyzer.py` | `v2/core/analysis/regex_analyzer.py` |
| `core/sqlglot_analyzer.py` | 개선 → `ast_analyzer.py` | `v2/core/analysis/ast_analyzer.py` |
| `core/sql_rewriter.py` | 복사 + base 상속 | `v2/core/rewrite/regex_rewriter.py` |
| `core/sqlglot_rewriter.py` | 복사 + base 상속 | `v2/core/rewrite/ast_rewriter.py` |
| `core/ai_provider.py` | 복사 | `v2/core/ai/ai_provider.py` |
| `core/ai_tuner.py` | 복사 | `v2/core/ai/ai_tuner.py` |
| `ui/connection_dialog.py` | 복사 + import 조정 | `v2/ui/dialogs/connection_dialog.py` |
| `ui/ai_settings_dialog.py` | 복사 + import 조정 | `v2/ui/dialogs/ai_settings_dialog.py` |
| `ui/main_window.py` | 재작성 (200줄 목표) | `v2/ui/main_window.py` |
| _(없음)_ | 신규 | `v2/core/analysis/base.py` |
| _(없음)_ | 신규 | `v2/core/analysis/composite_analyzer.py` |
| _(없음)_ | 신규 | `v2/core/rewrite/base.py` |
| _(없음)_ | 신규 | `v2/core/rewrite/composite_rewriter.py` |
| _(없음)_ | 신규 | `v2/core/pipeline/validation.py` |
| _(없음)_ | 신규 | `v2/ui/widgets/*.py` (6개) |
| _(없음)_ | 신규 | `v2/ui/workers/*.py` (3개) |
| _(없음)_ | 신규 | `v2/tests/test_*.py` (5개) |

## 부록 B: 주요 의존성 그래프

```
main_window
  └─ sql_editor (widget)
  └─ plan_tree_tab (widget)
  └─ xplan_tab (widget)
  └─ issues_tab (widget)
  └─ stats_tab (widget)
  └─ rewrite_tab (widget)
       ├─ CompositeRewriter
       └─ ValidationResult (표시용)
  └─ PlanWorker (worker)
       ├─ OracleClient
       ├─ PlanAnalyzer
       └─ CompositeAnalyzer
  └─ AiTuneWorker (worker)
       └─ AiSqlTuner
            └─ AIProvider (Claude / OpenAI호환 / Null)
  └─ ValidateWorker (worker)
       └─ TuningValidator
            └─ OracleClient
            └─ PlanAnalyzer
```
