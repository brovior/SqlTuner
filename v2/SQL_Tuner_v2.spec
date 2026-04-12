# -*- mode: python ; coding: utf-8 -*-
# SQL Tuner v2 PyInstaller 빌드 스펙
# 사용법: py -3.13-32 -m PyInstaller v2/SQL_Tuner_v2.spec --clean
#
# 주의: 반드시 프로젝트 루트에서 실행해야 합니다.
#   cd C:\Users\brovi\Project\SqlTuner
#   build_exe_v2.bat

import os
import sqlglot

# sqlglot 방언 파일 위치 (Oracle 방언 포함)
_sqlglot_dir = os.path.dirname(sqlglot.__file__)
_sqlglot_datas = [
    (os.path.join(_sqlglot_dir, 'dialects'), 'sqlglot/dialects'),
    (os.path.join(_sqlglot_dir, 'tokens.py'), 'sqlglot'),
]

a = Analysis(
    ['v2/main.py'],
    pathex=['.'],           # 프로젝트 루트를 기준으로 탐색
    binaries=[],
    datas=[
        ('v2/core',  'v2/core'),
        ('v2/ui',    'v2/ui'),
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
        'tkinter', 'unittest', 'email', 'html', 'http',
        'urllib', 'xml', 'xmlrpc', 'ftplib', 'imaplib',
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
    target_arch='x86',      # 32-bit 빌드
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
