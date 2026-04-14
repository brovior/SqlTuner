# -*- mode: python ; coding: utf-8 -*-
# SQL Tuner v2 PyInstaller 빌드 스펙
#
# 실행 방법 (프로젝트 루트에서):
#   pyinstaller v2/SQL_Tuner_v2.spec --clean          # 64-bit (CI/CD)
#   py -3.13-32 -m PyInstaller v2/SQL_Tuner_v2.spec --clean  # 32-bit (로컬)

import os
import sqlglot

# spec 파일 위치: <project_root>/v2/SQL_Tuner_v2.spec
# SPECPATH  = v2/  디렉토리 (PyInstaller 내장 변수)
# 프로젝트 루트 = SPECPATH 의 부모
_ROOT = os.path.dirname(SPECPATH)   # noqa: F821  (SPECPATH는 PyInstaller 내장)

# sqlglot 방언 파일 위치 (Oracle 방언 포함)
_sqlglot_dir = os.path.dirname(sqlglot.__file__)
_sqlglot_datas = [
    (os.path.join(_sqlglot_dir, 'dialects'), 'sqlglot/dialects'),
]
# tokens.py 가 없는 sqlglot 버전도 있으므로 존재할 때만 추가
_tokens_py = os.path.join(_sqlglot_dir, 'tokens.py')
if os.path.isfile(_tokens_py):
    _sqlglot_datas.append((_tokens_py, 'sqlglot'))

a = Analysis(
    [os.path.join(_ROOT, 'v2', 'main.py')],
    pathex=[_ROOT],           # 프로젝트 루트에서 v2 패키지 import 가능하도록
    binaries=[],
    datas=[
        (os.path.join(_ROOT, 'v2', 'core'), 'v2/core'),
        (os.path.join(_ROOT, 'v2', 'ui'),   'v2/ui'),
    ] + _sqlglot_datas,
    hiddenimports=[
        # oracledb
        'oracledb',
        'oracledb.thick_impl',
        'oracledb.thin_impl',
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
        # email/html/http/urllib 은 sqlglot → importlib.metadata 경로에서
        # 간접 의존하므로 제외하면 ModuleNotFoundError 발생 — 제거
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
