"""
SQL 튜닝 리포트 생성기

TuningReporter.generate_html(original_sql, tuned_sql, result) → 단독 열람 가능한 HTML 문자열
TuningReporter.save_html(path, original_sql, tuned_sql, result) → 파일 저장

외부 파일 의존 없이 CSS 인라인 포함 — 브라우저로 바로 열 수 있습니다.
"""
from __future__ import annotations

import html
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..pipeline.validation import ValidationResult


# ── 색상 상수 ─────────────────────────────────────────────────────
_VERDICT_COLORS: dict[str, dict[str, str]] = {
    'APPROVE': {'bg': '#d4edda', 'fg': '#155724', 'border': '#c3e6cb', 'badge': '#28a745'},
    'REVIEW':  {'bg': '#fff3cd', 'fg': '#856404', 'border': '#ffeeba', 'badge': '#ffc107'},
    'REJECT':  {'bg': '#f8d7da', 'fg': '#721c24', 'border': '#f5c6cb', 'badge': '#dc3545'},
}
_DEFAULT_COLORS = {'bg': '#e2e3e5', 'fg': '#383d41', 'border': '#d6d8db', 'badge': '#6c757d'}

_SEVERITY_COLOR: dict[str, str] = {
    'HIGH':   '#dc3545',
    'MEDIUM': '#fd7e14',
    'LOW':    '#ffc107',
    'INFO':   '#17a2b8',
}

# ── 인라인 CSS ────────────────────────────────────────────────────
_CSS = """
*, *::before, *::after { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  font-size: 14px; line-height: 1.6;
  background: #f8f9fa; color: #212529;
  margin: 0; padding: 24px;
}
h1 { font-size: 1.6rem; margin: 0 0 4px; }
h2 { font-size: 1.15rem; margin: 0 0 12px; border-bottom: 2px solid #dee2e6; padding-bottom: 6px; }
h3 { font-size: 1rem; margin: 12px 0 6px; }
.meta { color: #6c757d; font-size: 0.85rem; margin-bottom: 24px; }
section { background: #fff; border: 1px solid #dee2e6; border-radius: 8px;
          padding: 20px 24px; margin-bottom: 20px; }

/* 판정 배지 */
.verdict-badge {
  display: inline-block; padding: 8px 20px;
  border-radius: 20px; font-weight: 700; font-size: 1rem;
  letter-spacing: 0.05em; margin-bottom: 16px;
  color: #fff;
}
.verdict-reasons { margin: 0 0 16px; padding: 10px 14px;
  border-radius: 6px; font-size: 0.9rem; }
.verdict-reasons ul { margin: 4px 0 0; padding-left: 20px; }
.verdict-reasons li { margin-bottom: 2px; }

/* SQL 나란히 */
.sql-compare { display: flex; gap: 16px; }
.sql-box { flex: 1; min-width: 0; }
.sql-box h3 { font-size: 0.9rem; color: #495057; margin: 0 0 6px; }
pre.sql {
  background: #f1f3f5; border: 1px solid #dee2e6; border-radius: 4px;
  padding: 12px; font-size: 0.82rem; white-space: pre-wrap; word-break: break-word;
  margin: 0; overflow-x: auto;
}

/* 성능 테이블 */
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th { background: #f1f3f5; text-align: left; padding: 8px 12px;
     border: 1px solid #dee2e6; font-weight: 600; }
td { padding: 8px 12px; border: 1px solid #dee2e6; }
tr:nth-child(even) td { background: #f8f9fa; }
.delta-good { color: #155724; font-weight: 600; }
.delta-bad  { color: #721c24; font-weight: 600; }
.delta-neutral { color: #495057; }

/* 이슈 목록 */
.issue-list { list-style: none; margin: 0; padding: 0; }
.issue-list li {
  padding: 8px 12px; border-radius: 4px; margin-bottom: 6px;
  font-size: 0.88rem; border-left: 4px solid;
}
.issue-resolved { background: #d4edda; border-color: #28a745; }
.issue-new      { background: #f8d7da; border-color: #dc3545; }
.severity-badge {
  display: inline-block; padding: 1px 7px; border-radius: 10px;
  font-size: 0.75rem; font-weight: 700; color: #fff; margin-right: 6px;
  vertical-align: middle;
}
.empty-note { color: #6c757d; font-style: italic; font-size: 0.88rem; }
"""


class TuningReporter:
    """
    ValidationResult 를 받아 단독 열람 가능한 HTML 리포트를 생성합니다.
    """

    def generate_html(
        self,
        original_sql: str,
        tuned_sql: str,
        result: 'ValidationResult',
    ) -> str:
        """완전한 HTML 문서 문자열을 반환합니다."""
        colors = _VERDICT_COLORS.get(result.verdict, _DEFAULT_COLORS)
        generated_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        sections = [
            self._section_summary(original_sql, tuned_sql, result, colors),
            self._section_performance(result),
            self._section_issues(result),
            self._section_reasons(result, colors),
        ]

        body = '\n'.join(sections)
        return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SQL 튜닝 리포트</title>
  <style>{_CSS}</style>
</head>
<body>
  <h1>SQL 튜닝 리포트</h1>
  <p class="meta">생성 시각: {generated_at}</p>
  {body}
</body>
</html>"""

    def save_html(
        self,
        path: str,
        original_sql: str,
        tuned_sql: str,
        result: 'ValidationResult',
    ) -> None:
        """HTML 리포트를 파일로 저장합니다."""
        content = self.generate_html(original_sql, tuned_sql, result)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    # ------------------------------------------------------------------
    # 섹션 빌더
    # ------------------------------------------------------------------

    def _section_summary(
        self,
        original_sql: str,
        tuned_sql: str,
        result: 'ValidationResult',
        colors: dict[str, str],
    ) -> str:
        badge_label = {
            'APPROVE': '✅ APPROVE — 승인',
            'REVIEW':  '🔍 REVIEW — 검토 필요',
            'REJECT':  '❌ REJECT — 반려',
        }.get(result.verdict, result.verdict)

        orig_escaped = html.escape(original_sql)
        tuned_escaped = html.escape(tuned_sql)

        return f"""
  <section>
    <h2>요약</h2>
    <span class="verdict-badge" style="background:{colors['badge']};">{badge_label}</span>
    <div class="sql-compare">
      <div class="sql-box">
        <h3>원본 SQL</h3>
        <pre class="sql">{orig_escaped}</pre>
      </div>
      <div class="sql-box">
        <h3>튜닝 SQL</h3>
        <pre class="sql">{tuned_escaped}</pre>
      </div>
    </div>
  </section>"""

    def _section_performance(self, result: 'ValidationResult') -> str:
        rows: list[str] = []

        # Cost 행
        orig_cost = f"{result.original_cost:,}" if result.original_cost is not None else '—'
        tuned_cost = f"{result.tuned_cost:,}" if result.tuned_cost is not None else '—'
        delta_cost = self._delta_cell(result.cost_delta_pct)
        rows.append(f'<tr><td>Cost</td><td>{orig_cost}</td><td>{tuned_cost}</td><td>{delta_cost}</td></tr>')

        # 실행시간 행 (measure_time=True 시에만)
        if result.original_elapsed_ms is not None:
            orig_ms = f"{result.original_elapsed_ms:.1f} ms"
            tuned_ms = f"{result.tuned_elapsed_ms:.1f} ms" if result.tuned_elapsed_ms is not None else '—'
            delta_ms = self._delta_cell(result.elapsed_delta_pct)
            rows.append(f'<tr><td>실행시간</td><td>{orig_ms}</td><td>{tuned_ms}</td><td>{delta_ms}</td></tr>')

        # Row Count 행 (row_count_match 가 설정된 경우만)
        if result.row_count_match is not None:
            match_str = '일치 ✓' if result.row_count_match else '불일치 ✗'
            match_style = 'delta-good' if result.row_count_match else 'delta-bad'
            rows.append(
                f'<tr><td>결과 행 수</td><td colspan="2">—</td>'
                f'<td><span class="{match_style}">{match_str}</span></td></tr>'
            )

        table_body = '\n'.join(rows)
        return f"""
  <section>
    <h2>성능 비교</h2>
    <table>
      <thead>
        <tr><th>항목</th><th>원본</th><th>튜닝</th><th>변화율</th></tr>
      </thead>
      <tbody>
        {table_body}
      </tbody>
    </table>
  </section>"""

    def _section_issues(self, result: 'ValidationResult') -> str:
        resolved_html = self._issue_list(result.resolved_issues, 'issue-resolved')
        new_html = self._issue_list(result.new_issues, 'issue-new')

        if not result.is_valid:
            error_escaped = html.escape(result.error_message)
            content = f'<p style="color:#721c24;">{error_escaped}</p>'
        else:
            content = f"""
      <h3>해소된 이슈 ({len(result.resolved_issues)}건)</h3>
      {resolved_html}
      <h3 style="margin-top:16px;">신규 이슈 ({len(result.new_issues)}건)</h3>
      {new_html}"""

        return f"""
  <section>
    <h2>이슈 분석</h2>
    {content}
  </section>"""

    def _section_reasons(self, result: 'ValidationResult', colors: dict[str, str]) -> str:
        if not result.verdict_reasons:
            items = '<li class="empty-note">판정 근거 없음</li>'
        else:
            items = '\n'.join(f'<li>{html.escape(r)}</li>' for r in result.verdict_reasons)

        return f"""
  <section>
    <h2>판정 근거</h2>
    <div class="verdict-reasons" style="background:{colors['bg']};color:{colors['fg']};border:1px solid {colors['border']};">
      <strong>{result.verdict}</strong>
      <ul>{items}</ul>
    </div>
  </section>"""

    # ------------------------------------------------------------------
    # 유틸리티
    # ------------------------------------------------------------------

    @staticmethod
    def _delta_cell(pct: float | None) -> str:
        """변화율을 색상 클래스가 붙은 <span> 으로 반환합니다."""
        if pct is None:
            return '<span class="delta-neutral">—</span>'
        sign = '+' if pct >= 0 else ''
        css = 'delta-bad' if pct > 0 else ('delta-good' if pct < 0 else 'delta-neutral')
        return f'<span class="{css}">{sign}{pct:.1f}%</span>'

    @staticmethod
    def _issue_list(issues: list, css_class: str) -> str:
        """이슈 목록을 <ul> HTML 로 변환합니다."""
        if not issues:
            return '<p class="empty-note">없음</p>'

        items: list[str] = []
        for issue in issues:
            sev_color = _SEVERITY_COLOR.get(issue.severity, '#6c757d')
            badge = (
                f'<span class="severity-badge" style="background:{sev_color};">'
                f'{html.escape(issue.severity)}</span>'
            )
            title = html.escape(issue.title)
            desc = html.escape(issue.description) if issue.description else ''
            detail = f' — <small>{desc}</small>' if desc else ''
            items.append(f'<li class="{css_class}">{badge}{title}{detail}</li>')

        return '<ul class="issue-list">' + '\n'.join(items) + '</ul>'
