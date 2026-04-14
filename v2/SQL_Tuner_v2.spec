# -*- mode: python ; coding: utf-8 -*-
# SQL Tuner v2 PyInstaller 빌드 스펙
#
# 실행 방법 (프로젝트 루트에서):
#   pyinstaller v2/SQL_Tuner_v2.spec --clean          # 64-bit (CI/CD)
#   py -3.13-32 -m PyInstaller v2/SQL_Tuner_v2.spec --clean  # 32-bit (로컬)

import os
import sqlglot
from PyInstaller.utils.hooks import (
    collect_data_files,
    collect_dynamic_libs,
    collect_submodules,
    collect_all,
)

# spec 파일 위치: <project_root>/v2/SQL_Tuner_v2.spec
# SPECPATH  = v2/  디렉토리 (PyInstaller 내장 변수)
# 프로젝트 루트 = SPECPATH 의 부모
_ROOT = os.path.dirname(SPECPATH)   # noqa: F821  (SPECPATH는 PyInstaller 내장)

# ── oracledb: .pyd 바이너리 + 데이터 + 서브모듈 수동 수집 ─────────
_oracle_binaries  = collect_dynamic_libs('oracledb')
_oracle_datas     = collect_data_files('oracledb')
_oracle_hidden    = collect_submodules('oracledb')

# ── cryptography: oracledb Thin 모드 TLS 의존성 ───────────────────
_crypto_datas, _crypto_bins, _crypto_hidden = collect_all('cryptography')

# ── certifi: TLS 인증서 번들 ──────────────────────────────────────
_certifi_datas = collect_data_files('certifi')

# ── sqlglot: 방언 파일 수집 ────────────────────────────────────────
_sqlglot_dir = os.path.dirname(sqlglot.__file__)
_sqlglot_datas = [
    (os.path.join(_sqlglot_dir, 'dialects'), 'sqlglot/dialects'),
]
_tokens_py = os.path.join(_sqlglot_dir, 'tokens.py')
if os.path.isfile(_tokens_py):
    _sqlglot_datas.append((_tokens_py, 'sqlglot'))

a = Analysis(
    [os.path.join(_ROOT, 'v2', 'main.py')],
    pathex=[_ROOT],
    binaries=_oracle_binaries + _crypto_bins,
    datas=[
        (os.path.join(_ROOT, 'v2', 'core'), 'v2/core'),
        (os.path.join(_ROOT, 'v2', 'ui'),   'v2/ui'),
    ] + _sqlglot_datas + _oracle_datas + _crypto_datas + _certifi_datas,
    hiddenimports=[
        *_oracle_hidden,
        *_crypto_hidden,
        'certifi',
        'typing_extensions',
        # oracledb 가 내부적으로 사용하는 표준 라이브러리
        # (thick_impl.pyd 등 컴파일 확장은 AST 스캔 불가 → 포괄 추가)
        'getpass', 'ssl', 'socket', 'select', 'struct',
        'hashlib', 'hmac', 'secrets', 'array',
        'base64', 'json', 'uuid', 'threading',
        'collections', 'collections.abc',
        'urllib', 'urllib.parse', 'urllib.request', 'urllib.error',
        'email', 'email.message', 'email.parser', 'email.utils',
        'http', 'http.client',
        # PyQt5
        'PyQt5.QtWidgets',
        'PyQt5.QtCore',
        'PyQt5.QtGui',
        'PyQt5.sip',
        # sqlglot
        'sqlglot',
        'sqlglot.dialects',
        'sqlglot.dialects.oracle',
        'sqlglot.expressions',
        'sqlglot.errors',
        'sqlglot.optimizer',
        'sqlglot.tokens',
        # v2 패키지
        'v2',
        'v2.core',
        'v2.core.db',
        'v2.core.ai',
        'v2.core.analysis',
        'v2.core.rewrite',
        'v2.core.pipeline',
        'v2.ui',
        'v2.ui.workers',
        'v2.ui.widgets',
        'v2.ui.dialogs',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'unittest',
        'xmlrpc', 'ftplib', 'imaplib',
        'pytest', '_pytest',
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SQL Tuner v2',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    # target_arch: 로컬 32-bit 빌드 시에는 아래 주석을 해제하세요
    # target_arch='x86',
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='SQL Tuner v2',
)
