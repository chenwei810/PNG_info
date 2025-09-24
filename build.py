#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PNG 元數據解析器 - 自動打包腳本 (支援拖拽版本)
支援 Windows 和 macOS，自動檢測並包含拖拽功能
"""

import os
import sys
import platform
import subprocess
import shutil
import json
from pathlib import Path
import time

class BuildManager:
    def __init__(self):
        self.system = platform.system().lower()
        self.python_exe = sys.executable
        self.project_dir = Path(__file__).parent
        self.dist_dir = self.project_dir / "dist"
        self.build_dir = self.project_dir / "build"
        self.spec_files = list(self.project_dir.glob("*.spec"))
        
        # 應用程式資訊
        self.app_name = "PNG元數據解析器"
        self.app_version = "2.0"
        self.main_script = "png_info_parser.py"
        
        # 檢查拖拽支援
        self.has_windnd = self.check_windnd()
        
    def check_windnd(self):
        """檢查是否有 windnd 支援"""
        try:
            import windnd
            print("檢測到 windnd，將包含拖拽功能")
            return True
        except ImportError:
            print("未檢測到 windnd，程式將以選擇檔案模式運行")
            return False
        
    def print_header(self):
        """列印歡迎資訊"""
        print("=" * 70)
        print(f"    PNG元數據解析器 v{self.app_version} - 自動打包工具")
        if self.has_windnd:
            print("    包含拖拽功能支援")
        print("=" * 70)
        print(f"檢測到系統: {platform.system()} {platform.release()}")
        print(f"Python 版本: {sys.version.split()[0]}")
        print(f"專案目錄: {self.project_dir}")
        print()
    
    def check_environment(self):
        """檢查環境和相依性"""
        print("檢查環境和相依性...")
        
        # 檢查主腳本是否存在
        main_script_path = self.project_dir / self.main_script
        if not main_script_path.exists():
            print(f"找不到主腳本: {self.main_script}")
            return False
        
        print(f"主腳本存在: {self.main_script}")
        
        # 檢查 Python 模組
        required_modules = ['PIL', 'tkinter']
        optional_modules = ['windnd'] if self.system == 'windows' else []
        missing_modules = []
        
        for module in required_modules:
            try:
                __import__(module)
                print(f"{module} 模組可用")
            except ImportError:
                missing_modules.append(module)
                print(f"{module} 模組缺失")
        
        # 檢查可選模組
        for module in optional_modules:
            try:
                __import__(module)
                print(f"{module} 模組可用 (拖拽功能)")
            except ImportError:
                print(f"{module} 模組未安裝 (拖拽功能將不可用)")
        
        if missing_modules:
            print(f"\n缺少必要模組: {', '.join(missing_modules)}")
            if 'PIL' in missing_modules:
                print("請執行: pip install Pillow")
            return False
        
        # 檢查 PyInstaller
        try:
            result = subprocess.run([self.python_exe, '-c', 'import PyInstaller; print(PyInstaller.__version__)'], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print(f"PyInstaller 版本: {result.stdout.strip()}")
            else:
                raise ImportError
        except:
            print("PyInstaller 未安裝")
            return self.install_pyinstaller()
        
        print("環境檢查通過")
        return True
    
    def install_pyinstaller(self):
        """安裝 PyInstaller"""
        print("\n正在安裝 PyInstaller...")
        try:
            subprocess.run([self.python_exe, '-m', 'pip', 'install', 'pyinstaller'], 
                         check=True)
            print("PyInstaller 安裝成功")
            return True
        except subprocess.CalledProcessError as e:
            print(f"PyInstaller 安裝失敗: {e}")
            return False
    
    def install_windnd(self):
        """安裝 windnd（可選）"""
        if self.system != 'windows':
            return True
            
        if self.has_windnd:
            return True
            
        print("\n是否安裝 windnd 以獲得拖拽功能支援？")
        choice = input("輸入 y 安裝，或按 Enter 跳過: ").lower()
        
        if choice == 'y':
            print("正在安裝 windnd...")
            try:
                subprocess.run([self.python_exe, '-m', 'pip', 'install', 'windnd'], 
                             check=True)
                print("windnd 安裝成功")
                self.has_windnd = True
                return True
            except subprocess.CalledProcessError as e:
                print(f"windnd 安裝失敗: {e}")
                print("程式將以選擇檔案模式建構")
                return True
        else:
            print("跳過 windnd 安裝，程式將以選擇檔案模式建構")
            return True
    
    def cleanup_old_builds(self):
        """清理舊的建構檔案"""
        print("\n清理舊的建構檔案...")
        
        dirs_to_clean = [self.dist_dir, self.build_dir]
        files_cleaned = 0
        
        for directory in dirs_to_clean:
            if directory.exists():
                print(f"   刪除目錄: {directory}")
                shutil.rmtree(directory, ignore_errors=True)
                files_cleaned += 1
        
        for spec_file in self.spec_files:
            if spec_file.exists():
                print(f"   刪除設定: {spec_file}")
                spec_file.unlink()
                files_cleaned += 1
        
        if files_cleaned > 0:
            print(f"清理完成，刪除了 {files_cleaned} 個項目")
        else:
            print("沒有需要清理的檔案")
    
    def create_spec_file(self):
        """建立 PyInstaller 設定檔案"""
        print("\n建立 PyInstaller 設定...")
        
        # 根據系統選擇圖示
        icon_file = None
        if self.system == 'windows':
            if (self.project_dir / 'icon.ico').exists():
                icon_file = str(self.project_dir / 'icon.ico')
        elif self.system == 'darwin':  # macOS
            if (self.project_dir / 'icon.icns').exists():
                icon_file = str(self.project_dir / 'icon.icns')
        
        # 動態建構隱含匯入清單
        hidden_imports = [
            'PIL',
            'PIL.Image',
            'tkinter',
            'tkinter.ttk',
            'threading',
            'json',
            'datetime'
        ]
        
        # 如果有 windnd，加入到隱含匯入
        if self.has_windnd:
            hidden_imports.append('windnd')
        
        # 排除的模組
        excludes = [
            'matplotlib',
            'numpy',
            'pandas',
            'scipy',
            'IPython',
            'jupyter'
        ]
        
        # 如果沒有 windnd，確保不會嘗試匯入
        if not self.has_windnd:
            excludes.append('windnd')
        
        spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

a = Analysis(
    ['{self.main_script}'],
    pathex=['.'],
    binaries=[],
    datas=[],
    hiddenimports={hidden_imports},
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes={excludes},
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
    name='{self.app_name}',
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
    entitlements_file=None,'''

        if icon_file:
            spec_content += f"\n    icon='{icon_file}',"
        
        spec_content += "\n)"
        
        # macOS 特定設定
        if self.system == 'darwin':
            bundle_icon = f"'{icon_file}'" if icon_file else "None"
            spec_content += f'''

app = BUNDLE(
    exe,
    name='{self.app_name}.app',
    icon={bundle_icon},
    bundle_identifier='com.pngparser.app',
    info_plist={{
        'NSPrincipalClass': 'NSApplication',
        'NSAppleScriptEnabled': False,
        'CFBundleDocumentTypes': [
            {{
                'CFBundleTypeName': 'PNG Image',
                'CFBundleTypeExtensions': ['png'],
                'CFBundleTypeRole': 'Viewer'
            }}
        ]
    }},
)'''
        
        spec_file_path = self.project_dir / f'{self.app_name}.spec'
        with open(spec_file_path, 'w', encoding='utf-8') as f:
            f.write(spec_content)
        
        print(f"設定檔建立: {spec_file_path}")
        return spec_file_path
    
    def build_application(self, spec_file):
        """建構應用程式"""
        print(f"\n開始建構應用程式...")
        if self.has_windnd:
            print("包含拖拽功能支援")
        else:
            print("建構選擇檔案版本")
        print("這可能需要幾分鐘時間，請耐心等待...")
        
        start_time = time.time()
        
        try:
            # 建構指令
            cmd = [
                self.python_exe, '-m', 'PyInstaller',
                '--clean',
                '--noconfirm',
                str(spec_file)
            ]
            
            print(f"執行指令: {' '.join(cmd)}")
            
            # 執行建構
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # 即時顯示輸出
            output_lines = []
            while True:
                output = process.stdout.readline()
                if output == '' and process.poll() is not None:
                    break
                if output:
                    output_lines.append(output.strip())
                    # 只顯示重要資訊
                    if any(keyword in output.lower() for keyword in 
                          ['info', 'warning', 'error', 'building', 'analyzing']):
                        print(f"   {output.strip()}")
            
            rc = process.poll()
            build_time = time.time() - start_time
            
            if rc == 0:
                print(f"\n建構成功! 耗時: {build_time:.1f} 秒")
                return True
            else:
                print(f"\n建構失敗，回傳碼: {rc}")
                # 顯示最後幾行輸出用於除錯
                print("最後的錯誤資訊:")
                for line in output_lines[-10:]:
                    print(f"   {line}")
                return False
                
        except Exception as e:
            print(f"建構過程出錯: {e}")
            return False
    
    def verify_build(self):
        """驗證建構結果"""
        print("\n驗證建構結果...")
        
        if self.system == 'windows':
            exe_path = self.dist_dir / f"{self.app_name}.exe"
        elif self.system == 'darwin':
            exe_path = self.dist_dir / f"{self.app_name}.app"
        else:
            exe_path = self.dist_dir / self.app_name
        
        if not exe_path.exists():
            print(f"可執行檔未找到: {exe_path}")
            return False
        
        # 取得檔案大小
        if exe_path.is_file():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"可執行檔: {exe_path}")
            print(f"檔案大小: {size_mb:.1f} MB")
        elif exe_path.is_dir():  # macOS .app bundle
            print(f"應用程式套件: {exe_path}")
        
        return True
    
    def create_readme(self):
        """建立說明檔案"""
        print("\n建立使用說明...")
        
        drag_info = """
拖拽功能:
   • 直接拖拽 PNG 圖片到程式視窗
   • 支援自動解析功能
   • 拖拽後立即開始處理
   
使用方法:
   • 方式一: 拖拽 PNG 圖片到程式視窗
   • 方式二: 點選「選擇 PNG 檔案」按鈕""" if self.has_windnd else """
檔案選擇:
   • 點選「選擇 PNG 檔案」按鈕選擇圖片
   • 支援快速鍵 Ctrl+O 開啟檔案
   
使用方法:
   • 點選「選擇 PNG 檔案」按鈕選擇圖片
   • 點選「開始解析」按鈕進行解析
   
獲得拖拽功能:
   • 可安裝 windnd 以獲得拖拽支援
   • 指令: pip install windnd"""

        readme_content = f"""# {self.app_name} v{self.app_version}

## 功能說明
這是一個專門用來解析 PNG 圖片元數據的工具，特別適合查看 AI 生成圖片的參數。

{drag_info}

## 支援的格式
- ComfyUI 生成的 PNG 圖片（包含完整工作流程資訊）
- Stable Diffusion WebUI 生成的 PNG 圖片（包含參數資訊）
- 其他包含文字元數據的 PNG 圖片

## 程式特點
- 無需安裝 Python 環境，雙擊即可執行
- 現代化深色主題介面，護眼美觀
- 智慧識別不同的 AI 生成工具格式
- 美觀的參數展示和格式化輸出
- 支援儲存解析結果到文字檔案
- 完全離線工作，保護隱私安全
{"- 支援拖拽操作，使用便捷" if self.has_windnd else "- 檔案選擇模式，穩定可靠"}
- 自動解析功能，提升效率

## 系統需求
- Windows 7 及以上版本 / macOS 10.12 及以上版本
- 無需安裝其他軟體

## 快速鍵
- Ctrl+O: 開啟檔案
- F5: 開始解析
- Ctrl+S: 儲存結果
- F1: 關於程式

## 解析內容
- 圖片基本資訊（尺寸、色彩模式、檔案大小等）
- 生成參數（種子、取樣步數、CFG、採樣器等）
- 模型資訊（主模型、LoRA 模型等）
- 提示詞（正面和負面提示詞，格式化顯示）
- 工作流程統計（節點數量、版本資訊等）

## 問題回饋
如有問題或建議，歡迎回饋！

---
建構時間: {time.strftime('%Y-%m-%d %H:%M:%S')}
建構系統: {platform.system()} {platform.release()}
Python 版本: {sys.version.split()[0]}
{"拖拽功能: 已包含 (windnd)" if self.has_windnd else "拖拽功能: 未包含 (可安裝 windnd 獲得支援)"}
"""
        
        readme_path = self.dist_dir / "使用說明.txt"
        try:
            with open(readme_path, 'w', encoding='utf-8') as f:
                f.write(readme_content)
            print(f"說明檔案: {readme_path}")
        except Exception as e:
            print(f"建立說明檔案失敗: {e}")
    
    def show_summary(self):
        """顯示建構摘要"""
        print("\n" + "建構完成!".center(60, "="))
        print()
        
        if self.system == 'windows':
            exe_name = f"{self.app_name}.exe"
        elif self.system == 'darwin':
            exe_name = f"{self.app_name}.app"
        else:
            exe_name = self.app_name
            
        print(f"輸出目錄: {self.dist_dir}")
        print(f"可執行檔: {exe_name}")
        if self.has_windnd:
            print(f"拖拽功能: 已包含")
        else:
            print(f"拖拽功能: 未包含 (檔案選擇模式)")
        print()
        
        print("你現在可以:")
        print(f"   • 執行程式: 雙擊 {exe_name}")
        if self.has_windnd:
            print(f"   • 拖拽使用: 直接拖拽 PNG 圖片到程式視窗")
        print(f"   • 分享程式: 複製整個 dist 資料夾")
        print(f"   • 查看說明: 閱讀 使用說明.txt")
        
        if self.system == 'windows':
            print("\nWindows 提示:")
            print("   • 如果防毒軟體報毒，請加入到白名單")
            print("   • 首次執行可能需要一些時間來初始化")
        elif self.system == 'darwin':
            print("\nmacOS 提示:")
            print("   • 首次執行需要右鍵點選選擇'開啟'")
            print("   • 或在系統偏好設定中允許執行")
        
        print("\n" + "="*60)
    
    def run(self):
        """執行完整的建構流程"""
        try:
            self.print_header()
            
            # 1. 檢查環境
            if not self.check_environment():
                return False
            
            # 2. 詢問是否安裝 windnd（僅 Windows）
            if not self.install_windnd():
                return False
            
            # 3. 清理舊檔案
            self.cleanup_old_builds()
            
            # 4. 建立設定檔
            spec_file = self.create_spec_file()
            
            # 5. 建構應用程式
            if not self.build_application(spec_file):
                return False
            
            # 6. 驗證結果
            if not self.verify_build():
                return False
            
            # 7. 建立說明檔案
            self.create_readme()
            
            # 8. 顯示摘要
            self.show_summary()
            
            return True
            
        except KeyboardInterrupt:
            print("\n建構被使用者中斷")
            return False
        except Exception as e:
            print(f"\n建構過程出錯: {e}")
            return False

def main():
    """主函式"""
    print("啟動 PNG 元數據解析器建構工具...")
    
    try:
        builder = BuildManager()
        success = builder.run()
        
        if success:
            print("\n建構流程完成!")
            if input("\n是否嘗試執行程式進行測試？(y/N): ").lower() == 'y':
                try:
                    if platform.system().lower() == 'windows':
                        exe_path = builder.dist_dir / f"{builder.app_name}.exe"
                        if exe_path.exists():
                            os.startfile(str(exe_path))
                    else:
                        exe_path = builder.dist_dir / builder.app_name
                        if exe_path.exists():
                            subprocess.Popen([str(exe_path)])
                    print("程式啟動中...")
                except Exception as e:
                    print(f"啟動程式失敗: {e}")
        else:
            print("\n建構失敗")
            return 1
            
    except Exception as e:
        print(f"\n程式執行失敗: {e}")
        return 1
    
    return 0

if __name__ == "__main__":
    exit_code = main()
    
    # 如果是直接雙擊執行，等待使用者按鍵
    if len(sys.argv) == 1:
        input("\n按 Enter 鍵退出...")
    
    sys.exit(exit_code)