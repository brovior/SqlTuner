# SQL Tuner v2 - 프로젝트 안내서

> Oracle DB의 SQL 성능을 분석하고 개선 제안을 해주는 **Windows 데스크톱 앱**입니다.

---

## 이 앱이 하는 일

사용자가 SQL을 붙여넣으면:
1. Oracle DB에 실행 계획(EXPLAIN PLAN)을 요청한다
2. 실행 계획을 분석해서 문제점을 찾아낸다
3. 어떻게 고치면 좋을지 제안을 보여준다
4. AI를 활용해 SQL 재작성 및 추가 튜닝 제안을 제공한다

---

## 기술 스택

| 항목 | 사용 기술 | 역할 |
|------|-----------|------|
| 언어 | Python 3.13 (32-bit) | 전체 로직 |
| GUI | PyQt5 | 창, 버튼, 테이블 등 화면 구성 |
| DB 연결 | oracledb | Oracle DB와 통신 |
| SQL 파싱 | sqlglot | AST 기반 SQL 구조 분석 및 재작성 |
| 배포 | PyInstaller | Python 없이 실행 가능한 .exe로 변환 |

> **중요:** Python과 Oracle Client 모두 **32-bit** 사용. 64bit + 32bit 혼용 시 DPI-1047 오류 발생.

---

## 폴더 구조

```
SQL Tuner/
├── run_v2.bat               # 앱 실행
├── check_env_v2.bat         # 환경 점검
├── install_online_v2.bat    # 패키지 설치
├── build_exe_v2.bat         # .exe 빌드
├── run_tests_v2.bat         # 테스트 실행
│
├── docs/
│   ├── ARCHITECTURE.md      # 모듈/파일 상세 역할 설명
│   └── SETUP.md             # 개발 환경 설정 및 배포 안내
│
└── v2/                      # 소스코드
    ├── main.py
    ├── core/
    │   ├── ai/              # AI 튜닝 (ai_provider, ai_tuner)
    │   ├── analysis/        # SQL 정적 분석 (ast, regex, composite)
    │   ├── db/              # DB 연동 (oracle_client, plan_analyzer, tns_parser)
    │   ├── pipeline/        # 분석 파이프라인 (validation)
    │   └── rewrite/         # SQL 재작성 (ast, regex, composite)
    ├── ui/
    │   ├── main_window.py
    │   ├── dialogs/         # 다이얼로그 (connection, ai_settings, bind_vars)
    │   ├── widgets/         # 탭 위젯 (plan_tree, xplan, issues, rewrite, stats, result)
    │   └── workers/         # 백그라운드 워커 (plan, execute, validate, ai_tune)
    └── tests/               # 단위 테스트
```

---

## 앱 실행 흐름

```
앱 실행
  │
  ▼
[DB 연결] 버튼 클릭
  │  → tnsnames.ora 자동 탐색 → TNS 별칭 목록 표시
  │  → 사용자명 / 비밀번호 입력
  │
  ▼
Oracle DB 접속 성공 → 상태바에 "연결됨" 표시
  │
  ▼
SQL 입력창에 SQL 작성
  │
  ▼
[실행 계획 분석] 클릭 (Ctrl+Enter)
  │
  ├─ SQL에 :변수명 있으면 → 바인드 변수 값 입력 다이얼로그
  │
  ▼
백그라운드에서 분석 실행
  ├─ EXPLAIN PLAN 조회 (바인드 변수 포함 시 oracledb 바인드로 전달)
  ├─ DBMS_XPLAN 텍스트 조회
  ├─ 실행 계획 이슈 분석
  ├─ AST + 정규식 이슈 분석
  ├─ SQL 재작성 제안
  └─ V$SQL 실행 이력 조회
  │
  ▼
결과 탭에 표시
```

---

## 로컬 AI (Ollama) 환경

| 항목 | 값 |
|------|-----|
| 다운로드 | https://ollama.com/download |
| 모델 설치 | `ollama pull qwen2.5-coder:7b` |
| AI 설정 URL | `http://localhost:11434/v1` |
| AI 설정 Model | `qwen2.5-coder:7b` |

> 앱 실행 후 툴바 **[AI 설정]** 버튼 → 위 값 입력

---

## 주의사항

- Oracle **Thick Client**가 설치된 환경에서만 최적 동작 (설치 없으면 Thin 모드로 자동 전환)
- DB 계정에 `PLAN_TABLE` 쓰기 권한과 `V$SQL` 조회 권한이 필요
- Windows 전용 배포 (`.bat` 스크립트 기반)
- `Ctrl+Enter` 단축키로 빠르게 분석 가능
- 바인드 변수(`:변수명`) 포함 SQL도 분석 가능 (값 입력 다이얼로그 자동 표시)
- 로직에 큰 변화가 있을시에는 자동으로 claude.md 파일을 update 할 것.
- 신규 의존성이 생길떄는 requirements.txt 파일에 update할 것
- 소스 구조 변경사항이 있을시에는 ARCHITECTURE.md에 update 할 것.
- 소스 변경이 끝나면 test case에 대해서 가이드 할 것.
---

## 코드 수정 시 참고사항

| 하고 싶은 것 | 수정할 파일 |
|-------------|------------|
| 새로운 실행 계획 분석 규칙 | `v2/core/db/plan_analyzer.py` |
| 새로운 SQL 안티패턴 (AST) | `v2/core/analysis/ast_analyzer.py` |
| 새로운 SQL 안티패턴 (정규식) | `v2/core/analysis/regex_analyzer.py` |
| SQL 재작성 로직 | `v2/core/rewrite/` |
| 화면 레이아웃 | `v2/ui/main_window.py` |
| 탭 위젯 | `v2/ui/widgets/` |
| DB 연결 방식 | `v2/core/db/oracle_client.py` |
| 연결 다이얼로그 | `v2/ui/dialogs/connection_dialog.py` |
| AI 설정 | `v2/ui/dialogs/ai_settings_dialog.py` |
| 바인드 변수 다이얼로그 | `v2/ui/dialogs/bind_vars_dialog.py` |
| .exe 빌드 설정 | `v2/SQL_Tuner_v2.spec` |

> 상세 모듈 설명 → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)  
> 개발 환경 설정 → [docs/SETUP.md](docs/SETUP.md)


## 마지막 작업 현황 (2026-04-14)
- DBA 로드맵 7단계 완료
- 완료: STEP 7-1/7-2 (ROWNUM 페이징 안티패턴 감지)
  - ast_analyzer.py: _check_rownum_nested_paging, _check_rownum_no_order 추가
  - regex_analyzer.py: _check_rownum_nested_paging, _check_rownum_no_order 추가
- 완료: STEP 7-3 (스칼라 서브쿼리 → LEFT JOIN 변환)
  - ast_rewriter.py: _scalar_subquery_to_left_join 추가
- 완료: STEP 7-4 (WHERE IN 서브쿼리 → JOIN 변환)
  - ast_rewriter.py: _in_subquery_to_join 추가
- 완료: STEP 7-5 (힌트 자동 추천 — LEADING/USE_NL/USE_HASH/INDEX)
  - hint_advisor.py: 신규 생성 (HintSuggestion, HintAdvisor)
  - issues_tab.py: populate_hints(), _build_hint_group() 추가
  - main_window.py: HintAdvisor 연동
- 완료: STEP 7-6 (인라인 뷰 힌트 — PUSH_PRED/NO_MERGE)
  - hint_advisor.py: _suggest_inline_view, _has_filter_ancestor, _build_full_hint 추가
- 7단계 전체 완료 — 225 passed
- 다음 작업: 8단계 또는 신규 기능 논의