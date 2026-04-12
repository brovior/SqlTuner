"""
AI 기반 SQL 튜닝 모듈
AIProvider를 통해 SQL과 감지된 이슈를 전달하고 튜닝된 SQL을 받습니다.
"""
from __future__ import annotations
import re
from .ai_provider import AIProvider

# 소형 로컬 모델(Ollama 등)에서도 잘 동작하도록 지시를 구체적으로 작성
_SYSTEM_PROMPT = """\
You are an Oracle SQL tuning expert.
Return ONLY the optimized SQL query. No explanations outside the SQL.
Add -- comments inside the SQL to explain each change.
Do NOT use markdown code fences (```).
Do NOT add any text before or after the SQL.
The optimized SQL must return exactly the same result as the original.\
"""


class AiSqlTuner:
    def __init__(self, provider: AIProvider):
        self._provider = provider

    @property
    def is_available(self) -> bool:
        return self._provider.is_configured

    @property
    def provider_label(self) -> str:
        return self._provider.label

    def tune(self, sql: str, issues: list, db_version: str = '') -> str:
        if not self._provider.is_configured:
            raise RuntimeError(
                "AI 제공자가 설정되지 않았습니다.\n"
                "도구 모음의 'AI 설정' 버튼에서 설정하세요."
            )

        if issues:
            issue_lines = [
                f'- [{i.severity}] {i.title}: {i.description.splitlines()[0]}'
                for i in issues
            ]
            issues_str = '\n'.join(issue_lines)
        else:
            issues_str = 'No issues detected'

        version_line = f'[Database Version]\n{db_version}\n\n' if db_version else ''

        user = (
            f'Tune the following Oracle SQL.\n\n'
            f'{version_line}'
            f'[Original SQL]\n{sql}\n\n'
            f'[Detected performance issues]\n{issues_str}\n\n'
            'Return ONLY the optimized SQL with -- comments explaining each change. '
            'No markdown, no explanation text outside the SQL.'
        )

        raw = self._provider.complete(_SYSTEM_PROMPT, user)
        return self._clean_output(raw)

    @staticmethod
    def _clean_output(text: str) -> str:
        """모델 응답에서 마크다운 코드 펜스 등 불필요한 래퍼를 제거합니다."""
        # ```sql ... ``` 또는 ``` ... ``` 블록 추출
        fence = re.search(r'```(?:sql)?\s*\n?(.*?)```', text, re.DOTALL | re.IGNORECASE)
        if fence:
            return fence.group(1).strip()
        # 펜스가 없으면 앞뒤 공백만 정리
        return text.strip()
