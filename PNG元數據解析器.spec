# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['png_info_parser.py'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports=['PIL', 'PIL.Image', 'tkinter', 'tkinter.ttk', 'threading', 'json', 'datetime'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['matplotlib', 'numpy', 'pandas', 'scipy', 'IPython', 'jupyter', 'windnd'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PNG元數據解析器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

app = BUNDLE(
    exe,
    name='PNG元數據解析器.app',
    icon=None,
    bundle_identifier='com.pngparser.app',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeName': 'PNG Image',
                'CFBundleTypeExtensions': ['png'],
                'CFBundleTypeRole': 'Viewer'
            }
        ]
    },
)