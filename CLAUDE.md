# SQL Tuner - 프로젝트 안내서

> Oracle DB의 SQL 성능을 분석하고 개선 제안을 해주는 **Windows 데스크톱 앱**입니다.

---

## 이 앱이 하는 일

사용자가 SQL을 붙여넣으면:
1. Oracle DB에 실행 계획(EXPLAIN PLAN)을 요청한다
2. 실행 계획을 분석해서 문제점을 찾아낸다
3. 어떻게 고치면 좋을지 제안을 보여준다

---

## 기술 스택

| 항목 | 사용 기술 | 역할 |
|------|-----------|------|
| 언어 | Python 3.13 | 전체 로직 |
| GUI | PyQt6 | 창, 버튼, 테이블 등 화면 구성 |
| DB 연결 | oracledb | Oracle DB와 통신 |
| SQL 파싱 | sqlparse | SQL 텍스트 구조 분석 |
| 배포 | PyInstaller | Python 없이 실행 가능한 .exe로 변환 |

> **주의:** pip 패키지 이름이 `python-oracledb`에서 `oracledb`로 변경됨 (2025년 이후)

---

## 폴더 구조

```
SQL Tuner/
├── main.py                  # 앱 시작점 (여기서 실행)
├── requirements.txt         # 필요한 패키지 목록
├── SQL_Tuner.spec           # .exe 빌드 설정
│
├── core/                    # 핵심 로직 (DB 연결, 분석)
│   ├── oracle_client.py     # Oracle DB 연결 및 쿼리 실행
│   ├── plan_analyzer.py     # 실행 계획에서 문제 찾기
│   ├── tns_parser.py        # tnsnames.ora 파일 읽기
│   └── tuning_rules.py      # SQL 텍스트에서 문제 찾기
│
├── ui/                      # 화면 구성
│   ├── main_window.py       # 메인 창 (SQL 입력, 결과 탭)
│   └── connection_dialog.py # DB 연결 설정 창
│
└── *.bat                    # Windows 편의 스크립트
```

---

## 파일별 역할 설명

### core/oracle_client.py
Oracle DB와 실제로 통신하는 모듈.

- `OracleClient` 클래스가 핵심
- `connect()` : DB에 접속
- `explain_plan()` : SQL의 실행 계획을 가져옴
- `get_dbms_xplan()` : Oracle이 보여주는 텍스트 형태 플랜
- `get_sql_stats()` : 실제로 실행된 SQL의 성능 이력 조회
- **Oracle Thick Mode** 사용 → 컴퓨터에 Oracle Client가 설치되어 있어야 함

### core/plan_analyzer.py
가져온 실행 계획에서 성능 문제를 찾는 모듈.

감지하는 문제 7가지:
| 문제 | 심각도 |
|------|--------|
| Full Table Scan (전체 테이블 조회) | HIGH |
| Cartesian Join (조건 없는 조인) | HIGH |
| SORT DISK 사용 (메모리 부족) | HIGH |
| Index Full Scan | MEDIUM |
| 비용이 집중된 노드 | INFO |
| 대용량 Nested Loop Join | MEDIUM |
| 테이블 통계 없음 | MEDIUM |

### core/tuning_rules.py
SQL 텍스트 자체를 읽어서 나쁜 패턴을 찾는 모듈.

감지하는 패턴 10가지:
| 패턴 | 심각도 |
|------|--------|
| `UPDATE/DELETE` WHERE 절 없음 | HIGH |
| `WHERE 컬럼함수()` (인덱스 무효화) | MEDIUM |
| 묵시적 형변환 (숫자컬럼 = '숫자') | MEDIUM |
| `NOT IN` 서브쿼리 NULL 위험 | MEDIUM |
| `LIKE '%값'` 앞 와일드카드 | MEDIUM |
| 스칼라 서브쿼리 3개 이상 | MEDIUM |
| `SELECT *` 사용 | LOW |
| OR 조건 3개 이상 | LOW |
| DISTINCT + JOIN 조합 | INFO |
| UNION (UNION ALL 고려) | INFO |

### core/tns_parser.py
Oracle 연결 정보가 담긴 `tnsnames.ora` 파일을 자동으로 찾아서 읽는 모듈.
- 환경변수 `TNS_ADMIN` → `ORACLE_HOME` → 일반 설치 경로 순서로 탐색

### ui/main_window.py
메인 화면. 탭 4개로 구성:
1. **Plan Tree** : 실행 계획을 계층 트리로 표시 (FTS는 빨간색)
2. **DBMS_XPLAN** : Oracle이 출력하는 텍스트 형식 플랜
3. **튜닝 제안** : 감지된 문제 목록 + 개선 방법
4. **V$SQL 통계** : 실제 실행 이력 (횟수, 소요 시간, I/O)

분석은 백그라운드 스레드(`PlanWorker`)에서 실행되므로 UI가 멈추지 않는다.

### ui/connection_dialog.py
DB 연결 정보를 입력하는 창. 마지막 입력값을 자동으로 기억한다 (QSettings 사용).

---

## 개발 환경 설정

### 1. Python 설치

Python 3.13 이 필요합니다. (3.14는 oracledb 패키지 미지원)

python.org에서 **"Windows installer (64-bit)"** 를 받아 설치하세요.
설치 시 **"Add python.exe to PATH" 체크 해제** (다른 버전과 충돌 방지)

### 2. 패키지 설치
```bash
# 인터넷 연결 있을 때
install_online.bat

# 또는 직접 설치
py -3.13 -m pip install PyQt6 oracledb sqlparse
```

### 3. 실행
```bash
run.bat
# 또는
py -3.13 main.py
```

### 3. 환경 점검
```bash
check_env.bat
# Python, 패키지, Oracle Client 설치 여부를 자동으로 확인해줌
```

---

## .exe 파일로 배포하기

Python이 없는 PC에서도 실행할 수 있게 단일 폴더로 만드는 방법:

```bash
build_exe.bat
```

빌드 완료 후 `dist/SQL Tuner/` 폴더가 생성됨. 이 폴더째로 복사하면 배포 완료.

> 단, 실행하는 PC에 **Oracle Client는 별도로 설치**되어 있어야 한다.

---

## 앱 실행 흐름 (한눈에 보기)

```
앱 실행
  │
  ▼
[DB 연결] 버튼 클릭
  │  → tnsnames.ora 자동 탐색
  │  → TNS 별칭 목록 표시
  │  → 사용자명 / 비밀번호 입력
  │
  ▼
Oracle DB 접속 성공 → 상태바에 "연결됨" 표시
  │
  ▼
SQL 입력창에 SQL 작성
  │
  ▼
[실행 계획 분석] 클릭 (또는 Ctrl+Enter)
  │
  ▼
백그라운드에서 분석 실행
  ├─ EXPLAIN PLAN 조회
  ├─ DBMS_XPLAN 텍스트 조회
  ├─ 실행 계획 이슈 분석 (7가지 규칙)
  ├─ SQL 텍스트 이슈 분석 (10가지 규칙)
  └─ V$SQL 실행 이력 조회
  │
  ▼
결과 탭에 표시
```

---

## 주의사항

- Oracle **Thick Client**가 설치된 환경에서만 동작 (thin 모드 미사용)
- DB 계정에 `PLAN_TABLE` 쓰기 권한과 `V$SQL` 조회 권한이 필요
- Windows 전용 배포 (`.bat` 스크립트 기반)
- `Ctrl+Enter` 단축키로 빠르게 분석 가능

---

## 코드 수정 시 참고사항

| 하고 싶은 것 | 수정할 파일 |
|-------------|------------|
| 새로운 실행 계획 분석 규칙 추가 | `core/plan_analyzer.py` |
| 새로운 SQL 안티패턴 추가 | `core/tuning_rules.py` |
| 화면 레이아웃 변경 | `ui/main_window.py` |
| DB 연결 방식 변경 | `core/oracle_client.py` |
| 연결 다이얼로그 수정 | `ui/connection_dialog.py` |
| .exe 빌드 설정 변경 | `SQL_Tuner.spec` |
