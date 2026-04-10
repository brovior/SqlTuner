"""
Oracle DB 연결 다이얼로그
tnsnames.ora에서 TNS 별칭을 읽어 드롭다운으로 제공합니다.
마지막 연결 정보(별칭/사용자명/비밀번호)는 INI 파일에 저장됩니다.
"""
import os
import base64
from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLabel, QLineEdit, QComboBox, QPushButton,
    QFileDialog, QMessageBox, QGroupBox
)
from PyQt5.QtCore import Qt, QSettings
from PyQt5.QtGui import QFont

from core.tns_parser import find_tnsnames_path, get_alias_list
from core.oracle_client import ConnectionInfo

# INI 파일 경로: 앱 폴더 기준 config.ini
_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'config.ini'
)


class ConnectionDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Oracle DB 연결')
        self.setMinimumWidth(440)
        self.setModal(True)

        self._tns_filepath = ''
        self._result: ConnectionInfo | None = None
        self._settings = QSettings(_CONFIG_PATH, QSettings.IniFormat)

        self._build_ui()
        self._load_tnsnames_auto()
        self._restore_last_settings()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # -- tnsnames.ora 경로 그룹 --
        tns_group = QGroupBox('tnsnames.ora 파일')
        tns_layout = QHBoxLayout(tns_group)

        self._tns_path_label = QLabel('자동 탐색 중...')
        self._tns_path_label.setWordWrap(True)
        font = QFont()
        font.setPointSize(8)
        self._tns_path_label.setFont(font)

        btn_browse = QPushButton('찾아보기')
        btn_browse.setFixedWidth(80)
        btn_browse.clicked.connect(self._browse_tnsnames)

        tns_layout.addWidget(self._tns_path_label, 1)
        tns_layout.addWidget(btn_browse)
        layout.addWidget(tns_group)

        # -- 연결 정보 폼 --
        conn_group = QGroupBox('연결 정보')
        form = QFormLayout(conn_group)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)

        self._alias_combo = QComboBox()
        self._alias_combo.setEditable(True)
        self._alias_combo.setPlaceholderText('TNS 별칭 선택 또는 직접 입력')
        self._alias_combo.setMinimumWidth(250)
        form.addRow('TNS 별칭:', self._alias_combo)

        self._user_edit = QLineEdit()
        self._user_edit.setPlaceholderText('사용자명')
        form.addRow('사용자명:', self._user_edit)

        self._pwd_edit = QLineEdit()
        self._pwd_edit.setEchoMode(QLineEdit.Password)
        self._pwd_edit.setPlaceholderText('비밀번호')
        form.addRow('비밀번호:', self._pwd_edit)

        layout.addWidget(conn_group)

        # -- 버튼 --
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._btn_connect = QPushButton('연결')
        self._btn_connect.setDefault(True)
        self._btn_connect.setMinimumWidth(80)
        self._btn_connect.clicked.connect(self._on_connect)

        btn_cancel = QPushButton('취소')
        btn_cancel.setMinimumWidth(80)
        btn_cancel.clicked.connect(self.reject)

        btn_layout.addWidget(self._btn_connect)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)

        # Enter 키로 연결
        self._pwd_edit.returnPressed.connect(self._on_connect)

    def _load_tnsnames_auto(self):
        path = find_tnsnames_path()
        if path:
            self._set_tns_file(path)
        else:
            self._tns_path_label.setText('tnsnames.ora를 찾을 수 없습니다. [찾아보기] 버튼을 사용하세요.')
            self._tns_path_label.setStyleSheet('color: #cc6600;')

    def _set_tns_file(self, filepath: str):
        self._tns_filepath = filepath
        self._tns_path_label.setText(filepath)
        self._tns_path_label.setStyleSheet('color: #006600;')

        aliases = get_alias_list(filepath)
        self._alias_combo.clear()
        self._alias_combo.addItems(aliases)
        if not aliases:
            self._tns_path_label.setStyleSheet('color: #cc6600;')
            self._tns_path_label.setText(f'{filepath}\n(별칭을 찾을 수 없습니다)')

    def _browse_tnsnames(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            'tnsnames.ora 파일 선택',
            '',
            'Oracle TNS Files (tnsnames.ora);;All Files (*.*)'
        )
        if path:
            self._set_tns_file(path)

    def _restore_last_settings(self):
        last_alias = self._settings.value('Connection/last_alias', '')
        last_user  = self._settings.value('Connection/last_user', '')
        last_pwd   = self._settings.value('Connection/last_pwd', '')

        if last_alias:
            idx = self._alias_combo.findText(last_alias)
            if idx >= 0:
                self._alias_combo.setCurrentIndex(idx)
            else:
                self._alias_combo.setEditText(last_alias)
        if last_user:
            self._user_edit.setText(last_user)
        if last_pwd:
            try:
                self._pwd_edit.setText(base64.b64decode(last_pwd.encode()).decode())
            except Exception:
                pass  # 저장값이 손상된 경우 무시

        # 비밀번호가 채워진 경우 연결 버튼에 포커스, 아니면 비밀번호 입력란으로
        if last_pwd:
            self._btn_connect.setFocus()
        else:
            self._pwd_edit.setFocus()

    def _save_settings(self, alias: str, user: str, pwd: str):
        self._settings.setValue('Connection/last_alias', alias)
        self._settings.setValue('Connection/last_user', user)
        # 비밀번호는 base64 인코딩 후 저장 (평문 노출 방지)
        self._settings.setValue('Connection/last_pwd', base64.b64encode(pwd.encode()).decode())
        self._settings.sync()

    def _on_connect(self):
        alias = self._alias_combo.currentText().strip()
        user = self._user_edit.text().strip()
        pwd = self._pwd_edit.text()

        if not alias:
            QMessageBox.warning(self, '입력 오류', 'TNS 별칭을 입력하세요.')
            self._alias_combo.setFocus()
            return
        if not user:
            QMessageBox.warning(self, '입력 오류', '사용자명을 입력하세요.')
            self._user_edit.setFocus()
            return
        if not pwd:
            QMessageBox.warning(self, '입력 오류', '비밀번호를 입력하세요.')
            self._pwd_edit.setFocus()
            return

        self._result = ConnectionInfo(
            tns_alias=alias,
            username=user,
            password=pwd,
            tns_filepath=self._tns_filepath,
        )
        self._save_settings(alias, user, pwd)
        self.accept()

    @property
    def connection_info(self) -> ConnectionInfo | None:
        return self._result
