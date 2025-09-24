#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PNG 元數據解析器 v2.0 - 完整拖拽版本 (繁體中文)
支援拖拽和檔案選擇，使用 windnd 實現 Windows 拖拽功能
"""

import sys
import os
import tkinter as tk
from tkinter import scrolledtext, messagebox, filedialog, ttk
from PIL import Image
import json
from datetime import datetime
import threading

# 嘗試匯入 windnd 用於 Windows 拖拽支援
try:
    import windnd
    DRAG_DROP_AVAILABLE = True
except ImportError:
    DRAG_DROP_AVAILABLE = False

class PNGInfoParser:
    def __init__(self):
        # 建立主視窗
        self.root = tk.Tk()
        self.root.title("PNG 元數據解析器 v2.0 - 支援拖拽")
        self.root.geometry("950x750")
        self.root.configure(bg='#2b2b2b')
        self.root.minsize(800, 600)
        
        # 置中顯示視窗
        self.center_window()
        
        # 設定拖拽功能
        self.setup_drag_drop()
        
        # 設定介面
        self.setup_ui()
        
        # 目前選擇的檔案路徑
        self.current_file_path = None
    
    def center_window(self):
        """將視窗置中顯示"""
        self.root.update_idletasks()
        screen_width = self.root.winfo_screenwidth()
        screen_height = self.root.winfo_screenheight()
        window_width = 950
        window_height = 750
        x = (screen_width - window_width) // 2
        y = (screen_height - window_height) // 2
        self.root.geometry(f"{window_width}x{window_height}+{x}+{y}")
    
    def setup_drag_drop(self):
        """設定拖拽功能"""
        if DRAG_DROP_AVAILABLE and sys.platform.startswith('win'):
            try:
                # Windows 拖拽支援
                windnd.hook_dropfiles(self.root, func=self.on_drop_files)
                self.drag_enabled = True
                print("✅ 拖拽功能已啟用 (Windows)")
            except Exception as e:
                print(f"⚠️ 拖拽功能啟用失敗: {e}")
                self.drag_enabled = False
        else:
            self.drag_enabled = False
            if not DRAG_DROP_AVAILABLE:
                print("💡 提示: 可安裝 windnd 獲得拖拽支援: pip install windnd")
    
    def on_drop_files(self, files):
        """處理拖拽檔案事件"""
        if files:
            file_path = files[0].decode('utf-8') if isinstance(files[0], bytes) else files[0]
            if file_path.lower().endswith('.png'):
                self.current_file_path = file_path
                filename = os.path.basename(file_path)
                self.file_path_var.set(filename)
                self.parse_btn.configure(state='normal')
                self.status_var.set(f"✅ 已拖入檔案: {filename}")
                self.clear_output()
                
                # 如果開啟自動解析，則自動開始
                if hasattr(self, 'auto_parse_var') and self.auto_parse_var.get():
                    self.root.after(500, self.start_parsing)
            else:
                messagebox.showwarning("檔案類型錯誤", "請拖入 PNG 格式的圖片檔案")
    
    def setup_ui(self):
        """設定使用者介面"""
        # 主框架
        main_frame = tk.Frame(self.root, bg='#2b2b2b')
        main_frame.pack(fill='both', expand=True, padx=15, pady=15)
        
        # 標題區域
        title_frame = tk.Frame(main_frame, bg='#2b2b2b')
        title_frame.pack(fill='x', pady=(0, 20))
        
        title_label = tk.Label(
            title_frame, 
            text="🖼️ PNG 元數據解析器", 
            font=("", 20, "bold"),
            bg='#2b2b2b',
            fg='#ffffff'
        )
        title_label.pack()
        
        # 動態顯示副標題
        drag_status = "支援拖拽" if self.drag_enabled else "選擇檔案"
        subtitle_text = f"支援 ComfyUI 和 Stable Diffusion WebUI 格式 | {drag_status}版本"
        
        subtitle_label = tk.Label(
            title_frame,
            text=subtitle_text,
            font=("", 11),
            bg='#2b2b2b',
            fg='#888888'
        )
        subtitle_label.pack(pady=(8, 0))
        
        # 拖拽區域/檔案選擇區域
        drop_section = tk.LabelFrame(
            main_frame,
            text="  📁 檔案區域  ",
            font=("", 12, "bold"),
            bg='#2b2b2b',
            fg='#ffffff',
            bd=2,
            relief='groove'
        )
        drop_section.pack(fill='x', pady=(0, 20))
        
        # 拖拽提示區域
        self.drop_frame = tk.Frame(
            drop_section,
            bg='#404040',
            relief='ridge',
            bd=2,
            height=120
        )
        self.drop_frame.pack(fill='x', padx=20, pady=15)
        self.drop_frame.pack_propagate(False)  # 保持固定高度
        
        # 拖拽提示文字
        if self.drag_enabled:
            drop_text = "🎯 拖拽 PNG 圖片到這裡\n或點擊下方按鈕選擇檔案\n\n支援的格式: PNG 圖片"
        else:
            drop_text = "📁 點擊下方按鈕選擇 PNG 圖片\n\n支援的格式: PNG 圖片\n💡 可安裝 windnd 獲得拖拽支援"
        
        self.drop_label = tk.Label(
            self.drop_frame,
            text=drop_text,
            font=("", 12),
            bg='#404040',
            fg='#ffffff',
            justify='center'
        )
        self.drop_label.pack(expand=True, fill='both')
        
        # 讓拖拽區域可點擊
        self.drop_label.bind('<Button-1>', lambda e: self.browse_file())
        self.drop_frame.bind('<Button-1>', lambda e: self.browse_file())
        
        # 檔案路徑顯示
        self.file_path_var = tk.StringVar()
        self.file_path_var.set("未選擇檔案")
        
        path_frame = tk.Frame(drop_section, bg='#2b2b2b')
        path_frame.pack(fill='x', padx=20, pady=(0, 15))
        
        tk.Label(
            path_frame,
            text="目前檔案:",
            font=("", 11),
            bg='#2b2b2b',
            fg='#cccccc'
        ).pack(side='left')
        
        self.path_label = tk.Label(
            path_frame,
            textvariable=self.file_path_var,
            font=("", 11),
            bg='#2b2b2b',
            fg='#ffffff',
            anchor='w'
        )
        self.path_label.pack(side='left', fill='x', expand=True, padx=(15, 0))
        
        # 按鈕區域
        button_frame = tk.Frame(drop_section, bg='#2b2b2b')
        button_frame.pack(fill='x', padx=20, pady=(0, 20))
        
        # 第一行按鈕
        button_row1 = tk.Frame(button_frame, bg='#2b2b2b')
        button_row1.pack(fill='x', pady=(0, 10))
        
        # 選擇檔案按鈕
        self.browse_btn = tk.Button(
            button_row1,
            text="📁 選擇 PNG 檔案",
            command=self.browse_file,
            bg='#4a90e2',
            font=("", 12, "bold"),
            relief='flat',
            padx=30,
            pady=10,
            cursor='hand2',
            activebackground='#357abd'
        )
        self.browse_btn.pack(side='left', padx=(0, 15))
        
        # 解析按鈕
        self.parse_btn = tk.Button(
            button_row1,
            text="🔍 開始解析",
            command=self.start_parsing,
            bg='#27ae60',
            font=("", 12, "bold"),
            relief='flat',
            padx=30,
            pady=10,
            cursor='hand2',
            state='disabled',
            activebackground='#219a52'
        )
        self.parse_btn.pack(side='left', padx=(0, 15))
        
        # 自動解析開關
        self.auto_parse_var = tk.BooleanVar()
        self.auto_parse_var.set(True)  # 預設開啟自動解析
        
        self.auto_parse_check = tk.Checkbutton(
            button_row1,
            text="自動解析",
            variable=self.auto_parse_var,
            bg='#2b2b2b',
            fg='#ffffff',
            font=("", 11),
            selectcolor='#404040',
            activebackground='#2b2b2b',
            activeforeground='#ffffff'
        )
        self.auto_parse_check.pack(side='left', padx=(0, 15))
        
        # 第二行按鈕
        button_row2 = tk.Frame(button_frame, bg='#2b2b2b')
        button_row2.pack(fill='x')
        
        # 清空按鈕
        self.clear_btn = tk.Button(
            button_row2,
            text="🗑️ 清空",
            command=self.clear_output,
            bg='#e74c3c',
            font=("", 12),
            relief='flat',
            padx=25,
            pady=8,
            cursor='hand2',
            activebackground='#c0392b'
        )
        self.clear_btn.pack(side='left', padx=(0, 15))
        
        # 儲存按鈕
        self.save_btn = tk.Button(
            button_row2,
            text="💾 儲存結果",
            command=self.save_result,
            bg='#9b59b6',
            font=("", 12),
            relief='flat',
            padx=25,
            pady=8,
            cursor='hand2',
            activebackground='#8e44ad'
        )
        self.save_btn.pack(side='left', padx=(0, 15))
        
        # 關於按鈕
        self.about_btn = tk.Button(
            button_row2,
            text="ℹ️ 關於",
            command=self.show_about,
            bg='#34495e',
            font=("", 12),
            relief='flat',
            padx=25,
            pady=8,
            cursor='hand2',
            activebackground='#2c3e50'
        )
        self.about_btn.pack(side='right')
        
        # 進度條（預設隱藏）
        self.progress = ttk.Progressbar(
            main_frame,
            mode='indeterminate',
            style='TProgressbar'
        )
        
        # 結果顯示區域
        result_section = tk.LabelFrame(
            main_frame,
            text="  📋 解析結果  ",
            font=("", 12, "bold"),
            bg='#2b2b2b',
            fg='#ffffff',
            bd=2,
            relief='groove'
        )
        result_section.pack(fill='both', expand=True, pady=(0, 15))
        
        # 文字顯示區域
        text_frame = tk.Frame(result_section, bg='#1e1e1e')
        text_frame.pack(fill='both', expand=True, padx=15, pady=15)
        
        self.result_text = scrolledtext.ScrolledText(
            text_frame,
            bg='#1e1e1e',
            fg='#ffffff',
            font=("Consolas", 11),
            wrap=tk.WORD,
            state='disabled',
            insertbackground='white',
            selectbackground='#404040',
            selectforeground='#ffffff',
            bd=0,
            relief='flat'
        )
        self.result_text.pack(fill='both', expand=True)
        
        # 顯示歡迎訊息
        self.show_welcome_message()
        
        # 狀態列
        status_frame = tk.Frame(main_frame, bg='#34495e', relief='sunken', bd=1)
        status_frame.pack(fill='x')
        
        self.status_var = tk.StringVar()
        if self.drag_enabled:
            self.status_var.set("✅ 程式就緒 - 拖拽 PNG 圖片到上方區域或點選選擇檔案")
        else:
            self.status_var.set("✅ 程式就緒 - 點選選擇 PNG 圖片檔案")
        
        self.status_label = tk.Label(
            status_frame,
            textvariable=self.status_var,
            bg='#34495e',
            fg='#ffffff',
            font=("", 10),
            anchor='w',
            padx=15,
            pady=5
        )
        self.status_label.pack(fill='x')
    
    def show_welcome_message(self):
        """顯示歡迎訊息"""
        drag_info = """
🎯 拖拽功能:
   • 直接拖拽 PNG 圖片到上方區域
   • 支援自動解析（可在按鈕區域關閉）
   • 拖拽後立即開始處理""" if self.drag_enabled else """
📁 檔案選擇:
   • 點選「選擇 PNG 檔案」按鈕
   • 支援快速鍵 Ctrl+O 開啟檔案
   • 💡 可安裝 windnd 獲得拖拽支援: pip install windnd"""

        welcome_text = f"""🎉 歡迎使用 PNG 元數據解析器 v2.0！

📋 功能特點：
   • 支援 ComfyUI 生成的 PNG 圖片（包含完整工作流程資訊）
   • 支援 Stable Diffusion WebUI 生成的 PNG 圖片（包含參數資訊）
   • 支援其他包含文字元數據的 PNG 圖片
   • 現代化介面設計，深色主題護眼
{drag_info}

🚀 使用步驟：
   1️⃣ {"拖拽 PNG 圖片到上方區域，或" if self.drag_enabled else ""}點選 "選擇 PNG 檔案" 按鈕
   2️⃣ {"程式會自動解析（如果開啟自動解析），或" if self.drag_enabled else ""}點選 "開始解析" 按鈕
   3️⃣ 查看詳細的生成參數、模型資訊和提示詞
   4️⃣ 可選擇儲存解析結果到文字檔案

💡 解析內容包括：
   • 圖片基本資訊（尺寸、色彩模式、檔案大小等）
   • 生成參數（種子、採樣步數、CFG、採樣器等）
   • 模型資訊（主模型、LoRA 模型等）
   • 提示詞（正面和負面提示詞，格式化顯示）
   • 工作流程統計（節點數量、版本資訊等）

⌨️ 快速鍵：
   • Ctrl+O: 選擇檔案   • F5: 開始解析
   • Ctrl+S: 儲存結果   • F1: 關於程式

現在就{"拖拽一個 PNG 圖片或" if self.drag_enabled else ""}選擇一個 PNG 圖片開始解析吧！"""

        self.result_text.configure(state='normal')
        self.result_text.delete('1.0', tk.END)
        self.result_text.insert('1.0', welcome_text)
        self.result_text.configure(state='disabled')
    
    def browse_file(self):
        """瀏覽檔案對話框"""
        file_path = filedialog.askopenfilename(
            title="選擇 PNG 圖片檔案",
            filetypes=[
                ("PNG 圖片", "*.png"),
                ("所有圖片", "*.png;*.jpg;*.jpeg"),
                ("所有檔案", "*.*")
            ],
            initialdir=os.path.expanduser("~")
        )
        
        if file_path:
            self.current_file_path = file_path
            filename = os.path.basename(file_path)
            self.file_path_var.set(filename)
            self.parse_btn.configure(state='normal')
            self.status_var.set(f"✅ 已選擇檔案: {filename}")
            
            # 清空之前的結果
            self.clear_output()
            
            # 如果啟用自動解析，則自動開始解析
            if self.auto_parse_var.get():
                self.root.after(300, self.start_parsing)
    
    def start_parsing(self):
        """開始解析"""
        if not self.current_file_path:
            messagebox.showwarning("警告", "請先選擇一個 PNG 檔案")
            return
        
        # 停用解析按鈕，顯示進度條
        self.parse_btn.configure(state='disabled', text="🔄 解析中...")
        self.progress.pack(fill='x', pady=(10, 15))
        self.progress.start(10)
        self.status_var.set("🔄 正在解析圖片元數據，請稍候...")
        
        # 在背景執行緒中執行解析
        thread = threading.Thread(target=self.process_image_thread)
        thread.daemon = True
        thread.start()
    
    def process_image_thread(self):
        """在背景執行緒中處理圖片"""
        try:
            result = self.parse_png_info(self.current_file_path)
            self.root.after(0, self.parsing_complete, result, None)
        except Exception as e:
            self.root.after(0, self.parsing_complete, None, e)
    
    def parsing_complete(self, result, error):
        """解析完成的回調"""
        # 恢復介面狀態
        self.progress.stop()
        self.progress.pack_forget()
        self.parse_btn.configure(state='normal', text="🔍 開始解析")
        
        if error:
            error_msg = f"❌ 解析失敗: {str(error)}"
            self.display_result(error_msg)
            self.status_var.set("❌ 解析失敗，請檢查檔案")
            messagebox.showerror("解析錯誤", str(error))
        else:
            self.display_result(result)
            filename = os.path.basename(self.current_file_path)
            self.status_var.set(f"✅ 解析完成: {filename}")
    
    def parse_png_info(self, image_path):
        """解析 PNG 圖片的元數據"""
        result_lines = []
        
        try:
            img = Image.open(image_path)
            metadata = img.info
            
            # 基本資訊
            result_lines.append("=" * 80)
            result_lines.append("🖼️  PNG 圖片元數據解析報告")
            result_lines.append("=" * 80)
            result_lines.append(f"📁 檔案路徑: {image_path}")
            result_lines.append(f"📄 檔案名稱: {os.path.basename(image_path)}")
            result_lines.append(f"📐 圖片尺寸: {img.size[0]} × {img.size[1]} 像素")
            result_lines.append(f"🎨 色彩模式: {img.mode}")
            result_lines.append(f"📊 檔案大小: {os.path.getsize(image_path) / 1024:.1f} KB")
            result_lines.append(f"⏰ 解析時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            result_lines.append("=" * 80)
            
            if not metadata:
                result_lines.append("\n❌ 未找到元數據資訊")
                result_lines.append("\n💡 可能的原因:")
                result_lines.append("   • 該圖片不是由 AI 生成工具建立的")
                result_lines.append("   • 圖片在處理過程中遺失了元數據")
                result_lines.append("   • 圖片經過了壓縮或格式轉換")
                result_lines.append("\n🔍 建議:")
                result_lines.append("   • 確認圖片是由 ComfyUI 或 Stable Diffusion WebUI 直接生成")
                result_lines.append("   • 檢查圖片是否為原始輸出檔案")
                return "\n".join(result_lines)
            
            # 顯示找到的元數據金鑰
            result_lines.append(f"\n📋 發現的元數據金鑰: {', '.join(metadata.keys())}")
            
            # 檢查格式並解析
            if 'prompt' in metadata and 'workflow' in metadata:
                result_lines.append("\n🔍 檢測到 ComfyUI 工作流程格式")
                result_lines.extend(self.parse_comfyui_info(metadata))
            elif 'parameters' in metadata:
                result_lines.append("\n🔍 檢測到 Stable Diffusion WebUI 格式")
                result_lines.extend(self.parse_webui_info(metadata))
            else:
                result_lines.append("\n📋 通用元數據:")
                for key, value in metadata.items():
                    value_str = str(value)
                    if len(value_str) > 1000:
                        value_str = value_str[:1000] + "\n   ... (內容過長，已截斷)"
                    result_lines.append(f"   🔸 {key}: {value_str}")
                    
        except Exception as e:
            result_lines.append(f"❌ 解析出錯: {e}")
        
        return "\n".join(result_lines)
    
    def parse_comfyui_info(self, metadata):
        """解析 ComfyUI 工作流程資訊"""
        result_lines = []
        
        try:
            prompt_data = json.loads(metadata['prompt'])
            
            result_lines.append("\n" + "🎯 生成參數".center(60, "="))
            
            # 查找 KSampler 節點
            ksampler_node = None
            for node_id, node_data in prompt_data.items():
                if node_data.get('class_type') == 'KSampler':
                    ksampler_node = node_data
                    break
            
            if ksampler_node:
                inputs = ksampler_node['inputs']
                seed_value = inputs.get('seed', 'N/A')
                if isinstance(seed_value, (int, float)):
                    result_lines.append(f"   🌱 隨機種子: {seed_value:,}")
                else:
                    result_lines.append(f"   🌱 隨機種子: {seed_value}")
                    
                result_lines.append(f"   🔢 採樣步數: {inputs.get('steps', 'N/A')}")
                result_lines.append(f"   ⚖️  CFG Scale: {inputs.get('cfg', 'N/A')}")
                result_lines.append(f"   🎲 採樣器: {inputs.get('sampler_name', 'N/A')}")
                result_lines.append(f"   📅 調度器: {inputs.get('scheduler', 'N/A')}")
                result_lines.append(f"   🔄 去噪強度: {inputs.get('denoise', 'N/A')}")
            
            # 查找模型資訊
            model_nodes = [node for node in prompt_data.values() 
                          if node.get('class_type') == 'CheckpointLoaderSimple']
            if model_nodes:
                model_name = model_nodes[0]['inputs'].get('ckpt_name', 'N/A')
                result_lines.append(f"   🤖 使用模型: {model_name}")
            
            # 查找 LoRA 資訊
            lora_nodes = [node for node in prompt_data.values() 
                         if node.get('class_type') == 'LoraLoader']
            if lora_nodes:
                result_lines.append(f"\n" + "🎨 LoRA 模型".center(60, "="))
                for i, lora_node in enumerate(lora_nodes, 1):
                    inputs = lora_node['inputs']
                    lora_name = inputs.get('lora_name', inputs.get('model', 'N/A'))
                    strength = inputs.get('strength_model', inputs.get('strength', 'N/A'))
                    result_lines.append(f"   {i:02d}. {lora_name} (強度: {strength})")
            
            # 查找圖片尺寸
            latent_nodes = [node for node in prompt_data.values() 
                           if node.get('class_type') == 'EmptyLatentImage']
            if latent_nodes:
                inputs = latent_nodes[0]['inputs']
                width = inputs.get('width', 'N/A')
                height = inputs.get('height', 'N/A')
                batch_size = inputs.get('batch_size', 'N/A')
                result_lines.append(f"   📏 生成尺寸: {width} × {height}")
                result_lines.append(f"   📦 批次大小: {batch_size}")
            
            # 查找提示詞
            clip_nodes = [node for node in prompt_data.values() 
                         if node.get('class_type') == 'CLIPTextEncode']
            
            positive_prompt = None
            negative_prompt = None
            
            for node in clip_nodes:
                text = node['inputs'].get('text', '').strip()
                if text:
                    if positive_prompt is None:
                        positive_prompt = text
                    elif text != positive_prompt:
                        negative_prompt = text
            
            if positive_prompt:
                result_lines.append(f"\n" + "✨ 正面提示詞".center(60, "="))
                formatted_prompt = positive_prompt.replace(', ', ',\n   ')
                result_lines.append(f"   {formatted_prompt}")
            
            if negative_prompt:
                result_lines.append(f"\n" + "🚫 負面提示詞".center(60, "="))
                formatted_negative = negative_prompt.replace(', ', ',\n   ')
                result_lines.append(f"   {formatted_negative}")
            
            # 工作流程統計
            workflow_data = json.loads(metadata['workflow'])
            node_count = len(workflow_data.get('nodes', []))
            result_lines.append(f"\n" + "📊 工作流程統計".center(60, "="))
            result_lines.append(f"   🔗 節點總數: {node_count}")
            
            workflow_id = workflow_data.get('id', 'N/A')
            if workflow_id != 'N/A':
                result_lines.append(f"   🆔 工作流程ID: {workflow_id[:32]}...")
            
            frontend_version = workflow_data.get('extra', {}).get('frontendVersion', 'N/A')
            if frontend_version != 'N/A':
                result_lines.append(f"   🖥️  ComfyUI 版本: {frontend_version}")
            
        except json.JSONDecodeError as e:
            result_lines.append(f"❌ JSON 解析錯誤: {e}")
        except Exception as e:
            result_lines.append(f"❌ ComfyUI 資訊解析錯誤: {e}")
        
        return result_lines
    
    def parse_webui_info(self, metadata):
        """解析 WebUI 參數"""
        result_lines = []
        
        try:
            params = metadata['parameters']
            lines = params.split('\n')
            
            positive_prompt = ""
            negative_prompt = ""
            settings = {}
            
            in_negative = False
            for line in lines:
                line = line.strip()
                if line.startswith('Negative prompt:'):
                    in_negative = True
                    negative_prompt = line.replace('Negative prompt:', '').strip()
                elif line.startswith('Steps:'):
                    parts = line.split(', ')
                    for part in parts:
                        if ':' in part:
                            key, value = part.split(':', 1)
                            settings[key.strip()] = value.strip()
                    in_negative = False
                elif not in_negative and not line.startswith('Steps:'):
                    if positive_prompt:
                        positive_prompt += " " + line
                    else:
                        positive_prompt = line
                elif in_negative and not line.startswith('Steps:'):
                    negative_prompt += " " + line
            
            if positive_prompt:
                result_lines.append(f"\n" + "✨ 正面提示詞".center(60, "="))
                formatted_prompt = positive_prompt.replace(', ', ',\n   ')
                result_lines.append(f"   {formatted_prompt}")
            
            if negative_prompt:
                result_lines.append(f"\n" + "🚫 負面提示詞".center(60, "="))
                formatted_negative = negative_prompt.replace(', ', ',\n   ')
                result_lines.append(f"   {formatted_negative}")
            
            result_lines.append(f"\n" + "🎯 生成參數".center(60, "="))
            setting_names = {
                'Steps': '🔢 採樣步數',
                'Sampler': '🎲 採樣器',
                'CFG scale': '⚖️  CFG Scale',
                'Seed': '🌱 隨機種子',
                'Size': '📏 圖片尺寸',
                'Model hash': '🔑 模型雜湊',
                'Model': '🤖 使用模型',
                'Denoising strength': '🔄 去噪強度',
                'Clip skip': '⏭️  CLIP跳過',
            }
            
            for key, value in settings.items():
                display_name = setting_names.get(key, f"🔸 {key}")
                result_lines.append(f"   {display_name}: {value}")
                
        except Exception as e:
            result_lines.append(f"❌ WebUI 參數解析錯誤: {e}")
        
        return result_lines
    
    def display_result(self, result):
        """顯示解析結果"""
        self.result_text.configure(state='normal')
        self.result_text.delete('1.0', tk.END)
        self.result_text.insert('1.0', result)
        self.result_text.configure(state='disabled')
        self.result_text.see('1.0')
    
    def clear_output(self):
        """清空輸出"""
        self.show_welcome_message()
        self.status_var.set("🧹 已清空結果")
    
    def save_result(self):
        """儲存解析結果"""
        content = self.result_text.get('1.0', tk.END).strip()
        if not content or "歡迎使用" in content:
            messagebox.showwarning("警告", "沒有解析結果可儲存")
            return
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if self.current_file_path:
            base_name = os.path.splitext(os.path.basename(self.current_file_path))[0]
            default_filename = f"{base_name}_解析結果_{timestamp}.txt"
        else:
            default_filename = f"PNG解析結果_{timestamp}.txt"
        
        file_path = filedialog.asksaveasfilename(
            title="儲存解析結果",
            initialfilename=default_filename,
            defaultextension=".txt",
            filetypes=[("文字檔案", "*.txt"), ("所有檔案", "*.*")]
        )
        
        if file_path:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                    f.write(f"\n\n{'='*50}")
                    f.write(f"\n儲存時間: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    f.write(f"\n生成工具: PNG 元數據解析器 v2.0")
                
                messagebox.showinfo("儲存成功", f"結果已儲存到:\n{file_path}")
                self.status_var.set(f"💾 已儲存: {os.path.basename(file_path)}")
            except Exception as e:
                messagebox.showerror("儲存失敗", f"儲存檔案時出錯:\n{e}")
    
    def show_about(self):
        """顯示關於對話框"""
        drag_feature = "• 支援拖拽 PNG 圖片到程式視窗" if self.drag_enabled else "• 檔案選擇功能 (可安裝 windnd 獲得拖拽支援)"
        
        about_text = f"""PNG 元數據解析器 v2.0

🎯 功能特點:
• 解析 PNG 圖片的元數據資訊
• 支援 ComfyUI 工作流程格式  
• 支援 Stable Diffusion WebUI 格式
• 美化顯示生成參數和提示詞
• 儲存解析結果到文字檔案
{drag_feature}
• 自動解析功能

📋 支援的格式:
• ComfyUI 工作流程圖片
• Stable Diffusion WebUI 生成圖片
• 其他包含文字元數據的 PNG 圖片

🛠️ 技術資訊:
• 基於 Python + tkinter
• 使用 PIL 處理圖片
• 支援 JSON 格式元數據解析
{"• 使用 windnd 實現拖拽功能" if self.drag_enabled else "• 建議安裝 windnd 獲得拖拽支援"}

💡 使用提示:
1. {"拖拽 PNG 圖片到程式視窗，或" if self.drag_enabled else ""}選擇 PNG 格式的圖片檔案
2. 程式會{"自動解析（如啟用）或" if self.drag_enabled else ""}點選「開始解析」查看結果
3. 可儲存解析結果供後續使用

⌨️ 快速鍵:
• Ctrl+O: 開啟檔案  • F5: 開始解析  
• Ctrl+S: 儲存結果  • F1: 顯示此說明

如有問題或建議，歡迎回饋！"""
        
        messagebox.showinfo("關於 PNG 元數據解析器", about_text)
    
    def run(self):
        """執行應用程式"""
        # 綁定快速鍵
        self.root.bind('<Control-o>', lambda e: self.browse_file())
        self.root.bind('<F5>', lambda e: self.start_parsing())
        self.root.bind('<Control-s>', lambda e: self.save_result())
        self.root.bind('<F1>', lambda e: self.show_about())
        
        # 設定關閉事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 啟動主迴圈
        self.root.mainloop()
    
    def on_closing(self):
        """關閉程式"""
        if messagebox.askokcancel("結束程式", "確定要結束嗎？"):
            self.root.quit()
            self.root.destroy()

def main():
    """主函式"""
    try:
        app = PNGInfoParser()
        app.run()
    except Exception as e:
        messagebox.showerror("啟動失敗", f"程式啟動失敗:\n{e}")
        sys.exit(1)

if __name__ == "__main__":
    main()