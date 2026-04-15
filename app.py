import streamlit as st
import pandas as pd
import datetime
import yfinance as yf
import twstock
import re
import os

# 設定 yfinance 緩存路徑，避免在部署環境出現權限問題
yf.set_tz_cache_location("/tmp/py-yfinance")

# ⚠️ 確保 STOCK_GOD.py 在同目錄下
try:
    from STOCK_GOD import (
        TaiwanStockTradingSystem, 
        AdvancedQuantEngine, 
        YahooMarketScanner, 
        load_watchlist, 
        STOCK_MAP
    )
except ImportError:
    st.error("❌ 找不到 STOCK_GOD 模組，請確保 STOCK_GOD.py 在正確目錄")

# ==========================================
# 🎨 網頁基本設定與 CSS 樣式
# ==========================================
st.set_page_config(page_title="台股獵手 v2.0 - 專業版", page_icon="🎯", layout="wide")

st.markdown("""
    <style>
    .stMetric { background-color: #f8f9fa; padding: 15px; border-radius: 12px; border: 1px solid #e9ecef; }
    .stAlert { border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 🚀 優化點：初始化全域大盤快取狀態 ---
if 'cached_market_data' not in st.session_state:
    st.session_state.cached_market_data = None

# ==========================================
# 🗂️ 側邊欄選單
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
    index=1
)
st.sidebar.markdown("---")
tz = datetime.timezone(datetime.timedelta(hours=8))
st.sidebar.caption(f"📅 系統時間: {datetime.datetime.now(tz).strftime('%Y-%m-%d %H:%M')}")

# ==========================================
# 1️⃣ 執行完整策略掃描
# ==========================================
if menu == "1. 🚀 執行完整策略掃描":
    st.header("🚀 執行完整策略掃描")
    st.write("整合熱門強勢股、固定觀察名單與現有庫存進行掃描並同步 LINE 推播。")
    
    if st.button("開始全自動掃描", type="primary"):
        with st.spinner("正在掃描市場與執行演算法..."):
            scanner = YahooMarketScanner()
            hot_stocks = scanner.scan()
            DYNAMIC_MAP = {f"{item['code']}.TW": item['name'] for item in hot_stocks}
            STATIC_YF_MAP = {k: v for k, v in STOCK_MAP.items()}
            
            watchlist = load_watchlist()
            WATCHLIST_MAP = {k: v.get("名稱", "") for k, v in watchlist.items()}
            COMBINED_MAP = {**STATIC_YF_MAP, **DYNAMIC_MAP, **WATCHLIST_MAP}
            
            system = TaiwanStockTradingSystem(tickers=list(COMBINED_MAP.keys()), start_date="2025-01-01")
            
            # --- 套用快取邏輯 ---
            if st.session_state.cached_market_data is None:
                system.fetch_market_data()
                st.session_state.cached_market_data = system.market_data
            else:
                system.market_data = st.session_state.cached_market_data
                
            summary, alerts, logs = system.run_analysis()
            
            st.subheader("🔔 今日交易提示")
            alert_data = []
            for stock, alert in alerts.items():
                name = COMBINED_MAP.get(stock, "")
                status = "⚪ 觀望"
                
                if alert.get('是否觸發賣出'): status = "🔴 強制賣出"
                elif alert.get('高檔背離') or alert.get('乖離過大'): status = "🚨 高檔了結"
                elif alert.get('沉寂發動'): status = "⚡ 沉寂噴發"
                elif alert.get('專業起漲'): status = "🌊 VCP 突破"
                elif alert.get('縮量埋伏'): status = "🥷 縮量埋伏"
                elif alert.get('假跌破'): status = "🛡️ 假摔洗盤"
                elif alert['今日評分'] >= 65: status = "🟢 強力買進"
                
                alert_data.append({
                    "代碼": stock.replace('.TW', '').replace('.TWO', ''),
                    "名稱": name,
                    "收盤價": alert['收盤價'],
                    "今日評分": alert['今日評分'],
                    "系統判定": status
                })
            
            if alert_data:
                st.dataframe(pd.DataFrame(alert_data), use_container_width=True)
            else:
                st.info("今日無特別訊號。")

# ==========================================
# 2️⃣ 單股深度診斷
# ==========================================
elif menu == "2. 🔎 單股深度診斷":
    st.header("🔎 單股深度診斷 (主力行為分析)")
    
    user_input = st.text_input("請輸入股票代碼或名稱 (例如: 2330, 2454, 或 台積電)", "2330")
    
    if st.button("啟動 AI 診斷", type="primary"):
        user_input = user_input.strip()
        ticker = ""
        stock_name = ""

        # 自動辨識代碼與市場
        try:
            if user_input.isdigit():
                if user_input in twstock.codes:
                    info = twstock.codes[user_input]
                    ticker = f"{user_input}.TW" if "上市" in info.market else f"{user_input}.TWO"
                    stock_name = info.name
                else: ticker, stock_name = f"{user_input}.TW", user_input
            else:
                found = False
                for code, info in twstock.codes.items():
                    if user_input == info.name:
                        ticker = f"{code}.TW" if "上市" in info.market else f"{code}.TWO"
                        stock_name = info.name
                        found = True; break
                if not found:
                    for k, v in STOCK_MAP.items():
                        if user_input in v: ticker, stock_name = k, v; found = True; break
                if not found: st.error(f"❌ 無法辨識「{user_input}」"); st.stop()
        except Exception: 
            ticker, stock_name = f"{user_input}.TW", user_input

        st.success(f"✅ 已鎖定標的： **{stock_name} ({ticker})**")

        # --- 🚀 優化點：連續查詢時跳過大盤抓取 ---
        with st.spinner("正在讀取數據並執行策略演算法..."):
            system = TaiwanStockTradingSystem(tickers=[ticker], start_date="2024-01-01")
            
            if st.session_state.cached_market_data is None:
                st.write("🔄 正在獲取今日最新大盤數據...")
                system.fetch_market_data()
                st.session_state.cached_market_data = system.market_data
            else:
                st.write("⚡ 使用大盤快取數據，加速分析中...")
                system.market_data = st.session_state.cached_market_data
            
            summary, alerts, logs = system.run_analysis()
            
            if ticker in alerts:
                alert = alerts[ticker]
                stock_logs = logs.get(ticker, [])
                
                # 儀表板
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("收盤價", f"{alert['收盤價']:.2f}")
                c2.metric("月線 (MA20)", f"{alert['月線價']:.2f}", f"{(alert['收盤價']-alert['月線價']):.2f}")
                c3.metric("技術籌碼評分", f"{alert['今日評分']}分")
                c4.metric("大盤狀態", "✅ 安全" if alert['大盤安全'] else "❌ 警戒")

                st.markdown("---")
                col_l, col_r = st.columns(2)
                
                with col_l:
                    st.markdown("### 🏹 主力洗盤辨識")
                    if alert.get('高檔背離') or alert.get('乖離過大'):
                        st.error("🚨 **誘多出貨風險**：股價高檔背離。")
                    elif alert.get('假跌破'):
                        st.success("🛡️ **假跌破真拉抬**：洗盤完成。")
                    elif alert.get('縮量埋伏'):
                        st.info("🎭 **縮量洗盤**：主力壓低吃貨中。")
                    else: st.write("📊 目前無極端洗盤特徵。")

                with col_r:
                    st.markdown("### 🚀 變盤與攻擊預警")
                    if alert.get('沉寂發動'): st.warning("⚡ **橫盤蓄勢變盤**：今日爆量突破。")
                    elif alert.get('沉寂多時'): st.info("🧘 **橫盤沉寂中**：準備蹲低跳遠。")
                    elif alert.get('專業起漲'): st.success("🌊 **VCP 突破**：攻擊正式發起。")
                    else: st.write("💡 動能穩定醞釀中。")

                st.markdown("---")
                st.subheader("📋 系統深度診斷紀錄")
                for log in stock_logs[-5:]: st.text(f"• {log}")
            else:
                st.error("❌ Yahoo Finance 暫時無法獲取該股數據。")

# ==========================================
# 3️⃣ 策略回測
# ==========================================
elif menu == "3. 📈 策略回測":
    st.header("📈 策略回測摘要 (固定監控清單)")
    
    if st.button("開始回測"):
        with st.spinner("分析歷史勝率中..."):
            STATIC_YF_MAP = {k: v for k, v in STOCK_MAP.items()}
            system = TaiwanStockTradingSystem(tickers=list(STATIC_YF_MAP.keys()), start_date="2024-01-01")
            
            if st.session_state.cached_market_data is None:
                system.fetch_market_data()
                st.session_state.cached_market_data = system.market_data
            else:
                system.market_data = st.session_state.cached_market_data

            summary, alerts, logs = system.run_analysis()
            
            df_summary = pd.DataFrame([
                {
                    "代碼": s.replace('.TW', ''),
                    "名稱": STATIC_YF_MAP.get(s, ""),
                    "勝率 (%)": d['勝率 (%)'],
                    "累積報酬 (%)": d['策略累積報酬 (%)']
                } for s, d in summary.items()
            ])
            st.dataframe(df_summary, use_container_width=True)

# ==========================================
# 5️⃣ 檢查大盤現況
# ==========================================
elif menu == "5. 📊 檢查大盤現況":
    st.header("📊 台股大盤即時診斷 (^TWII)")
    
    if st.button("執行大盤診斷"):
        # 大盤現況不使用舊快取，確保是最新的
        with st.spinner("獲取最新數據中..."):
            try:
                df = yf.download("^TWII", period="3mo", progress=False, auto_adjust=True)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                df['MA20'] = df['Close'].rolling(window=20).mean()
                last_close = float(df['Close'].iloc[-1])
                ma20 = float(df['MA20'].iloc[-1])
                change = last_close - float(df['Close'].iloc[-2])
                
                # 更新快取
                st.session_state.cached_market_data = df.assign(Market_MA20=df['MA20'], Market_OK=df['Close'] > df['MA20'])

                col1, col2 = st.columns(2)
                col1.metric("目前指數", f"{last_close:.2f}", f"{change:.2f}")
                col2.metric("月線位置", f"{ma20:.2f}", f"乖離: {((last_close-ma20)/ma20*100):.2f}%")
                
                if last_close > ma20:
                    st.success("🔥 大盤站上月線，多頭架構安全。")
                else:
                    st.error("❄️ 大盤跌破月線，操作需趨於保守。")
            except Exception as e:
                st.error(f"錯誤: {e}")