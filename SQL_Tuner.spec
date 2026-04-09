# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec 파일 - 자동 생성 대신 이 파일 사용 시 더 세밀한 제어 가능
# 사용법: pyinstaller SQL_Tuner.spec

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('core', 'core'),
        ('ui', 'ui'),
    ],
    hiddenimports=[
        'oracledb',
        'oracledb.thick_impl',
        'oracledb.thin_impl',
        'PyQt6.QtWidgets',
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.sip',
        'sqlparse',
        'sqlparse.filters',
        'sqlparse.lexer',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'unittest', 'email', 'html', 'http',
        'urllib', 'xml', 'xmlrpc', 'ftplib', 'imaplib',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='SQL Tuner',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,   # 콘솔 창 숨김 (GUI 앱)
    disable_windowed_traceback=False,
    target_arch=None,
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
    name='SQL Tuner',
)
