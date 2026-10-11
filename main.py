#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py — PNG Info 命令列版

用法：
  python main.py 圖片.png                 # 顯示完整報告
  python main.py 資料夾/ 另一張.png        # 可以一次給多個檔案或資料夾
  python main.py 圖片.png --webui         # 輸出 WebUI 格式（可直接貼到 A1111 / Forge 的 PNG Info）
  python main.py 資料夾/ --json > out.json
"""

import argparse
import json
import sys

import pnginfo_core as core


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='讀取 AI 生成圖片中的生成參數（ComfyUI / WebUI / Forge）')
    parser.add_argument('paths', nargs='+', help='圖片檔案或資料夾')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--webui', action='store_true', help='輸出 WebUI 格式')
    group.add_argument('--json', action='store_true', help='輸出 JSON')
    parser.add_argument('--raw', action='store_true', help='JSON 輸出時包含原始中繼資料')
    args = parser.parse_args(argv)

    files = core.expand_paths(args.paths)
    if not files:
        print('找不到支援的圖片（PNG / JPG / WebP）', file=sys.stderr)
        return 1

    infos = [core.parse_file(f) for f in files]

    if args.json:
        data = [core.to_dict(i, include_raw=args.raw) for i in infos]
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    for index, info in enumerate(infos):
        if index:
            print('\n' + '═' * 60 + '\n')
        if args.webui:
            print(f'# {info.filename}')
            print(core.to_webui_text(info) or f'（{info.source_label}，沒有生成參數）')
        else:
            print(core.format_report(info))
    return 0


if __name__ == '__main__':
    sys.exit(main())
