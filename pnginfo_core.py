#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pnginfo_core.py — AI 生成圖片中繼資料解析核心

不依賴任何 GUI，CLI（main.py）與 GUI（png_info_parser.py）共用同一套邏輯。

支援：
  • ComfyUI：PNG 的 prompt / workflow 文字區塊（WebP 則存在 EXIF）
    以「從採樣器反向追蹤節點連線」判斷正面／負面提示詞、LoRA、模型與尺寸，
    不依賴節點順序。
  • Stable Diffusion WebUI / Forge：PNG 的 parameters（JPEG / WebP 則存在 EXIF UserComment）
  • 其他含文字中繼資料的圖片：原樣列出
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from PIL import Image

IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp')
LORA_FILE_EXTS = ('.safetensors', '.pt', '.ckpt', '.bin', '.pth')

SOURCE_LABELS = {
    'comfyui': 'ComfyUI',
    'webui': 'WebUI / Forge',
    'generic': '其他中繼資料',
    'none': '無中繼資料',
    'error': '讀取失敗',
}

# WebUI 參數行的標準順序（ComfyUI 轉 WebUI 格式時也用這個順序）
PARAM_ORDER = [
    'Steps', 'Sampler', 'Schedule type', 'CFG scale', 'Guidance', 'Seed', 'Size',
    'Model hash', 'Model', 'VAE', 'Denoising strength', 'Clip skip', 'Batch size',
]

# 顯示用的中文名稱（沒列在這裡的參數直接顯示英文原名）
PARAM_LABELS = {
    'Steps': '採樣步數',
    'Sampler': '採樣器',
    'Schedule type': '排程器',
    'CFG scale': 'CFG',
    'Guidance': 'Guidance',
    'Seed': '種子',
    'Size': '生成尺寸',
    'Model hash': '模型雜湊',
    'Model': '模型',
    'VAE': 'VAE',
    'VAE hash': 'VAE 雜湊',
    'Denoising strength': '去噪強度',
    'Clip skip': 'CLIP 跳過',
    'Batch size': '批次大小',
    'Hires upscale': '高解析放大倍率',
    'Hires upscaler': '高解析放大器',
    'Hires steps': '高解析步數',
    'Lora hashes': 'LoRA 雜湊',
    'Version': '版本',
}

CSV_FIELDS = [
    '檔案', '路徑', '來源', '正面提示詞', '負面提示詞', 'LoRA',
    'Steps', 'Sampler', 'Schedule type', 'CFG scale', 'Seed', 'Size', 'Model',
]

# 本工具編輯圖片後寫入的標記（PNG 文字區塊的關鍵字）
EDIT_MARKER_KEY = 'pnginfo_edit'

# PNG 的 img.info 裡這些是二進位資料，不是文字中繼資料
_BINARY_INFO_KEYS = {'icc_profile', 'exif', 'xmp', 'photoshop', 'adobe'}


# ──────────────────────────────────────────────────────────────
# 資料結構
# ──────────────────────────────────────────────────────────────

@dataclass
class LoraInfo:
    name: str
    strength_model: float | None = None
    strength_clip: float | None = None
    origin: str = ''  # 'node'：工作流節點、'prompt'：提示詞中的 <lora:> 標籤、'hashes'：Lora hashes 欄位
    # ComfyUI：名稱與權重在 API prompt 裡的位置 {'name': Ref, 'model': Ref, 'clip': Ref}，編輯時使用
    refs: dict = field(default_factory=dict, repr=False, compare=False)
    tag_kind: str = 'lora'  # WebUI 標籤是 <lora:…> 還是 <lyco:…>

    @property
    def short_name(self) -> str:
        """去掉資料夾與副檔名的名稱，例如 'sdxl/detail.safetensors' → 'detail'"""
        base = self.name.replace('\\', '/').rsplit('/', 1)[-1]
        root, ext = os.path.splitext(base)
        return root if ext.lower() in LORA_FILE_EXTS else base

    def to_tag(self) -> str:
        weight = self.strength_model if self.strength_model is not None else 1
        return f'<lora:{self.short_name}:{format_number(weight)}>'


@dataclass
class GenInfo:
    path: str
    source: str = 'none'
    positive: str = ''
    negative: str = ''
    loras: list[LoraInfo] = field(default_factory=list)
    params: dict[str, Any] = field(default_factory=dict)   # 生成參數（會輸出到 WebUI 格式）
    extra: dict[str, Any] = field(default_factory=dict)    # 其他資訊（只顯示，不輸出到 WebUI 格式）
    notes: list[str] = field(default_factory=list)
    raw: dict[str, str] = field(default_factory=dict)
    width: int = 0
    height: int = 0
    mode: str = ''
    file_size: int = 0
    error: str = ''
    # 每個值在原始資料裡的位置（給 pnginfo_editor 使用，不會出現在匯出結果）
    sources: dict = field(default_factory=dict, repr=False, compare=False)
    edit_record: dict = field(default_factory=dict)  # 由本工具編輯過的紀錄

    @property
    def filename(self) -> str:
        return os.path.basename(self.path)

    @property
    def source_label(self) -> str:
        return SOURCE_LABELS.get(self.source, self.source)

    @property
    def has_generation_data(self) -> bool:
        return self.source in ('comfyui', 'webui')


# ──────────────────────────────────────────────────────────────
# 小工具
# ──────────────────────────────────────────────────────────────

def format_number(value: Any) -> str:
    """7.0 → '7'、0.550000 → '0.55'，其他型別直接轉字串"""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return f'{value:.4f}'.rstrip('0').rstrip('.')
    return str(value)


def format_size(num_bytes: int) -> str:
    if num_bytes >= 1024 * 1024:
        return f'{num_bytes / 1024 / 1024:.1f} MB'
    return f'{num_bytes / 1024:.1f} KB'


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _try_json(text: Any) -> Any:
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped or stripped[0] not in '{[':
        return None
    try:
        return json.loads(stripped)
    except (ValueError, RecursionError):
        return None


def _is_lora_name(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != '' and value.strip().lower() != 'none'


def _node_sort_key(nid: str):
    try:
        return (0, int(nid), '')
    except ValueError:
        # 子圖（group node）的節點 ID 可能長得像 "12:5"
        nums = re.findall(r'\d+', nid)
        return (1, int(nums[0]) if nums else 0, nid)


def expand_paths(paths: Iterable[str]) -> list[str]:
    """把檔案與資料夾展開成圖片清單（資料夾會遞迴搜尋），去除重複並保持順序"""
    result: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        if p not in seen:
            seen.add(p)
            result.append(p)

    for raw_path in paths:
        if not raw_path:
            continue
        path = os.path.abspath(os.path.expanduser(str(raw_path)))
        if os.path.isdir(path):
            for root, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if not d.startswith('.'))
                for name in sorted(files):
                    if not name.startswith('.') and name.lower().endswith(IMAGE_EXTENSIONS):
                        add(os.path.join(root, name))
        elif os.path.isfile(path) and path.lower().endswith(IMAGE_EXTENSIONS):
            add(path)
    return result


# ──────────────────────────────────────────────────────────────
# 讀取中繼資料
# ──────────────────────────────────────────────────────────────

def _decode_user_comment(data: Any) -> str:
    """解碼 EXIF UserComment（WebUI 存 JPEG / WebP 時使用）"""
    if isinstance(data, str):
        return data.strip('\x00')
    if not isinstance(data, (bytes, bytearray)):
        return ''
    data = bytes(data)
    header, body = data[:8], data[8:]
    if header.startswith(b'UNICODE'):
        for encoding in ('utf-16-be', 'utf-16-le'):
            try:
                text = body.decode(encoding)
            except UnicodeDecodeError:
                continue
            # 位元組順序猜錯時會變成一堆罕見字元；正確時絕大多數是拉丁字元
            if text and sum(1 for c in text if ord(c) < 0x0800) / len(text) > 0.6:
                return text.strip('\x00')
        return body.decode('utf-16-be', 'ignore').strip('\x00')
    if header.startswith(b'ASCII'):
        return body.decode('latin-1').strip('\x00')
    return data.decode('utf-8', 'ignore').strip('\x00')


def read_metadata(img: Image.Image) -> dict[str, str]:
    """取出圖片中所有文字型的中繼資料"""
    meta: dict[str, str] = {}

    for key, value in img.info.items():
        if isinstance(value, bytes):
            if key in _BINARY_INFO_KEYS:
                continue
            try:
                value = value.decode('utf-8')
            except UnicodeDecodeError:
                continue
        if isinstance(value, str) and value.strip():
            meta[str(key)] = value

    try:
        exif = img.getexif()
    except Exception:
        exif = None

    if exif:
        # ComfyUI 存 WebP 時，會把 "prompt:{...}"、"workflow:{...}" 寫進 EXIF 的 Make / Model 等欄位
        for value in exif.values():
            if isinstance(value, bytes):
                value = value.decode('utf-8', 'ignore')
            if isinstance(value, str):
                for prefix in ('prompt', 'workflow'):
                    if value.startswith(prefix + ':') and prefix not in meta:
                        meta[prefix] = value[len(prefix) + 1:]

        # WebUI 存 JPEG / WebP 時，參數放在 EXIF UserComment
        if 'parameters' not in meta:
            try:
                user_comment = exif.get_ifd(0x8769).get(0x9286)
            except Exception:
                user_comment = None
            if user_comment:
                text = _decode_user_comment(user_comment)
                if text.strip():
                    meta['parameters'] = text

    return meta


# ──────────────────────────────────────────────────────────────
# ComfyUI：節點圖反向追蹤
# ──────────────────────────────────────────────────────────────

_MAX_DEPTH = 60

# 文字編碼器上存放提示詞的欄位（CLIPTextEncode、CLIPTextEncodeSDXL、CLIPTextEncodeFlux 等）
_TEXT_ENCODER_KEYS = ('text', 'text_g', 'text_l', 'clip_l', 't5xxl', 'prompt')
# 字串類節點（Primitive、String、Wildcard 等）存放字串的欄位
_STRING_KEYS = ('populated_text', 'text', 'string', 'value', 'prompt',
                'text_a', 'text_b', 'string_a', 'string_b', 'wildcard_text')
# 數值類節點（Primitive、Seed 節點等）存放數值的欄位
_SCALAR_KEYS = ('value', 'seed', 'noise_seed', 'int', 'float', 'number', 'Value',
                'steps', 'cfg', 'sampler_name', 'scheduler', 'width', 'height', 'string', 'text')
_MODEL_NAME_KEYS = ('ckpt_name', 'unet_name', 'model_name', 'gguf_name', 'base_ckpt_name')
_LATENT_UPSTREAM_KEYS = ('samples', 'latent', 'latent_image', 'latents', 'pixels', 'image')


# 一個值在 API prompt 裡的位置：(節點 ID, 輸入名稱, 子欄位)。
# 子欄位只用在 rgthree Power Lora Loader 這種「輸入值是字典」的節點，其他都是 None。
Ref = tuple  # tuple[str, str, str | None]


@dataclass
class _Sampler:
    nid: str
    positive: Any
    negative: Any
    model: Any
    latent: Any
    refs: dict[str, tuple[str, str]]   # 參數名稱 → 存放位置（還沒追蹤連線）
    fixed: dict[str, Any]              # 沒有欄位、只能由節點類型推得的參數（例如 KSamplerSelect 以外的採樣器）


class _ComfyGraph:
    """ComfyUI 的 API 格式 prompt：{節點ID: {"class_type": ..., "inputs": {...}}}
    輸入值如果是 [來源節點ID, 輸出編號]，代表一條連線。"""

    def __init__(self, prompt: dict):
        self.nodes = {str(k): v for k, v in prompt.items()
                      if isinstance(v, dict) and 'class_type' in v}
        self.guidance: Any = None
        self.guidance_ref: Ref | None = None

    # ── 基本操作 ──

    def is_link(self, value: Any) -> bool:
        return (isinstance(value, (list, tuple)) and len(value) == 2
                and isinstance(value[1], int) and str(value[0]) in self.nodes)

    def inputs(self, nid: Any) -> dict:
        node = self.nodes.get(str(nid))
        return (node.get('inputs') or {}) if node else {}

    def ctype(self, nid: Any) -> str:
        return str(self.nodes.get(str(nid), {}).get('class_type', ''))

    def resolve(self, value: Any, prefer: str | None = None) -> Any:
        """如果輸入值是連線（例如 seed 接到 Primitive 節點），往上找到實際數值"""
        depth = 0
        while self.is_link(value) and depth < _MAX_DEPTH:
            inputs = self.inputs(value[0])
            keys = ((prefer,) if prefer else ()) + _SCALAR_KEYS
            for key in keys:
                if key in inputs:
                    value = inputs[key]
                    break
            else:
                return None
            depth += 1
        return None if self.is_link(value) else value

    def ref_value(self, ref: Ref) -> Any:
        nid, key, sub = ref
        value = self.inputs(nid).get(key)
        return value.get(sub) if sub is not None and isinstance(value, dict) else value

    def locate(self, nid: Any, key: str | None, prefer: str | None = None) -> Ref | None:
        """跟 resolve 走同一條路，但回傳「實際數值存在哪個節點的哪個欄位」，編輯時就改那裡"""
        if key is None:
            return None
        nid = str(nid)
        inputs = self.inputs(nid)
        if key not in inputs:
            return None
        value = inputs[key]
        depth = 0
        while self.is_link(value) and depth < _MAX_DEPTH:
            src = str(value[0])
            src_inputs = self.inputs(src)
            for k in ((prefer,) if prefer else ()) + _SCALAR_KEYS:
                if k in src_inputs:
                    nid, key, value = src, k, src_inputs[k]
                    break
            else:
                return None
            depth += 1
        return None if self.is_link(value) else (nid, key, None)

    def string_sources(self, nid: Any, key: str, depth: int = 0) -> list[Ref]:
        """跟 resolve_string 走同一條路，回傳組成這段文字的每個字串欄位位置（包含空字串，才能讓使用者填入）"""
        nid = str(nid)
        value = self.inputs(nid).get(key)
        if isinstance(value, str):
            return [(nid, key, None)]
        if not self.is_link(value) or depth > _MAX_DEPTH:
            return []
        src = str(value[0])
        inputs = self.inputs(src)
        ctype = self.ctype(src).lower()

        if any(word in ctype for word in ('concat', 'join', 'combine', 'append')):
            refs: list[Ref] = []
            for k in sorted(inputs):
                if k in ('delimiter', 'separator', 'clean_whitespace'):
                    continue
                if k.startswith(('text', 'string')):
                    refs += self.string_sources(src, k, depth + 1)
            if refs:
                return refs

        fallback: list[Ref] = []
        for k in _STRING_KEYS:
            if k in inputs:
                refs = self.string_sources(src, k, depth + 1)
                if any(str(self.ref_value(r)).strip() for r in refs):
                    return refs
                if refs and not fallback:
                    fallback = refs
        return fallback

    def resolve_string(self, value: Any, depth: int = 0) -> str:
        """把文字輸入解析成字串，支援 Primitive / String / 字串串接 / Wildcard 等節點"""
        if isinstance(value, str):
            return value
        if not self.is_link(value) or depth > _MAX_DEPTH:
            return ''
        inputs = self.inputs(value[0])
        ctype = self.ctype(value[0]).lower()

        if any(word in ctype for word in ('concat', 'join', 'combine', 'append')):
            delimiter = inputs.get('delimiter', inputs.get('separator', ', '))
            if not isinstance(delimiter, str):
                delimiter = ', '
            delimiter = delimiter.replace('\\n', '\n')
            parts = []
            for key in sorted(inputs):
                if key in ('delimiter', 'separator', 'clean_whitespace'):
                    continue
                if key.startswith(('text', 'string')):
                    text = self.resolve_string(inputs[key], depth + 1)
                    if text:
                        parts.append(text)
            if parts:
                return delimiter.join(parts)

        for key in _STRING_KEYS:
            if key in inputs:
                text = self.resolve_string(inputs[key], depth + 1)
                if text:
                    return text
        return ''

    def reachable(self, start: str) -> list[str]:
        """從某個節點往上游走，列出所有連得到的節點"""
        order, seen, stack = [], set(), [str(start)]
        while stack:
            nid = stack.pop()
            if nid in seen or nid not in self.nodes:
                continue
            seen.add(nid)
            order.append(nid)
            for value in self.inputs(nid).values():
                if self.is_link(value):
                    stack.append(str(value[0]))
        return order

    # ── 採樣器 ──

    def _custom_sampler_refs(self, nid: str, inputs: dict) -> tuple[dict, dict]:
        """SamplerCustom / SamplerCustomAdvanced 的參數分散在 noise、sampler、sigmas 節點上"""
        refs: dict[str, tuple[str, str]] = {}
        fixed: dict[str, Any] = {}
        if 'noise_seed' in inputs:
            refs['seed'] = (nid, 'noise_seed')
        if self.is_link(inputs.get('noise')):
            noise_id = str(inputs['noise'][0])
            for key in ('noise_seed', 'seed'):
                if key in self.inputs(noise_id):
                    refs['seed'] = (noise_id, key)
                    break
        if self.is_link(inputs.get('sampler')):
            sid = str(inputs['sampler'][0])
            if 'sampler_name' in self.inputs(sid):
                refs['sampler_name'] = (sid, 'sampler_name')
            else:
                fixed['sampler_name'] = self.ctype(sid)
        if self.is_link(inputs.get('sigmas')):
            gid = str(inputs['sigmas'][0])
            sig = self.inputs(gid)
            for key in ('steps', 'denoise', 'scheduler'):
                if key in sig:
                    refs[key] = (gid, key)
            if 'scheduler' not in sig:
                fixed['scheduler'] = self.ctype(gid)
        if 'cfg' in inputs:
            refs['cfg'] = (nid, 'cfg')
        return refs, fixed

    def find_samplers(self) -> list[_Sampler]:
        found = []
        for nid in sorted(self.nodes, key=_node_sort_key):
            inputs = self.inputs(nid)
            if self.is_link(inputs.get('guider')):
                # SamplerCustomAdvanced：提示詞與 CFG 在 guider（CFGGuider / BasicGuider）上
                gid = str(inputs['guider'][0])
                guider = self.inputs(gid)
                positive = guider.get('positive', guider.get('conditioning', guider.get('cond1')))
                refs = {'cfg': (gid, 'cfg')} if 'cfg' in guider else {}
                more, fixed = self._custom_sampler_refs(nid, inputs)
                refs.update(more)
                found.append(_Sampler(nid, positive, guider.get('negative'), guider.get('model'),
                                      inputs.get('latent_image'), refs, fixed))
            elif 'positive' in inputs and 'latent_image' in inputs:
                # KSampler / KSamplerAdvanced / SamplerCustom 以及多數自訂採樣器
                refs = {k: (nid, k) for k in
                        ('seed', 'noise_seed', 'steps', 'cfg', 'sampler_name', 'scheduler', 'denoise')
                        if k in inputs}
                fixed = {}
                if self.is_link(inputs.get('sampler')) or self.is_link(inputs.get('sigmas')):
                    more, fixed = self._custom_sampler_refs(nid, inputs)
                    refs.update(more)
                if 'seed' not in refs and 'noise_seed' in refs:   # KSamplerAdvanced 叫 noise_seed
                    refs['seed'] = refs.pop('noise_seed')
                refs.pop('noise_seed', None)
                found.append(_Sampler(nid, inputs.get('positive'), inputs.get('negative'),
                                      inputs.get('model'), inputs.get('latent_image'), refs, fixed))
        return found

    def is_sampler(self, nid: Any) -> bool:
        inputs = self.inputs(nid)
        return self.is_link(inputs.get('guider')) or ('positive' in inputs and 'latent_image' in inputs)

    def latent_source(self, ref: Any) -> tuple[str, str, str, str | None] | None:
        """沿著 latent 往上找空白 latent 節點，回傳 (節點ID, 寬欄位, 高欄位, 批次欄位)。
        途中遇到其他採樣器（代表這是 Hires fix 的第二階段）或圖生圖時回傳 None。"""
        depth = 0
        while self.is_link(ref) and depth < 30:
            nid = str(ref[0])
            inputs = self.inputs(nid)
            if self.is_sampler(nid):
                return None
            upstream = next((inputs[k] for k in _LATENT_UPSTREAM_KEYS if self.is_link(inputs.get(k))), None)
            if upstream is None:
                # Efficiency Loader 這類節點本身就輸出空白 latent，尺寸欄位叫 empty_latent_width
                wkey = next((k for k in ('width', 'empty_latent_width') if k in inputs), None)
                hkey = next((k for k in ('height', 'empty_latent_height') if k in inputs), None)
                if wkey and hkey:
                    return nid, wkey, hkey, ('batch_size' if 'batch_size' in inputs else None)
                return None
            ref = upstream
            depth += 1
        return None

    def trace_latent(self, ref: Any) -> tuple[int, int, Any] | None:
        """回傳生成尺寸 (寬, 高, 批次)；不是從空白 latent 開始的話回傳 None"""
        src = self.latent_source(ref)
        if src is None:
            return None
        nid, wkey, hkey, bkey = src
        inputs = self.inputs(nid)
        width = self.resolve(inputs.get(wkey), 'width')
        height = self.resolve(inputs.get(hkey), 'height')
        if _to_float(width) is None or _to_float(height) is None:
            return None
        batch = self.resolve(inputs.get(bkey), 'batch_size') if bkey else None
        return int(float(width)), int(float(height)), batch

    def pick_primary(self, samplers: list[_Sampler]) -> _Sampler:
        """有多個採樣器（例如 Hires fix 兩階段）時，取從空白 latent 開始的第一階段"""
        for sampler in samplers:
            if self.trace_latent(sampler.latent) is not None:
                return sampler
        return samplers[0]

    # ── 提示詞 ──

    def collect_texts(self, ref: Any, role: str, depth: int = 0, visited: set | None = None) -> list[str]:
        """從採樣器的 positive / negative 輸入往上追，收集最終的提示詞文字"""
        if visited is None:
            visited = set()
        if isinstance(ref, str):
            return [ref] if ref.strip() else []
        if not self.is_link(ref) or depth > _MAX_DEPTH:
            return []
        key = (str(ref[0]), ref[1])
        if key in visited:
            return []
        visited.add(key)
        inputs = self.inputs(ref[0])

        # FluxGuidance 這類節點會帶 guidance 數值
        guidance = inputs.get('guidance')
        if role == 'positive' and self.guidance is None and guidance is not None and not self.is_link(guidance):
            self.guidance = guidance
            self.guidance_ref = (str(ref[0]), 'guidance', None)

        # 同時有 positive / negative 的節點（ControlNetApplyAdvanced、Efficiency Loader 等）：依角色選邊
        if 'positive' in inputs and 'negative' in inputs:
            return self.collect_texts(inputs[role], role, depth + 1, visited)

        # Wildcard 節點：優先使用展開後的文字
        populated = self.resolve_string(inputs.get('populated_text')).strip() if 'populated_text' in inputs else ''
        if populated:
            return [populated]

        # 文字編碼器
        texts: list[str] = []
        for k in _TEXT_ENCODER_KEYS:
            if k in inputs:
                text = self.resolve_string(inputs[k]).strip()
                if text and text not in texts:
                    texts.append(text)
        if texts:
            return texts

        # 其他節點（ConditioningCombine、ControlNetApply、FluxGuidance…）：沿 conditioning 連線往上
        result: list[str] = []
        for k, value in inputs.items():
            if not self.is_link(value):
                continue
            lk = k.lower()
            if 'cond' in lk or lk in ('positive', 'negative'):
                for text in self.collect_texts(value, role, depth + 1, visited):
                    if text not in result:
                        result.append(text)
        return result

    def text_sources(self, ref: Any, role: str, depth: int = 0, visited: set | None = None) -> list[Ref]:
        """跟 collect_texts 走同一條路，回傳提示詞文字實際存放的欄位（編輯時用）"""
        if visited is None:
            visited = set()
        if not self.is_link(ref) or depth > _MAX_DEPTH:
            return []
        key = (str(ref[0]), ref[1])
        if key in visited:
            return []
        visited.add(key)
        nid = str(ref[0])
        inputs = self.inputs(nid)

        if 'positive' in inputs and 'negative' in inputs:
            if isinstance(inputs[role], str):        # Efficiency Loader：提示詞直接是字串欄位
                return [(nid, role, None)]
            return self.text_sources(inputs[role], role, depth + 1, visited)

        if 'populated_text' in inputs:
            refs = self.string_sources(nid, 'populated_text')
            if any(str(self.ref_value(r)).strip() for r in refs):
                return refs

        refs: list[Ref] = []
        for k in _TEXT_ENCODER_KEYS:
            if k in inputs:
                for r in self.string_sources(nid, k):
                    if r not in refs:
                        refs.append(r)
        if refs:
            return refs

        result: list[Ref] = []
        for k, value in inputs.items():
            if not self.is_link(value):
                continue
            lk = k.lower()
            if 'cond' in lk or lk in ('positive', 'negative'):
                for r in self.text_sources(value, role, depth + 1, visited):
                    if r not in result:
                        result.append(r)
        return result

    def all_encoder_texts(self) -> list[str]:
        """找不到採樣器時的備案：依節點 ID 順序列出所有文字編碼器的文字"""
        texts = []
        for nid in sorted(self.nodes, key=_node_sort_key):
            if 'TextEncode' not in self.ctype(nid):
                continue
            for k in _TEXT_ENCODER_KEYS:
                text = self.resolve_string(self.inputs(nid).get(k)).strip()
                if text and text not in texts:
                    texts.append(text)
                    break
        return texts

    # ── 模型與 LoRA ──

    def loras_in_node(self, nid: str) -> list[LoraInfo]:
        nid = str(nid)
        inputs = self.inputs(nid)
        result: list[LoraInfo] = []

        def first(*keys) -> tuple[Any, Ref | None]:
            for k in keys:
                if k in inputs:
                    value = self.resolve(inputs[k])
                    if value is not None:
                        return value, self.locate(nid, k)
            return None, None

        # 標準 LoraLoader / LoraLoaderModelOnly / Efficiency Loader
        name = self.resolve(inputs.get('lora_name'))
        if _is_lora_name(name):
            sm, sm_ref = first('strength_model', 'lora_model_strength', 'strength', 'lora_strength', 'model_weight')
            sc, sc_ref = first('strength_clip', 'lora_clip_strength', 'clip_strength', 'clip_weight')
            lora = LoraInfo(name, _to_float(sm), _to_float(sc), 'node')
            lora.refs = {'name': self.locate(nid, 'lora_name'), 'model': sm_ref, 'clip': sc_ref}
            result.append(lora)

        for key, value in inputs.items():
            # rgthree Power Lora Loader：{"on": true, "lora": "...", "strength": 1, "strengthTwo": null}
            if isinstance(value, dict) and _is_lora_name(value.get('lora')):
                if value.get('on', True) is False:
                    continue
                lora = LoraInfo(value['lora'], _to_float(value.get('strength')),
                                _to_float(value.get('strengthTwo')), 'node')
                lora.refs = {'name': (nid, key, 'lora'),
                             'model': (nid, key, 'strength') if 'strength' in value else None,
                             'clip': (nid, key, 'strengthTwo') if value.get('strengthTwo') is not None else None}
                result.append(lora)
                continue

            # 編號式堆疊節點，例如 LoRA Stacker：lora_name_1 / lora_wt_1 / model_str_1 / clip_str_1
            if key == 'lora_name' or 'lora' not in key.lower():
                continue
            name = self.resolve(value)
            if not _is_lora_name(name) or _to_float(name) is not None:
                continue
            match = re.search(r'(\d+)', key)
            if not match:
                continue
            num = match.group(1)
            siblings = {k: self.resolve(v) for k, v in inputs.items()
                        if k != key and re.search(rf'(?<!\d){num}(?!\d)', k)}
            if any(k.lower().startswith(('switch', 'enable', 'toggle')) and str(v).lower() in ('off', 'false')
                   for k, v in siblings.items()):
                continue
            strength_model = strength_clip = None
            sm_key = sc_key = None
            for k, v in siblings.items():
                fv = _to_float(v)
                if fv is None:
                    continue
                lk = k.lower()
                if 'clip' in lk:
                    if strength_clip is None:
                        strength_clip, sc_key = fv, k
                elif any(w in lk for w in ('wt', 'str', 'weight', 'model')):
                    if strength_model is None:
                        strength_model, sm_key = fv, k
            lora = LoraInfo(name, strength_model, strength_clip, 'node')
            lora.refs = {'name': self.locate(nid, key), 'model': self.locate(nid, sm_key),
                         'clip': self.locate(nid, sc_key)}
            result.append(lora)
        return result

    def walk_model_chain(self, ref: Any) -> tuple[str | None, list[LoraInfo], list[str], Ref | None]:
        """沿著 model 連線往上走到模型載入器，回傳 (模型名稱, 鏈上的 LoRA, 走過的節點, 模型名稱的位置)"""
        model_name = model_ref = None
        loras: list[LoraInfo] = []
        visited: list[str] = []
        depth = 0
        while self.is_link(ref) and depth < _MAX_DEPTH:
            nid = str(ref[0])
            if nid in visited:
                break
            visited.append(nid)
            inputs = self.inputs(nid)
            loras.extend(self.loras_in_node(nid))
            for key in _MODEL_NAME_KEYS:
                value = self.resolve(inputs.get(key))
                if _is_lora_name(value) and model_name is None:
                    model_name, model_ref = value, self.locate(nid, key)
            ref = inputs.get('model')
            depth += 1
        loras.reverse()  # 改成從模型載入器往下套用的順序
        return model_name, loras, visited, model_ref


def _parse_comfyui(info: GenInfo, meta: dict[str, str], prompt: dict) -> None:
    info.source = 'comfyui'
    graph = _ComfyGraph(prompt)
    samplers = graph.find_samplers()
    sources: dict[str, Any] = {'kind': 'comfyui', 'sampler_count': len(samplers)}

    if samplers:
        primary = graph.pick_primary(samplers)
        info.positive = '\n\n'.join(graph.collect_texts(primary.positive, 'positive'))
        info.negative = '\n\n'.join(graph.collect_texts(primary.negative, 'negative'))
        sources['positive'] = graph.text_sources(primary.positive, 'positive')
        sources['negative'] = graph.text_sources(primary.negative, 'negative')
        sources['sampler'] = (primary.nid, graph.ctype(primary.nid))
        reach = graph.reachable(primary.nid)
        model_name, chain_loras, chain_nodes, model_ref = graph.walk_model_chain(primary.model)
        if len(samplers) > 1:
            info.notes.append(f'工作流中有 {len(samplers)} 個採樣器（例如 Hires fix），'
                              f'參數以第一階段（節點 {primary.nid}）為準。')
    else:
        info.notes.append('找不到採樣器節點，提示詞是依節點順序推測的，正負面可能不準確。')
        texts = graph.all_encoder_texts()
        info.positive = texts[0] if texts else ''
        info.negative = texts[1] if len(texts) > 1 else ''
        reach = sorted(graph.nodes, key=_node_sort_key)
        primary, model_name, chain_loras, chain_nodes, model_ref = None, None, [], [], None

    # LoRA：先放模型鏈上的（順序可靠），再補上其他連得到的節點（例如 LoRA 堆疊節點）
    loras = list(chain_loras)
    seen = {(l.name, l.strength_model, l.strength_clip) for l in loras}
    for nid in reach:
        if nid in chain_nodes:
            continue
        for lora in graph.loras_in_node(nid):
            key = (lora.name, lora.strength_model, lora.strength_clip)
            if key not in seen:
                seen.add(key)
                loras.append(lora)
    info.loras = loras

    # 模型、VAE、CLIP 跳過
    vae_name = clip_skip = vae_ref = clip_skip_ref = None
    for nid in reach:
        inputs = graph.inputs(nid)
        if model_name is None:
            for key in _MODEL_NAME_KEYS:
                value = graph.resolve(inputs.get(key))
                if _is_lora_name(value):
                    model_name, model_ref = value, graph.locate(nid, key)
                    break
        vae = graph.resolve(inputs.get('vae_name'))
        if vae_name is None and _is_lora_name(vae) and vae.strip().lower() != 'baked vae':
            vae_name, vae_ref = vae, graph.locate(nid, 'vae_name')
        if clip_skip is None:
            # CLIPSetLastLayer 用 stop_at_clip_layer，Efficiency Loader 用 clip_skip，都是 -2 這種負數
            key = 'stop_at_clip_layer' if 'stop_at_clip_layer' in inputs else 'clip_skip'
            layer = _to_float(graph.resolve(inputs.get(key)))
            if layer is not None:
                clip_skip, clip_skip_ref = abs(int(layer)), graph.locate(nid, key)

    # VAELoader 接在採樣器下游的 VAEDecode，往上游找不到，所以改掃整張圖
    if vae_name is None:
        for nid in sorted(graph.nodes, key=_node_sort_key):
            vae = graph.resolve(graph.inputs(nid).get('vae_name'))
            if _is_lora_name(vae) and vae.strip().lower() != 'baked vae':
                vae_name, vae_ref = vae, graph.locate(nid, 'vae_name')
                break

    params: dict[str, Any] = {}
    param_refs: dict[str, Any] = {}
    if primary:
        p = {name: graph.resolve(graph.inputs(nid).get(key), name) for name, (nid, key) in primary.refs.items()}
        for name, value in primary.fixed.items():
            p.setdefault(name, value)
        for name, display in (('steps', 'Steps'), ('sampler_name', 'Sampler'), ('scheduler', 'Schedule type'),
                              ('cfg', 'CFG scale'), ('seed', 'Seed'), ('denoise', 'Denoising strength')):
            if name in primary.refs:
                param_refs[display] = graph.locate(*primary.refs[name], prefer=name)
        size = graph.trace_latent(primary.latent)
        params['Steps'] = p.get('steps')
        params['Sampler'] = p.get('sampler_name')
        params['Schedule type'] = p.get('scheduler')
        params['CFG scale'] = p.get('cfg')
        params['Guidance'] = graph.resolve(graph.guidance, 'guidance')
        param_refs['Guidance'] = graph.guidance_ref
        params['Seed'] = p.get('seed')
        if size:
            params['Size'] = f'{size[0]}x{size[1]}'
            lnid, wkey, hkey, bkey = graph.latent_source(primary.latent)
            param_refs['Size'] = (graph.locate(lnid, wkey, 'width'), graph.locate(lnid, hkey, 'height'))
            param_refs['Batch size'] = graph.locate(lnid, bkey, 'batch_size')
        denoise = _to_float(p.get('denoise'))
        if denoise is not None and denoise != 1.0:
            params['Denoising strength'] = denoise
        if size and _to_float(size[2]) not in (None, 1.0):
            params['Batch size'] = size[2]
    params['Model'] = model_name
    params['VAE'] = vae_name
    params['Clip skip'] = clip_skip
    param_refs['Model'] = model_ref
    param_refs['VAE'] = vae_ref
    param_refs['Clip skip'] = clip_skip_ref
    info.params = {k: v for k, v in params.items() if v is not None and v != ''}
    sources['params'] = {k: v for k, v in param_refs.items() if v}
    info.sources = sources

    # 工作流統計（只顯示）
    if primary:
        info.extra['採樣器節點'] = f'{primary.nid}（{graph.ctype(primary.nid)}）'
    info.extra['API 節點數'] = len(graph.nodes)
    workflow = _try_json(meta.get('workflow'))
    if isinstance(workflow, dict):
        info.extra['工作流節點數'] = len(workflow.get('nodes', []))
        version = (workflow.get('extra') or {}).get('frontendVersion')
        if version:
            info.extra['ComfyUI 前端版本'] = version


# ──────────────────────────────────────────────────────────────
# WebUI / Forge
# ──────────────────────────────────────────────────────────────

# 與 A1111 原始碼相同的參數行規則：支援帶引號、內含逗號的值（例如 Lora hashes）
_RE_PARAM = re.compile(r'\s*(\w[\w \-/]+):\s*("(?:\\.|[^\\"])+"|[^,]*)(?:,|$)')
_RE_LORA_TAG = re.compile(r'<(lora|lyco):([^:>]+)((?::[^:>]*)*)>', re.IGNORECASE)


def _parse_webui(info: GenInfo, text: str) -> None:
    info.source = 'webui'
    info.sources = {'kind': 'webui', 'has_negative_line': 'Negative prompt:' in text}
    lines = text.strip().replace('\r\n', '\n').split('\n')

    params_line = ''
    if lines and len(_RE_PARAM.findall(lines[-1])) >= 3:
        params_line = lines.pop()

    positive, negative, in_negative = [], [], False
    for line in lines:
        if line.strip().startswith('Negative prompt:'):
            in_negative = True
            line = line.strip()[len('Negative prompt:'):].lstrip()
        (negative if in_negative else positive).append(line)
    info.positive = '\n'.join(positive).strip()
    info.negative = '\n'.join(negative).strip()

    for key, value in _RE_PARAM.findall(params_line):
        value = value.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            try:
                value = json.loads(value)
            except ValueError:
                value = value[1:-1]
        info.params[key.strip()] = value


def _merge_prompt_loras(info: GenInfo) -> None:
    """補上提示詞中的 <lora:名稱:權重> 標籤，以及 WebUI 的 Lora hashes 欄位"""
    known = {l.short_name.lower() for l in info.loras}

    for match in _RE_LORA_TAG.finditer(info.positive):
        lora = LoraInfo(match.group(2).strip(), origin='prompt', tag_kind=match.group(1))
        weights = [w for w in match.group(3).split(':')[1:]]
        if weights:
            lora.strength_model = _to_float(weights[0].split('=')[-1])
        if len(weights) > 1:
            lora.strength_clip = _to_float(weights[1].split('=')[-1])
        if lora.short_name.lower() not in known:
            known.add(lora.short_name.lower())
            info.loras.append(lora)

    hashes = info.params.get('Lora hashes')
    if isinstance(hashes, str):
        for item in hashes.split(','):
            name = item.split(':', 1)[0].strip()
            if name and name.lower() not in known:
                known.add(name.lower())
                info.loras.append(LoraInfo(name, origin='hashes'))


# ──────────────────────────────────────────────────────────────
# 主要入口
# ──────────────────────────────────────────────────────────────

def parse_file(path: str) -> GenInfo:
    """解析一張圖片，任何錯誤都會記錄在 GenInfo 裡，不會拋出例外"""
    info = GenInfo(path=os.path.abspath(path))
    try:
        info.file_size = os.path.getsize(path)
        with Image.open(path) as img:
            info.width, info.height = img.size
            info.mode = img.mode
            meta = read_metadata(img)
    except Exception as exc:
        info.source = 'error'
        info.error = f'{type(exc).__name__}: {exc}'
        return info

    info.raw = meta
    record = _try_json(meta.get(EDIT_MARKER_KEY))
    if isinstance(record, dict):
        info.edit_record = record
        info.notes.append(f'這張圖的參數曾用 PNG Info 檢視器編輯過（{record.get("edited_at", "時間不明")}），'
                          '不一定是原始生成參數。')
    try:
        prompt = _try_json(meta.get('prompt'))
        if isinstance(prompt, dict):
            _parse_comfyui(info, meta, prompt)
        elif 'parameters' in meta:
            _parse_webui(info, meta['parameters'])
        elif 'workflow' in meta:
            info.source = 'comfyui'
            info.notes.append('只有 workflow、沒有 API prompt，無法可靠判斷參數，請查看原始中繼資料。')
        elif any(k != EDIT_MARKER_KEY for k in meta):
            info.source = 'generic'
        else:
            info.source = 'none'
        _merge_prompt_loras(info)
    except Exception as exc:
        info.notes.append(f'解析時發生錯誤：{type(exc).__name__}: {exc}')
    return info


# ──────────────────────────────────────────────────────────────
# 輸出格式
# ──────────────────────────────────────────────────────────────

def params_line(info: GenInfo) -> str:
    """WebUI 格式的參數行：Steps: 20, Sampler: euler, ..."""
    keys = [k for k in PARAM_ORDER if k in info.params] + [k for k in info.params if k not in PARAM_ORDER]
    items = []
    for key in keys:
        value = info.params[key]
        if value is None or value == '':
            continue
        text = format_number(value)
        if any(c in text for c in ',:\n"'):
            text = json.dumps(text, ensure_ascii=False)
        items.append(f'{key}: {text}')
    return ', '.join(items)


def loras_text(info: GenInfo) -> str:
    return ' '.join(l.to_tag() for l in info.loras)


def to_webui_text(info: GenInfo) -> str:
    """組成 A1111 WebUI 的標準 PNG Info 文字，ComfyUI 的 LoRA 會補成 <lora:> 標籤"""
    if not info.has_generation_data:
        return ''
    positive = info.positive
    lowered = positive.lower()
    missing = [l.to_tag() for l in info.loras
               if l.origin == 'node' and f'<lora:{l.short_name.lower()}' not in lowered]
    if missing:
        positive = (positive.rstrip() + ', ' if positive.strip() else '') + ' '.join(missing)
    lines = [positive]
    if info.negative:
        lines.append(f'Negative prompt: {info.negative}')
    line = params_line(info)
    if line:
        lines.append(line)
    return '\n'.join(lines)


def raw_text(info: GenInfo) -> str:
    if not info.raw:
        return '（沒有文字中繼資料）'
    out = []
    for key, value in info.raw.items():
        out.append(f'── {key} ──')
        parsed = _try_json(value)
        out.append(json.dumps(parsed, ensure_ascii=False, indent=2) if parsed is not None else value)
        out.append('')
    return '\n'.join(out).rstrip()


def format_report(info: GenInfo) -> str:
    """人看的完整報告（CLI 輸出、匯出 TXT、複製完整報告都用這個）"""
    lines = [f'檔案：{info.filename}', f'路徑：{info.path}', f'來源：{info.source_label}']
    if info.width:
        lines.append(f'圖片：{info.width} × {info.height} 像素，{info.mode}，{format_size(info.file_size)}')
    if info.error:
        lines.append(f'錯誤：{info.error}')
    for note in info.notes:
        lines.append(f'注意：{note}')

    if info.source == 'none':
        lines.append('\n（沒有找到任何文字中繼資料）')
        return '\n'.join(lines)
    if info.source == 'generic':
        lines += ['', '【原始中繼資料】', raw_text(info)]
        return '\n'.join(lines)
    if info.source == 'error':
        return '\n'.join(lines)

    lines += ['', '【正面提示詞】', info.positive or '（無）']
    lines += ['', '【負面提示詞】', info.negative or '（無）']
    if info.loras:
        lines += ['', '【LoRA】']
        for i, lora in enumerate(info.loras, 1):
            weights = []
            if lora.strength_model is not None:
                weights.append(f'model {format_number(lora.strength_model)}')
            if lora.strength_clip is not None:
                weights.append(f'clip {format_number(lora.strength_clip)}')
            suffix = f'（{" / ".join(weights)}）' if weights else ''
            lines.append(f'  {i}. {lora.name}{suffix}')
    if info.params:
        lines += ['', '【生成參數】']
        keys = [k for k in PARAM_ORDER if k in info.params] + [k for k in info.params if k not in PARAM_ORDER]
        for key in keys:
            lines.append(f'  {PARAM_LABELS.get(key, key)}：{format_number(info.params[key])}')
    if info.extra:
        lines += ['', '【其他資訊】']
        for key, value in info.extra.items():
            lines.append(f'  {key}：{format_number(value)}')
    return '\n'.join(lines)


def to_dict(info: GenInfo, include_raw: bool = False) -> dict:
    data = asdict(info)
    data.pop('sources', None)
    if not data.get('edit_record'):
        data.pop('edit_record', None)
    data['filename'] = info.filename
    data['source_label'] = info.source_label
    for lora_dict, lora in zip(data['loras'], info.loras):
        lora_dict.pop('refs', None)
        lora_dict.pop('tag_kind', None)
        lora_dict['short_name'] = lora.short_name
        lora_dict['tag'] = lora.to_tag()
    if include_raw:
        data['raw'] = {k: (_try_json(v) if _try_json(v) is not None else v) for k, v in info.raw.items()}
    else:
        data.pop('raw', None)
    return data


def csv_row(info: GenInfo) -> dict[str, Any]:
    row = {
        '檔案': info.filename,
        '路徑': info.path,
        '來源': info.source_label,
        '正面提示詞': info.positive,
        '負面提示詞': info.negative,
        'LoRA': loras_text(info),
    }
    for key in ('Steps', 'Sampler', 'Schedule type', 'CFG scale', 'Seed', 'Size', 'Model'):
        value = info.params.get(key)
        row[key] = format_number(value) if value is not None else ''
    return row
