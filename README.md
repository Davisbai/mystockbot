# mystockbot

台股策略掃描與 Streamlit 診斷介面。策略分析與訊號追蹤不代表券商成交。

## 執行

在 repository 目錄安裝相依套件並啟動網頁：

```sh
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

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
- 每次執行分析重新讀取大盤，不沿用其他頁面的短期歷史資料。

成本、可選參考價風控、LINE Secrets 與歷史證據見 [PERFORMANCE_REVIEW.md](PERFORMANCE_REVIEW.md)。
這些修正尚未證實能提高未來報酬。

## 驗證

```sh
python -m unittest test_strategy_performance test_app -v
```

測試包含核心策略邊界、五個頁面、歷史篩選、回測欄位、AI 驗證顯示及失敗回退。
UI 測試以替代行情／模型驗證流程，不對外發送訊息，也不改寫原始紀錄。
