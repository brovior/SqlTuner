"""
AI Provider 추상화 레이어
새로운 AI 서비스 추가 시 AIProvider를 상속하여 complete()만 구현하면 됩니다.

지원 제공자:
  - NullProvider         : AI 기능 비활성화
  - ClaudeProvider       : Anthropic Claude API
  - OpenAICompatibleProvider : OpenAI 호환 API (사내 LLM, Azure, Ollama 등)
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class AIProviderConfig:
    """AI 제공자 연결 설정"""
    provider_type: str = 'none'         # 'none' | 'claude' | 'openai_compatible'
    api_key: str = ''
    base_url: str = ''                  # OpenAI 호환 API 엔드포인트
    model: str = ''


class AIProvider(ABC):
    """AI 텍스트 생성 제공자 인터페이스"""

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """시스템 프롬프트와 사용자 메시지를 받아 응답을 반환합니다."""
        ...

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """제공자가 사용 가능한 상태인지 반환합니다."""
        ...

    @property
    def label(self) -> str:
        return '미설정'


# ──────────────────────────────────────────────────────────────
# 구현체
# ──────────────────────────────────────────────────────────────

class NullProvider(AIProvider):
    """AI 기능 비활성화 시 사용하는 빈 제공자"""

    def complete(self, system: str, user: str) -> str:
        raise RuntimeError(
            "AI 제공자가 설정되지 않았습니다.\n"
            "도구 모음의 'AI 설정' 버튼에서 API 키를 입력하세요."
        )

    @property
    def is_configured(self) -> bool:
        return False

    @property
    def label(self) -> str:
        return '사용 안함'


class ClaudeProvider(AIProvider):
    """Anthropic Claude API"""

    def __init__(self, api_key: str, model: str = 'claude-opus-4-6'):
        self._api_key = api_key
        self._model = model or 'claude-opus-4-6'

    def complete(self, system: str, user: str) -> str:
        try:
            import anthropic
        except ImportError:
            raise RuntimeError(
                "anthropic 패키지가 설치되어 있지 않습니다.\n"
                "터미널에서 실행: pip install anthropic"
            )
        client = anthropic.Anthropic(api_key=self._api_key)
        msg = client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=system,
            messages=[{'role': 'user', 'content': user}],
        )
        return msg.content[0].text

    @property
    def is_configured(self) -> bool:
        return bool(self._api_key)

    @property
    def label(self) -> str:
        return f'Claude ({self._model})'


class OpenAICompatibleProvider(AIProvider):
    """
    OpenAI 호환 API 제공자.
    base_url 변경만으로 Azure OpenAI, Ollama, 사내 LLM 등
    모든 OpenAI 호환 엔드포인트에 연결됩니다.
    """

    def __init__(self, api_key: str, base_url: str, model: str):
        self._api_key = api_key or 'dummy'   # 인증 없는 사내 API 대응
        self._base_url = base_url.rstrip('/')
        self._model = model

    def complete(self, system: str, user: str) -> str:
        try:
            import openai
        except ImportError:
            raise RuntimeError(
                "openai 패키지가 설치되어 있지 않습니다.\n"
                "터미널에서 실행: pip install openai"
            )
        client = openai.OpenAI(api_key=self._api_key, base_url=self._base_url)
        resp = client.chat.completions.create(
            model=self._model,
            messages=[
                {'role': 'system', 'content': system},
                {'role': 'user', 'content': user},
            ],
            max_tokens=2048,
        )
        return resp.choices[0].message.content

    @property
    def is_configured(self) -> bool:
        return bool(self._base_url and self._model)

    @property
    def label(self) -> str:
        return f'OpenAI 호환 ({self._model})'


# ──────────────────────────────────────────────────────────────
# 팩토리
# ──────────────────────────────────────────────────────────────

def create_provider(config: AIProviderConfig) -> AIProvider:
    """설정을 바탕으로 적절한 AIProvider 인스턴스를 생성합니다."""
    if config.provider_type == 'claude' and config.api_key:
        return ClaudeProvider(config.api_key, config.model)
    if config.provider_type == 'openai_compatible' and config.base_url and config.model:
        return OpenAICompatibleProvider(config.api_key, config.base_url, config.model)
    return NullProvider()
