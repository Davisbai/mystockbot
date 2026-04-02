import streamlit as st
import pandas as pd
import datetime
import yfinance as yf
import twstock  # 加入 twstock 來支援自動辨識股票名稱與市場屬性
import re

# ⚠️ 確保這裡的 STOCK_GOD 符合你真實的檔案名稱 (注意大小寫)
# 如果你的檔案叫 god_system.py，請把 STOCK_GOD 換成 god_system
from STOCK_GOD import (
    TaiwanStockTradingSystem, 
    AdvancedQuantEngine, 
    YahooMarketScanner, 
    load_watchlist, 
    STOCK_MAP
)

# 網頁基本設定
st.set_page_config(page_title="台股獵手 v2.0", page_icon="🎯", layout="wide")

# ==========================================
# 🗂️ 建立側邊欄選單
# ==========================================
st.sidebar.title("🎯 台股獵手 v2.0")
st.sidebar.markdown("---")
menu = st.sidebar.radio(
    "請選擇功能:",
    (
        "1. 🚀 執行完整策略掃描", 
        "2. 🔎 單股深度診斷", 
        "3. 📈 策略回測", 
        "5. 📊 檢查大盤現況"
    ),
    index=1  # 👈 新增這行：設定預設選擇第二個項目 (選項 2)
)
st.sidebar.markdown("---")
st.sidebar.markdown("---")
st.sidebar.caption(f"系統時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")

# ==========================================
# 1️⃣ 執行完整策略掃描
# ==========================================
if menu == "1. 🚀 執行完整策略掃描":
    st.header("🚀 執行完整策略掃描")
    st.write("整合熱門強勢股、固定觀察名單與現有庫存進行掃描。")
    
    if st.button("開始掃描 (需時約幾十秒)", type="primary"):
        with st.spinner("正在掃描市場與執行演算法，請稍候..."):
            scanner = YahooMarketScanner()
            hot_stocks = scanner.scan()
            DYNAMIC_MAP = {f"{item['code']}.TW": item['name'] for item in hot_stocks}
            STATIC_YF_MAP = {k: v for k, v in STOCK_MAP.items()}
            
            watchlist = load_watchlist()
            WATCHLIST_MAP = {k: v.get("名稱", "") for k, v in watchlist.items()}
            
            COMBINED_MAP = {**STATIC_YF_MAP, **DYNAMIC_MAP, **WATCHLIST_MAP}
            
            system = TaiwanStockTradingSystem(tickers=list(COMBINED_MAP.keys()), start_date="2025-09-01")
            summary, alerts, logs = system.run_analysis()
            
            # 將結果整理成表格顯示在網頁上
            st.subheader("🔔 今日交易提示")
            alert_data = []
            for stock, alert in alerts.items():
                name = COMBINED_MAP.get(stock, "")
                status = "⚪ 觀望"
                
                if alert.get('是否觸發賣出'): 
                    status = "🔴 強制賣出"
                elif alert.get('高檔背離') or alert.get('乖離過大'):
                    status = "🚨 高檔了結"
                elif alert.get('專業起漲'): 
                    status = "🌊 VCP 突破"
                elif alert.get('縮量埋伏'): 
                    status = "🥷 縮量埋伏"
                elif alert['今日評分'] >= 65: 
                    status = "🟢 強力買進"
                
                alert_data.append({
                    "代碼": stock.replace('.TW', '').replace('.TWO', ''),
                    "名稱": name,
                    "收盤價": alert['收盤價'],
                    "月線價": alert['月線價'],
                    "今日評分": alert['今日評分'],
                    "系統判定": status
                })
            
            if alert_data:
                st.dataframe(pd.DataFrame(alert_data), use_container_width=True)
            else:
                st.info("今日無特別訊號。")

# ==========================================
# 2️⃣ 單股深度診斷 (自動辨識名稱與代碼)
# ==========================================
elif menu == "2. 🔎 單股深度診斷":
    st.header("🔎 單股深度診斷 (AI & 量價結構)")
    user_input = st.text_input("請輸入股票代碼或名稱 (例如: 2330, 鈊象, 或 台積電)", "2330")
    
    if st.button("開始診斷", type="primary"):
        user_input = user_input.strip()
        ticker = ""
        stock_name = ""

        # --- 自動辨識與代碼轉換邏輯 ---
        try:
            if user_input.isdigit():
                # 輸入的是數字代碼
                if user_input in twstock.codes:
                    stock_info = twstock.codes[user_input]
                    suffix = ".TW" if "上市" in stock_info.market else ".TWO"
                    ticker = f"{user_input}{suffix}"
                    stock_name = stock_info.name
                else:
                    ticker = f"{user_input}.TW"
                    stock_name = user_input
            else:
                # 輸入的是中文名稱
                found = False
                for code, info in twstock.codes.items():
                    if user_input == info.name:
                        suffix = ".TW" if "上市" in info.market else ".TWO"
                        ticker = f"{code}{suffix}"
                        stock_name = info.name
                        found = True
                        break
                # 若 twstock 沒找到，去 STOCK_MAP 找 (自訂義清單)
                if not found:
                    for k, v in STOCK_MAP.items():
                        if user_input in v:
                            ticker = k
                            stock_name = v
                            found = True
                            break
                if not found:
                    st.error(f"❌ 無法辨識「{user_input}」，請確認代碼或名稱是否正確。")
                    st.stop() # 終止後續執行
                    
        except Exception as e:
            # 萬一 twstock 當機的備用方案
            ticker = f"{user_input}.TW" if user_input.isdigit() else user_input
            stock_name = user_input
            st.warning("⚠️ twstock 模組查詢異常，採用預設 .TW 模式進行搜尋...")

        st.success(f"✅ 已成功識別標的： **{stock_name} ({ticker})**")

        # --- 執行回測與分析 ---
        with st.spinner(f"正在下載 {stock_name} 數據並執行深度診斷..."):
            system = TaiwanStockTradingSystem(tickers=[ticker], start_date="2023-01-01")
            system.fetch_market_data() # 確保大盤資料載入
            summary, alerts, logs = system.run_analysis()
            
            if ticker in alerts:
                alert = alerts[ticker]
                
                # 顯示關鍵指標卡片
                col1, col2, col3, col4 = st.columns(4)
                col1.metric("收盤價", alert['收盤價'])
                col2.metric("月線價", alert['月線價'], f"{(alert['收盤價'] - alert['月線價']):.2f} 價差")
                col3.metric("技術籌碼評分", alert['今日評分'])
                col4.metric("大盤狀態", "✅ 安全" if alert['大盤安全'] else "❌ 跌破月線")
                
                st.markdown("---")
                st.subheader("💡 系統最終判定結果")
                
                # 顯示你加入的精髓訊號狀態
                if alert.get('是否觸發賣出'):
                    if alert.get('高檔背離') or alert.get('乖離過大'):
                        st.error("🚨 **【高檔警報：獲利了結】** 爆量滯漲或乖離過大，主力可能在出貨！")
                    else:
                        st.error("🔴 **【強制賣出 / 停損訊號】** 指標轉弱或破線。")
                elif alert.get('專業起漲'):
                    st.info("🌊 **【VCP 波動收斂突破】** 籌碼高度集中，布林極限壓縮後爆量！(強買)")
                elif alert.get('縮量埋伏'):
                    st.success("🥷 **【縮量黃金：右側埋伏】** 跌不動且成交量極度萎縮，準備發動！(試單)")
                elif alert['今日評分'] >= 65:
                    st.success(f"🟢 **【強力買進】** 綜合評分 {alert['今日評分']} 分，量價與籌碼共振。")
                elif not alert['大盤安全'] and alert['個股原始評分'] >= 75:
                    st.warning(f"⚡ **【無視大盤：獨立強勢】** 個股展現獨立特質，無視大盤逆風。")
                else:
                    st.warning(f"⚪ **【建議觀望】** 動能不足，綜合評分 {alert['今日評分']} 分。")
                        
                if logs.get(ticker):
                    st.markdown("---")
                    st.subheader("📋 近期交易紀錄 (最近五筆)")
                    for log in logs[ticker][-5:]:
                        st.text(log)
            else:
                st.error("❌ 無法從 Yahoo Finance 獲取該股票的歷史資料，可能剛上市或代碼有誤。")

# ==========================================
# 3️⃣ 策略回測
# ==========================================
elif menu == "3. 📈 策略回測":
    st.header("📈 策略回測摘要")
    st.write("分析現有固定觀察名單的歷史勝率與報酬。")
    
    if st.button("執行回測", type="primary"):
        with st.spinner("正在計算歷史回測數據..."):
            STATIC_YF_MAP = {k: v for k, v in STOCK_MAP.items()}
            system = TaiwanStockTradingSystem(tickers=list(STATIC_YF_MAP.keys()), start_date="2024-01-01")
            summary, alerts, logs = system.run_analysis()
            
            st.subheader("📊 回測結果")
            summary_data = []
            for stock, data in summary.items():
                summary_data.append({
                    "代碼": stock.replace('.TW', '').replace('.TWO', ''),
                    "名稱": STATIC_YF_MAP.get(stock, ""),
                    "交易次數": data['總交易天數'],
                    "勝率 (%)": data['勝率 (%)'],
                    "累積報酬 (%)": data['策略累積報酬 (%)']
                })
            st.dataframe(pd.DataFrame(summary_data), use_container_width=True)

# ==========================================
# 5️⃣ 檢查大盤現況
# ==========================================
elif menu == "5. 📊 檢查大盤現況":
    st.header("📊 台股大盤即時診斷 (^TWII)")
    
    if st.button("開始診斷", type="primary"):
        with st.spinner("獲取大盤數據中..."):
            try:
                df = yf.download("^TWII", period="3mo", progress=False, auto_adjust=True)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                df['MA20'] = df['Close'].rolling(window=20).mean()
                df['MA5'] = df['Close'].rolling(window=5).mean()
                
                last_close = float(df['Close'].iloc[-1])
                ma20 = float(df['MA20'].iloc[-1])
                ma5 = float(df['MA5'].iloc[-1])
                prev_close = float(df['Close'].iloc[-2])
                
                change = last_close - prev_close
                pct_change = (change / prev_close) * 100
                dist_to_ma20 = ((last_close - ma20) / ma20) * 100
                
                is_above_ma20 = last_close > ma20
                is_up_trend = ma20 > df['MA20'].iloc[-5] 
                
                col1, col2, col3 = st.columns(3)
                col1.metric("目前指數", f"{last_close:.2f}", f"{change:.2f} ({pct_change:.2f}%)")
                col2.metric("月線 (MA20)", f"{ma20:.2f}", f"乖離率: {dist_to_ma20:.2f}%")
                col3.metric("週線 (MA5)", f"{ma5:.2f}")
                
                st.markdown("---")
                if is_above_ma20 and is_up_trend:
                    st.success("🔥 **多頭強勢** (站上月線且月線標高) \n\n **💡 操作建議:** 適度加碼精選個股")
                elif is_above_ma20 and not is_up_trend:
                    st.warning("⚖️ **高檔震盪** (站上月線但均線走平) \n\n **💡 操作建議:** 挑選獨立強勢股")
                elif not is_above_ma20 and is_up_trend:
                    st.info("🛡️ **支撐測試** (跌破月線但均線仍上揚) \n\n **💡 操作建議:** 觀察是否破底翻")
                else:
                    st.error("❄️ **空頭架構** (跌破月線且均線下彎) \n\n **💡 操作建議:** 嚴控倉位，保留現金")
                    
            except Exception as e:
                st.error(f"無法獲取大盤數據: {e}")