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
        save_watchlist,  # 🌟 新增導入 save_watchlist 以支援自動收錄功能
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
# 2️⃣ 單股深度診斷 (🌟 完美結合 AI 引擎與防追高邏輯)
# ==========================================
# ==========================================
# 2️⃣ 單股深度診斷 (🌟 完美結合 AI 引擎與防追高邏輯)
# ==========================================
# ==========================================
# 2️⃣ 單股深度診斷 (簡單判斷邏輯 + 豐富 UI 說明)
# ==========================================
# ==========================================
# 2️⃣ 單股深度診斷 (簡單判斷邏輯 + 豐富 UI 說明 + 基本面顯示)
# ==========================================
elif menu == "2. 🔎 單股深度診斷":
    st.header("🔎 單股深度診斷 (整合 AI 勝率預測)")
    
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

        col_left, col_right = st.columns([3, 1])
        with col_left:
            st.success(f"✅ 已鎖定標的： **{stock_name} ({ticker})**")
        with col_right:
            analysis_url = f"https://tw.stock.yahoo.com/quote/{ticker}/technical-analysis"
            st.link_button("📈 技術分析", analysis_url)

        # --- 執行分析 ---
        with st.spinner("正在下載數據並執行系統與 AI 雙重診斷..."):
            try:
                # 1. 傳統技術與籌碼分析
                system = TaiwanStockTradingSystem(tickers=[ticker], start_date="2023-01-01")
                if st.session_state.cached_market_data is None:
                    system.fetch_market_data()
                    st.session_state.cached_market_data = system.market_data
                else:
                    system.market_data = st.session_state.cached_market_data
                summary, alerts, logs = system.run_analysis()
                
                if ticker not in alerts:
                    st.error(f"❌ Yahoo Finance 無法取得 {ticker} 的歷史資料。")
                    st.stop()

                # 2. AI Meta-Labeling 模型診斷
                ai_engine = AdvancedQuantEngine(ticker=ticker)
                meta_prob, regime_idx, ai_success = 0.0, None, False
                if ai_engine.fetch_data(period="2y"):
                    ai_engine.detect_market_regime()
                    ai_engine.apply_triple_barrier()
                    if ai_engine.train_meta_labeling_model():
                        latest_ai = ai_engine.data.iloc[-1]
                        regime_idx = int(latest_ai['Regime'])
                        feat = latest_ai[['Volatility_20', 'Volatility_50', 'Momentum_10', 'Momentum_20', 'Regime']].values.reshape(1, -1)
                        meta_prob = ai_engine.meta_classifier.predict_proba(feat)[0][1]
                        ai_success = True

                # 🌟 3. 獲取基本面資料 (僅供畫面顯示，絕對不影響後續任何判斷)
                try:
                    ticker_obj = yf.Ticker(ticker)
                    info = ticker_obj.info
                    raw_yield = info.get('dividendYield') or info.get('trailingAnnualDividendYield') or 0
                    # 防呆處理：若 Yahoo 已經乘過 100 給出 4.17，就不再乘；若是 0.0417，則乘 100
                    dividend_yield = raw_yield if raw_yield > 1 else raw_yield * 100
                    book_value = info.get('bookValue', 0)
                    pb_ratio = info.get('priceToBook', 0)
                except Exception:
                    dividend_yield, book_value, pb_ratio = 0, 0, 0

                # --- 4. 提取進階訊號 ---
                alert = alerts[ticker]
                stock_logs = logs.get(ticker, [])
                score = alert['今日評分']
                raw_score = alert['個股原始評分']
                market_ok = alert['大盤安全']
                today_return = alert.get('今日漲幅', 0.0)
                
                mkt_close = float(system.market_data['Close'].iloc[-1])
                mkt_ma20 = float(system.market_data['Market_MA20'].iloc[-1])
                
                # 提取洗盤與變盤特徵
                is_rebel = (not market_ok and raw_score >= 75)
                pro_bottom_breakout = alert.get('專業起漲', False)
                ambush_setup = alert.get('縮量埋伏', False)
                fake_break = alert.get('假跌破', False)
                long_quiet = alert.get('沉寂多時', False)
                quiet_momentum = alert.get('沉寂發動', False)
                is_top_divergent = alert.get('高檔背離', False) or alert.get('乖離過大', False)
                
                macd_val = alert.get('MACD_數值', 0.0)
                macd_sig = alert.get('MACD_訊號', 0.0)
                is_water_above = (macd_val > 0)
                macd_golden_cross = (macd_val > macd_sig)

                # --- 5. 繪製 Streamlit 數據面板 ---
                st.info(f"📅 數據日期: **{alert.get('日期', 'N/A')}**")
                st.markdown("### 📊 核心數據儀表板")
                
                col1, col2, col3 = st.columns(3)
                col1.metric(label="今日收盤價", value=f"{alert['收盤價']:.2f}", delta=f"{today_return:.2f}%")
                
                ma20_status = "🌟 剛站上月線" if alert.get('剛過月線') else f"與月線乖離: {(alert['收盤價']-alert['月線價']):.2f}"
                col2.metric(label="月線 (MA20)", value=f"{alert['月線價']:.2f}", delta=ma20_status, delta_color="off")
                
                col3.metric(label="技術籌碼評分", value=f"{score} 分", delta=f"原始: {raw_score}分", delta_color="off")

                # 🌟 新增：基本面參考指標 (純顯示)
                st.markdown("#### 💎 基本面參考指標")
                f_col1, f_col2, f_col3 = st.columns(3)
                f_col1.metric(label="現金殖利率 (LTM)", value=f"{dividend_yield:.2f} %")
                f_col2.metric(label="每股淨值 (NAV)", value=f"{book_value:.2f}")
                pb_color = "normal" if pb_ratio < 2 else "inverse"
                f_col3.metric(label="股價淨值比 (P/B)", value=f"{pb_ratio:.2f}", delta="價值低估" if pb_ratio > 0 and pb_ratio < 1.5 else "", delta_color=pb_color)

                st.markdown("#### 🔍 趨勢與 AI 狀態")
                mkt_status = "🟢 站上月線 (安全)" if market_ok else "🔴 跌破月線 (風險)"
                macd_str = "🟢 水上" if is_water_above else "🔴 水下"
                macd_cross_str = "金叉" if macd_golden_cross else "死叉"
                
                st.write(f"- **大盤狀態**: {mkt_status} (指數: {mkt_close:.0f} | 月線: {mkt_ma20:.0f})")
                st.write(f"- **MACD (10,20,8)**: {macd_str} ({macd_cross_str}) | DIF: {macd_val:.2f}")

                if ai_success:
                    REGIME_DESC = {
                        0: "🟢 0 低波動穩定期 (多頭特徵)",
                        1: "🔴 1 高波動混亂期 (空頭或洗盤)",
                        2: "🟡 2 轉折過渡期 (動能改變中)"
                    }
                    st.write(f"- **GMM 市場狀態**: {REGIME_DESC.get(regime_idx, '未知狀態')}")
                    st.write(f"- **AI 預測勝率**: **{meta_prob*100:.1f}%**")
                else:
                    st.write("- **AI 預測**: 樣本不足，無法判定")

                st.markdown("---")

                # --- 6. 核心判定與濾網邏輯 (完全保持原邏輯，不受基本面影響) ---
                st.markdown("### 🎯 最終系統判定")
                add_to_watchlist_flag = False
                is_chasing_high = alert.get('今日漲幅', 0) >= 7.0

                if alert.get("是否觸發賣出"):
                    st.error("👉 最終判定: 🔴 **【建議賣出/停損】**")
                elif score >= 60:
                    if not ai_success or meta_prob >= 0.6:
                        if is_chasing_high:
                             st.warning(f"👉 最終判定: ⚠️ **【切勿追高】** (今日漲幅達 {alert.get('今日漲幅', 0)}%, 已大漲表態，請耐心等待量縮回檔)")
                        else:
                            st.success("👉 最終判定: 🟢 **【強力買進】**")
                            add_to_watchlist_flag = True
                    else:
                        if is_chasing_high:
                            st.warning("👉 最終判定: 🟡 **【建議觀望 / ⚠️ 切勿追高】** (今日漲幅大且 AI 勝率過低，慎防假突破)")
                        else:
                            st.warning("👉 最終判定: 🟡 **【建議觀望】** (技術面達標但 AI 勝率過低)")
                else:
                    st.info("👉 最終判定: ⚪ **【建議觀望】** (綜合評分與動能不足)")

                # --- 7. 自動收錄至長期監控清單 ---
                if add_to_watchlist_flag:
                    watchlist = load_watchlist()
                    entry_date = alert["日期"]
                    entry_price = alert["收盤價"]
                    
                    if stock_logs:
                        for log_entry in reversed(stock_logs):
                            if "🟢 買進" in log_entry:
                                parts = log_entry.split('|')
                                entry_date = parts[0].strip()
                                p_match = re.search(r"價格:\s*([\d\.]+)", parts[2])
                                if p_match: entry_price = float(p_match.group(1))
                                break
                            elif "🔴 賣出" in log_entry: break
                    
                    if ticker not in watchlist or watchlist[ticker].get("加入日期") != entry_date:
                        watchlist[ticker] = {"名稱": stock_name, "加入日期": entry_date, "加入價格": entry_price}
                        save_watchlist(watchlist)
                        st.balloons() # 加入慶祝特效
                        st.success(f"📌 **已自動將 {stock_name} ({ticker}) 納入長期監控清單！** (紀錄成本: {entry_price})")

                st.markdown("---")

                # --- 8. 主力行為細節與歷史紀錄 ---
                col_l, col_r = st.columns(2)
                with col_l:
                    st.markdown("### 🏹 主力洗盤辨識")
                    if is_top_divergent:
                        st.error("🚨 **警告：【誘多出貨風險】**\n\n股價雖處高檔，但動能背離或乖離過大。切勿追高。")
                    elif fake_break:
                        st.success("🛡️ **偵測到【假跌破真拉抬】**\n\n近期刻意殺破支撐後迅速收回。這代表主力洗盤成功，下方籌碼已換手，後市看好。")
                    elif ambush_setup:
                        st.info("🎭 **偵測到【縮量洗盤】**\n\n股價回落且量能極度萎縮。主力正在壓低吃貨。")
                    else:
                        st.write("📊 目前無極端的洗盤或出貨特徵。")

                    st.markdown("### 🚀 變盤與攻擊預警")
                    if quiet_momentum:
                        st.success("🌋 **標的特徵：【沉寂後帶量噴發】**\n\n經歷長期的窄幅震盪後，今日突然爆量起漲。此為明確的變盤攻擊訊號！")
                    elif long_quiet:
                        st.info("🧘 **標的特徵：【橫盤沉寂中】**\n\n股價已長時間處於窄幅震盪區間 (震幅 < 10%)。這是在蹲下準備跳躍，建議先加入觀察，一旦帶量突破將是噴發。")
                    elif pro_bottom_breakout:
                        st.success("🌊 **標的特徵：【VCP 波動收斂突破】**\n\n籌碼極限壓縮後今日帶量突破，建議建立核心部位。")
                    else:
                        st.write("📊 目前無明顯的變盤特徵。")

                with col_r:
                    st.markdown("### 📋 最近交易紀錄")
                    if stock_logs:
                        for log in stock_logs[-5:]:
                            st.text(f"• {log}")
                    else:
                        st.write("今日無特別系統紀錄。")

            except Exception as e:
                st.error(f"執行分析時發生錯誤: {e}")
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
                df = yf.download("^TWII", period="3mo", progress=False, auto_adjust=True)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                df['MA20'] = df['Close'].rolling(window=20).mean()
                df['MA5'] = df['Close'].rolling(window=5).mean()
                
                last_close = float(df['Close'].iloc[-1])
                ma20 = float(df['MA20'].iloc[-1])
                ma5 = float(df['MA5'].iloc[-1])
                prev_close = float(df['Close'].iloc[-2])
                
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