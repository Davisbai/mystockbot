---
name: hand-drawn-infographic
description: 把任何主題／文章／影片重點／財報數據，生成「日系手繪筆記圖」資訊圖表（繁體中文，水彩＋鋼筆線稿，類似 ChatGPT 手繪風）。當使用者說「生成手繪圖」「手繪筆記圖」「做成資訊圖」「infographic」「nano banana 畫圖」時使用。使用 Gemini 圖像模型（預設 gemini-nano-banana-2.1，失敗自動降級）。
---

# 手繪筆記圖 skill

## 流程
1. **整理內容**：把使用者給的主題／連結／數據整理成條列。總字數控制在 150–250 個中文字；數字只放重點。
2. **填模板**：複製 `template.md`，把每一格要寫的字填進去（標題、副標、人物／主視覺、2–4 張數據卡、流程、表格、觀察指標、結論、結語）。
3. **存成 prompt 檔**後執行：
   ```
   python3 .claude/skills/hand-drawn-infographic/scripts/generate.py prompt.txt out.png [--aspect 16:9] [--model MODEL]
   ```
4. 用 SendUserFile 把 PNG 傳給使用者，並提醒中文字可能有錯字。
5. **局部修字**：用 `--edit out.png` 帶原圖，prompt 寫「只把某處的『X』改成『Y』，其他完全不變」，輸出新檔；不要整張重畫。

## 規則
- 模型順序（自動降級）：`gemini-nano-banana-2.1` → `gemini-3.1-flash-image` → `gemini-3-pro-image` → `gemini-2.5-flash-image`。可用 `--model` 指定；有更新的模型時，用 ListModels 查出後置於最前面。
- 憑證由 proxy 注入，`x-goog-api-key` 用假值即可，不要向使用者索取金鑰。
- prompt 一定要加「所有文字完全照以下內容，不要自行增減」。
- 使用者摘要偏好：精簡、不要自動帶入其工作背景；影片整理給大意＋重點，不要逐字稿。
