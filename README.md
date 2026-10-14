# mystockbot

台股策略掃描與 Streamlit 診斷介面。策略分析與訊號追蹤不代表券商成交。

## 執行

在 repository 目錄啟動網頁：

```sh
python run_app.py
```

啟動器使用 `.venv-app` 專用環境，第一次會建立環境並安裝相依套件；需可連線至套件來源。
既有環境會先檢查 Streamlit 版本及核心模組，再啟動伺服器，不更動系統 Python。
瀏覽器開啟 `http://localhost:8501`。停止時在終端機按 Ctrl+C。
可用 `python run_app.py --check` 只檢查環境，或 `python run_app.py --port 8502` 更換連接埠。

若使用系統舊版 Streamlit，可能在載入時出現 `Descriptors cannot be created directly`
（Streamlit／protobuf 不相容）。請改用上述啟動器；不用在系統環境降版 protobuf。
Codespaces 也使用同一個專用環境；更新設定後執行 Rebuild Container，於 Ports 開啟 8501。
Streamlit Cloud 的入口仍為 `app.py`，平台需從根目錄的 `requirements.txt` 安裝相依套件。

網頁選單：完整掃描、單股診斷、規則策略回測、歷史追蹤績效、大盤診斷。
歷史追蹤頁直接讀取 `line_push_log.txt` 與 `long_term_watchlist.json`，可篩選目前監控、
最少觀察日數，下載完整分析 JSON。無需下載新行情。

終端機掃描使用 `python STOCK_GOD.py`；離線追蹤分析使用 `python analyze_push_history.py`。
GitHub Actions 僅執行終端機掃描，不會啟動網頁。

## 解讀結果

- 規則回測採收盤訊號、次日開盤成交假設，含研究成本；勝率只計已平倉交易。
  持倉交易日數與完成交易筆數分開列出，並顯示最大回撤及未平倉狀態。
- AI 正類機率與時序留出驗證指標分開顯示；模型機率不等於交易勝率。
  GMM 分群編號沒有固定多空意義。
- 歷史追蹤使用推播參考價；最後觀察不等於出場，觀察缺漏可能低估回撤。
  缺乏股數及完整成交資訊，不能當作投資組合績效。
- 單股診斷沿用 BUY／SELL 同步訊號監控清單的行為，會寫入本機 JSON，
  不送出券商訂單，也不發送 LINE。既有加入日期及參考成本會保留，更新觀察高點。
  完整掃描頁只顯示結果，不新增或移除清單。
- 行情／規則／TD/RL 與 AI 診斷結果暫存最多 5 分鐘，基本面最多 1 小時。
  行情快取依股票清單、起始日期與大盤區分，不混用其他頁面的短期資料；
  監控清單不快取，每次重新讀取。可按側欄「清除分析快取」後再次診斷。
- 單股診斷顯示行情與 TD/RL、AI 模型、基本面三個階段。
  TD/RL 預先計算歷史狀態與 reward，保留原本 epochs 與更新順序。
  同機 800 筆固定合成資料測量約由 11.29 秒降至 0.53 秒，輸出一致；
  此數字僅涵蓋 TD/RL 計算，不代表整個網頁或實際行情下載時間。

成本、可選參考價風控、LINE Secrets 與歷史證據見 [PERFORMANCE_REVIEW.md](PERFORMANCE_REVIEW.md)。
這些修正尚未證實能提高未來報酬。

## 進場通知與模型修正（2026-10-14）

`entry_watchlist.json` 是候選觀察清單，初始包含國喬、台化；與有成本紀錄的
`long_term_watchlist.json` 分開。完整掃描會持續檢查候選股，不依賴當天熱門股榜。

通知分成三類，優先列於 LINE 日報及網頁：

- `ENTRY`：模型與既有規則確認進場，法人資料完整、日線完成，且無進場風控阻擋。
- `SETUP`：既有趨勢／型態出現轉強，或資料、模型尚待確認；只是預警，不當作 BUY。
- `BLOCKED`：模型偏買，但既有風控禁止進場，明確列出阻擋原因。

通知包含日期、收盤參考價、觸發條件、原始模型／最終判定、Q 值與樣本支持。
月線×98% 僅為既有規則參考，不能保證成交；未完成日線不產生確認進場。
同股票、交易日及通知層級只確認一次；預警可升級為進場。LINE 完整傳送成功才記為已通知，
失敗保留待傳，但過期或已反轉的進場通知不會當作當前機會補送。

排程維持工作日台北時間 19:00；這次沒有增加盤中監控。網頁只顯示通知，不發送 LINE。
通知狀態保存在 `entry_signal_state.json`，GitHub Actions 與日誌一同保存。

法人資料修正支援 FinMind 英文／中文名稱，缺失保留為缺失，不補成零或沿用昨日買賣超。
TD/RL 各正式入口統一從 `strategy_config.py` 的 `2023-01-01` 訓練，快取包含模型版本。
Q 偏好指數不是校準勝率；模型原判、仲裁覆寫原因及資料狀態分開顯示。
模型樣本不足、法人資料不完整或日線未完成時，暫緩確認新的 BUY；原有持倉風控仍可退出。

對照比較未支持全面放寬五日乖離退出，因此維持原預設政策。
研究模式 `TaiwanStockTradingSystem(..., extension_exit_mode='warning')` 僅供比較，
不會由每日排程或網頁預設啟用。沒有為兩檔案例調低買進門檻或改由七法則接管。
詳細數據與限制見 [調整驗證報告](diagnostics/tdrl_20261014/ADJUSTMENTS.md)。

## 驗證

```sh
python -m unittest test_strategy_performance test_app test_tdrl_audit test_entry_notifications -v
```

測試包含核心策略邊界、五個頁面、歷史篩選、回測欄位、AI 驗證顯示及失敗回退。
UI 測試以替代行情／模型驗證流程，不對外發送訊息，也不改寫原始紀錄。
