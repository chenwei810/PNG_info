#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PNG Info 檢視器 v3.0（macOS）

tkinter + tkinterdnd2 介面，解析邏輯在 pnginfo_core.py。
  • 把圖片或資料夾拖進視窗任何位置，可一次拖多張
  • 打包成 .app 後，也可以把圖片拖到 Dock 圖示上，或在 Finder 用「打開方式」開啟
  • 每個欄位都能一鍵複製，也能複製成 WebUI 格式
"""

from __future__ import annotations

import csv
import importlib.metadata
import json
import os
import platform
import queue
import re
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

import pnginfo_core as core

try:
    # 匯入時 tkinterdnd2 就會替所有元件加上 drop_target_register / dnd_bind
    from tkinterdnd2 import DND_FILES, TkinterDnD
except Exception:  # 沒裝 tkinterdnd2 時仍可用「加入圖片」按鈕
    DND_FILES = TkinterDnD = None

APP_NAME = 'PNG Info 檢視器'
APP_VERSION = '3.1'

IS_MAC = sys.platform == 'darwin'
MOD = 'Command' if IS_MAC else 'Control'

# 0.6.4 起同時內含 Apple Silicon 的 Tk 8.6 與 Tk 9 版本（Homebrew 的 Python 用 Tk 9）
MIN_DND_VERSION = (0, 6, 4)


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r'\d+', str(text))[:3])


def _dnd_package_version() -> str | None:
    try:
        return importlib.metadata.version('tkinterdnd2')
    except importlib.metadata.PackageNotFoundError:
        return None


def load_dnd(root: tk.Tk) -> tuple[str, str]:
    """在既有的視窗上載入 tkdnd 拖放函式庫。
    成功回傳 ('', '')；失敗回傳 (看得懂的原因, 修正指令)。"""
    pip_cmd = f'"{sys.executable}" -m pip install -U tkinterdnd2'
    if TkinterDnD is None:
        return '沒有安裝 tkinterdnd2。', pip_cmd

    tk_version = str(root.tk.call('info', 'patchlevel'))
    if _version_tuple(tk_version) < (8, 6):
        return (f'這個 Python 的 Tk 版本太舊（{tk_version}），通常是 macOS 內建的 /usr/bin/python3。\n'
                '請改用 python.org 的 Python 安裝檔重新建立 venv。'), ''

    try:
        TkinterDnD._require(root)
        return '', ''
    except Exception:
        pass
    # tkinterdnd2 只會說「Unable to load tkdnd library」，再載入一次拿到 Tcl 的真正錯誤
    try:
        root.tk.call('package', 'require', 'tkdnd')
        return '', ''
    except tk.TclError as exc:
        detail = str(exc)

    version = _dnd_package_version()
    reason = f'無法載入 tkdnd 拖放函式庫：{detail}'
    if version and _version_tuple(version) < MIN_DND_VERSION:
        reason += f'\ntkinterdnd2 版本太舊（{version}），需要 0.6.4 以上。'
    reason += f'\n（Python {platform.python_version()}，{platform.machine()}，Tk {tk_version}）'
    return reason, pip_cmd


def accel(key: str, shift: bool = False) -> str:
    """選單上顯示的快捷鍵文字（macOS 會自動顯示成 ⌘ 符號）"""
    if IS_MAC:
        return f'Command-{"Shift-" if shift else ""}{key}'
    return f'Ctrl+{"Shift+" if shift else ""}{key}'


WELCOME_TEXT = f"""把 PNG / JPG / WebP 圖片拖進這個視窗的任何位置就會自動解析，也可以一次拖多張或整個資料夾。

支援：
  • ComfyUI（從採樣器反向追蹤節點連線，正負面不會判斷反）
  • Stable Diffusion WebUI / Forge
  • 其他含文字中繼資料的圖片

快捷鍵：
  {accel('O')}　加入圖片　　　　{accel('O', True)}　加入資料夾
  {accel('1')}　複製正面提示詞　{accel('2')}　複製負面提示詞
  {accel('3')}　複製 LoRA　　　 {accel('4')}　複製生成參數
  {accel('C', True)}　複製 WebUI 格式　{accel('E')}　匯出目前圖片為 TXT

小提示：在 LoRA 或參數清單上連點兩下，可以只複製那一列。"""

NO_META_TEXT = ('這張圖片沒有任何文字中繼資料。\n\n'
                '常見原因：截圖、經過壓縮或轉檔、從社群網站或聊天軟體下載，'
                '或是由不寫入參數的服務產生（例如 ChatGPT 的圖片只帶 C2PA 來源憑證，沒有提示詞）。')


class PngInfoApp:
    THUMB_SIZE = 168

    def __init__(self, initial_paths: list[str] | None = None):
        self.dnd_enabled = False
        self.dnd_error = ''
        self.dnd_fix_cmd = ''
        self.root = self._create_root()
        self.root.title(f'{APP_NAME} v{APP_VERSION}')
        self.root.geometry('1200x800')
        self.root.minsize(900, 600)

        self._init_fonts_and_style()

        # 清單資料：iid → {'path', 'mtime', 'info', 'thumb'}
        self.entries: dict[str, dict] = {}
        self.path_to_iid: dict[str, str] = {}
        self._iid_counter = 0
        self.current_iid: str | None = None
        self.focus_iid: str | None = None
        self._rendered: tuple | None = None
        self._thumb_photo = None
        self._pending = 0
        self.last_dir = os.path.expanduser('~')

        # 背景解析執行緒：主執行緒只負責介面，避免拖很多張時卡住
        self.task_q: queue.Queue = queue.Queue()
        self.result_q: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()

        self.auto_follow = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar()

        self._build_menu()
        self._build_ui()
        self._bind_shortcuts()
        self._setup_drop()
        self._setup_mac_events()
        self._show_empty()
        self._update_empty_hint()

        if self.dnd_enabled:
            self.set_status('就緒：把圖片拖進視窗即可解析')
        else:
            self.set_status('拖放功能未啟用，請看提示視窗')
            self.root.after(400, self._warn_dnd_disabled)

        self.root.after(80, self._poll_results)
        if initial_paths:
            self.root.after(300, lambda: self.add_paths(initial_paths))

    # ──────────────────────────────────────────────
    # 初始化
    # ──────────────────────────────────────────────

    def _create_root(self) -> tk.Tk:
        # 只建立一個視窗，再把 tkdnd 載入進去。
        # （TkinterDnD.Tk() 失敗時視窗已經建好了，再開一個 tk.Tk() 會多出一個空白視窗）
        root = tk.Tk()
        self.dnd_error, self.dnd_fix_cmd = load_dnd(root)
        self.dnd_enabled = not self.dnd_error
        return root

    def _warn_dnd_disabled(self) -> None:
        message = self.dnd_error
        if self.dnd_fix_cmd:
            self.root.clipboard_clear()
            self.root.clipboard_append(self.dnd_fix_cmd)
            message += ('\n\n修正方式：在終端機貼上並執行下面這行（已複製到剪貼簿），再重新開啟程式：\n\n'
                        + self.dnd_fix_cmd)
        message += f'\n\n在那之前，仍然可以用「加入圖片…」（{accel("O")}）。'
        messagebox.showwarning('拖放功能未啟用', message, parent=self.root)

    def _init_fonts_and_style(self) -> None:
        families = set(tkfont.families(self.root))
        default_family = tkfont.nametofont('TkDefaultFont').actual('family')
        ui_family = next((f for f in ('PingFang TC', 'Heiti TC', 'Microsoft JhengHei UI',
                                      'Microsoft JhengHei', 'Noto Sans CJK TC') if f in families),
                         default_family)
        mono_family = next((f for f in ('Menlo', 'SF Mono', 'Consolas', 'DejaVu Sans Mono') if f in families),
                           'TkFixedFont')
        base = 14 if IS_MAC else 10
        self.text_font = tkfont.Font(family=ui_family, size=base)
        self.section_font = tkfont.Font(family=ui_family, size=base, weight='bold')
        self.title_font = tkfont.Font(family=ui_family, size=base + 4, weight='bold')
        self.mono_font = tkfont.Font(family=mono_family, size=base - 1)

        style = ttk.Style(self.root)
        style.configure('Treeview', rowheight=max(22, self.text_font.metrics('linespace') + 6))
        style.configure('Muted.TLabel', foreground='gray')
        style.configure('Warn.TLabel', foreground='#d35400')

    def _build_menu(self) -> None:
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label='加入圖片…', accelerator=accel('O'), command=self.browse_files)
        file_menu.add_command(label='加入資料夾…', accelerator=accel('O', True), command=self.browse_folder)
        file_menu.add_separator()
        file_menu.add_command(label='匯出目前圖片為 TXT…', accelerator=accel('E'), command=self.export_current_txt)
        file_menu.add_command(label='匯出全部為 JSON…', command=lambda: self.export_all('json'))
        file_menu.add_command(label='匯出全部為 CSV…', command=lambda: self.export_all('csv'))
        file_menu.add_separator()
        file_menu.add_command(label='在 Finder 中顯示', command=self.reveal_in_finder)
        file_menu.add_command(label='顯示原始中繼資料', command=self.show_raw)
        file_menu.add_separator()
        file_menu.add_command(label='移除選取的圖片', command=self.remove_selected)
        file_menu.add_command(label='清空清單', command=self.clear_all)
        menubar.add_cascade(label='檔案', menu=file_menu)

        copy_menu = tk.Menu(menubar, tearoff=0)
        copy_menu.add_command(label='正面提示詞', accelerator=accel('1'), command=lambda: self.copy_field('positive'))
        copy_menu.add_command(label='負面提示詞', accelerator=accel('2'), command=lambda: self.copy_field('negative'))
        copy_menu.add_command(label='LoRA', accelerator=accel('3'), command=lambda: self.copy_field('loras'))
        copy_menu.add_command(label='生成參數', accelerator=accel('4'), command=lambda: self.copy_field('params'))
        copy_menu.add_separator()
        copy_menu.add_command(label='WebUI 格式', accelerator=accel('C', True), command=lambda: self.copy_field('webui'))
        copy_menu.add_command(label='完整報告', command=lambda: self.copy_field('report'))
        menubar.add_cascade(label='複製', menu=copy_menu)

        if not IS_MAC:  # macOS 的「關於」放在應用程式選單（見 _setup_mac_events）
            help_menu = tk.Menu(menubar, tearoff=0)
            help_menu.add_command(label='關於', command=self.show_about)
            menubar.add_cascade(label='說明', menu=help_menu)

        self.root.config(menu=menubar)

    def _build_ui(self) -> None:
        # 狀態列要先 pack，視窗縮小時才不會被擠掉
        ttk.Label(self.root, textvariable=self.status_var, anchor='w',
                  padding=(12, 4)).pack(side='bottom', fill='x')

        outer = ttk.Frame(self.root, padding=(10, 10, 10, 0))
        outer.pack(fill='both', expand=True)
        paned = ttk.PanedWindow(outer, orient='horizontal')
        paned.pack(fill='both', expand=True)

        left = ttk.Frame(paned, padding=(0, 0, 8, 0))
        right = ttk.Frame(paned, padding=(8, 0, 0, 0))
        paned.add(left, weight=1)
        paned.add(right, weight=3)

        self._build_left(left)
        self._build_right(right)

    def _build_left(self, parent: ttk.Frame) -> None:
        self._hint_text = ('⬇  把圖片或資料夾拖進視窗任何位置' if self.dnd_enabled
                           else '拖放未啟用，請用下方「加入圖片」')
        self.drop_hint = ttk.Label(parent, text=self._hint_text, anchor='center',
                                   padding=(8, 14), relief='groove')
        self.drop_hint.pack(fill='x', pady=(0, 8))

        tree_box = ttk.Frame(parent)
        tree_box.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(tree_box, columns=('name', 'source', 'status'),
                                 show='headings', selectmode='extended')
        self.tree.heading('name', text='檔名')
        self.tree.heading('source', text='來源')
        self.tree.heading('status', text='狀態')
        self.tree.column('name', width=210, stretch=True)
        self.tree.column('source', width=110, stretch=False)
        self.tree.column('status', width=60, stretch=False, anchor='center')
        scroll = ttk.Scrollbar(tree_box, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self._on_select)
        self.tree.bind('<Delete>', lambda e: self.remove_selected())
        self.tree.bind('<BackSpace>', lambda e: self.remove_selected())

        # 清單是空的時候，在中間顯示大大的拖放提示（它本身也是拖放目標）
        empty_text = ('把圖片拖到這裡\n\n可以一次拖多張，或整個資料夾' if self.dnd_enabled
                      else f'拖放功能未啟用\n\n請用下方「加入圖片…」或 {accel("O")}')
        # 背景要跟清單一樣；macOS 用系統顏色名稱，深色／淺色模式都會自動跟著變
        style = ttk.Style(self.root)
        list_bg = ('systemTextBackgroundColor' if IS_MAC else
                   style.lookup('Treeview', 'fieldbackground') or style.lookup('Treeview', 'background') or 'white')
        try:
            self.empty_hint = tk.Label(tree_box, text=empty_text, justify='center', font=self.section_font,
                                       fg='gray', bg=list_bg, padx=12, pady=12)
        except tk.TclError:  # 舊版 Tk 不認得系統顏色名稱
            self.empty_hint = tk.Label(tree_box, text=empty_text, justify='center', font=self.section_font,
                                       fg='gray', bg='white', padx=12, pady=12)

        buttons = ttk.Frame(parent)
        buttons.pack(fill='x', pady=(8, 4))
        ttk.Button(buttons, text='加入圖片…', command=self.browse_files).pack(side='left')
        ttk.Button(buttons, text='加入資料夾…', command=self.browse_folder).pack(side='left', padx=4)
        ttk.Button(buttons, text='清空', command=self.clear_all).pack(side='right')
        ttk.Button(buttons, text='移除', command=self.remove_selected).pack(side='right', padx=4)

        ttk.Checkbutton(parent, text='自動跳到最新拖入的圖片',
                        variable=self.auto_follow).pack(anchor='w', pady=(2, 8))

    def _build_right(self, parent: ttk.Frame) -> None:
        # ── 頂部：縮圖與檔案資訊 ──
        header = ttk.Frame(parent)
        header.pack(fill='x')
        self.thumb_label = ttk.Label(header)
        self.thumb_label.pack(side='left', padx=(0, 14))

        meta = ttk.Frame(header)
        meta.pack(side='left', fill='both', expand=True)
        self.name_label = ttk.Label(meta, font=self.title_font, anchor='w')
        self.name_label.pack(fill='x')
        self.source_label = ttk.Label(meta, anchor='w')
        self.source_label.pack(fill='x', pady=(4, 0))
        self.image_label = ttk.Label(meta, anchor='w')
        self.image_label.pack(fill='x')
        self.path_label = ttk.Label(meta, anchor='w', style='Muted.TLabel', wraplength=620)
        self.path_label.pack(fill='x')
        self.notes_label = ttk.Label(meta, anchor='w', style='Warn.TLabel', wraplength=620, justify='left')
        self.notes_label.pack(fill='x', pady=(2, 0))

        actions = ttk.Frame(meta)
        actions.pack(anchor='w', pady=(8, 0))
        ttk.Button(actions, text='在 Finder 中顯示', command=self.reveal_in_finder).pack(side='left')
        ttk.Button(actions, text='原始中繼資料', command=self.show_raw).pack(side='left', padx=4)
        ttk.Button(actions, text='匯出 TXT…', command=self.export_current_txt).pack(side='left')

        # ── 中間：可調整高度的各個區塊 ──
        body = ttk.PanedWindow(parent, orient='vertical')
        body.pack(fill='both', expand=True, pady=(10, 0))

        self.pos_text = self._text_section(body, '正面提示詞', lambda: self.copy_field('positive'), weight=3)
        self.neg_text = self._text_section(body, '負面提示詞', lambda: self.copy_field('negative'), weight=2)

        bottom = ttk.Frame(body)
        body.add(bottom, weight=2)
        bottom.columnconfigure(0, weight=1)
        bottom.columnconfigure(1, weight=1)
        bottom.rowconfigure(0, weight=1)

        lora_frame = ttk.Frame(bottom)
        lora_frame.grid(row=0, column=0, sticky='nsew', padx=(0, 6))
        self.lora_tree = self._tree_section(
            lora_frame, 'LoRA', lambda: self.copy_field('loras'),
            columns=(('name', 'LoRA', 220, True), ('model', 'Model', 70, False), ('clip', 'CLIP', 70, False)))
        self.lora_tree.bind('<Double-1>', self._copy_lora_row)

        param_frame = ttk.Frame(bottom)
        param_frame.grid(row=0, column=1, sticky='nsew', padx=(6, 0))
        self.param_tree = self._tree_section(
            param_frame, '生成參數', lambda: self.copy_field('params'),
            columns=(('key', '項目', 110, False), ('value', '數值', 240, True)))
        self.param_tree.bind('<Double-1>', self._copy_param_row)

        # ── 底部：主要動作 ──
        footer = ttk.Frame(parent)
        footer.pack(fill='x', pady=(8, 8))
        ttk.Button(footer, text='複製 WebUI 格式', default='active',
                   command=lambda: self.copy_field('webui')).pack(side='left')
        ttk.Button(footer, text='複製完整報告',
                   command=lambda: self.copy_field('report')).pack(side='left', padx=6)

    def _section_header(self, parent, title: str, copy_cmd) -> None:
        head = ttk.Frame(parent)
        head.pack(fill='x', pady=(6, 4))
        ttk.Label(head, text=title, font=self.section_font).pack(side='left')
        ttk.Button(head, text='複製', width=6, command=copy_cmd).pack(side='right')

    def _text_section(self, paned: ttk.PanedWindow, title: str, copy_cmd, weight: int) -> tk.Text:
        frame = ttk.Frame(paned)
        paned.add(frame, weight=weight)
        self._section_header(frame, title, copy_cmd)
        box = ttk.Frame(frame)
        box.pack(fill='both', expand=True)
        text = tk.Text(box, wrap='word', height=5, font=self.text_font, relief='flat',
                       borderwidth=0, highlightthickness=1, padx=8, pady=6, undo=False)
        scroll = ttk.Scrollbar(box, orient='vertical', command=text.yview)
        text.configure(yscrollcommand=scroll.set, state='disabled')
        scroll.pack(side='right', fill='y')
        text.pack(side='left', fill='both', expand=True)
        # 唯讀但可以選取、⌘C 複製（disabled 的 Text 預設點了不會取得焦點）
        text.bind('<1>', lambda e: text.focus_set())
        return text

    def _tree_section(self, parent, title: str, copy_cmd, columns) -> ttk.Treeview:
        self._section_header(parent, title, copy_cmd)
        box = ttk.Frame(parent)
        box.pack(fill='both', expand=True)
        tree = ttk.Treeview(box, columns=[c[0] for c in columns], show='headings',
                            selectmode='browse', height=5)
        for cid, label, width, stretch in columns:
            tree.heading(cid, text=label)
            # 權重這種短數字置中，其他文字靠左
            tree.column(cid, width=width, stretch=stretch, anchor='center' if cid in ('model', 'clip') else 'w')
        scroll = ttk.Scrollbar(box, orient='vertical', command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        tree.pack(side='left', fill='both', expand=True)
        return tree

    def _bind_shortcuts(self) -> None:
        bind = self.root.bind_all
        bind(f'<{MOD}-o>', lambda e: self.browse_files())
        bind(f'<{MOD}-O>', lambda e: self.browse_folder())          # 加上 Shift
        bind(f'<{MOD}-e>', lambda e: self.export_current_txt())
        bind(f'<{MOD}-C>', lambda e: self.copy_field('webui'))      # 加上 Shift
        # 數字鍵一定要寫成 Key-1，否則 Tk 會當成滑鼠按鍵 1
        for key, field in (('1', 'positive'), ('2', 'negative'), ('3', 'loras'), ('4', 'params')):
            bind(f'<{MOD}-Key-{key}>', lambda e, f=field: self.copy_field(f))

    # ──────────────────────────────────────────────
    # 拖放與 macOS 事件
    # ──────────────────────────────────────────────

    def _setup_drop(self) -> None:
        if self.dnd_enabled:
            self._register_drop_targets(self.root)

    def _register_drop_targets(self, widget) -> None:
        """整個視窗的每個元件都註冊為拖放目標，丟在哪裡都可以"""
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind('<<Drop>>', self._on_drop)
            widget.dnd_bind('<<DropEnter>>', self._on_drop_enter)
            widget.dnd_bind('<<DropLeave>>', self._on_drop_leave)
        except Exception:
            pass
        for child in widget.winfo_children():
            if not isinstance(child, tk.Menu):
                self._register_drop_targets(child)

    def _on_drop_enter(self, event):
        self.drop_hint.configure(text='放開以加入圖片')
        return event.action

    def _on_drop_leave(self, event):
        self.drop_hint.configure(text=self._hint_text)
        return event.action

    def _on_drop(self, event):
        # 拖放回呼裡只收路徑，實際處理交回主迴圈
        paths = list(self.root.tk.splitlist(event.data))
        self.drop_hint.configure(text=self._hint_text)
        self.root.after(0, lambda: self.add_paths(paths))
        return event.action

    def _setup_mac_events(self) -> None:
        if not IS_MAC:
            return
        try:
            # 拖到 Dock 圖示、Finder「打開方式」都會觸發這個事件
            self.root.createcommand('::tk::mac::OpenDocument', self._on_open_document)
            self.root.createcommand('tkAboutDialog', self.show_about)
        except tk.TclError:
            pass

    def _on_open_document(self, *paths) -> None:
        self.root.after(0, lambda: self.add_paths(list(paths)))
        self.root.deiconify()
        self.root.lift()

    # ──────────────────────────────────────────────
    # 背景解析
    # ──────────────────────────────────────────────

    def _worker(self) -> None:
        while True:
            iid, path = self.task_q.get()
            try:
                info = core.parse_file(path)
            except Exception as exc:
                info = core.GenInfo(path=path, source='error', error=str(exc))
            thumb = None
            try:
                with Image.open(path) as img:
                    img.thumbnail((self.THUMB_SIZE, self.THUMB_SIZE))
                    thumb = img.convert('RGBA') if img.mode not in ('RGB', 'RGBA') else img.copy()
            except Exception:
                pass
            self.result_q.put((iid, info, thumb))

    def _poll_results(self) -> None:
        try:
            while True:
                self._apply_result(*self.result_q.get_nowait())
        except queue.Empty:
            pass
        self.root.after(80, self._poll_results)

    def _apply_result(self, iid: str, info: core.GenInfo, thumb) -> None:
        entry = self.entries.get(iid)
        if entry is None:  # 已經被移除
            return
        entry['info'] = info
        entry['thumb'] = thumb
        if info.source == 'error':
            mark = '✗'
        elif info.has_generation_data:
            mark = '✓'
        else:
            mark = '—'
        self.tree.item(iid, values=(info.filename, info.source_label, mark))

        self._pending = max(0, self._pending - 1)
        if self._pending:
            self.set_status(f'解析中…（剩下 {self._pending} 張）')
        else:
            self.set_status(f'解析完成，清單共 {len(self.entries)} 張')

        if iid == self.focus_iid:
            self.focus_iid = None
            self._select(iid)
        elif iid == self.current_iid:
            self._show(iid)

    # ──────────────────────────────────────────────
    # 清單操作
    # ──────────────────────────────────────────────

    def add_paths(self, paths) -> None:
        files = core.expand_paths(paths)
        if not files:
            self.set_status('沒有找到支援的圖片（PNG / JPG / WebP）')
            return

        first_iid = None
        queued = 0
        for path in reversed(files):  # 倒著插到最上面，批次裡的第一張就會排在最上面
            mtime = self._mtime(path)
            iid = self.path_to_iid.get(path)
            if iid and self.entries[iid]['mtime'] == mtime:
                # 同一張圖、檔案沒變：不重新解析，只移到最上面
                self.tree.move(iid, '', 0)
                first_iid = iid
                continue
            if iid is None:
                self._iid_counter += 1
                iid = f'img{self._iid_counter}'
                self.tree.insert('', 0, iid=iid, values=(os.path.basename(path), '', '解析中…'))
                self.path_to_iid[path] = iid
            else:
                self.tree.move(iid, '', 0)
                self.tree.item(iid, values=(os.path.basename(path), '', '解析中…'))
            self.entries[iid] = {'path': path, 'mtime': mtime, 'info': None, 'thumb': None}
            self.task_q.put((iid, path))
            queued += 1
            first_iid = iid

        self._pending += queued
        self.last_dir = os.path.dirname(files[0])
        self._update_empty_hint()
        if queued:
            self.set_status(f'加入 {queued} 張圖片，解析中…')
        else:
            self.set_status('這些圖片已經在清單中')

        if first_iid and (self.auto_follow.get() or self.current_iid is None):
            if self.entries[first_iid]['info'] is not None:
                self._select(first_iid)
            else:
                self.focus_iid = first_iid

    def browse_files(self) -> None:
        paths = filedialog.askopenfilenames(
            title='加入圖片', initialdir=self.last_dir,
            filetypes=[('圖片', ('*.png', '*.jpg', '*.jpeg', '*.webp')), ('所有檔案', '*')])
        if paths:
            self.add_paths(list(paths))

    def browse_folder(self) -> None:
        folder = filedialog.askdirectory(title='加入資料夾（包含子資料夾）', initialdir=self.last_dir)
        if folder:
            self.add_paths([folder])

    def remove_selected(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        next_iid = self.tree.next(selected[-1]) or self.tree.prev(selected[0])
        for iid in selected:
            entry = self.entries.pop(iid, None)
            if entry:
                self.path_to_iid.pop(entry['path'], None)
                if entry['info'] is None:
                    self._pending = max(0, self._pending - 1)
            self.tree.delete(iid)
        if next_iid and next_iid in self.entries:
            self._select(next_iid)
        else:
            self._show_empty()
        self._update_empty_hint()
        self.set_status(f'已移除 {len(selected)} 張')

    def clear_all(self) -> None:
        if not self.entries:
            return
        if not messagebox.askyesno('清空清單', f'要清空清單中的 {len(self.entries)} 張圖片嗎？', parent=self.root):
            return
        while not self.task_q.empty():
            try:
                self.task_q.get_nowait()
            except queue.Empty:
                break
        self.tree.delete(*self.tree.get_children())
        self.entries.clear()
        self.path_to_iid.clear()
        self._pending = 0
        self.focus_iid = None
        self._show_empty()
        self._update_empty_hint()
        self.set_status('已清空清單')

    def _update_empty_hint(self) -> None:
        if self.entries:
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(relx=0.5, rely=0.45, anchor='center')

    def _select(self, iid: str) -> None:
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)
        self._show(iid)

    def _on_select(self, _event=None) -> None:
        selected = self.tree.selection()
        if selected:
            self._show(selected[0])

    @staticmethod
    def _mtime(path: str) -> float:
        try:
            return os.path.getmtime(path)
        except OSError:
            return 0.0

    # ──────────────────────────────────────────────
    # 顯示
    # ──────────────────────────────────────────────

    def _current_info(self) -> core.GenInfo | None:
        entry = self.entries.get(self.current_iid or '')
        return entry['info'] if entry else None

    @staticmethod
    def _set_text(widget: tk.Text, content: str) -> None:
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', content)
        widget.configure(state='disabled')
        widget.yview_moveto(0)

    def _clear_details(self) -> None:
        self.thumb_label.configure(image='')
        self._thumb_photo = None
        for label in (self.source_label, self.image_label, self.path_label, self.notes_label):
            label.configure(text='')
        self._set_text(self.pos_text, '')
        self._set_text(self.neg_text, '')
        self.lora_tree.delete(*self.lora_tree.get_children())
        self.param_tree.delete(*self.param_tree.get_children())

    def _show_empty(self) -> None:
        self.current_iid = None
        self._rendered = None
        self._clear_details()
        self.name_label.configure(text=f'{APP_NAME} v{APP_VERSION}')
        self._set_text(self.pos_text, WELCOME_TEXT)

    def _show(self, iid: str) -> None:
        entry = self.entries.get(iid)
        if entry is None:
            return
        info = entry['info']
        if self._rendered == (iid, id(info)):
            return
        self.current_iid = iid
        self._rendered = (iid, id(info))
        self._clear_details()
        self.name_label.configure(text=os.path.basename(entry['path']))

        if info is None:
            self.source_label.configure(text='解析中…')
            return

        self.source_label.configure(text=f'來源：{info.source_label}')
        if info.width:
            self.image_label.configure(
                text=f'{info.width} × {info.height} 像素　·　{info.mode}　·　{core.format_size(info.file_size)}')
        self.path_label.configure(text=info.path)
        notes = [f'⚠ {n}' for n in info.notes]
        if info.error:
            notes.insert(0, f'⚠ {info.error}')
        self.notes_label.configure(text='\n'.join(notes))

        if entry['thumb'] is not None:
            self._thumb_photo = ImageTk.PhotoImage(entry['thumb'])
            self.thumb_label.configure(image=self._thumb_photo)

        if info.source == 'none':
            self._set_text(self.pos_text, NO_META_TEXT)
        elif info.source == 'generic':
            raw = core.raw_text(info)
            if len(raw) > 20000:
                raw = raw[:20000] + '\n…（內容過長，完整內容請按「原始中繼資料」）'
            self._set_text(self.pos_text, '沒有辨識到 ComfyUI 或 WebUI 的生成參數，以下是原始中繼資料：\n\n' + raw)
        elif info.source == 'error':
            self._set_text(self.pos_text, f'無法讀取這個檔案：\n{info.error}')
        else:
            self._set_text(self.pos_text, info.positive)
            self._set_text(self.neg_text, info.negative)

        for index, lora in enumerate(info.loras):
            self.lora_tree.insert('', 'end', iid=str(index), values=(
                lora.name,
                core.format_number(lora.strength_model) if lora.strength_model is not None else '—',
                core.format_number(lora.strength_clip) if lora.strength_clip is not None else '—'))

        keys = [k for k in core.PARAM_ORDER if k in info.params] + \
               [k for k in info.params if k not in core.PARAM_ORDER]
        for key in keys:
            self.param_tree.insert('', 'end', values=(core.PARAM_LABELS.get(key, key),
                                                      core.format_number(info.params[key])))
        for key, value in info.extra.items():
            self.param_tree.insert('', 'end', values=(key, core.format_number(value)))

    # ──────────────────────────────────────────────
    # 複製
    # ──────────────────────────────────────────────

    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    def _copy(self, text: str, label: str) -> None:
        if not text:
            self.set_status(f'沒有可複製的{label}')
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.set_status(f'✓ 已複製{label}')

    def copy_field(self, field: str) -> None:
        info = self._current_info()
        if info is None:
            self.set_status('請先選擇一張已解析完成的圖片')
            return
        getters = {
            'positive': (lambda: info.positive, '正面提示詞'),
            'negative': (lambda: info.negative, '負面提示詞'),
            'loras': (lambda: core.loras_text(info), ' LoRA'),
            'params': (lambda: core.params_line(info), '生成參數'),
            'webui': (lambda: core.to_webui_text(info), ' WebUI 格式'),
            'report': (lambda: core.format_report(info), '完整報告'),
        }
        getter, label = getters[field]
        self._copy(getter(), label)

    def _copy_lora_row(self, event) -> None:
        info = self._current_info()
        row = self.lora_tree.identify_row(event.y)
        if info and row and row.isdigit() and int(row) < len(info.loras):
            lora = info.loras[int(row)]
            self._copy(lora.to_tag(), f' {lora.short_name}')

    def _copy_param_row(self, event) -> None:
        row = self.param_tree.identify_row(event.y)
        if row:
            key, value = self.param_tree.item(row, 'values')
            self._copy(str(value), f'「{key}」')

    # ──────────────────────────────────────────────
    # 其他功能
    # ──────────────────────────────────────────────

    def reveal_in_finder(self) -> None:
        info = self._current_info()
        if info is None:
            return
        try:
            if IS_MAC:
                subprocess.Popen(['open', '-R', info.path])
            elif sys.platform.startswith('win'):
                subprocess.Popen(['explorer', '/select,', info.path])
            else:
                subprocess.Popen(['xdg-open', os.path.dirname(info.path)])
        except Exception as exc:
            self.set_status(f'無法開啟資料夾：{exc}')

    def show_raw(self) -> None:
        info = self._current_info()
        if info is None:
            return
        win = tk.Toplevel(self.root)
        win.title(f'原始中繼資料 — {info.filename}')
        win.geometry('860x660')
        frame = ttk.Frame(win, padding=10)
        frame.pack(fill='both', expand=True)
        content = core.raw_text(info)

        bar = ttk.Frame(frame)
        bar.pack(fill='x', pady=(0, 8))
        ttk.Button(bar, text='複製全部', command=lambda: self._copy(content, '原始中繼資料')).pack(side='left')
        ttk.Button(bar, text='關閉', command=win.destroy).pack(side='right')

        box = ttk.Frame(frame)
        box.pack(fill='both', expand=True)
        text = tk.Text(box, wrap='word', font=self.mono_font, relief='flat',
                       highlightthickness=1, padx=8, pady=6)
        scroll = ttk.Scrollbar(box, orient='vertical', command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        text.pack(side='left', fill='both', expand=True)
        text.insert('1.0', content)
        text.configure(state='disabled')
        text.bind('<1>', lambda e: text.focus_set())
        win.bind('<Escape>', lambda e: win.destroy())
        win.bind(f'<{MOD}-w>', lambda e: win.destroy())

    def export_current_txt(self) -> None:
        info = self._current_info()
        if info is None:
            self.set_status('請先選擇一張已解析完成的圖片')
            return
        path = filedialog.asksaveasfilename(
            title='匯出目前圖片', parent=self.root,
            initialdir=os.path.dirname(info.path),
            initialfile=os.path.splitext(info.filename)[0] + '.txt',
            defaultextension='.txt', filetypes=[('文字檔', '*.txt')])
        if not path:
            return
        content = core.format_report(info)
        webui = core.to_webui_text(info)
        if webui:
            content += '\n\n' + '─' * 40 + '\nWebUI 格式：\n' + webui
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content + '\n')
            self.set_status(f'✓ 已匯出：{os.path.basename(path)}')
        except OSError as exc:
            messagebox.showerror('匯出失敗', str(exc), parent=self.root)

    def export_all(self, kind: str) -> None:
        infos = [self.entries[iid]['info'] for iid in self.tree.get_children()
                 if self.entries.get(iid, {}).get('info') is not None]
        if not infos:
            self.set_status('清單中沒有已解析完成的圖片')
            return
        ext = '.json' if kind == 'json' else '.csv'
        path = filedialog.asksaveasfilename(
            title=f'匯出全部為 {kind.upper()}', parent=self.root, initialdir=self.last_dir,
            initialfile=f'pnginfo{ext}', defaultextension=ext,
            filetypes=[(kind.upper(), f'*{ext}')])
        if not path:
            return
        try:
            if kind == 'json':
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump([core.to_dict(i) for i in infos], f, ensure_ascii=False, indent=2)
            else:
                # utf-8-sig 讓 Numbers / Excel 正確顯示中文
                with open(path, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=core.CSV_FIELDS)
                    writer.writeheader()
                    for info in infos:
                        writer.writerow(core.csv_row(info))
            self.set_status(f'✓ 已匯出 {len(infos)} 張：{os.path.basename(path)}')
        except OSError as exc:
            messagebox.showerror('匯出失敗', str(exc), parent=self.root)

    def show_about(self) -> None:
        dnd = (f'已啟用（tkinterdnd2 {_dnd_package_version()}）' if self.dnd_enabled
               else f'未啟用\n{self.dnd_error}')
        messagebox.showinfo(
            f'關於 {APP_NAME}',
            f'{APP_NAME} v{APP_VERSION}\n\n'
            '讀取 ComfyUI、Stable Diffusion WebUI / Forge 圖片中的生成參數。\n'
            '完全離線執行，不會上傳任何圖片。\n\n'
            f'拖放功能：{dnd}\n'
            f'Python {sys.version.split()[0]}　Tk {self.root.tk.call("info", "patchlevel")}',
            parent=self.root)

    def run(self) -> None:
        self.root.mainloop()


def run_check() -> int:
    """python png_info_parser.py --check：檢查拖放功能能不能用，不開主視窗"""
    print(f'Python      {platform.python_version()}（{platform.machine()}）')
    print(f'執行檔      {sys.executable}')
    print(f'tkinterdnd2 {_dnd_package_version() or "未安裝"}')
    root = tk.Tk()
    root.withdraw()
    print(f'Tk          {root.tk.call("info", "patchlevel")}')
    reason, fix_cmd = load_dnd(root)
    if not reason:
        # 實際註冊一個拖放目標，確認整條路是通的
        label = tk.Label(root)
        label.drop_target_register(DND_FILES)
        print(f'tkdnd       {root.tk.call("package", "present", "tkdnd")}')
        print('\n✓ 拖放功能正常')
    else:
        print(f'\n✗ 拖放功能無法使用\n{reason}')
        if fix_cmd:
            print(f'\n修正方式：\n  {fix_cmd}')
    root.destroy()
    return 0 if not reason else 1


def main() -> None:
    if '--check' in sys.argv[1:]:
        sys.exit(run_check())
    # 從 Finder 啟動時，macOS 舊版可能會傳入 -psn_ 參數，要過濾掉
    initial = [a for a in sys.argv[1:] if not a.startswith('-psn_') and os.path.exists(a)]
    PngInfoApp(initial).run()


if __name__ == '__main__':
    main()