# PNG Info 檢視器

讀取 AI 生成圖片裡的生成參數：正面／負面提示詞、LoRA、模型、Seed、Steps、CFG、採樣器等，
也可以修改 PNG 裡的參數並另存新檔。支援 ComfyUI、Stable Diffusion WebUI / Forge，完全離線執行。

## 檔案結構

| 檔案 | 用途 |
|---|---|
| `pnginfo_core.py` | 解析核心（不含介面），CLI 和 GUI 共用 |
| `pnginfo_editor.py` | 改寫 PNG 參數、移除中繼資料、批次取代（不含介面） |
| `png_info_parser.py` | GUI 主視窗（tkinter + tkinterdnd2） |
| `edit_dialogs.py` | GUI 的編輯視窗與批次取代視窗 |
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
| ⌘E | 編輯提示詞與參數 |
| ⌘F | 批次取代提示詞 |
| ⇧⌘E | 匯出目前圖片為 TXT（v3.1 以前是 ⌘E） |
| ⌘S（編輯視窗中） | 另存新檔 |

## 編輯圖片裡的參數（只支援 PNG，一律另存新檔）

選好圖片後按「編輯…」、⌘E，或在清單上連點兩下。編輯視窗有三個分頁：

- **提示詞**：ComfyUI 的每個文字框對應工作流中的一個節點（例如「節點 8 · CLIPTextEncode」）；
  提示詞由字串串接節點組成時，每一段會分開列出。原本空白的負面提示詞也可以直接填入。
- **LoRA**：名稱、Model 權重、CLIP 權重。WebUI 圖片的修改會套用到提示詞裡的 `<lora:名稱:權重>` 標籤。
- **生成參數**：步數、採樣器、排程器、CFG、種子、尺寸、批次、去噪強度、模型、VAE、CLIP 跳過等。
  WebUI 圖片把欄位清空就會移除該參數。

改過的欄位會用橘色圓點標示，每個欄位都能單獨還原。按「另存新檔…」後：

- 預設檔名是 `原檔名_edited.png`，**不能覆蓋原圖**。
- 只替換 PNG 的文字區塊，**影像資料逐位元組原樣複製，畫面完全不變**。
- ComfyUI 圖片會**同時更新 API prompt 與 workflow**，拖回 ComfyUI 看到的也是新值
  （包括接到 Primitive 節點的欄位）。少數自訂節點對應不到時，存檔後會列出是哪些欄位。
- 存檔前會先寫到暫存檔，確認影像資料相同、重新解析讀得到新值才會完成；任何一項不符就取消，不留下檔案。
- 新檔會記錄「由 PNG Info 檢視器編輯過」與時間，之後打開時會顯示提示，避免誤以為是原始生成參數。
  原本的參數**不會**保留在新檔裡。

工作流有多個採樣器（例如 Hires fix）時，生成參數只會修改第一階段；提示詞與 LoRA 通常是各階段共用的。
被略過（bypass）的節點不會出現在生成參數裡，也不會被修改。

### 批次取代（⌘F）

在選取的圖片或清單中全部圖片的提示詞裡尋找並取代文字，可選擇正面／負面、是否區分大小寫。
先按「預覽」看每張圖有幾處符合，再按「執行取代」，結果會存成各自的 `_edited.png`。
`<lora:…>` 標籤不會被取代，避免改壞 LoRA 檔名。

### 移除中繼資料

「編輯」選單 →「另存為無中繼資料的圖片…」，另存一張不含提示詞與工作流的 `_clean.png`，分享時使用。
色彩描述檔等影響顯示的資料會保留，畫面完全相同。

## 疑難排解

- **拖放沒反應**：執行 `python png_info_parser.py --check`，它會顯示真正的原因和修正指令。
  最常見的是 tkinterdnd2 太舊或沒裝在目前的 venv 裡，執行 `python -m pip install -U tkinterdnd2` 即可。
  拖放失敗時，程式開啟時也會跳出提示視窗，並把修正指令複製到剪貼簿。
- **.app 打不開**：在終端機執行 `"dist/PNG Info Viewer.app/Contents/MacOS/PNGInfoViewer"`，可以看到錯誤訊息。
- **圖片沒有資料**：從社群網站、聊天軟體下載或截圖的圖片通常已經沒有中繼資料，請使用原始輸出檔。
