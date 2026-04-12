"""
AI 제공자 설정 다이얼로그
provider_type / api_key / base_url / model 을 입력하고 config.ini 에 저장합니다.
"""
from __future__ import annotations
import os
import base64

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton,
    QGroupBox, QMessageBox,
)
from PyQt5.QtCore import Qt, QSettings

from v2.core.ai.ai_provider import AIProviderConfig, create_provider

_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'config.ini',
)

_PROVIDER_OPTIONS = [
    ('none',              '사용 안함'),
    ('claude',            'Claude  (Anthropic API)'),
    ('openai_compatible', 'OpenAI 호환 API  (사내 LLM / Azure / Ollama 등)'),
]


class AISettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('AI 튜닝 설정')
        self.setMinimumWidth(500)
        self.setModal(True)

        self._settings = QSettings(_CONFIG_PATH, QSettings.IniFormat)
        self._build_ui()
        self._restore()
        self._on_type_changed()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        group = QGroupBox('AI 제공자 설정')
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        self._type_combo = QComboBox()
        for key, label in _PROVIDER_OPTIONS:
            self._type_combo.addItem(label, key)
        self._type_combo.currentIndexChanged.connect(self._on_type_changed)
        form.addRow('제공자:', self._type_combo)

        self._api_key_edit = QLineEdit()
        self._api_key_edit.setEchoMode(QLineEdit.Password)
        self._api_key_edit.setPlaceholderText('API 키 입력')
        form.addRow('API 키:', self._api_key_edit)

        self._base_url_label = QLabel('API URL:')
        self._base_url_edit = QLineEdit()
        self._base_url_edit.setPlaceholderText('http://내부서버:8080/v1')
        form.addRow(self._base_url_label, self._base_url_edit)

        self._model_edit = QLineEdit()
        self._model_edit.setPlaceholderText('예: claude-opus-4-6 / gpt-4o / llama3')
        form.addRow('모델명:', self._model_edit)

        layout.addWidget(group)

        self._hint_label = QLabel()
        self._hint_label.setWordWrap(True)
        self._hint_label.setStyleSheet('color: #555555; font-size: 9pt;')
        layout.addWidget(self._hint_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_test = QPushButton('연결 테스트')
        self._btn_test.setMinimumWidth(100)
        self._btn_test.clicked.connect(self._on_test)
        btn_layout.addWidget(self._btn_test)

        btn_save = QPushButton('저장')
        btn_save.setDefault(True)
        btn_save.setMinimumWidth(80)
        btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(btn_save)

        btn_cancel = QPushButton('취소')
        btn_cancel.setMinimumWidth(80)
        btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(btn_cancel)

        layout.addLayout(btn_layout)

    def _on_type_changed(self):
        ptype = self._type_combo.currentData()
        is_none   = ptype == 'none'
        is_compat = ptype == 'openai_compatible'

        self._api_key_edit.setEnabled(not is_none)
        self._base_url_label.setVisible(is_compat)
        self._base_url_edit.setVisible(is_compat)
        self._btn_test.setEnabled(not is_none)

        hints = {
            'none': 'AI 튜닝 기능이 비활성화됩니다.',
            'claude': (
                'Anthropic API 키를 입력하세요.\n'
                '모델 예시: claude-opus-4-6, claude-sonnet-4-6'
            ),
            'openai_compatible': (
                'OpenAI 호환 엔드포인트 URL과 모델명을 입력하세요.\n'
                '사내 LLM, Azure OpenAI, Ollama 등 대부분의 호환 API를 지원합니다.\n'
                'API 키가 필요 없는 경우 비워 두세요.'
            ),
        }
        self._hint_label.setText(hints.get(ptype, ''))

    def _on_test(self):
        config = self._current_config()
        provider = create_provider(config)
        if not provider.is_configured:
            QMessageBox.warning(self, '설정 오류', '필수 항목(URL, 모델명 등)을 모두 입력하세요.')
            return

        self._btn_test.setEnabled(False)
        self._btn_test.setText('테스트 중...')
        try:
            result = provider.complete('You are a helpful assistant.', 'Reply with exactly: OK')
            QMessageBox.information(
                self, '연결 성공',
                f'AI 응답 확인 완료.\n응답 미리보기: {result[:120]}',
            )
        except Exception as e:
            QMessageBox.critical(self, '연결 실패', str(e))
        finally:
            self._btn_test.setEnabled(True)
            self._btn_test.setText('연결 테스트')

    def _on_save(self):
        config = self._current_config()
        self._settings.setValue('AI/provider_type', config.provider_type)
        encoded_key = base64.b64encode(config.api_key.encode()).decode() if config.api_key else ''
        self._settings.setValue('AI/api_key', encoded_key)
        self._settings.setValue('AI/base_url', config.base_url)
        self._settings.setValue('AI/model', config.model)
        self._settings.sync()
        self.accept()

    def _restore(self):
        ptype = self._settings.value('AI/provider_type', 'none')
        idx = next((i for i, (k, _) in enumerate(_PROVIDER_OPTIONS) if k == ptype), 0)
        self._type_combo.setCurrentIndex(idx)

        raw_key = self._settings.value('AI/api_key', '')
        if raw_key:
            try:
                self._api_key_edit.setText(base64.b64decode(raw_key.encode()).decode())
            except Exception:
                pass

        self._base_url_edit.setText(self._settings.value('AI/base_url', ''))
        self._model_edit.setText(self._settings.value('AI/model', ''))

    def _current_config(self) -> AIProviderConfig:
        return AIProviderConfig(
            provider_type=self._type_combo.currentData(),
            api_key=self._api_key_edit.text().strip(),
            base_url=self._base_url_edit.text().strip(),
            model=self._model_edit.text().strip(),
        )
