import streamlit as st
import pandas as pd
import datetime
import yfinance as yf
import twstock
import re

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
    st.error("❌ 找不到 STOCK_GOD 模組，請檢查檔案名稱是否為 STOCK_GOD.py")

# ==========================================
# 🎨 網頁基本設定
# ==========================================
st.set_page_config(page_title="台股獵手 v2.0 - 專業版", page_icon="🎯", layout="wide")

# 自定義 CSS 讓警告更加顯眼
st.markdown("""
    <style>
    .reportview-container .main .block-container { padding-top: 2rem; }
    .stMetric { background-color: #f0f2f6; padding: 10px; border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

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
st.sidebar.caption(f"📅 系統時間: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}")

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
            summary, alerts, logs = system.run_analysis()
            
            st.subheader("🔔 今日交易提示")
            alert_data = []
            for stock, alert in alerts.items():
                name = COMBINED_MAP.get(stock, "")
                status = "⚪ 觀望"
                
                if alert.get('是否觸發賣出'): status = "🔴 強制賣出"
                elif alert.get('高檔背離') or alert.get('乖離過大'): status = "🚨 高檔了結"
                elif alert.get('專業起漲'): status = "🌊 VCP 突破"
                elif alert.get('縮量埋伏'): status = "🥷 縮量埋伏"
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
# 2️⃣ 單股深度診斷 (重點優化：主力洗盤偵測)
# ==========================================
elif menu == "2. 🔎 單股深度診斷":
    st.header("🔎 單股深度診斷 (AI & 主力洗盤辨識)")
    
    # 知識科普
    with st.expander("💡 如何識破主力「欺騙洗盤」手法？"):
        st.markdown("""
        * **假跌破：** 刻意殺破支撐位（如月線、前低）誘發恐慌賣壓，若 3 日內收回即為強勢洗盤。
        * **量能萎縮（窒息量）：** 股價修正但量能低於 5 日均量 60%，代表主力持股穩固，只是在磨耐心。
        * **誘多陷阱：** 股價在高檔爆量卻收長上影線，且隨後幾日無法收復影線高點，小心主力邊拉邊出。
        """)

    user_input = st.text_input("請輸入股票代碼或名稱 (例如: 2330, 台積電)", "2330")
    
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
                else:
                    ticker, stock_name = f"{user_input}.TW", user_input
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
                if not found:
                    st.error(f"❌ 無法辨識「{user_input}」"); st.stop()
        except:
            ticker, stock_name = f"{user_input}.TW", user_input

        st.success(f"✅ 已鎖定標的： **{stock_name} ({ticker})**")

        # --- 執行分析 ---
        with st.spinner("正在解析量價結構與主力動向..."):
            system = TaiwanStockTradingSystem(tickers=[ticker], start_date="2024-01-01")
            system.fetch_market_data()
            summary, alerts, logs = system.run_analysis()
            
            if ticker in alerts:
                alert = alerts[ticker]
                
                # 數據卡片
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("收盤價", f"{alert['收盤價']:.2f}")
                c2.metric("月線位置", f"{alert['月線價']:.2f}", f"{(alert['收盤價']-alert['月線價']):.2f}")
                c3.metric("技術籌碼評分", f"{alert['今日評分']}分")
                c4.metric("大盤狀態", "✅ 安全" if alert['大盤安全'] else "❌ 警戒")

                st.markdown("---")
                
                # --- 🚨 重點：主力洗盤偵測呈現 ---
                st.subheader("🎭 主力行為行為深度偵測")
                
                # 判定變數
                is_wash = alert.get('縮量埋伏', False)
                # 偵測過去 3 日日誌中是否有跌破紀錄，但今日評分 > 60 且在月線上
                is_fake_break = alert['今日評分'] >= 60 and alert['收盤價'] > alert['月線價'] and any("破" in l for l in logs[ticker][-3:])
                is_trap = alert.get('高檔背離', False) or alert.get('乖離過大', False)

                col_l, col_r = st.columns(2)
                
                with col_l:
                    if is_wash:
                        st.info("🥷 **偵測到【縮量洗盤】**\n\n主力正在進行最後的「壓低吃貨」，成交量極度萎縮代表賣壓已盡，這是標準的黎明前黑暗。")
                    elif is_fake_break:
                        st.success("🛡️ **偵測到【假跌破真拉抬】**\n\n近期曾刻意殺破關鍵位，隨後迅速收復。這顯示主力已成功洗出恐慌籌碼，後市看好。")
                    else:
                        st.write("📊 **目前量價穩定**，尚未偵測到極端的欺騙行為。")

                with col_r:
                    if is_trap:
                        st.error("🚨 **警告：【主力誘多陷阱】**\n\n目前股價雖強，但技術指標背離或乖離過大。主力可能正在利用散戶追價情緒「邊拉邊出」，不建議追高。")
                    elif alert.get('專業起漲'):
                        st.success("🌊 **偵測到【換手突破】**\n\n經歷洗盤後今日爆量突破壓力位，主力攻擊意圖明顯，適合積極關注。")
                    else:
                        st.write("💡 **建議觀察**月線支撐力道，等待下一波帶量訊號。")

                st.markdown("---")
                st.subheader("📋 近期系統紀錄")
                for log in logs[ticker][-5:]:
                    st.text(f"• {log}")
            else:
                st.error("❌ 無法取得數據。")

# ==========================================
# 3️⃣ 策略回測
# ==========================================
elif menu == "3. 📈 策略回測":
    st.header("📈 策略回測摘要")
    if st.button("執行回測", type="primary"):
        with st.spinner("計算中..."):
            STATIC_YF_MAP = {k: v for k, v in STOCK_MAP.items()}
            system = TaiwanStockTradingSystem(tickers=list(STATIC_YF_MAP.keys()), start_date="2024-01-01")
            summary, alerts, logs = system.run_analysis()
            
            res = []
            for s, d in summary.items():
                res.append({"代碼": s, "名稱": STATIC_YF_MAP.get(s, ""), "勝率 (%)": d['勝率 (%)'], "累積報酬 (%)": d['策略累積報酬 (%)']})
            st.dataframe(pd.DataFrame(res), use_container_width=True)

# ==========================================
# 5️⃣ 檢查大盤現況
# ==========================================
elif menu == "5. 📊 檢查大盤現況":
    st.header("📊 台股大盤診斷 (^TWII)")
    if st.button("開始診斷", type="primary"):
        df = yf.download("^TWII", period="3mo", progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        last = df['Close'].iloc[-1]; ma20 = df['Close'].rolling(20).mean().iloc[-1]
        change = last - df['Close'].iloc[-2]
        
        col1, col2 = st.columns(2)
        col1.metric("加權指數", f"{last:.2f}", f"{change:.2f}")
        col2.metric("月線 (MA20)", f"{ma20:.2f}")
        
        if last > ma20: st.success("🔥 多頭環境：適合積極操作")
        else: st.error("❄️ 空頭環境：建議保留現金")