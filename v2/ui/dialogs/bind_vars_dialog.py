"""
바인드 변수 입력 다이얼로그

SQL에서 :변수명 패턴을 감지하고,
사용자에게 각 변수의 값을 입력받는다.
"""
import re

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout,
    QLabel, QLineEdit, QDialogButtonBox, QScrollArea, QWidget,
)
from PyQt5.QtCore import Qt


def extract_bind_vars(sql: str) -> list[str]:
    """
    SQL에서 :변수명 패턴을 찾아 중복 없이 등장 순서대로 반환.

    - :=  (PL/SQL 대입 연산자) 는 제외
    - 따옴표 안 리터럴은 단순 정규식 수준에서 최선 처리
    """
    pattern = re.compile(r':(?!=)([a-zA-Z_][a-zA-Z0-9_]*)', re.IGNORECASE)
    seen: set[str] = set()
    result: list[str] = []
    for m in pattern.finditer(sql):
        upper = m.group(1).upper()
        if upper not in seen:
            seen.add(upper)
            result.append(m.group(1))  # 원본 케이스 유지
    return result


class BindVarsDialog(QDialog):
    """바인드 변수 값 입력 다이얼로그."""

    def __init__(
        self,
        var_names: list[str],
        parent=None,
        defaults: dict[str, str] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle('바인드 변수 값 입력')
        self.setMinimumWidth(400)
        self._inputs: dict[str, QLineEdit] = {}
        self._build_ui(var_names, defaults or {})

    def _build_ui(self, var_names: list[str], defaults: dict[str, str]) -> None:
        layout = QVBoxLayout(self)

        has_defaults = any(defaults.get(n) for n in var_names)
        note = '<br><span style="color:#555555; font-size:small;">이전 입력값이 자동으로 채워졌습니다.</span>' if has_defaults else ''
        desc = QLabel(
            f'SQL에 바인드 변수 <b>{len(var_names)}개</b>가 감지되었습니다.<br>'
            f'각 변수의 값을 입력하세요.{note}'
        )
        desc.setTextFormat(Qt.RichText)
        desc.setWordWrap(True)
        layout.addWidget(desc)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(320)

        form_widget = QWidget()
        form = QFormLayout(form_widget)
        form.setLabelAlignment(Qt.AlignRight)
        form.setContentsMargins(8, 8, 8, 8)
        form.setSpacing(8)

        for name in var_names:
            edit = QLineEdit()
            cached = defaults.get(name, '')
            if cached:
                edit.setText(cached)
            else:
                edit.setPlaceholderText('값 입력...')
            form.addRow(f':{name}', edit)
            self._inputs[name] = edit

        scroll.setWidget(form_widget)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel,
            Qt.Horizontal,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # 첫 번째 입력 필드에 포커스
        if self._inputs:
            next(iter(self._inputs.values())).setFocus()

    @property
    def bind_values(self) -> dict[str, str]:
        """입력된 바인드 변수 값 반환. {변수명: 입력값}"""
        return {name: edit.text() for name, edit in self._inputs.items()}
