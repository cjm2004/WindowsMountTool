# -*- mode: python ; coding: utf-8 -*-
# mount_wizard.exe 构建（PyInstaller）
# 内嵌 source/tools/{alist,rclone}.exe + source/config/rclone.conf
# 产物：py_src_wizard\dist\mount_wizard.exe（~85MB）

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[],
    datas=[('payload/source', 'source')],
    hiddenimports=['pywinstyles', 'webview', 'webview.platforms.winforms', 'clr_loader', 'pythonnet', 'ui_theme'],
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
    name='mount_wizard',
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
