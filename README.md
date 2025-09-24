# 🖼️ PNG 元數據解析器

輕量級工具，用於解析 **AI 生成圖片 (ComfyUI / Stable Diffusion WebUI)** 的 PNG 元數據。支援拖拽與檔案選擇，介面簡潔好用。

---

## ✨ 功能
- 解析 PNG 隱藏元數據  
- 支援 **ComfyUI / WebUI** 格式  
- 顯示提示詞、模型、生成參數  
- 可儲存結果為 `.txt`  
- 深色主題，支援拖拽 (Windows)  

---

## 🛠️ 環境需求
- Python 3.7+  
- 套件: `pillow`, `windnd` (僅 Windows, 拖拽用)

---

## 🚀 使用方式
```bash
git clone https://github.com/yourusername/png-metadata-parser.git
cd png-metadata-parser
pip install -r requirements.txt
python png_parser_v2.py
