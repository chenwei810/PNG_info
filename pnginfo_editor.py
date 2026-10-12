#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pnginfo_editor.py — 改寫 PNG 圖片裡的生成參數（只另存新檔，不覆蓋原圖）

做法：
  • 只替換 PNG 的文字區塊（tEXt / zTXt / iTXt），影像資料與其他區塊逐位元組原樣複製，
    所以畫面一個像素都不會變。
  • ComfyUI：依照 pnginfo_core 追蹤到的節點位置，同時修改 API prompt 與 workflow，
    拖回 ComfyUI 時看到的也是新值。
  • WebUI / Forge：重組 parameters 文字，格式與 A1111 相同。
  • 存檔前先寫到暫存檔並驗證（影像資料相同、重新解析能讀到新值），通過才改名成目標檔案。
"""

from __future__ import annotations

import copy
import datetime
import json
import os
import re
import stat
import struct
import tempfile
import zlib
from dataclasses import dataclass, field
from typing import Any

from PIL import Image

import pnginfo_core as core

PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
TEXT_CHUNKS = {b'tEXt', b'zTXt', b'iTXt'}

# 移除中繼資料時保留的區塊：影像本身、色彩與顯示相關、APNG 動畫
KEEP_WHEN_STRIPPING = {
    b'IHDR', b'PLTE', b'IDAT', b'IEND', b'tRNS', b'gAMA', b'cHRM', b'sRGB', b'iCCP',
    b'sBIT', b'pHYs', b'bKGD', b'cICP', b'mDCV', b'cLLI', b'acTL', b'fcTL', b'fdAT',
}

# 參數欄位的顯示順序與型別
COMFY_PARAM_ORDER = ['Steps', 'Sampler', 'Schedule type', 'CFG scale', 'Guidance', 'Seed', 'Size',
                     'Batch size', 'Denoising strength', 'Model', 'VAE', 'Clip skip']
INT_PARAMS = {'Steps', 'Seed', 'Batch size', 'Clip skip'}
FLOAT_PARAMS = {'CFG scale', 'Guidance', 'Denoising strength'}

LORA_PART_LABELS = {'name': '名稱', 'model': 'Model 權重', 'clip': 'CLIP 權重'}


class EditError(Exception):
    """編輯或存檔失敗，訊息可以直接顯示給使用者"""


# ──────────────────────────────────────────────────────────────
# PNG 區塊讀寫
# ──────────────────────────────────────────────────────────────

def is_png(path: str) -> bool:
    try:
        with open(path, 'rb') as f:
            return f.read(8) == PNG_SIGNATURE
    except OSError:
        return False


def read_chunks(path: str) -> list[tuple[bytes, bytes]]:
    """讀出所有區塊 [(類型, 內容)]，同時檢查結構與校驗碼"""
    with open(path, 'rb') as f:
        data = f.read()
    if not data.startswith(PNG_SIGNATURE):
        raise EditError('這不是 PNG 檔案。')
    pos, chunks = 8, []
    while pos < len(data):
        if pos + 12 > len(data):
            raise EditError('PNG 檔案不完整。')
        length, = struct.unpack('>I', data[pos:pos + 4])
        ctype = data[pos + 4:pos + 8]
        end = pos + 12 + length
        if end > len(data):
            raise EditError('PNG 檔案不完整。')
        body = data[pos + 8:pos + 8 + length]
        crc, = struct.unpack('>I', data[end - 4:end])
        if zlib.crc32(ctype + body) & 0xFFFFFFFF != crc:
            raise EditError(f'PNG 區塊 {ctype.decode("latin-1")} 的校驗碼錯誤，檔案可能已損毀。')
        chunks.append((ctype, body))
        pos = end
        if ctype == b'IEND':
            break
    if not chunks or chunks[0][0] != b'IHDR' or chunks[-1][0] != b'IEND':
        raise EditError('PNG 檔案結構不正確。')
    return chunks


def _chunk_bytes(ctype: bytes, body: bytes) -> bytes:
    return struct.pack('>I', len(body)) + ctype + body + struct.pack('>I', zlib.crc32(ctype + body) & 0xFFFFFFFF)


def _text_keyword(body: bytes) -> str:
    return body.split(b'\0', 1)[0].decode('latin-1')


def _make_text_chunk(key: str, text: str, like: tuple[bytes, bytes] | None = None) -> tuple[bytes, bytes]:
    """產生文字區塊；盡量沿用原本區塊的類型與壓縮方式。
    tEXt / zTXt 只能存 Latin-1，含中文等字元時改用 iTXt（UTF-8），跟 Pillow 的做法相同。"""
    kb = key.encode('latin-1')
    like_type, like_body = like if like else (None, b'')

    def itxt(compress: bool) -> tuple[bytes, bytes]:
        payload = text.encode('utf-8')
        if compress:
            payload = zlib.compress(payload)
        # 關鍵字\0 壓縮旗標 壓縮方法 語言\0 翻譯關鍵字\0 內容
        return b'iTXt', kb + b'\0' + bytes([1 if compress else 0, 0]) + b'\0\0' + payload

    if like_type == b'iTXt':
        flag_pos = len(kb) + 1
        return itxt(len(like_body) > flag_pos and like_body[flag_pos] == 1)
    try:
        latin = text.encode('latin-1')
    except UnicodeEncodeError:
        return itxt(like_type == b'zTXt')
    if like_type == b'zTXt':
        return b'zTXt', kb + b'\0\0' + zlib.compress(latin)
    return b'tEXt', kb + b'\0' + latin


def _rebuild_chunks(chunks: list[tuple[bytes, bytes]], replace: dict[str, str | None],
                    strip: bool = False) -> list[tuple[bytes, bytes]]:
    """replace：{關鍵字: 新內容}，內容為 None 代表刪除；原本沒有的關鍵字會插在第一個 IDAT 之前"""
    out: list[tuple[bytes, bytes]] = []
    done: set[str] = set()
    inserted = False
    for ctype, body in chunks:
        if ctype == b'IDAT' and not inserted:
            for key, value in replace.items():
                if value is not None and key not in done:
                    out.append(_make_text_chunk(key, value))
                    done.add(key)
            inserted = True
        if strip:
            if ctype in KEEP_WHEN_STRIPPING:
                out.append((ctype, body))
            continue
        if ctype in TEXT_CHUNKS:
            key = _text_keyword(body)
            if key in replace:
                if key not in done and replace[key] is not None:
                    out.append(_make_text_chunk(key, replace[key], (ctype, body)))
                    done.add(key)
                continue
        out.append((ctype, body))
    return out


def _write_temp(dst: str, chunks: list[tuple[bytes, bytes]], mode_from: str) -> str:
    """寫到目標資料夾裡的暫存檔，回傳暫存檔路徑（驗證通過後才改名）"""
    folder = os.path.dirname(os.path.abspath(dst))
    fd, tmp = tempfile.mkstemp(prefix='.pnginfo-', suffix='.png', dir=folder)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(PNG_SIGNATURE)
            for ctype, body in chunks:
                f.write(_chunk_bytes(ctype, body))
            f.flush()
            os.fsync(f.fileno())
        try:
            os.chmod(tmp, stat.S_IMODE(os.stat(mode_from).st_mode))  # 權限跟原圖一樣
        except OSError:
            pass
        return tmp
    except BaseException:
        _remove_quietly(tmp)
        raise


def _remove_quietly(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def _check_destination(src: str, dst: str) -> None:
    if not dst.lower().endswith('.png'):
        raise EditError('另存的檔名必須是 .png。')
    if os.path.abspath(dst) == os.path.abspath(src) or (os.path.exists(dst) and os.path.samefile(src, dst)):
        raise EditError('不能覆蓋原始圖片，請換一個檔名另存。')
    if not os.path.isdir(os.path.dirname(os.path.abspath(dst))):
        raise EditError('目標資料夾不存在。')


def _verify_image_data(src: str, tmp: str, strip: bool) -> None:
    """影像資料（以及其他非文字區塊）必須跟原圖逐位元組相同"""
    before = [c for c in read_chunks(src) if c[0] not in TEXT_CHUNKS]
    if strip:
        before = [c for c in before if c[0] in KEEP_WHEN_STRIPPING]
    after = [c for c in read_chunks(tmp) if c[0] not in TEXT_CHUNKS]
    if before != after:
        raise EditError('驗證失敗：新檔案的影像資料與原圖不一致，已取消存檔。')
    with Image.open(tmp) as img:
        img.verify()


def unique_path(src: str, suffix: str = '_edited') -> str:
    """在原圖旁邊找一個不會撞名的檔名：圖_edited.png、圖_edited-2.png…"""
    folder, name = os.path.split(os.path.abspath(src))
    stem = re.sub(r'(_edited|_clean)(-\d+)?$', '', os.path.splitext(name)[0])
    candidate = os.path.join(folder, f'{stem}{suffix}.png')
    n = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f'{stem}{suffix}-{n}.png')
        n += 1
    return candidate


# ──────────────────────────────────────────────────────────────
# 可編輯欄位
# ──────────────────────────────────────────────────────────────

@dataclass
class EditField:
    fid: str                 # 穩定的欄位代號，例如 'text:9:text'、'param:Steps'、'lora:0:model'
    group: str               # 'positive' | 'negative' | 'lora' | 'params'
    label: str               # 顯示名稱
    original: str            # 原始值（字串形式，用來顯示與比較）
    kind: str = 'str'        # 'text' | 'str' | 'int' | 'float' | 'size' | 'clipskip'
    detail: str = ''         # 補充說明，例如「節點 9 · CLIPTextEncode · text」
    refs: tuple = ()         # ComfyUI：值在 API prompt 中的位置
    optional: bool = False   # 可以留空（WebUI 參數留空 = 刪除這個參數）
    lora_index: int = -1
    lora_part: str = ''

    def differs(self, text: str) -> bool:
        if self.kind == 'text':
            return text != self.original
        return text.strip() != self.original.strip()


@dataclass
class EditSession:
    path: str
    info: core.GenInfo
    kind: str                                    # 'comfyui' | 'webui'
    fields: list[EditField] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def field(self, fid: str) -> EditField:
        for f in self.fields:
            if f.fid == fid:
                return f
        raise KeyError(fid)

    def find(self, fid: str) -> EditField | None:
        return next((f for f in self.fields if f.fid == fid), None)

    def group(self, name: str) -> list[EditField]:
        return [f for f in self.fields if f.group == name]

    def changed(self, values: dict[str, str]) -> dict[str, str]:
        """只留下真的有改的欄位"""
        return {fid: text for fid, text in values.items() if (f := self.find(fid)) and f.differs(text)}


@dataclass
class SaveResult:
    path: str
    changed_labels: list[str]
    warnings: list[str]


def _fmt(value: Any) -> str:
    return '' if value is None else core.format_number(value)


def _api_get(api: dict, ref) -> Any:
    nid, key, sub = ref
    value = api[nid]['inputs'][key]
    return value.get(sub) if sub is not None and isinstance(value, dict) else value


def _api_set(api: dict, ref, new: Any) -> None:
    nid, key, sub = ref
    if sub is not None:
        api[nid]['inputs'][key][sub] = new
    else:
        api[nid]['inputs'][key] = new


def build_session(info: core.GenInfo) -> EditSession:
    """依照解析結果列出所有可編輯的欄位；不能編輯時丟出 EditError 並說明原因"""
    if not is_png(info.path):
        raise EditError('目前只支援編輯 PNG 圖片。')
    kind = info.sources.get('kind')
    if kind == 'comfyui':
        return _comfy_session(info)
    if kind == 'webui':
        return _webui_session(info)
    if info.source == 'comfyui':
        raise EditError('這張 ComfyUI 圖片只有 workflow、沒有 API prompt，無法安全地編輯。')
    raise EditError('這張圖片沒有可編輯的生成參數（不是 ComfyUI 或 WebUI / Forge 產生的）。')


def _comfy_session(info: core.GenInfo) -> EditSession:
    api = json.loads(info.raw['prompt'])
    session = EditSession(info.path, info, 'comfyui')

    def detail(ref) -> str:
        nid, key, sub = ref
        return f'節點 {nid} · {api[nid].get("class_type", "")} · {key}' + (f'.{sub}' if sub else '')

    # 提示詞：每個來源節點各自一個欄位，存檔時才能準確寫回去
    seen: set[str] = set()
    for role, label in (('positive', '正面提示詞'), ('negative', '負面提示詞')):
        for ref in info.sources.get(role, []):
            fid = f'text:{ref[0]}:{ref[1]}'
            if fid in seen:
                continue
            seen.add(fid)
            session.fields.append(EditField(fid, role, label, str(_api_get(api, ref)), 'text',
                                            detail(ref), (ref,)))

    # LoRA
    for i, lora in enumerate(info.loras):
        if lora.origin != 'node':
            continue
        for part in ('name', 'model', 'clip'):
            ref = lora.refs.get(part)
            if not ref:
                continue
            session.fields.append(EditField(
                f'lora:{i}:{part}', 'lora', f'LoRA「{lora.short_name}」的{LORA_PART_LABELS[part]}',
                _fmt(_api_get(api, ref)), 'str' if part == 'name' else 'float', detail(ref), (ref,),
                lora_index=i, lora_part=part))

    # 生成參數
    param_refs = info.sources.get('params', {})
    for key in COMFY_PARAM_ORDER:
        ref = param_refs.get(key)
        if not ref:
            continue
        label = core.PARAM_LABELS.get(key, key)
        if key == 'Size':
            rw, rh = ref
            if not (rw and rh):
                continue
            original = f'{_fmt(_api_get(api, rw))}x{_fmt(_api_get(api, rh))}'
            session.fields.append(EditField('param:Size', 'params', label, original, 'size',
                                            f'{detail(rw)} / {rh[1]}', (rw, rh)))
            continue
        value = _api_get(api, ref)
        if key == 'Clip skip':
            number = core._to_float(value)
            if number is None:
                continue
            original, kind = str(abs(int(number))), 'clipskip'
        else:
            original = _fmt(value)
            kind = 'int' if key in INT_PARAMS else 'float' if key in FLOAT_PARAMS else 'str'
        session.fields.append(EditField(f'param:{key}', 'params', label, original, kind, detail(ref), (ref,)))

    count = info.sources.get('sampler_count', 0)
    sampler = info.sources.get('sampler')
    if count > 1 and sampler:
        session.notes.append(f'工作流中有 {count} 個採樣器，生成參數只會修改第一階段（節點 {sampler[0]}）；'
                             '提示詞與 LoRA 通常是各階段共用的。')
    if not core._try_json(info.raw.get('workflow')):
        session.notes.append('這張圖沒有 workflow 資料，只會改寫 API prompt。')
    if not session.fields:
        raise EditError('在這張 ComfyUI 圖片中找不到可以編輯的欄位。')
    return session


def _webui_session(info: core.GenInfo) -> EditSession:
    session = EditSession(info.path, info, 'webui')
    session.fields.append(EditField('positive', 'positive', '正面提示詞', info.positive, 'text'))
    session.fields.append(EditField('negative', 'negative', '負面提示詞', info.negative, 'text'))

    for i, lora in enumerate(info.loras):
        if lora.origin != 'prompt':
            continue
        name = f'LoRA「{lora.short_name}」的'
        session.fields.append(EditField(f'lora:{i}:name', 'lora', name + '名稱', lora.name, 'str',
                                        f'<{lora.tag_kind}:…> 標籤', lora_index=i, lora_part='name'))
        session.fields.append(EditField(f'lora:{i}:model', 'lora', name + 'Model 權重', _fmt(lora.strength_model),
                                        'float', optional=True, lora_index=i, lora_part='model'))
        session.fields.append(EditField(f'lora:{i}:clip', 'lora', name + 'CLIP 權重', _fmt(lora.strength_clip),
                                        'float', optional=True, lora_index=i, lora_part='clip'))

    for key, value in info.params.items():
        kind = 'size' if key == 'Size' else 'int' if key in INT_PARAMS else 'float' if key in FLOAT_PARAMS else 'str'
        session.fields.append(EditField(f'param:{key}', 'params', core.PARAM_LABELS.get(key, key),
                                        str(value), kind, key, optional=True))
    if any(l.origin == 'hashes' for l in info.loras):
        session.notes.append('只出現在 Lora hashes、提示詞中沒有 <lora:…> 標籤的 LoRA 無法個別編輯，'
                             '可以直接修改「LoRA 雜湊」參數。')
    return session


# ──────────────────────────────────────────────────────────────
# 驗證與轉換
# ──────────────────────────────────────────────────────────────

def convert(f: EditField, text: str) -> Any:
    """把使用者輸入轉成要寫入的值；格式錯誤時丟出 ValueError（訊息會顯示給使用者）"""
    if f.kind == 'text':
        return text
    t = text.strip()
    if t == '':
        if f.optional:
            return None
        raise ValueError('不能空白')
    if f.kind == 'str':
        return t
    if f.kind in ('int', 'clipskip'):
        try:
            number = int(t)
        except ValueError:
            raise ValueError('必須是整數') from None
        if f.kind == 'clipskip' and number < 1:
            raise ValueError('必須是 1 以上的整數')
        return number
    if f.kind == 'float':
        try:
            number = float(t)
        except ValueError:
            raise ValueError('必須是數字') from None
        if number != number or number in (float('inf'), float('-inf')):
            raise ValueError('必須是一般的數字')
        return number
    if f.kind == 'size':
        m = re.fullmatch(r'(\d+)\s*[xX×*]\s*(\d+)', t)
        if not m or int(m.group(1)) <= 0 or int(m.group(2)) <= 0:
            raise ValueError('格式應為「寬x高」，例如 832x1216')
        return int(m.group(1)), int(m.group(2))
    return t


def check_changes(session: EditSession, changes: dict[str, str]) -> list[str]:
    """回傳所有格式錯誤（空清單代表都沒問題）"""
    errors = []
    for fid, text in changes.items():
        f = session.field(fid)
        try:
            convert(f, text)
        except ValueError as exc:
            errors.append(f'{f.label}：{exc}')
    return errors


def _same(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(float(a) - float(b)) <= 1e-9 * max(1.0, abs(float(a)))
    if isinstance(a, tuple) and isinstance(b, tuple):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b))
    return a == b


# ──────────────────────────────────────────────────────────────
# ComfyUI：寫回 API prompt 與 workflow
# ──────────────────────────────────────────────────────────────

def _is_api_link(value: Any) -> bool:
    return (isinstance(value, list) and len(value) == 2 and isinstance(value[1], int)
            and isinstance(value[0], (str, int)) and not isinstance(value[0], bool))


def _find_wf_node(workflow: dict, nid: str) -> dict | None:
    for node in workflow.get('nodes') or []:
        if str(node.get('id')) == nid:
            return node
    if ':' in nid:  # 子圖裡的節點，API 中的 ID 長得像「外層:內層」
        last = nid.split(':')[-1]
        candidates = [n for sg in (workflow.get('definitions') or {}).get('subgraphs') or []
                      for n in sg.get('nodes') or [] if str(n.get('id')) == last]
        if len(candidates) == 1:
            return candidates[0]
    return None


def _sync_primitive(wf: dict, wf_orig: dict, node_orig: dict, key: str, old: Any, new: Any) -> bool:
    """欄位如果接到前端的 PrimitiveNode（不會出現在 API prompt），載入時會被它覆蓋，所以要一起改"""
    link_id = None
    for inp in node_orig.get('inputs') or []:
        widget = (inp.get('widget') or {}).get('name')
        if (widget == key or inp.get('name') == key) and inp.get('link') is not None:
            link_id = inp['link']
            break
    if link_id is None:
        return False
    origin = None
    for link in wf_orig.get('links') or []:
        if isinstance(link, list) and link and link[0] == link_id:
            origin = link[1]
            break
        if isinstance(link, dict) and link.get('id') == link_id:
            origin = link.get('origin_id')
            break
    if origin is None:
        return False
    src, src_orig = _find_wf_node(wf, str(origin)), _find_wf_node(wf_orig, str(origin))
    if not src or not src_orig or src_orig.get('type') != 'PrimitiveNode':
        return False
    values, values_orig = src.get('widgets_values'), src_orig.get('widgets_values')
    if isinstance(values, list) and values_orig and _same(values_orig[0], old):
        values[0] = new
        return True
    return False


def _sync_workflow(wf: dict, wf_orig: dict, api_orig: dict, ref, old: Any, new: Any) -> bool:
    """在 workflow 裡找到同一個欄位並改成新值。
    workflow 的 widgets_values 是沒有名稱的清單，所以用「原值相同的第幾個」對應到 API 的欄位。
    比對一律用修改前的副本，同一個節點改多個欄位時才不會互相干擾。"""
    nid, key, sub = ref
    node, node_orig = _find_wf_node(wf, nid), _find_wf_node(wf_orig, nid)
    synced = False
    if node is not None and node_orig is not None:
        values, values_orig = node.get('widgets_values'), node_orig.get('widgets_values')
        api_inputs = api_orig[nid]['inputs']
        if isinstance(values, dict):
            if key in values:
                if sub is not None and isinstance(values[key], dict):
                    values[key][sub] = new
                else:
                    values[key] = new
                synced = True
        elif isinstance(values, list):
            if sub is not None:
                # rgthree Power Lora Loader：第 k 個 LoRA 字典對應第 k 個 lora_N 輸入
                api_keys = [k for k, v in api_inputs.items() if isinstance(v, dict) and 'lora' in v]
                wf_index = [i for i, v in enumerate(values_orig) if isinstance(v, dict) and 'lora' in v]
                if key in api_keys and len(api_keys) == len(wf_index):
                    values[wf_index[api_keys.index(key)]][sub] = new
                    synced = True
            else:
                same_keys = [k for k, v in api_inputs.items() if not _is_api_link(v) and _same(v, old)]
                matches = [i for i, v in enumerate(values_orig) if _same(v, old)]
                if key in same_keys:
                    rank = same_keys.index(key)
                    if rank < len(matches):
                        values[matches[rank]] = new
                        synced = True
        if sub is None and _sync_primitive(wf, wf_orig, node_orig, key, old, new):
            synced = True
    return synced


def _apply_comfy(session: EditSession, changes: dict[str, str]) -> tuple[dict, list[str], dict]:
    raw = session.info.raw
    api = json.loads(raw['prompt'])
    api_orig = copy.deepcopy(api)
    workflow = core._try_json(raw.get('workflow'))
    if not isinstance(workflow, dict):
        workflow = None
    wf_orig = copy.deepcopy(workflow)
    warnings: list[str] = []
    expected: dict[str, Any] = {}

    for fid, text in changes.items():
        f = session.field(fid)
        value = convert(f, text)
        expected[fid] = value
        if f.kind == 'size':
            pairs = [(f.refs[0], value[0]), (f.refs[1], value[1])]
        elif f.kind == 'clipskip':
            old = _api_get(api_orig, f.refs[0])
            negative = isinstance(old, (int, float)) and old < 0   # CLIPSetLastLayer 存的是 -2 這種負數
            pairs = [(f.refs[0], -value if negative else value)]
        else:
            pairs = [(f.refs[0], value)]
        synced_all = True
        for ref, new in pairs:
            old = _api_get(api_orig, ref)
            _api_set(api, ref, new)
            if workflow is not None and not _sync_workflow(workflow, wf_orig, api_orig, ref, old, new):
                synced_all = False
        if workflow is not None and not synced_all:
            warnings.append(f'「{f.label}」（{f.detail}）在 workflow 中找不到對應欄位：圖片裡的參數已經更新，'
                            '但拖進 ComfyUI 時這個欄位可能會顯示舊值。')

    chunks = {'prompt': json.dumps(api)}
    if workflow is not None:
        chunks['workflow'] = json.dumps(workflow)
    return chunks, warnings, expected


# ──────────────────────────────────────────────────────────────
# WebUI / Forge：重組 parameters
# ──────────────────────────────────────────────────────────────

def _a1111_quote(text: str) -> str:
    """與 A1111 原始碼相同：含逗號、冒號或換行的值才加上引號"""
    if ',' not in text and '\n' not in text and ':' not in text:
        return text
    return json.dumps(text, ensure_ascii=False)


def _replace_lora_tag(prompt: str, lora: core.LoraInfo, parts: dict[str, Any]) -> tuple[str, bool]:
    for m in core._RE_LORA_TAG.finditer(prompt):
        if m.group(2).strip().lower() != lora.name.lower():
            continue
        name = parts.get('name', lora.name)
        model = parts['model'] if 'model' in parts else lora.strength_model
        clip = parts['clip'] if 'clip' in parts else lora.strength_clip
        tag = f'<{m.group(1)}:{name}'
        if model is not None or clip is not None:
            tag += f':{_fmt(model if model is not None else 1.0)}'
        if clip is not None:
            tag += f':{_fmt(clip)}'
        tag += '>'
        return prompt[:m.start()] + tag + prompt[m.end():], True
    return prompt, False


def _apply_webui(session: EditSession, changes: dict[str, str]) -> tuple[dict, list[str], dict]:
    info = session.info
    values = {fid: convert(session.field(fid), text) for fid, text in changes.items()}
    positive = values.get('positive', info.positive).strip()
    negative = values.get('negative', info.negative).strip()
    warnings: list[str] = []

    lora_parts: dict[int, dict[str, Any]] = {}
    for fid, value in values.items():
        if fid.startswith('lora:'):
            f = session.field(fid)
            lora_parts.setdefault(f.lora_index, {})[f.lora_part] = value
    for index, parts in lora_parts.items():
        lora = info.loras[index]
        if not parts.get('name', lora.name):
            parts['name'] = lora.name
        positive, ok = _replace_lora_tag(positive, lora, parts)
        if not ok:
            warnings.append(f'提示詞中找不到 LoRA「{lora.name}」的 <lora:…> 標籤（可能已在提示詞中被改掉），'
                            '這個 LoRA 的修改沒有套用。')

    params = dict(info.params)
    for fid, value in values.items():
        if not fid.startswith('param:'):
            continue
        key = fid[len('param:'):]
        if value is None:
            params.pop(key, None)
        elif isinstance(value, tuple):
            params[key] = f'{value[0]}x{value[1]}'
        else:
            params[key] = _fmt(value)

    lines = [positive]
    if negative:
        lines.append(f'Negative prompt: {negative}')
    params_line = ', '.join(f'{k}: {_a1111_quote(str(v))}' for k, v in params.items() if str(v) != '')
    if params_line:
        lines.append(params_line)

    expected: dict[str, Any] = {'positive': positive, 'negative': negative}
    for fid, value in values.items():
        if fid.startswith('param:'):
            expected[fid] = value
    return {'parameters': '\n'.join(lines)}, warnings, expected


# ──────────────────────────────────────────────────────────────
# 存檔
# ──────────────────────────────────────────────────────────────

def _edit_marker(session: EditSession, changes: dict[str, str], app_version: str) -> str:
    labels = list(dict.fromkeys(session.field(fid).label for fid in changes))
    record = {
        'tool': 'PNG Info 檢視器',
        'version': app_version,
        'edited_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        'fields': labels,
    }
    return json.dumps(record)   # 預設 ensure_ascii，中文會轉成 \uXXXX，可以存在 tEXt 區塊


def _verify_fields(session: EditSession, tmp: str, expected: dict[str, Any]) -> None:
    """重新解析新檔案，確認每個修改都讀得回來"""
    new_info = core.parse_file(tmp)
    try:
        new_session = build_session(new_info)
    except EditError as exc:
        raise EditError(f'驗證失敗：新檔案無法重新解析（{exc}），已取消存檔。') from None
    for fid, value in expected.items():
        f_new = new_session.find(fid)
        if value is None:   # WebUI 參數留空 = 刪除
            if f_new is not None:
                raise EditError(f'驗證失敗：「{session.field(fid).label}」沒有被移除，已取消存檔。')
            continue
        if f_new is None:
            raise EditError(f'驗證失敗：新檔案中讀不到「{session.field(fid).label}」，已取消存檔。')
        actual = f_new.original if f_new.kind == 'text' else convert(f_new, f_new.original)
        if f_new.kind == 'text' and session.kind == 'webui':
            actual = actual.strip()
        if not _same(actual, value):
            raise EditError(f'驗證失敗：「{session.field(fid).label}」寫入後讀回的值不一致，已取消存檔。\n'
                            '這通常是提示詞裡含有「Negative prompt:」或參數格式的文字造成的。')


def save_as(session: EditSession, values: dict[str, str], dst: str, app_version: str = '') -> SaveResult:
    """把修改另存成新的 PNG。values 可以包含沒改的欄位，會自動忽略。"""
    changes = session.changed(values)
    if not changes:
        raise EditError('沒有任何修改。')
    errors = check_changes(session, changes)
    if errors:
        raise EditError('以下欄位的格式不正確：\n' + '\n'.join(errors))
    _check_destination(session.path, dst)

    apply = _apply_comfy if session.kind == 'comfyui' else _apply_webui
    replace, warnings, expected = apply(session, changes)
    replace[core.EDIT_MARKER_KEY] = _edit_marker(session, changes, app_version)

    chunks = _rebuild_chunks(read_chunks(session.path), replace)
    tmp = _write_temp(dst, chunks, session.path)
    try:
        _verify_image_data(session.path, tmp, strip=False)
        _verify_fields(session, tmp, expected)
        os.replace(tmp, dst)
    except BaseException:
        _remove_quietly(tmp)
        raise
    labels = list(dict.fromkeys(session.field(fid).label for fid in changes))
    return SaveResult(dst, labels, warnings)


def strip_metadata(src: str, dst: str) -> int:
    """另存一張不含任何文字中繼資料的 PNG，回傳移除的區塊數"""
    if not is_png(src):
        raise EditError('目前只支援 PNG 圖片。')
    _check_destination(src, dst)
    chunks = read_chunks(src)
    kept = _rebuild_chunks(chunks, {}, strip=True)
    tmp = _write_temp(dst, kept, src)
    try:
        _verify_image_data(src, tmp, strip=True)
        with Image.open(tmp) as img:
            if core.read_metadata(img):
                raise EditError('驗證失敗：新檔案仍含有文字中繼資料，已取消存檔。')
        os.replace(tmp, dst)
    except BaseException:
        _remove_quietly(tmp)
        raise
    return len(chunks) - len(kept)


# ──────────────────────────────────────────────────────────────
# 批次取代
# ──────────────────────────────────────────────────────────────

def batch_replace(session: EditSession, find: str, replacement: str,
                  groups: tuple[str, ...] = ('positive', 'negative'),
                  case_sensitive: bool = False) -> tuple[dict[str, str], int]:
    """在提示詞欄位中取代文字，回傳 (修改內容, 取代次數)；修改內容可以直接交給 save_as。
    <lora:…> / <lyco:…> 標籤會原封不動，避免改壞 LoRA 檔名（改 LoRA 請用編輯視窗的 LoRA 分頁）。"""
    if not find:
        return {}, 0
    pattern = re.compile(re.escape(find), 0 if case_sensitive else re.IGNORECASE)
    changes: dict[str, str] = {}
    total = 0
    for f in session.fields:
        if f.kind != 'text' or f.group not in groups:
            continue
        pieces, count, last = [], 0, 0
        for tag in core._RE_LORA_TAG.finditer(f.original):
            text, n = pattern.subn(lambda _m: replacement, f.original[last:tag.start()])
            pieces += [text, tag.group(0)]
            count += n
            last = tag.end()
        text, n = pattern.subn(lambda _m: replacement, f.original[last:])
        pieces.append(text)
        count += n
        if count:
            changes[f.fid] = ''.join(pieces)
            total += count
    return changes, total
