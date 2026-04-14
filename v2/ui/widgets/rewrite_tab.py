"""
튜닝된 SQL 탭 위젯

세 개의 섹션:
  1. 규칙 기반 자동 재작성 (CompositeRewriter)
  2. AI 튜닝 제안 (AiSqlTuner via AiTuneWorker)
  3. 검증 결과 (TuningValidator via ValidateWorker)
"""
from __future__ import annotations

import webbrowser

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox,
    QPlainTextEdit, QTextEdit, QPushButton, QLabel,
    QApplication, QCheckBox, QFileDialog, QMessageBox,
)
from PyQt5.QtGui import QFont

from v2.core.rewrite.composite_rewriter import CompositeRewriter
from v2.core.ai.ai_tuner import AiSqlTuner
from v2.core.db.oracle_client import OracleClient
from v2.core.pipeline.validation import ValidationResult
from v2.core.report.tuning_report import TuningReporter
from v2.ui.workers.ai_tune_worker import AiTuneWorker
from v2.ui.workers.validate_worker import ValidateWorker
from v2.ui.widgets.sql_editor import SqlHighlighter


class RewriteTab(QWidget):
    """
    규칙 재작성 + AI 튜닝 + 검증 결과를 하나의 탭에 표시합니다.

    외부 의존 주입:
      set_client(client)  — ValidateWorker 용
      set_tuner(tuner)    — AiTuneWorker 용
      refresh(sql, issues) — 분석 완료 후 호출
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._client: OracleClient | None = None
        self._tuner: AiSqlTuner | None = None
        self._rewriter = CompositeRewriter()
        self._ai_worker: AiTuneWorker | None = None
        self._validate_worker: ValidateWorker | None = None
        self._last_validation: ValidationResult | None = None
        self._last_tuned_sql: str = ''
        self._current_sql: str = ''
        self._current_issues: list = []
        self._db_version: str = ''
        # 분석 완료 시 채워지는 추가 컨텍스트 (AI 프롬프트에 포함)
        self._index_infos: list = []
        self._stats_infos: list = []
        self._plan_rows: list = []

        self._build_ui()

    # ── 외부 인터페이스 ──────────────────────────

    def set_client(self, client: OracleClient):
        self._client = client

    def set_db_version(self, version: str):
        self._db_version = version

    def set_tuner(self, tuner: AiSqlTuner):
        self._tuner = tuner
        self._btn_ai_tune.setEnabled(
            tuner.is_available and bool(self._current_sql)
        )

    def update_ai_provider_label(self, label: str):
        self._ai_provider_label.setText(f'제공자: {label}')

    def refresh(
        self,
        sql: str,
        issues: list,
        index_infos: list | None = None,
        stats_infos: list | None = None,
        plan_rows: list | None = None,
    ):
        """분석 완료 후 MainWindow 가 호출. 규칙 재작성 자동 실행."""
        self._current_sql = sql
        self._current_issues = issues
        self._index_infos = index_infos or []
        self._stats_infos = stats_infos or []
        self._plan_rows = plan_rows or []
        self._populate_rule_rewrite(sql)
        self._ai_sql_edit.clear()
        self._clear_validation()
        if self._tuner:
            self._btn_ai_tune.setEnabled(self._tuner.is_available)

    def clear(self):
        self._current_sql = ''
        self._current_issues = []
        self._index_infos = []
        self._stats_infos = []
        self._plan_rows = []
        self._rewrite_changes_label.setText('분석 실행 후 자동으로 표시됩니다.')
        self._rewrite_changes_label.setStyleSheet('color: #888888;')
        self._rewrite_sql_edit.clear()
        self._ai_sql_edit.clear()
        self._btn_ai_tune.setEnabled(False)
        self._clear_validation()

    # ── UI 구성 ──────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        layout.addWidget(self._build_rule_group(), 1)
        layout.addWidget(self._build_ai_group(), 1)
        layout.addWidget(self._build_validation_group())

    def _build_rule_group(self) -> QGroupBox:
        group = QGroupBox('규칙 기반 자동 재작성')
        vbox = QVBoxLayout(group)
        vbox.setSpacing(6)

        self._rewrite_changes_label = QLabel('분석 실행 후 자동으로 표시됩니다.')
        self._rewrite_changes_label.setWordWrap(True)
        self._rewrite_changes_label.setStyleSheet('color: #888888;')
        vbox.addWidget(self._rewrite_changes_label)

        self._rewrite_sql_edit = QPlainTextEdit()
        self._rewrite_sql_edit.setReadOnly(True)
        self._rewrite_sql_edit.setFont(QFont('Consolas', 10))
        self._rewrite_sql_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        SqlHighlighter(self._rewrite_sql_edit.document())
        vbox.addWidget(self._rewrite_sql_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_copy = QPushButton('클립보드에 복사')
        btn_copy.setFixedWidth(120)
        btn_copy.clicked.connect(
            lambda: QApplication.clipboard().setText(self._rewrite_sql_edit.toPlainText())
        )
        btn_row.addWidget(btn_copy)
        vbox.addLayout(btn_row)

        return group

    def _build_ai_group(self) -> QGroupBox:
        group = QGroupBox('AI 튜닝 제안')
        vbox = QVBoxLayout(group)
        vbox.setSpacing(6)

        top_row = QHBoxLayout()
        self._ai_provider_label = QLabel('제공자: -')
        self._ai_provider_label.setStyleSheet('color: #555555;')
        top_row.addWidget(self._ai_provider_label)
        top_row.addStretch()
        vbox.addLayout(top_row)

        self._ai_sql_edit = QPlainTextEdit()
        self._ai_sql_edit.setReadOnly(True)
        self._ai_sql_edit.setFont(QFont('Consolas', 10))
        self._ai_sql_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self._ai_sql_edit.setPlaceholderText(
            'AI 튜닝 요청 버튼을 클릭하면 이곳에 튜닝된 SQL이 표시됩니다.\n'
            'AI 설정이 필요하면 툴바의 [AI 설정] 버튼을 사용하세요.'
        )
        SqlHighlighter(self._ai_sql_edit.document())
        vbox.addWidget(self._ai_sql_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        btn_copy_ai = QPushButton('클립보드에 복사')
        btn_copy_ai.setFixedWidth(120)
        btn_copy_ai.clicked.connect(
            lambda: QApplication.clipboard().setText(self._ai_sql_edit.toPlainText())
        )
        btn_row.addWidget(btn_copy_ai)

        self._btn_ai_tune = QPushButton('AI 튜닝 요청')
        self._btn_ai_tune.setFixedWidth(120)
        self._btn_ai_tune.setEnabled(False)
        self._btn_ai_tune.clicked.connect(self._on_ai_tune_clicked)
        btn_row.addWidget(self._btn_ai_tune)

        self._chk_measure_time = QCheckBox('실행시간 측정')
        self._chk_measure_time.setToolTip(
            '실제 SQL을 실행하여 원본/튜닝 SQL의 실행시간을 비교합니다\n'
            '(SELECT / WITH 전용 — DML은 거부됩니다)'
        )
        btn_row.addWidget(self._chk_measure_time)

        self._btn_validate = QPushButton('검증 실행')
        self._btn_validate.setFixedWidth(100)
        self._btn_validate.setEnabled(False)
        self._btn_validate.setToolTip('AI 튜닝 결과와 원본 SQL의 실행 계획을 비교합니다')
        self._btn_validate.clicked.connect(self._on_validate_clicked)
        btn_row.addWidget(self._btn_validate)

        vbox.addLayout(btn_row)
        return group

    def _build_validation_group(self) -> QGroupBox:
        group = QGroupBox('검증 결과')
        vbox = QVBoxLayout(group)

        self._validation_text = QTextEdit()
        self._validation_text.setReadOnly(True)
        self._validation_text.setFont(QFont('Consolas', 10))
        self._validation_text.setMaximumHeight(160)
        self._validation_text.setPlaceholderText(
            '[검증 실행] 버튼을 클릭하면 원본 SQL과 AI 튜닝 SQL의 실행 계획을 비교합니다.'
        )
        vbox.addWidget(self._validation_text)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._btn_save_report = QPushButton('리포트 저장')
        self._btn_save_report.setFixedWidth(110)
        self._btn_save_report.setEnabled(False)
        self._btn_save_report.setToolTip('검증 결과를 HTML 리포트로 저장하고 브라우저에서 엽니다')
        self._btn_save_report.clicked.connect(self._on_save_report_clicked)
        btn_row.addWidget(self._btn_save_report)
        vbox.addLayout(btn_row)

        return group

    # ── 규칙 재작성 ──────────────────────────────

    def _populate_rule_rewrite(self, sql: str):
        result = self._rewriter.rewrite(sql)
        if result.has_changes:
            bullets = '\n'.join(f'  • {c}' for c in result.changes)
            self._rewrite_changes_label.setText(
                f'적용된 변환 [{result.engine_used}]:\n{bullets}'
            )
            self._rewrite_changes_label.setStyleSheet('color: #006600;')
            self._rewrite_sql_edit.setPlainText(result.rewritten_sql)
        else:
            self._rewrite_changes_label.setText(
                '자동 적용 가능한 변환이 없습니다. (원본 SQL 표시 중)'
            )
            self._rewrite_changes_label.setStyleSheet('color: #888888;')
            self._rewrite_sql_edit.setPlainText(sql)

    # ── AI 튜닝 ──────────────────────────────────

    def _on_ai_tune_clicked(self):
        if not self._current_sql or not self._tuner:
            return
        self._btn_ai_tune.setEnabled(False)
        self._btn_ai_tune.setText('요청 중...')
        self._btn_validate.setEnabled(False)
        self._ai_sql_edit.setPlainText('AI 튜닝 요청 중입니다...')

        self._ai_worker = AiTuneWorker(
            self._tuner,
            self._current_sql,
            self._current_issues,
            self._db_version,
            index_infos=self._index_infos or None,
            stats_infos=self._stats_infos or None,
            plan_rows=self._plan_rows or None,
        )
        self._ai_worker.finished.connect(self._on_ai_done)
        self._ai_worker.error.connect(self._on_ai_error)
        self._ai_worker.start()

    def _on_ai_done(self, result: str):
        self._ai_sql_edit.setPlainText(result)
        self._btn_ai_tune.setEnabled(True)
        self._btn_ai_tune.setText('AI 튜닝 요청')
        self._btn_validate.setEnabled(bool(result.strip()))

    def _on_ai_error(self, msg: str):
        self._ai_sql_edit.setPlainText(f'[오류] {msg}')
        self._btn_ai_tune.setEnabled(True)
        self._btn_ai_tune.setText('AI 튜닝 요청')

    # ── 검증 ─────────────────────────────────────

    def _on_validate_clicked(self):
        if not self._client or not self._current_sql:
            return
        tuned_sql = self._ai_sql_edit.toPlainText().strip()
        if not tuned_sql:
            return

        self._btn_validate.setEnabled(False)
        self._btn_validate.setText('검증 중...')
        self._validation_text.setPlainText('검증 중입니다...')

        self._validate_worker = ValidateWorker(
            self._client,
            self._current_sql,
            tuned_sql,
            measure_time=self._chk_measure_time.isChecked(),
        )
        self._validate_worker.finished.connect(self._on_validate_done)
        self._validate_worker.error.connect(self._on_validate_error)
        self._validate_worker.start()

    def _on_validate_done(self, result: ValidationResult):
        self._last_validation = result
        self._last_tuned_sql = self._ai_sql_edit.toPlainText().strip()
        self._btn_validate.setEnabled(True)
        self._btn_validate.setText('검증 실행')
        self._btn_save_report.setEnabled(result.is_valid)
        self._display_validation(result)

    def _on_validate_error(self, msg: str):
        self._btn_validate.setEnabled(True)
        self._btn_validate.setText('검증 실행')
        self._validation_text.setPlainText(f'[검증 오류]\n{msg}')

    # 판정별 배경/글자 색상
    _VERDICT_STYLE: dict[str, tuple[str, str]] = {
        'APPROVE': ('#d4edda', '#155724'),   # 초록
        'REVIEW':  ('#fff3cd', '#856404'),   # 노랑
        'REJECT':  ('#f8d7da', '#721c24'),   # 빨강
    }

    def _display_validation(self, r: ValidationResult):
        bg, fg = self._VERDICT_STYLE.get(r.verdict, ('#ffffff', '#000000'))

        # ── 판정 헤더 (색상 배경) ──
        reasons_html = '  /  '.join(r.verdict_reasons) if r.verdict_reasons else ''
        header = (
            f'<div style="background:{bg};color:{fg};padding:6px 8px;'
            f'border-radius:4px;font-weight:bold;">'
            f'{r.verdict_label}'
            f'{"<br/><span style=\'font-weight:normal;font-size:0.9em\'>" + reasons_html + "</span>" if reasons_html else ""}'
            f'</div>'
        )

        # ── 본문 ──
        body_lines: list[str] = []

        if r.is_valid:
            body_lines.append(r.cost_summary)
            if r.original_elapsed_ms is not None:
                body_lines.append(r.elapsed_summary)
            body_lines.append('')

            if r.resolved_issues:
                body_lines.append(f'해결된 이슈 ({len(r.resolved_issues)}건):')
                for i in r.resolved_issues:
                    body_lines.append(f'  ✓ [{i.severity}] {i.title}')
                body_lines.append('')

            if r.new_issues:
                body_lines.append(f'새로 생긴 이슈 ({len(r.new_issues)}건):')
                for i in r.new_issues:
                    body_lines.append(f'  ! [{i.severity}] {i.title}')
        else:
            body_lines.append(r.error_message)

        body_html = '<pre style="margin:6px 0 0 0;">' + '\n'.join(body_lines) + '</pre>'
        self._validation_text.setHtml(header + body_html)

    def _clear_validation(self):
        self._validation_text.clear()
        self._last_validation = None
        self._last_tuned_sql = ''
        self._btn_validate.setEnabled(False)
        self._btn_validate.setText('검증 실행')
        self._btn_save_report.setEnabled(False)

    # ── 리포트 저장 ───────────────────────────────

    def _on_save_report_clicked(self):
        if not self._last_validation or not self._current_sql:
            return

        path, _ = QFileDialog.getSaveFileName(
            self,
            '리포트 저장',
            'tuning_report.html',
            'HTML 파일 (*.html)',
        )
        if not path:
            return

        try:
            TuningReporter().save_html(
                path,
                self._current_sql,
                self._last_tuned_sql,
                self._last_validation,
            )
            webbrowser.open(path)
        except Exception as e:
            QMessageBox.warning(self, '저장 오류', f'리포트 저장 중 오류가 발생했습니다.\n{e}')
