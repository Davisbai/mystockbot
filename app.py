import streamlit as st
import pandas as pd
import datetime
import yfinance as yf
import twstock
import re
import os

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

# 自定義 CSS 強化視覺提醒
st.markdown("""
    <style>
    .stMetric { background-color: #f8f9fa; padding: 15px; border-radius: 12px; border: 1px solid #e9ecef; }
    .stAlert { border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 🚀 優化點：初始化大盤快取狀態 ---
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
    st.write("整合熱門強勢股、固定觀察名單與現有庫存進行掃描。")
    
    if st.button("開始掃描 (需時約幾十秒)", type="primary"):
        with st.spinner("正在掃描市場與執行演算法..."):
            scanner = YahooMarketScanner()
            hot_stocks = scanner.scan()
            DYNAMIC_MAP = {f"{item['code']}.TW": item['name'] for item in hot_stocks}
            STATIC_YF_MAP = {k: v for k, v in STOCK_MAP.items()}
            
            watchlist = load_watchlist()
            WATCHLIST_MAP = {k: v.get("名稱", "") for k, v in watchlist.items()}
            COMBINED_MAP = {**STATIC_YF_MAP, **DYNAMIC_MAP, **WATCHLIST_MAP}
            
            system = TaiwanStockTradingSystem(tickers=list(COMBINED_MAP.keys()), start_date="2025-01-01")
            
            # --- 優化處：複用大盤快取 ---
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
    st.header("🔎 單股深度診斷 (主力洗盤與噴發預警)")
    
    with st.expander("💡 籌碼與技術型態小百科：如何看懂主力意圖？"):
        st.markdown("""
        **【洗盤階段特徵】**
        * **假跌破 (Fake Break)：** 刻意殺破支撐位（如月線、前低）誘發恐慌賣壓，若能迅速收回即為強勢洗盤。
        * **縮量窒息 (Quiet Wash)：** 股價回檔但量能極降（不到均量60%），代表主力鎖碼未出，僅洗發浮額。
        
        **【準備發動特徵】**
        * **布林極致壓縮 (Squeeze)：** 股價波動縮小到極限，代表多空即將決裂，通常是變盤前兆。
        * **長期沉寂量增 (Quiet Breakout)：** 股價長期低迷（橫盤震幅<10%），今日突然量比急增，是起漲訊號。
        * **均線糾結：** 短中長期均線黏合，股價帶量突破將展開大行情。
        """)

    user_input = st.text_input("請輸入股票代碼或名稱 (例如: 2330, 鈊象, 或 台積電)", "2330")
    
    if st.button("開始診斷", type="primary"):
        user_input = user_input.strip()
        ticker = ""
        stock_name = ""

        # --- 自動辨識邏輯 ---
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

        # --- 執行分析 ---
        with st.spinner("正在進行大數據掃描、籌碼解析與動能計算..."):
            system = TaiwanStockTradingSystem(tickers=[ticker], start_date="2024-01-01")
            
            if st.session_state.cached_market_data is None:
                system.fetch_market_data()
                st.session_state.cached_market_data = system.market_data
            else:
                system.market_data = st.session_state.cached_market_data
                
            summary, alerts, logs = system.run_analysis()
            
            if ticker in alerts:
                alert = alerts[ticker]
                stock_logs = logs.get(ticker, [])
                
                # --- [❗唯一修改處：顯示抓取日期] ---
                st.info(f"📅 數據日期: **{alert.get('日期', 'N/A')}**")
                display_price = alert.get('收盤價', 0)
                # --- 儀表板 ---
                c1, c2, c3, c4 = st.columns(4)
                #c1.metric("收盤價", f"{alert['收盤價']:.2f}")
                c1.metric("收盤價", f"{display_price:.2f}")
                c2.metric("月線 (MA20)", f"{alert['月線價']:.2f}", f"{(alert['收盤價']-alert['月線價']):.2f}")
                c3.metric("技術籌碼評分", f"{alert['今日評分']}分")
                c4.metric("大盤狀態", "✅ 安全" if alert['大盤安全'] else "❌ 警戒")

                st.markdown("---")
                st.subheader("🕵️ 主力行為與潛在噴發偵測")
                
                col_l, col_r = st.columns(2)
                
                with col_l:
                    st.markdown("### 🏹 主力洗盤辨識")
                    if alert.get('高檔背離') or alert.get('乖離過大'):
                        st.error("🚨 **警告：【誘多出貨風險】**\n\n股價雖處高檔，但動能背離或乖離過大。主力可能利用利多消息掩護出貨，切勿追高。")
                    elif alert.get('假跌破'):
                        st.success("🛡️ **偵測到【假跌破真拉抬】**\n\n近期刻意殺破支撐後迅速收回。這代表主力洗盤成功，下方籌碼已換手，後市看好。")
                    elif alert.get('縮量埋伏'):
                        st.info("🎭 **偵測到【縮量洗盤】**\n\n股價回落且量能極度萎縮。主力正在壓低吃貨，這是標準的洗盤特徵，適合分批試單。")
                    else:
                        st.write("📊 走勢符合正常軌跡，目前無極端的洗盤或出貨特徵。")

                with col_r:
                    st.markdown("### 🚀 變盤與攻擊預警")
                    if alert.get('沉寂發動'):
                        st.warning("⚡ **高度關注：【橫盤蓄勢即將變盤】**\n\n股價長久沉寂後今日突然爆量突破。這是標準的「沉寂變盤」起跑點，漲勢動能極強！")
                    elif alert.get('沉寂多時'):
                        st.info("🧘 **標的特徵：【橫盤沉寂中】**\n\n股價已長時間處於窄幅震盪區則（震幅 < 10%）。這是在蹲下準備跳躍，建議先加入觀察，一旦帶量突破將是噴發。")
                    elif alert.get('布林壓縮') or alert.get('布林極致壓縮'):
                        st.warning("🗜️ **高度關注：【布林極致壓縮中】**\n\n股價波動降到極限。這是暴風雨前的寧靜，一旦帶量突破布林上軌，將啟動奔漲行情。")
                    elif alert.get('專業起漲'):
                        st.success("🌊 **攻擊發起：【VCP 波動收斂突破】**\n\n經過壓縮後，今日正式帶量突破壓力區間。主力攻擊意圖強烈，適合順勢操作。")
                    else:
                        st.write("💡 動能持續醞釀中，建議耐心等待明確的帶量突破訊號。")

                st.markdown("---")
                st.subheader("📋 系統深度診斷紀錄")
                if stock_logs:
                    for log in stock_logs[-5:]:
                        st.text(f"• {log}")
                else:
                    st.write("今日無特別系統紀錄。")
            else:
                st.error("❌ 無法獲取該股票的歷史資料，請確認代碼是否正確或剛上市。")

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
            
            # --- 優化處：複用大盤快取 ---
            if st.session_state.cached_market_data is None:
                system.fetch_market_data()
                st.session_state.cached_market_data = system.market_data
            else:
                system.market_data = st.session_state.cached_market_data
                
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
                df = yf.download("^TWII", period="3mo", progress=False, auto_adjust=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                df['MA20'] = df['Close'].rolling(window=20).mean()
                df['MA5'] = df['Close'].rolling(window=5).mean()
                
                last_close = float(df['Close'].iloc[-1])
                ma20 = float(df['MA20'].iloc[-1])
                ma5 = float(df['MA5'].iloc[-1])
                prev_close = float(df['Close'].iloc[-2])
                
                # --- 同步更新系統快取 ---
                st.session_state.cached_market_data = df.assign(Market_MA20=df['MA20'], Market_OK=df['Close'] > df['MA20'])

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
                    st.success("🔥 **多頭強勢** (站上月線且月線走揚) \n\n **💡 操作建議:** 適度加碼精選個股")
                elif is_above_ma20 and not is_up_trend:
                    st.warning("⚖️ **高檔震盪** (站上月線但均線走平) \n\n **💡 操作建議:** 挑選獨立強勢股")
                elif not is_above_ma20 and is_up_trend:
                    st.info("🛡️ **支撐測試** (跌破月線但均線仍上揚) \n\n **💡 操作建議:** 觀察是否出現假跌破破底翻")
                else:
                    st.error("❄️ **空頭架構** (跌破月線且均線下彎) \n\n **💡 操作建議:** 嚴控倉位，保留現金")
                    
            except Exception as e:
                st.error(f"無法獲取大盤數據: {e}")