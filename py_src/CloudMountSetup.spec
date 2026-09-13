# -*- mode: python ; coding: utf-8 -*-
# CloudMountSetup.exe 构建脚本（PyInstaller，忠实还原旧版安装器 + 三驱动释放）
# 产物：dist\CloudMountSetup.exe（~95MB），与旧版界面一致

a = Analysis(
    ['installer.py'],
    pathex=[],
    binaries=[],
    datas=[('payload', 'payload')],
    hiddenimports=['pywinstyles', 'ui_theme'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='CloudMountSetup',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='icon.ico',
)
