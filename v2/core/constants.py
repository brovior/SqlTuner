"""
공유 상수 모듈 — 단일 출처(single source of truth)

여러 모듈에 중복 정의되던 색상·임계값 상수를 일원화한다.
"""
from __future__ import annotations

# ── 심각도 색상 (fg, bg) ──────────────────────────────────────────────────────
SEVERITY_COLORS: dict[str, tuple[str, str]] = {
    'HIGH':   ('#CC0000', '#FFE0E0'),
    'MEDIUM': ('#CC6600', '#FFF3E0'),
    'LOW':    ('#887700', '#FFFFF0'),
    'INFO':   ('#005599', '#E8F4FF'),
}

# ── 실행 계획 분석 임계값 ─────────────────────────────────────────────────────
# Nested Loop Join 내부 집합 행 수 경고 기준
NL_INNER_CARD_THRESHOLD = 50_000
# 통계 부재 의심: cardinality=1이고 cost 가 이 값 초과 시 경고
NO_STATS_COST_THRESHOLD = 100
# High Cost Ratio 검사: root cost 가 이 값 이하면 건너뜀
HIGH_COST_MIN_ROOT = 100

# ── I/O 통계 임계값 ──────────────────────────────────────────────────────────
DISK_READS_HIGH   = 1_000
DISK_READS_MEDIUM = 100
BUFFER_GETS_MEDIUM = 100_000

# V$MYSTAT 세션 통계 임계값
MYSTAT_PHYSICAL_READS_HIGH    = 1_000
MYSTAT_PHYSICAL_READS_MEDIUM  = 100
MYSTAT_LOGICAL_READS_HIGH     = 100_000
MYSTAT_LOGICAL_READS_MEDIUM   = 10_000
MYSTAT_REDO_SIZE_HIGH         = 1_000_000
MYSTAT_REDO_SIZE_MEDIUM       = 100_000

# ── 튜닝 검증 임계값 ─────────────────────────────────────────────────────────
# 비용 변화율(%) 기준: 이 값 초과 시 REJECT, 이하(-) 시 APPROVE 후보
COST_DELTA_WARN_PCT = 10

# ── 테이블 통계 경과일 임계값 (stats_tab) ────────────────────────────────────
STALE_STATS_HIGH_DAYS   = 30
STALE_STATS_MEDIUM_DAYS = 7
