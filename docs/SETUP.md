# SQL Tuner v2 - 개발 환경 설정 및 배포 안내

---

## 개발 환경 설정

### 1. Python 설치

Python 3.13이 필요합니다. (3.14는 oracledb 패키지 미지원)

python.org에서 **"Windows installer (32-bit)"** 를 받아 설치하세요.
설치 시 **"Add python.exe to PATH" 체크 해제** (다른 버전과 충돌 방지)

> **중요:** 회사 환경이 **Oracle Client 32-bit**이므로 Python도 반드시 **32-bit** 사용.
> 64-bit Python + 32-bit Oracle Client 조합은 DPI-1047 오류 발생.

---

### 2. 패키지 설치

```bash
# 인터넷 연결 있을 때
install_online_v2.bat

# 또는 직접 설치
py -3.13-32 -m pip install PyQt5 oracledb sqlglot pytest
```

---

### 3. 앱 실행

```bash
run_v2.bat
# 또는
py -3.13-32 v2/main.py
```

---

### 4. 환경 점검

```bash
check_env_v2.bat
# Python, 패키지, Oracle Client 설치 여부를 자동으로 확인해줌
```

---

### 5. 테스트 실행

```bash
run_tests_v2.bat
# 또는
py -3.13-32 -m pytest v2/tests/ -v
```

---

## .exe 파일로 배포하기

Python이 없는 PC에서도 실행 가능하도록 단일 폴더로 빌드:

```bash
build_exe_v2.bat
```

빌드 완료 후 `dist/SQL Tuner v2/` 폴더가 생성됨. 이 폴더째로 복사하면 배포 완료.

> 단, 실행하는 PC에 **Oracle Client 32-bit는 별도로 설치**되어 있어야 한다.

---

## DB 권한 요구사항

앱을 사용하는 DB 계정에 아래 권한이 필요합니다:

| 권한 | 용도 |
|------|------|
| `PLAN_TABLE` 쓰기 | EXPLAIN PLAN 실행 |
| `V$SQL` 조회 | SQL 실행 이력 확인 |
| `ALL_INDEXES`, `ALL_IND_COLUMNS` 조회 | 인덱스 정보 확인 |
| `ALL_TABLES` 조회 | 테이블 통계 확인 |

---

## 연결 모드

| 모드 | 조건 | 특징 |
|------|------|------|
| Thick | Oracle Client 32-bit 설치됨 | 전체 기능 사용 가능 |
| Thin | Oracle Client 미설치 | 기본 기능만 사용 가능, 자동 전환 |

---

## 로컬 AI (Ollama) 설정

| 항목 | 값 |
|------|-----|
| 다운로드 | https://ollama.com/download |
| 모델 설치 | `ollama pull qwen2.5-coder:7b` |
| AI 설정 URL | `http://localhost:11434/v1` |
| AI 설정 Model | `qwen2.5-coder:7b` |

> 앱 실행 후 툴바 **[AI 설정]** 버튼 → 위 값 입력

---

## 오프라인 설치 (인터넷 없는 환경)

1. 인터넷이 되는 PC에서 패키지 다운로드
2. 다운로드된 `.whl` 파일을 대상 PC로 복사
3. `py -3.13-32 -m pip install --no-index --find-links=. PyQt5 oracledb sqlglot`
