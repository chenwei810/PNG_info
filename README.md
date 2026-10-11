# PNG Info 檢視器

讀取 AI 生成圖片裡的生成參數：正面／負面提示詞、LoRA、模型、Seed、Steps、CFG、採樣器等。
支援 ComfyUI、Stable Diffusion WebUI / Forge，完全離線執行。

## 檔案結構

| 檔案 | 用途 |
|---|---|
| `pnginfo_core.py` | 解析核心（不含介面），CLI 和 GUI 共用 |
| `png_info_parser.py` | GUI（tkinter + tkinterdnd2） |
| `main.py` | 命令列版 |
| `build.py` | 打包成 macOS `.app` |

## 在 Mac 上安裝

建議使用 **python.org 的 Python 安裝檔**（3.12 或 3.13）。Homebrew 的 Python 也可以（tkinterdnd2 0.6.4 起支援 Tk 9）。
不要用 macOS 內建的 `/usr/bin/python3`，它的 Tk 太舊，拖放無法使用。

```bash
cd 專案資料夾
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python png_info_parser.py --check    # 確認拖放功能正常
```

## 執行

```bash
python png_info_parser.py            # GUI
python main.py 圖片.png               # 命令列：完整報告
python main.py 資料夾/ --webui         # 命令列：WebUI 格式
python main.py 資料夾/ --json > out.json
```

## 打包成 .app

```bash
python build.py              # 輸出到 dist/PNG Info Viewer.app
python build.py --install    # 同時複製到「應用程式」資料夾
```

- 必須在 Mac 上打包；M3 / M4 都是 arm64，打包一次兩台都能用。
- 自己打包、自己使用不需要簽章。從別台電腦複製過去的話，第一次請按右鍵 →「打開」。
- 想要自訂圖示，把 `icon.icns` 放在專案根目錄再打包即可。

## 使用方式

- 把圖片或資料夾拖進視窗任何位置（可一次拖多張）
- 打包成 `.app` 後，也可以拖到 Dock 圖示上，或在 Finder 按右鍵 →「打開方式」
- 每個區塊都有「複製」按鈕；在 LoRA 或參數清單上連點兩下，可只複製那一列
- 「複製 WebUI 格式」可以直接貼到 A1111 / Forge 的 PNG Info 使用

| 快捷鍵 | 功能 |
|---|---|
| ⌘O / ⇧⌘O | 加入圖片 / 加入資料夾 |
| ⌘1 / ⌘2 | 複製正面 / 負面提示詞 |
| ⌘3 / ⌘4 | 複製 LoRA / 生成參數 |
| ⇧⌘C | 複製 WebUI 格式 |
| ⌘E | 匯出目前圖片為 TXT |

## 疑難排解

- **拖放沒反應**：執行 `python png_info_parser.py --check`，它會顯示真正的原因和修正指令。
  最常見的是 tkinterdnd2 太舊或沒裝在目前的 venv 裡，執行 `python -m pip install -U tkinterdnd2` 即可。
  拖放失敗時，程式開啟時也會跳出提示視窗，並把修正指令複製到剪貼簿。
- **.app 打不開**：在終端機執行 `"dist/PNG Info Viewer.app/Contents/MacOS/PNGInfoViewer"`，可以看到錯誤訊息。
- **圖片沒有資料**：從社群網站、聊天軟體下載或截圖的圖片通常已經沒有中繼資料，請使用原始輸出檔。