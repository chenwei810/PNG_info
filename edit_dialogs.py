#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
edit_dialogs.py — 編輯視窗與批次取代視窗（tkinter）

實際的寫檔邏輯都在 pnginfo_editor.py，這裡只負責介面。
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING, Callable

import pnginfo_core as core
import pnginfo_editor as editor

if TYPE_CHECKING:
    from png_info_parser import PngInfoApp

IS_MAC = sys.platform == 'darwin'
MOD = 'Command' if IS_MAC else 'Control'

# ComfyUI 內建的採樣器與排程器名稱（下拉選單用，也可以直接輸入其他名稱）
COMFY_SAMPLERS = [
    'euler', 'euler_cfg_pp', 'euler_ancestral', 'euler_ancestral_cfg_pp', 'heun', 'heunpp2',
    'dpm_2', 'dpm_2_ancestral', 'lms', 'dpm_fast', 'dpm_adaptive', 'dpmpp_2s_ancestral',
    'dpmpp_2s_ancestral_cfg_pp', 'dpmpp_sde', 'dpmpp_sde_gpu', 'dpmpp_2m', 'dpmpp_2m_cfg_pp',
    'dpmpp_2m_sde', 'dpmpp_2m_sde_gpu', 'dpmpp_3m_sde', 'dpmpp_3m_sde_gpu', 'ddpm', 'lcm',
    'ipndm', 'ipndm_v', 'deis', 'res_multistep', 'res_multistep_cfg_pp', 'gradient_estimation',
    'er_sde', 'seeds_2', 'seeds_3', 'sa_solver', 'ddim', 'uni_pc', 'uni_pc_bh2',
]
COMFY_SCHEDULERS = ['simple', 'sgm_uniform', 'karras', 'exponential', 'ddim_uniform', 'beta',
                    'normal', 'linear_quadratic', 'kl_optimal']

CHANGED_COLOR = '#d35400'


def _setup_styles(root: tk.Misc) -> None:
    style = ttk.Style(root)
    style.configure('Changed.TLabel', foreground=CHANGED_COLOR)
    style.configure('Dot.TLabel', foreground=CHANGED_COLOR)
    style.configure('Hint.TLabel', foreground='gray')
    style.configure('Warn.TLabel', foreground=CHANGED_COLOR)


def _make_modal(win: tk.Toplevel, parent: tk.Misc) -> None:
    win.transient(parent)
    try:
        win.wait_visibility()
        win.grab_set()
    except tk.TclError:
        pass
    win.focus_set()


def _wheel_steps(event) -> int:
    if getattr(event, 'num', None) == 4:
        return -1
    if getattr(event, 'num', None) == 5:
        return 1
    delta = event.delta
    if abs(delta) >= 120:          # Windows 與部分 Tk 9：一格是 120
        return -int(delta / 120)
    return -1 if delta > 0 else 1 if delta < 0 else 0   # macOS Tk 8.6：一格是 ±1


class _ScrollFrame(ttk.Frame):
    """可以垂直捲動的區域，內容放在 self.body"""

    def __init__(self, parent: tk.Misc):
        super().__init__(parent)
        bg = ttk.Style(self).lookup('TFrame', 'background') or None
        self.canvas = tk.Canvas(self, highlightthickness=0, borderwidth=0)
        if bg:
            try:
                self.canvas.configure(background=bg)
            except tk.TclError:
                pass
        scroll = ttk.Scrollbar(self, orient='vertical', command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.canvas.pack(side='left', fill='both', expand=True)
        self.body = ttk.Frame(self.canvas, padding=(14, 12))
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor='nw')
        self.body.bind('<Configure>', lambda e: self.canvas.configure(scrollregion=self.canvas.bbox('all')))
        self.canvas.bind('<Configure>', lambda e: self.canvas.itemconfigure(self._window, width=e.width))

    def scroll(self, steps: int) -> None:
        if self.body.winfo_height() > self.canvas.winfo_height():
            self.canvas.yview_scroll(steps, 'units')


# ──────────────────────────────────────────────────────────────
# 編輯視窗
# ──────────────────────────────────────────────────────────────

class EditDialog:
    def __init__(self, app: 'PngInfoApp', session: editor.EditSession,
                 on_saved: Callable[[editor.SaveResult], None]):
        self.app = app
        self.session = session
        self.on_saved = on_saved
        self.rows: dict[str, dict] = {}       # fid → {'get', 'set', 'label', 'revert', 'dot'}
        self._lora_rows: dict[int, dict] = {}

        root = app.root
        _setup_styles(root)
        self.win = win = tk.Toplevel(root)
        win.title(f'編輯 — {session.info.filename}')
        win.geometry('940x760')
        win.minsize(720, 560)
        win.protocol('WM_DELETE_WINDOW', self.cancel)

        self._build_header()
        self._build_footer()
        self.notebook = ttk.Notebook(win)
        self.notebook.pack(fill='both', expand=True, padx=12, pady=(4, 0))
        self.tabs: list[_ScrollFrame] = []
        self._build_prompt_tab()
        self._build_lora_tab()
        self._build_params_tab()

        win.bind(f'<{MOD}-s>', lambda e: self.save())
        win.bind('<Escape>', lambda e: self.cancel())
        win.bind('<MouseWheel>', self._on_wheel)
        win.bind('<Button-4>', self._on_wheel)
        win.bind('<Button-5>', self._on_wheel)
        self._refresh_status()
        _make_modal(win, root)

    # ── 版面 ──

    def _build_header(self) -> None:
        head = ttk.Frame(self.win, padding=(14, 12, 14, 4))
        head.pack(fill='x')
        info = self.session.info
        ttk.Label(head, text=info.filename, font=self.app.title_font).pack(anchor='w')
        ttk.Label(head, text=f'來源：{info.source_label}　·　修改後會另存成新檔，原圖不會被變更',
                  style='Hint.TLabel').pack(anchor='w', pady=(2, 0))
        for note in self.session.notes:
            ttk.Label(head, text=f'⚠ {note}', style='Warn.TLabel', wraplength=880,
                      justify='left').pack(anchor='w', pady=(4, 0))

    def _build_footer(self) -> None:
        foot = ttk.Frame(self.win, padding=(14, 10))
        foot.pack(side='bottom', fill='x')
        self.status = ttk.Label(foot, text='')
        self.status.pack(side='left')
        self.save_btn = ttk.Button(foot, text='另存新檔…', default='active', command=self.save)
        self.save_btn.pack(side='right')
        ttk.Button(foot, text='取消', command=self.cancel).pack(side='right', padx=6)
        self.revert_all_btn = ttk.Button(foot, text='全部還原', command=self.revert_all)
        self.revert_all_btn.pack(side='right')

    def _add_tab(self, title: str) -> ttk.Frame:
        frame = _ScrollFrame(self.notebook)
        self.notebook.add(frame, text=title)
        self.tabs.append(frame)
        return frame.body

    def _build_prompt_tab(self) -> None:
        body = self._add_tab('提示詞')
        if self.session.kind == 'comfyui':
            ttk.Label(body, text='每個文字框對應工作流中的一個節點；存檔時會同時更新 API prompt 與 workflow，'
                                 '拖回 ComfyUI 也會看到新內容。', style='Hint.TLabel',
                      wraplength=840, justify='left').pack(anchor='w', pady=(0, 8))
        for group, title, height in (('positive', '正面提示詞', 8), ('negative', '負面提示詞', 5)):
            ttk.Label(body, text=title, font=self.app.section_font).pack(anchor='w', pady=(10, 4))
            fields = self.session.group(group)
            if not fields:
                ttk.Label(body, text='這個工作流沒有負面提示詞（例如 Flux 不使用負面提示詞）。'
                          if group == 'negative' else '找不到正面提示詞。', style='Hint.TLabel').pack(anchor='w')
            for f in fields:
                self._text_field(body, f, height if len(fields) == 1 else max(4, height - 3))

    def _text_field(self, parent: ttk.Frame, f: editor.EditField, height: int) -> None:
        row = ttk.Frame(parent)
        row.pack(fill='x', pady=(2, 2))
        label = ttk.Label(row, text=f.detail or ' ')
        label.pack(side='left')
        revert = ttk.Button(row, text='↺ 還原', width=7, command=lambda: self.revert(f.fid))
        revert.pack(side='right')

        box = ttk.Frame(parent)
        box.pack(fill='x', pady=(0, 6))
        text = tk.Text(box, height=height, wrap='word', undo=True, font=self.app.text_font,
                       relief='flat', highlightthickness=1, padx=8, pady=6)
        scroll = ttk.Scrollbar(box, orient='vertical', command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        text.pack(side='left', fill='x', expand=True)
        text.insert('1.0', f.original)
        text.edit_reset()
        text.edit_modified(False)

        def on_modified(_event=None):
            if text.edit_modified():
                text.edit_modified(False)
                self._on_change(f.fid)
        text.bind('<<Modified>>', on_modified)

        def set_value(value: str) -> None:
            text.delete('1.0', 'end')
            text.insert('1.0', value)
            self._on_change(f.fid)

        self.rows[f.fid] = {'get': lambda: text.get('1.0', 'end-1c'), 'set': set_value,
                            'label': label, 'revert': revert, 'base': f.detail or ' ', 'widget': text}

    def _entry(self, parent: ttk.Frame, f: editor.EditField, width: int) -> tk.Widget:
        var = tk.StringVar(value=f.original)
        values = None
        if self.session.kind == 'comfyui' and f.fid == 'param:Sampler':
            values = COMFY_SAMPLERS
        elif self.session.kind == 'comfyui' and f.fid == 'param:Schedule type':
            values = COMFY_SCHEDULERS
        widget = (ttk.Combobox(parent, textvariable=var, values=values, width=width) if values
                  else ttk.Entry(parent, textvariable=var, width=width))
        var.trace_add('write', lambda *_: self._on_change(f.fid))
        self.rows[f.fid] = {'get': var.get, 'set': var.set, 'widget': widget}
        return widget

    def _build_lora_tab(self) -> None:
        body = self._add_tab('LoRA')
        fields = self.session.group('lora')
        if not fields:
            ttk.Label(body, text='這張圖片沒有可以編輯的 LoRA。', style='Hint.TLabel').pack(anchor='w')
            return
        hint = ('名稱要跟 ComfyUI 的 loras 資料夾裡的檔名一致（包含子資料夾與副檔名）。'
                if self.session.kind == 'comfyui' else
                '修改會套用到正面提示詞裡的 <lora:名稱:權重> 標籤。權重留空代表不寫權重。')
        ttk.Label(body, text=hint, style='Hint.TLabel', wraplength=840, justify='left').pack(anchor='w', pady=(0, 10))

        grid = ttk.Frame(body)
        grid.pack(fill='x')
        grid.columnconfigure(1, weight=1)
        for col, text in enumerate(('', '名稱', 'Model 權重', 'CLIP 權重', '')):
            ttk.Label(grid, text=text, font=self.app.section_font).grid(row=0, column=col, sticky='w', padx=4, pady=(0, 6))

        by_index: dict[int, dict[str, editor.EditField]] = {}
        for f in fields:
            by_index.setdefault(f.lora_index, {})[f.lora_part] = f
        for row, (index, parts) in enumerate(by_index.items(), start=1):
            dot = ttk.Label(grid, text='', style='Dot.TLabel', width=2)
            dot.grid(row=row, column=0, sticky='w')
            for col, part, width in ((1, 'name', 40), (2, 'model', 9), (3, 'clip', 9)):
                f = parts.get(part)
                if f is None:
                    ttk.Label(grid, text='—', style='Hint.TLabel').grid(row=row, column=col, padx=4, pady=3)
                    continue
                widget = self._entry(grid, f, width)
                widget.grid(row=row, column=col, sticky='ew' if part == 'name' else 'w', padx=4, pady=3)
                self.rows[f.fid]['dot'] = dot
            fids = [f.fid for f in parts.values()]
            revert = ttk.Button(grid, text='↺', width=3, command=lambda ids=fids: [self.revert(i) for i in ids])
            revert.grid(row=row, column=4, padx=4)
            for fid in fids:
                self.rows[fid]['revert'] = revert
            self._lora_rows[index] = {'dot': dot, 'fids': fids}

    def _build_params_tab(self) -> None:
        body = self._add_tab('生成參數')
        fields = self.session.group('params')
        if not fields:
            ttk.Label(body, text='這張圖片沒有可以編輯的生成參數。', style='Hint.TLabel').pack(anchor='w')
            return
        if self.session.kind == 'webui':
            ttk.Label(body, text='把欄位清空就會從參數中移除該項目。', style='Hint.TLabel').pack(anchor='w', pady=(0, 10))
        grid = ttk.Frame(body)
        grid.pack(fill='x')
        grid.columnconfigure(2, weight=1)
        for row, f in enumerate(fields):
            dot = ttk.Label(grid, text='', style='Dot.TLabel', width=2)
            dot.grid(row=row, column=0, sticky='w')
            label = ttk.Label(grid, text=f.label)
            label.grid(row=row, column=1, sticky='w', padx=(0, 10), pady=3)
            widget = self._entry(grid, f, 42)
            widget.grid(row=row, column=2, sticky='ew', pady=3)
            revert = ttk.Button(grid, text='↺', width=3, command=lambda fid=f.fid: self.revert(fid))
            revert.grid(row=row, column=3, padx=6)
            ttk.Label(grid, text=f.detail, style='Hint.TLabel').grid(row=row, column=4, sticky='w')
            self.rows[f.fid].update({'dot': dot, 'label': label, 'revert': revert, 'base': f.label})

    # ── 狀態 ──

    def values(self) -> dict[str, str]:
        return {fid: row['get']() for fid, row in self.rows.items()}

    def changes(self) -> dict[str, str]:
        return self.session.changed(self.values())

    def _is_changed(self, fid: str) -> bool:
        return self.session.field(fid).differs(self.rows[fid]['get']())

    def _on_change(self, fid: str) -> None:
        """欄位內容變了：更新它的標示，再更新整體狀態"""
        row = self.rows.get(fid)
        if row is None:
            return
        f = self.session.field(fid)
        changed = self._is_changed(fid)
        if 'label' in row:
            # 有獨立圓點欄的列（生成參數）只改顏色；提示詞的標題則在前面加上圓點
            prefix = '● ' if changed and 'dot' not in row else ''
            row['label'].configure(text=prefix + row['base'], style='Changed.TLabel' if changed else 'TLabel')
        if f.group == 'lora' and f.lora_index in self._lora_rows:
            lora_row = self._lora_rows[f.lora_index]
            lora_row['dot'].configure(text='●' if any(self._is_changed(i) for i in lora_row['fids']) else '')
        elif 'dot' in row:
            row['dot'].configure(text='●' if changed else '')
        self._refresh_status()

    def _refresh_status(self) -> None:
        for fid, row in self.rows.items():
            if 'revert' not in row:
                continue
            f = self.session.field(fid)
            if f.group == 'lora' and f.lora_index in self._lora_rows:
                changed = any(self._is_changed(i) for i in self._lora_rows[f.lora_index]['fids'])
            else:
                changed = self._is_changed(fid)
            row['revert'].configure(state='normal' if changed else 'disabled')
        count = len(self.changes())
        self.status.configure(text=f'已修改 {count} 個欄位' if count else '尚未修改',
                              style='Changed.TLabel' if count else 'Hint.TLabel')
        self.save_btn.configure(state='normal' if count else 'disabled')
        self.revert_all_btn.configure(state='normal' if count else 'disabled')

    def revert(self, fid: str) -> None:
        self.rows[fid]['set'](self.session.field(fid).original)
        self._on_change(fid)

    def revert_all(self) -> None:
        for fid in list(self.changes()):
            self.revert(fid)

    def _on_wheel(self, event) -> None:
        if isinstance(event.widget, (tk.Text, ttk.Combobox)):
            return   # 文字框自己會捲動
        try:
            tab = self.tabs[self.notebook.index('current')]
        except (tk.TclError, IndexError):
            return
        tab.scroll(_wheel_steps(event))

    # ── 動作 ──

    def cancel(self) -> None:
        if self.changes() and not messagebox.askyesno('放棄修改', '有尚未儲存的修改，確定要放棄嗎？', parent=self.win):
            return
        self.close()

    def close(self) -> None:
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()

    def save(self, dst: str | None = None) -> editor.SaveResult | None:
        changes = self.changes()
        if not changes:
            return None
        errors = editor.check_changes(self.session, changes)
        if errors:
            messagebox.showerror('有欄位的格式不正確', '\n'.join(errors), parent=self.win)
            first = next(fid for fid in changes if any(e.startswith(self.session.field(fid).label) for e in errors))
            self._focus_field(first)
            return None
        if dst is None:
            suggestion = editor.unique_path(self.session.path)
            dst = filedialog.asksaveasfilename(
                parent=self.win, title='另存新檔', initialdir=os.path.dirname(suggestion),
                initialfile=os.path.basename(suggestion), defaultextension='.png',
                filetypes=[('PNG 圖片', '*.png')])
            if not dst:
                return None
            if not dst.lower().endswith('.png'):
                dst += '.png'
        try:
            result = editor.save_as(self.session, changes, dst, self.app.version)
        except editor.EditError as exc:
            messagebox.showerror('無法存檔', str(exc), parent=self.win)
            return None
        except OSError as exc:
            messagebox.showerror('無法存檔', f'寫入檔案時發生錯誤：{exc}', parent=self.win)
            return None
        self.close()
        self.on_saved(result)
        return result

    def _focus_field(self, fid: str) -> None:
        f = self.session.field(fid)
        tab = {'positive': 0, 'negative': 0, 'lora': 1, 'params': 2}[f.group]
        self.notebook.select(tab)
        widget = self.rows[fid].get('widget')
        if widget is not None:
            widget.focus_set()


# ──────────────────────────────────────────────────────────────
# 批次取代視窗
# ──────────────────────────────────────────────────────────────

class BatchReplaceDialog:
    def __init__(self, app: 'PngInfoApp', selected: list[str], all_items: list[str]):
        self.app = app
        self.selected = selected
        self.all_items = all_items
        self.plans: list[dict] = []

        _setup_styles(app.root)
        self.win = win = tk.Toplevel(app.root)
        win.title('批次取代提示詞')
        win.geometry('820x620')
        win.minsize(640, 480)
        win.protocol('WM_DELETE_WINDOW', self.close)

        form = ttk.Frame(win, padding=(14, 14, 14, 6))
        form.pack(fill='x')
        form.columnconfigure(1, weight=1)
        self.find_var = tk.StringVar()
        self.repl_var = tk.StringVar()
        ttk.Label(form, text='尋找').grid(row=0, column=0, sticky='w', padx=(0, 8), pady=3)
        find_entry = ttk.Entry(form, textvariable=self.find_var)
        find_entry.grid(row=0, column=1, sticky='ew', pady=3)
        ttk.Label(form, text='取代為').grid(row=1, column=0, sticky='w', padx=(0, 8), pady=3)
        ttk.Entry(form, textvariable=self.repl_var).grid(row=1, column=1, sticky='ew', pady=3)

        opts = ttk.Frame(win, padding=(14, 0))
        opts.pack(fill='x')
        self.pos_var = tk.BooleanVar(value=True)
        self.neg_var = tk.BooleanVar(value=True)
        self.case_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text='正面提示詞', variable=self.pos_var).pack(side='left')
        ttk.Checkbutton(opts, text='負面提示詞', variable=self.neg_var).pack(side='left', padx=10)
        ttk.Checkbutton(opts, text='區分大小寫', variable=self.case_var).pack(side='left')

        scope = ttk.Frame(win, padding=(14, 6))
        scope.pack(fill='x')
        self.scope_var = tk.StringVar(value='selected' if len(selected) > 1 else 'all')
        ttk.Label(scope, text='範圍：').pack(side='left')
        ttk.Radiobutton(scope, text=f'選取的圖片（{len(selected)} 張）', value='selected',
                        variable=self.scope_var, state='normal' if selected else 'disabled').pack(side='left')
        ttk.Radiobutton(scope, text=f'清單中全部（{len(all_items)} 張）', value='all',
                        variable=self.scope_var).pack(side='left', padx=10)
        ttk.Button(scope, text='預覽', command=self.preview).pack(side='right')

        ttk.Label(win, text='新檔會存在原圖旁邊（檔名加上 _edited），原圖不會被修改。目前只處理 PNG。\n'
                            '<lora:…> 標籤不會被取代；要改 LoRA 請用編輯視窗。',
                  style='Hint.TLabel', padding=(14, 0), justify='left').pack(anchor='w')

        box = ttk.Frame(win, padding=(14, 6))
        box.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(box, columns=('name', 'count', 'result'), show='headings')
        for cid, text, width, stretch in (('name', '檔名', 220, False), ('count', '符合', 60, False),
                                          ('result', '結果', 400, True)):
            self.tree.heading(cid, text=text)
            self.tree.column(cid, width=width, stretch=stretch, anchor='center' if cid == 'count' else 'w')
        scroll = ttk.Scrollbar(box, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(side='left', fill='both', expand=True)

        foot = ttk.Frame(win, padding=(14, 10))
        foot.pack(side='bottom', fill='x')
        self.status = ttk.Label(foot, text='輸入要尋找的文字後按「預覽」。', style='Hint.TLabel')
        self.status.pack(side='left')
        self.run_btn = ttk.Button(foot, text='執行取代', default='active', command=self.run, state='disabled')
        self.run_btn.pack(side='right')
        ttk.Button(foot, text='關閉', command=self.close).pack(side='right', padx=6)

        for var in (self.find_var, self.repl_var, self.pos_var, self.neg_var, self.case_var, self.scope_var):
            var.trace_add('write', lambda *_: self._invalidate())
        win.bind('<Return>', lambda e: self.preview())
        win.bind('<Escape>', lambda e: self.close())
        _make_modal(win, app.root)
        find_entry.focus_set()

    def _invalidate(self) -> None:
        if self.plans:
            self.plans = []
            self.run_btn.configure(state='disabled')
            self.status.configure(text='條件已變更，請重新預覽。', style='Hint.TLabel')

    def _targets(self) -> list[str]:
        return self.selected if self.scope_var.get() == 'selected' else self.all_items

    def preview(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.plans = []
        find = self.find_var.get()
        groups = tuple(g for g, v in (('positive', self.pos_var), ('negative', self.neg_var)) if v.get())
        if not find:
            self.status.configure(text='請輸入要尋找的文字。', style='Warn.TLabel')
            return
        if not groups:
            self.status.configure(text='請至少勾選正面或負面提示詞。', style='Warn.TLabel')
            return
        files = matches = 0
        for iid in self._targets():
            entry = self.app.entries.get(iid)
            if entry is None:
                continue
            name = os.path.basename(entry['path'])
            info = entry['info']
            plan = {'iid': iid, 'name': name, 'session': None, 'changes': {}, 'count': 0}
            if info is None:
                result = '略過：仍在解析中'
            else:
                try:
                    session = editor.build_session(info)
                    changes, count = editor.batch_replace(session, find, self.repl_var.get(), groups,
                                                          self.case_var.get())
                    plan.update(session=session, changes=changes, count=count)
                    result = f'將另存為 {os.path.basename(editor.unique_path(info.path))}' if count else '沒有符合'
                    if count:
                        files += 1
                        matches += count
                except editor.EditError as exc:
                    result = '略過：' + str(exc).splitlines()[0]
            plan['row'] = self.tree.insert('', 'end', values=(name, plan['count'] or '', result))
            self.plans.append(plan)
        if files:
            self.status.configure(text=f'{files} 張圖片共 {matches} 處符合。', style='TLabel')
            self.run_btn.configure(state='normal')
        else:
            self.status.configure(text='沒有找到符合的文字。', style='Hint.TLabel')
            self.run_btn.configure(state='disabled')

    def run(self) -> list[str]:
        todo = [p for p in self.plans if p['count']]
        if not todo:
            return []
        self.run_btn.configure(state='disabled')
        saved, failed = [], 0
        for plan in todo:
            dst = editor.unique_path(plan['session'].path)
            try:
                editor.save_as(plan['session'], plan['changes'], dst, self.app.version)
                saved.append(dst)
                self.tree.set(plan['row'], 'result', f'✓ 已另存為 {os.path.basename(dst)}')
            except (editor.EditError, OSError) as exc:
                failed += 1
                self.tree.set(plan['row'], 'result', '✗ ' + str(exc).splitlines()[0])
            self.win.update_idletasks()
        self.plans = []
        text = f'完成：另存 {len(saved)} 張' + (f'，{failed} 張失敗' if failed else '')
        self.status.configure(text=text, style='Warn.TLabel' if failed else 'TLabel')
        if saved:
            self.app.add_paths(saved)
            self.app.set_status(f'✓ 批次取代：{text}')
        return saved

    def close(self) -> None:
        try:
            self.win.grab_release()
        except tk.TclError:
            pass
        self.win.destroy()
