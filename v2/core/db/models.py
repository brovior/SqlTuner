"""
Oracle DB 관련 데이터 클래스 및 상수 정의
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ConnectionInfo:
    tns_alias: str
    username: str
    password: str
    tns_filepath: str


@dataclass
class PlanRow:
    """EXPLAIN PLAN 한 행"""
    id: int
    parent_id: Optional[int]
    operation: str
    options: str
    object_name: str
    cost: Optional[int]
    cardinality: Optional[int]
    bytes: Optional[int]
    cpu_cost: Optional[int]
    io_cost: Optional[int]
    depth: int = 0
    children: list = field(default_factory=list)

    @property
    def full_operation(self) -> str:
        if self.options:
            return f"{self.operation} {self.options}"
        return self.operation


@dataclass
class SqlStats:
    """V$SQL 실행 통계"""
    sql_id: str
    executions: int
    elapsed_time_ms: float
    cpu_time_ms: float
    buffer_gets: int
    disk_reads: int
    rows_processed: int
    parse_calls: int


# Wait Class → 심각도 매핑
WAIT_CLASS_SEVERITY: dict[str, str] = {
    'User I/O':    'HIGH',
    'Concurrency': 'HIGH',
    'System I/O':  'MEDIUM',
    'Application': 'MEDIUM',
    'Network':     'LOW',
    'Commit':      'LOW',
    'Other':       'INFO',
    'Idle':        'INFO',
}

# Wait Class → 개선 제안
WAIT_CLASS_SUGGESTION: dict[str, str] = {
    'User I/O': (
        '물리적 I/O 병목입니다. 인덱스 추가·재구성으로 Full Table Scan을 줄이세요. '
        'BUFFER_GETS 대비 DISK_READS 비율이 높다면 DB Buffer Cache 크기를 검토하세요.'
    ),
    'Concurrency': (
        '락(Lock) 또는 래치(Latch) 경합이 발생하고 있습니다. '
        '트랜잭션 범위를 줄이거나 커밋 주기를 단축하세요. '
        'V$LOCK, V$SESSION을 조회해 블로킹 세션을 확인하세요.'
    ),
    'System I/O': (
        'Redo 로그 또는 컨트롤 파일 I/O가 발생하고 있습니다. '
        'Redo Log 파일 크기·개수를 늘리거나 빠른 디스크로 이동을 검토하세요.'
    ),
    'Application': (
        '애플리케이션 수준의 대기(예: 락 대기)가 발생하고 있습니다. '
        '트랜잭션 설계 및 커밋 주기를 검토하세요.'
    ),
}


@dataclass
class ResourceMetric:
    """리소스 분석 결과 항목 하나 (V$SESSION_WAIT / V$SQL / V$MYSTAT 공통)"""
    name: str
    category: str
    raw_value: int
    display_value: str
    severity: str
    suggestion: str


@dataclass
class ResourceAnalysis:
    """리소스 분석 결과 전체 (조회 방법 레이블 + 항목 목록 + 폴백 원인)"""
    method: str
    metrics: list = field(default_factory=list)
    error_chain: list = field(default_factory=list)
