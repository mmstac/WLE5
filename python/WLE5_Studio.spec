# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs

# 1. Grab all standard data (Fonts, Textures, Shaders, Config.prc)
ursina_datas = collect_data_files('ursina')
panda3d_datas = collect_data_files('panda3d')

# 2. Grab the hidden C++ Graphics Drivers
panda3d_binaries = collect_dynamic_libs('panda3d')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=panda3d_binaries,  
    datas=[
        # Map local project folders
        ('../config/*', 'config'),
        ('../anims/*', 'anims'),
        ('../media/*', 'media'),
    ] + ursina_datas + panda3d_datas,
    hiddenimports=['panda3d', 'direct'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='WLE5_Studio',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,  # <--- THIS IS THE MAGIC SWITCH! (Changed from True to False)
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)