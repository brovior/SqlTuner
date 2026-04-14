# Oracle SQL Tuner v2

Oracle DB의 SQL 성능을 분석하고 개선 제안을 해주는 Windows 데스크톱 앱입니다.

SQL을 붙여넣으면 실행 계획(EXPLAIN PLAN)을 분석하여 인덱스 문제·안티패턴을 감지하고,
AI(로컬 Ollama 또는 OpenAI)를 활용한 SQL 재작성 제안을 제공합니다.

---

## 사전 설치 항목

### 1. Python 3.13 32-bit

> **반드시 32-bit** — 64-bit 혼용 시 Oracle Client와 충돌(DPI-1047)

- 다운로드: https://www.python.org/downloads/
- 설치 후 확인: `py -3.13-32 --version`

### 2. Oracle Instant Client (선택)

Thick 모드로 전체 기능을 사용하려면 필요합니다.
설치 없으면 Thin 모드로 자동 전환됩니다.

- 다운로드: https://www.oracle.com/database/technologies/instant-client/winsoft-downloads.html
- **32-bit** 버전 선택

### 3. Ollama (로컬 AI, 선택)

- 다운로드: https://ollama.com/download
- 모델 설치:
  ```
  ollama pull qwen2.5-coder:7b
  ```

---

## 설치

프로젝트 루트(`SQL Tuner/`)에서 실행합니다.

```bat
install_online_v2.bat
```

패키지 목록: `v2/requirements.txt` (PyQt5, oracledb, sqlglot, openai, pytest)

---

## 실행

```bat
run_v2.bat
```

또는 직접:

```bat
py -3.13-32 -m v2.main
```

환경 점검:

```bat
check_env_v2.bat
```

---

## Oracle Docker 로컬 테스트 환경

로컬에서 Oracle DB 없이 테스트할 수 있습니다.

```bat
cd v2\test_data
docker compose up -d

:: 준비 완료 대기 (DATABASE IS READY TO USE! 메시지 확인)
docker logs -f oracle-xe
docker run -d --name oracle-free -p 1521:1521 -e ORACLE_PASSWORD=test123 gvenzl/oracle-free:slim
```

### 연결 정보

| 항목 | 값 |
|------|-----|
| Host | localhost |
| Port | 1521 |
| Service | FREEPDB1 |
| 유저 | system |
| 비밀번호 | test123 |

앱에서 **[DB 연결]** → TNS 직접 입력 탭 → 위 값 입력 localhost:1521/FREEPDB1

---

## AI 설정 방법

툴바 **[AI 설정]** 버튼에서 AI 제공자를 선택합니다.

### Ollama (로컬, 무료 권장)

| 항목 | 값 |
|------|-----|
| 제공자 | OpenAI 호환 |
| Base URL | `http://localhost:11434/v1` |
| Model | `qwen2.5-coder:7b` |
| API Key | (비워 두거나 임의 문자) |

### OpenAI

| 항목 | 값 |
|------|-----|
| 제공자 | OpenAI |
| API Key | `sk-...` |
| Model | `gpt-4o` 등 |

---

## 단축키

| 동작 | 단축키 |
|------|--------|
| 실행 계획 분석 | `Ctrl+Enter` |
| SQL 직접 실행 | `Ctrl+Shift+Enter` |

---

## 테스트 실행

```bat
run_tests_v2.bat
```

또는:

```bat
py -3.13-32 -m pytest v2/tests/ -v
```
