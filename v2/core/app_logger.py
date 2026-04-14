"""
앱 전역 로거 설정

로그 파일: <프로젝트 루트>/logs/sql_tuner.log
  - 최대 5 MB × 3 세대 로테이션
  - 레벨: DEBUG (파일) / WARNING (콘솔)

사용법:
    from v2.core.app_logger import get_logger
    logger = get_logger(__name__)
    logger.error("메시지", exc_info=True)   # 스택 트레이스 포함

로그 파일 경로:
    from v2.core.app_logger import LOG_FILE_PATH
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler

# ── 로그 파일 경로 ────────────────────────────────────────────────
# 이 파일: v2/core/app_logger.py → 두 단계 위가 프로젝트 루트
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_LOG_DIR = os.path.join(_PROJECT_ROOT, 'logs')
LOG_FILE_PATH = os.path.join(_LOG_DIR, 'sql_tuner.log')

# ── 포맷 ─────────────────────────────────────────────────────────
_FMT = '%(asctime)s [%(levelname)s] %(name)s — %(message)s'
_DATE_FMT = '%Y-%m-%d %H:%M:%S'

_initialized = False


def _setup():
    global _initialized
    if _initialized:
        return

    os.makedirs(_LOG_DIR, exist_ok=True)

    root = logging.getLogger('sql_tuner')
    root.setLevel(logging.DEBUG)

    # 파일 핸들러 — 5 MB × 3 세대
    fh = RotatingFileHandler(
        LOG_FILE_PATH,
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding='utf-8',
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_FMT, _DATE_FMT))
    root.addHandler(fh)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """모듈 전용 로거를 반환합니다. 최초 호출 시 파일 핸들러를 설정합니다."""
    _setup()
    # 'sql_tuner.<name>' 네임스페이스로 루트에 전달
    return logging.getLogger(f'sql_tuner.{name}')
