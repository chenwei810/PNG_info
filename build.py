#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build.py — 把 PNG Info 檢視器打包成 macOS .app（PyInstaller，onedir 模式）

必須在 Mac 上執行（PyInstaller 無法跨平台打包）。M3 / M4 都是 arm64，打包一次兩台都能用。

用法：
  python build.py             # 建構，結果在 dist/
  python build.py --install   # 建構後複製到「應用程式」資料夾
  python build.py --open      # 建構後直接開啟
"""

import argparse
import importlib.util
import platform
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENTRY_SCRIPT = ROOT / 'png_info_parser.py'

BUNDLE_NAME = 'PNG Info Viewer'         # .app 的檔名
EXEC_NAME = 'PNGInfoViewer'             # 執行檔名稱（用英文比較不會出問題）
DISPLAY_NAME = 'PNG Info 檢視器'        # Dock、選單列上顯示的名稱
BUNDLE_ID = 'local.pnginfo.viewer'

REQUIRED_MODULES = {
    'PIL': 'pip install Pillow',
    'tkinter': '請改用 python.org 的 Python 安裝檔（已內建 Tk）',
    'tkinterdnd2': 'pip install -U tkinterdnd2',
    'PyInstaller': 'pip install pyinstaller',
}

EXCLUDES = ['matplotlib', 'numpy', 'pandas', 'scipy', 'IPython', 'jupyter',
            'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'windnd']

SPEC_TEMPLATE = '''# -*- mode: python ; coding: utf-8 -*-
# 由 build.py 自動產生，每次建構都會覆蓋，請改 build.py 而不是這個檔案
from PyInstaller.utils.hooks import collect_all

# tkinterdnd2 內含 tkdnd 的 Tcl 腳本與原生函式庫，必須整包收進來，否則拖放會失效
dnd_datas, dnd_binaries, dnd_hiddenimports = collect_all('tkinterdnd2')

a = Analysis(
    [{entry!r}],
    pathex=[{root!r}],
    binaries=dnd_binaries,
    datas=dnd_datas,
    hiddenimports=dnd_hiddenimports + ['PIL._tkinter_finder'],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes={excludes!r},
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name={exec_name!r},
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name={exec_name!r},
)

app = BUNDLE(
    coll,
    name={bundle_file!r},
    icon={icon!r},
    bundle_identifier={bundle_id!r},
    version={version!r},
    info_plist={info_plist!r},
)
'''


def step(message: str) -> None:
    print(f'\n▶ {message}')


def read_version() -> str:
    match = re.search(r"^APP_VERSION\s*=\s*['\"]([^'\"]+)['\"]",
                      ENTRY_SCRIPT.read_text(encoding='utf-8'), re.MULTILINE)
    return match.group(1) if match else '0.0'


def check_environment() -> bool:
    step('檢查環境')
    if platform.system() != 'Darwin':
        print('  ✗ 這個腳本只能在 macOS 上執行（PyInstaller 無法跨平台打包）')
        return False
    print(f'  macOS {platform.mac_ver()[0]}（{platform.machine()}）')
    print(f'  Python {platform.python_version()}：{sys.executable}')

    if not ENTRY_SCRIPT.exists():
        print(f'  ✗ 找不到主程式：{ENTRY_SCRIPT.name}')
        return False
    for module in ('pnginfo_core.py', 'pnginfo_editor.py', 'edit_dialogs.py'):
        if not (ROOT / module).exists():
            print(f'  ✗ 找不到 {module}')
            return False

    missing = [name for name in REQUIRED_MODULES if importlib.util.find_spec(name) is None]
    for name in REQUIRED_MODULES:
        print(f'  {"✗" if name in missing else "✓"} {name}')
    if missing:
        print('\n  缺少必要套件，請先在 venv 中執行：')
        for name in missing:
            print(f'    {REQUIRED_MODULES[name]}')
        return False

    # 拖放是這個工具的核心功能：先實際載入一次，失敗就不要打包
    step('檢查拖放功能')
    result = subprocess.run([sys.executable, str(ENTRY_SCRIPT), '--check'], cwd=ROOT)
    if result.returncode != 0:
        print('\n  ✗ 拖放功能無法使用，請先依照上面的修正方式處理，再重新打包')
        return False
    return True


def clean() -> None:
    step('清理舊的建構結果')
    for path in (ROOT / 'build', ROOT / 'dist'):
        if path.exists():
            shutil.rmtree(path)
            print(f'  刪除 {path.name}/')
    for spec in ROOT.glob('*.spec'):
        spec.unlink()
        print(f'  刪除 {spec.name}')


def write_spec(version: str) -> Path:
    step('產生 PyInstaller 設定檔')
    icon = ROOT / 'icon.icns'
    info_plist = {
        'CFBundleName': 'PNG Info',
        'CFBundleDisplayName': DISPLAY_NAME,
        'CFBundleShortVersionString': version,
        'CFBundleVersion': version,
        'NSHighResolutionCapable': True,
        'NSRequiresAquaSystemAppearance': False,   # 跟著系統深色／淺色模式
        'LSMinimumSystemVersion': '11.0',
        # 宣告可以開啟圖片：才能把圖片拖到 Dock 圖示上、或在 Finder 用「打開方式」開啟
        # LSHandlerRank = Alternate：不會搶走「預覽程式」的預設開啟方式
        'CFBundleDocumentTypes': [{
            'CFBundleTypeName': 'Image',
            'CFBundleTypeRole': 'Viewer',
            'LSHandlerRank': 'Alternate',
            'LSItemContentTypes': ['public.png', 'public.jpeg', 'org.webmproject.webp'],
        }],
    }
    content = SPEC_TEMPLATE.format(
        entry=str(ENTRY_SCRIPT),
        root=str(ROOT),
        excludes=EXCLUDES,
        exec_name=EXEC_NAME,
        bundle_file=f'{BUNDLE_NAME}.app',
        icon=str(icon) if icon.exists() else None,
        bundle_id=BUNDLE_ID,
        version=version,
        info_plist=info_plist,
    )
    spec_path = ROOT / f'{EXEC_NAME}.spec'
    spec_path.write_text(content, encoding='utf-8')
    print(f'  {spec_path.name}' + ('' if icon.exists() else '（沒有 icon.icns，使用預設圖示）'))
    return spec_path


def run_pyinstaller(spec_path: Path) -> bool:
    step('執行 PyInstaller（約需一兩分鐘）')
    start = time.time()
    result = subprocess.run(
        [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean', str(spec_path)],
        cwd=ROOT)
    if result.returncode != 0:
        print(f'\n  ✗ 建構失敗（回傳碼 {result.returncode}），請看上方的錯誤訊息')
        return False
    print(f'\n  ✓ 建構完成，耗時 {time.time() - start:.0f} 秒')
    return True


def app_path() -> Path:
    return ROOT / 'dist' / f'{BUNDLE_NAME}.app'


def verify() -> bool:
    step('檢查輸出')
    app = app_path()
    if not app.exists():
        print(f'  ✗ 找不到 {app}')
        return False
    size = subprocess.run(['du', '-sh', str(app)], capture_output=True, text=True).stdout.split('\t')[0]
    print(f'  ✓ {app.relative_to(ROOT)}（{size.strip()}）')

    # Tk 8.6 用 libtkdnd*.dylib，Tk 9 用 libtcl9tkdnd*.dylib
    dnd_libs = list(app.rglob('*tkdnd*.dylib'))
    if dnd_libs:
        print('  ✓ 已包含 tkdnd 拖放函式庫')
    else:
        print('  ⚠ .app 中找不到 tkdnd 函式庫，拖放可能無法使用')
    return True


def install() -> Path:
    step('安裝到「應用程式」資料夾')
    target = Path('/Applications') / f'{BUNDLE_NAME}.app'
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(app_path(), target, symlinks=True)   # .app 裡有符號連結，必須保留
    print(f'  ✓ {target}')
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description='把 PNG Info 檢視器打包成 macOS .app')
    parser.add_argument('--install', action='store_true', help='建構後複製到 /Applications')
    parser.add_argument('--open', action='store_true', help='建構後直接開啟')
    args = parser.parse_args()

    version = read_version()
    print('=' * 60)
    print(f'  {DISPLAY_NAME} v{version} — macOS 打包工具')
    print('=' * 60)

    if not check_environment():
        return 1
    clean()
    spec_path = write_spec(version)
    if not run_pyinstaller(spec_path) or not verify():
        return 1

    target = install() if args.install else app_path()

    print('\n' + '=' * 60)
    print(f'  完成！{target}')
    print('  • 雙擊開啟，或把圖片拖到 Dock 圖示上')
    print('  • 在自己的 Mac 上打包、自己使用，不需要簽章')
    print('  • 如果是從別台電腦複製過來，第一次請按右鍵 →「打開」')
    print('=' * 60)

    if args.open:
        subprocess.run(['open', str(target)])
    return 0


if __name__ == '__main__':
    sys.exit(main())
