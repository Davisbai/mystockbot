import streamlit as st
import pandas as pd
import numpy as np
import datetime
import yfinance as yf
import twstock
import re
import json
import tempfile
from pathlib import Path
from app_support import performance_rows, observed_holding, sync_watchlist, tracking_report

yf.set_tz_cache_location(str(Path(tempfile.gettempdir()) / "py-yfinance"))
# ⚠️ 確保 STOCK_GOD.py 在同目錄下
try:
    from STOCK_GOD import (
        TaiwanStockTradingSystem,
        AdvancedQuantEngine,
        YahooMarketScanner,
        load_watchlist,
        save_watchlist,  # 🌟 新增導入 save_watchlist 以支援自動收錄功能
        STOCK_MAP,
        TDRLDecisionEngine,
        resolve_td_rl_strategy,
    )
except ImportError as exc:
    st.error(f"❌ 核心模組載入失敗：{exc}，請安裝 requirements.txt 並確認 STOCK_GOD.py 位於同目錄。")
    st.stop()

# ==========================================
# 🎨 網頁基本設定與 CSS 樣式
# ==========================================
st.set_page_config(page_title="台股獵手 v2.1 - TD/RL 專業版", page_icon="🎯", layout="wide")

# 自定義 CSS 強化視覺提醒
st.markdown("""
    <style>
    .stMetric { background-color: #f8f9fa; padding: 15px; border-radius: 12px; border: 1px solid #e9ecef; }
    .stAlert { border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# 共用 STOCK_GOD 的決策引擎，避免網頁與每日掃描使用不同版本。
def _apply_tdrl_result(alert, result):
    alert.update({
        "RL可用": bool(result.get("available", False)),
        "TD期待值": round(float(result.get("td_expected_pct", 0.0)), 2),
        "TD樣本支持": int(result.get("td_support", 0)),
        "RL空手策略": str(result.get("flat_action", "HOLD")),
        "RL持有策略": str(result.get("held_action", "HOLD")),
        "RL空手信心": round(float(result.get("flat_confidence", 50.0)), 1),
        "RL持有信心": round(float(result.get("held_confidence", 50.0)), 1),
        "Q買入": round(float(result.get("q_buy_flat", 0.0)), 3),
        "Q空手等待": round(float(result.get("q_hold_flat", 0.0)), 3),
        "Q賣出": round(float(result.get("q_sell_held", 0.0)), 3),
        "Q續抱": round(float(result.get("q_hold_held", 0.0)), 3),
    })
    return alert


def ensure_tdrl_alert(system, ticker, alert):
    """確保 alert 具備 TD/RL 欄位；新版 STOCK_GOD 已有時不重算。"""
    if "RL可用" in alert and "TD期待值" in alert:
        return alert

    try:
        df = system.process_stock(ticker)
        result = TDRLDecisionEngine().fit_predict(df)
        return _apply_tdrl_result(alert, result)
    except Exception as e:
        result = {
            "available": False, "td_expected_pct": 0.0, "td_support": 0,
            "flat_action": "HOLD", "held_action": "HOLD",
            "flat_confidence": 50.0, "held_confidence": 50.0,
            "q_buy_flat": 0.0, "q_hold_flat": 0.0,
            "q_sell_held": 0.0, "q_hold_held": 0.0,
        }
        alert["TD_RL錯誤"] = str(e)
        return _apply_tdrl_result(alert, result)


def run_system_analysis(system):
    try:
        return system.run_analysis()
    except Exception as exc:
        st.error(f"行情分析失敗，請稍後重試：{exc}")
        st.stop()


def tdrl_label(decision, is_held=False):
    return {
        "BUY": "🟢 買入",
        "SELL": "🔴 賣出",
        "WATCH": "🟡 關注期待／續抱" if is_held else "🟡 關注期待",
        "IGNORE": "⚪ 不理會",
    }.get(decision, decision)


# ==========================================
# 🧠 前面策略優化欄位的前端判讀工具
#    僅讀取 STOCK_GOD 已輸出的 alert 欄位，不改動核心演算法
# ==========================================
def _flag(alert, key, default=False):
    return bool(alert.get(key, default))

def _num(alert, key, default=0):
    try:
        return float(alert.get(key, default))
    except Exception:
        return default

def get_limitup_structure(alert):
    if _flag(alert, '低位縮量漲停'):
        return '🟢 低位縮量漲停｜籌碼鎖定佳，續航力較強'
    if _flag(alert, '前高放量漲停'):
        return '🔥 前高放量突破｜有效消化套牢賣壓'
    if _flag(alert, '低位放量漲停'):
        return '🟡 低位放量漲停｜分歧較大，等洗盤確認'
    if _flag(alert, '前高縮量漲停'):
        return '🔴 前高縮量漲停｜假突破風險高'
    if _flag(alert, '漲停基因'):
        return '🏹 近期有漲停基因｜等待量價結構確認'
    return '—'

def get_rule7_tags(alert):
    tags = []
    if _flag(alert, '上升趨勢'):
        tags.append('📈 上升趨勢')
    if _flag(alert, '紅肥綠瘦'):
        tags.append('💪 紅肥綠瘦')
    if _flag(alert, '短線資格'):
        tags.append('🆕 短線資格')
    if _flag(alert, '連續小陽'):
        tags.append('🌱 連續小陽')
    if _flag(alert, '連續小陰'):
        tags.append('⚠️ 連續小陰')
    if _flag(alert, '恐慌反轉'):
        tags.append('🔄 恐慌反轉')
    if _flag(alert, '強勢高位'):
        tags.append('🚀 強勢高位')
    if _flag(alert, '高位過熱'):
        tags.append('🔥 高位過熱')
    if _num(alert, '新鮮度分數', 0) >= 15:
        tags.append(f"🆕 新鮮度{int(_num(alert, '新鮮度分數', 0))}")
    return ' / '.join(tags) if tags else '—'

def get_frontend_status(alert, score_threshold=60):
    score = int(alert.get('今日評分', 0))
    raw_score = int(alert.get('個股原始評分', score))
    market_ok = _flag(alert, '大盤安全')
    is_rebel = (not market_ok and raw_score >= 75)

    if _flag(alert, '是否觸發賣出'):
        return '🔴 建議賣出/停損'
    if _flag(alert, '假突破風險') or _flag(alert, '前高縮量漲停'):
        return '🚨 假突破風險'
    if _flag(alert, '高檔背離') or _flag(alert, '乖離過大') or _flag(alert, '高位過熱'):
        return '🚨 高檔過熱/了結'
    if _flag(alert, '漲停低吸'):
        return '🎯 漲停回檔低吸'
    if _flag(alert, '前高放量漲停'):
        return '🔥 前高放量突破'
    if _flag(alert, '低位縮量漲停'):
        return '🟢 低位縮量發動'
    if _flag(alert, '沉寂發動'):
        return '⚡ 沉寂噴發'
    if _flag(alert, '專業起漲'):
        return '🌊 VCP 突破'
    if _flag(alert, '縮量埋伏'):
        return '🥷 縮量埋伏'
    if _flag(alert, '假跌破'):
        return '🛡️ 假摔洗盤'
    if _flag(alert, '恐慌反轉'):
        return '🔄 恐慌反轉觀察'
    if score >= score_threshold and (_flag(alert, '上升趨勢') or _flag(alert, '短線資格') or is_rebel):
        return '🟢 強力買進'
    if score >= score_threshold:
        return '🟡 達分數但濾網不足'
    return '⚪ 觀望'

def is_frontend_watchlist_candidate(alert, ticker):
    score = int(alert.get('今日評分', 0))
    market_ok = _flag(alert, '大盤安全')
    raw_score = int(alert.get('個股原始評分', score))
    is_rebel = (not market_ok and raw_score >= 75)
    pass_trend = _flag(alert, '上升趨勢') or _flag(alert, '漲停低吸') or _flag(alert, '獨立行情') or is_rebel
    pass_short = _flag(alert, '短線資格') or _flag(alert, '漲停基因') or ticker in STOCK_MAP
    blocked = (
        _flag(alert, '是否觸發賣出') or
        _flag(alert, '假突破風險') or
        _flag(alert, '前高縮量漲停') or
        _flag(alert, '高位過熱')
    )
    return score >= 60 and pass_trend and pass_short and not blocked

# ==========================================
# 🗂️ 側邊欄選單
# ==========================================
st.sidebar.title("🎯 台股獵手 v2.1 TD/RL")
st.sidebar.markdown("---")
menu = st.sidebar.radio(
    "請選擇功能:",
    (
        "1. 🚀 執行完整策略掃描",
        "2. 🔎 單股深度診斷",
        "3. 📈 策略回測",
        "4. 🗂️ 歷史追蹤績效",
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
    st.write("整合熱門強勢股、固定觀察名單與目前監控清單進行掃描。")
    
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
            
            summary, alerts, logs = run_system_analysis(system)
            
            st.subheader("🔔 今日交易提示｜TD + 強化學習仲裁")
            alert_data = []
            for stock, alert in alerts.items():
                name = COMBINED_MAP.get(stock, "")
                alert = ensure_tdrl_alert(system, stock, alert)
                alerts[stock] = alert
                is_held = stock in watchlist
                holding = observed_holding(watchlist[stock], alert) if is_held else None
                rl_decision, rl_reason, rl_meta = resolve_td_rl_strategy(alert, is_held=is_held, holding=holding)
                rl_policy = alert.get('RL持有策略' if is_held else 'RL空手策略', 'HOLD')
                rl_confidence = float(rl_meta.get('confidence', 50.0))

                alert_data.append({
                    "代碼": stock.replace('.TW', '').replace('.TWO', ''),
                    "名稱": name,
                    "列入監控": "✅" if is_held else "—",
                    "資料日期": alert["日期"],
                    "收盤價": alert['收盤價'],
                    "漲幅%": alert.get('今日漲幅', 0),
                    "今日評分": alert['今日評分'],
                    "TD期待%": alert.get('TD期待值', 0),
                    "RL動作": rl_policy,
                    "RL信心%": rl_confidence,
                    "Q值": (
                        f"SELL {alert.get('Q賣出', 0):.3f} / HOLD {alert.get('Q續抱', 0):.3f}"
                        if is_held else
                        f"BUY {alert.get('Q買入', 0):.3f} / CASH {alert.get('Q空手等待', 0):.3f}"
                    ),
                    "策略": tdrl_label(rl_decision, is_held),
                    "判斷理由": rl_reason,
                    "量能倍率": alert.get('量能倍率', 0),
                    "漲停量價結構": get_limitup_structure(alert),
                    "七法則標籤": get_rule7_tags(alert),
                })
            
            if alert_data:
                scan_df = pd.DataFrame(alert_data)
                decision_order = {"🟢 買入": 0, "🟡 關注期待／續抱": 1, "🟡 關注期待": 2, "🔴 賣出": 3, "⚪ 不理會": 4}
                scan_df["_排序"] = scan_df["策略"].map(decision_order).fillna(9)
                scan_df = scan_df.sort_values(["_排序", "TD期待%"], ascending=[True, False]).drop(columns=["_排序"])
                st.dataframe(scan_df, use_container_width=True, hide_index=True)
                st.caption("TD期待% 是歷史相似狀態經 TD(0) 折現後的期待值，不是保證報酬；RL信心表示 Q 值差距與樣本支持度。")
            else:
                st.info("今日無特別訊號。")

# ==========================================
# 2️⃣ 單股深度診斷 (🌟 完美結合 AI 引擎、美股與防追高邏輯)
# ==========================================
elif menu == "2. 🔎 單股深度診斷":
    st.header("🔎 單股深度診斷 (整合 AI 模型與時序驗證)")
    
    with st.expander("💡 籌碼與技術型態小百科：如何看懂主力意圖？"):
        st.markdown("""
        **【洗盤階段特徵】**
        * **假跌破 (Fake Break)：** 刻意殺破支撐位（如月線、前低）誘發恐慌賣壓，若能迅速收回即為強勢洗盤。
        * **縮量窒息 (Quiet Wash)：** 股價回檔但量能極降（不到均量60%），代表主力鎖碼未出，僅洗發浮額。
        
        **【準備發動特徵】**
        * **布林極致壓縮 (Squeeze)：** 股價波動縮小到極限，代表多空即將決裂，通常是變盤前兆。
        * **長期沉寂量增 (Quiet Breakout)：** 股價長期低迷（橫盤震幅<10%），今日突然量比急增，是起漲訊號。
        * **均線糾結：** 短中長期均線黏合，股價帶量突破將展開大行情。

        **【前面新增的兩套短線濾網】**
        * **漲停量價結構：** 低位縮量漲停偏強；前高放量突破偏強；低位放量需等洗盤；前高縮量需防假突破。
        * **七法則標籤：** 上升趨勢、紅肥綠瘦、短線資格、新鮮度、連續小陽、恐慌反轉與高位過熱會同步顯示在診斷面板。
        """)

    user_input = st.text_input("請輸入股票代碼或名稱 (例如: 2330, AAPL, 或 台積電)", "2330")
    
    if st.button("開始診斷", type="primary"):
        user_input = user_input.strip()
        user_upper = user_input.upper()
        ticker = ""
        stock_name = ""
        mkt_ticker = "^TWII"

        # --- 自動辨識邏輯 (支援美股) ---
        if re.match(r'^[A-Z]+$', user_upper):
            ticker = user_upper
            stock_name = ticker
            mkt_ticker = "^GSPC"  # 美股切換大盤
        else:
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
                system.market_ticker = mkt_ticker
                
                summary, alerts, logs = run_system_analysis(system)
                
                if ticker not in alerts:
                    st.error(f"❌ Yahoo Finance 無法取得 {ticker} 的歷史資料。")
                    st.stop()

                # 2. AI Meta-Labeling 模型診斷
                ai_engine = AdvancedQuantEngine(ticker=ticker)
                meta_prob, regime_idx, ai_success = 0.0, None, False
                try:
                    if ai_engine.fetch_data(period="2y"):
                        ai_engine.detect_market_regime()
                        ai_engine.apply_triple_barrier()
                        if ai_engine.train_meta_labeling_model():
                            latest_ai = ai_engine.data.iloc[-1]
                            regime_idx = int(latest_ai['Regime'])
                            feat = latest_ai[['Volatility_20', 'Volatility_50', 'Momentum_10', 'Momentum_20', 'Regime']].values.reshape(1, -1)
                            meta_prob = ai_engine.meta_classifier.predict_proba(feat)[0][1]
                            ai_success = True

                except Exception as exc:
                    st.caption(f"AI 模型目前無可用結果：{exc}，以下仍顯示規則策略診斷。")

                # 🌟 3. 獲取基本面資料 (僅供畫面顯示，絕對不影響後續任何判斷)
                try:
                    ticker_obj = yf.Ticker(ticker)
                    info = ticker_obj.info
                    raw_yield = info.get('dividendYield') or info.get('trailingAnnualDividendYield') or 0
                    dividend_yield = raw_yield if raw_yield > 1 else raw_yield * 100
                    book_value = info.get('bookValue', 0)
                    pb_ratio = info.get('priceToBook', 0)
                except Exception:
                    dividend_yield, book_value, pb_ratio = 0, 0, 0

                # --- 4. 提取進階訊號 ---
                alert = ensure_tdrl_alert(system, ticker, alerts[ticker])
                alerts[ticker] = alert
                stock_logs = logs.get(ticker, [])
                watchlist = load_watchlist()
                is_held = ticker in watchlist
                holding = observed_holding(watchlist[ticker], alert) if is_held else None
                rl_decision, rl_reason, rl_meta = resolve_td_rl_strategy(alert, is_held=is_held, holding=holding)
                rl_confidence = float(rl_meta.get('confidence', 50.0))
                rl_policy = alert.get('RL持有策略' if is_held else 'RL空手策略', 'HOLD')
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

                # 前面策略加強版欄位：若 STOCK_GOD 尚未升級，皆以預設值安全處理
                false_breakout_risk = alert.get('假突破風險', False) or alert.get('前高縮量漲停', False)
                trend_up_strong = alert.get('上升趨勢', False)
                strong_candle_structure = alert.get('紅肥綠瘦', False)
                short_term_eligible = alert.get('短線資格', False)
                panic_reversal = alert.get('恐慌反轉', False)
                high_position_strong = alert.get('強勢高位', False)
                high_position_overheat = alert.get('高位過熱', False)
                fresh_theme_score = alert.get('新鮮度分數', 0)

                # --- 5. 繪製 Streamlit 數據面板 ---
                st.info(f"📅 數據日期: **{alert.get('日期', 'N/A')}**")
                st.markdown("#### 規則策略回測")
                st.dataframe(pd.DataFrame(performance_rows({ticker: summary[ticker]}, {ticker: stock_name})),
                             use_container_width=True, hide_index=True)
                st.caption("收盤訊號於次日開盤執行，含研究成本；這是規則策略，與 TD/RL 仲裁及訊號追蹤報酬分開解讀。")
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
                mkt_name = "標普500" if mkt_ticker == "^GSPC" else "加權指數"
                
                st.write(f"- **{mkt_name}大盤狀態**: {mkt_status} (指數: {mkt_close:.0f} | 月線: {mkt_ma20:.0f})")
                st.write(f"- **MACD (10,20,8)**: {macd_str} ({macd_cross_str}) | DIF: {macd_val:.2f}")

                st.markdown("#### 🏹 漲停量價結構")
                lu_col1, lu_col2, lu_col3 = st.columns(3)
                lu_col1.metric("量能倍率", f"{alert.get('量能倍率', 0):.2f}x" if isinstance(alert.get('量能倍率', 0), (int, float)) else str(alert.get('量能倍率', 0)))
                lu_col2.metric("區間位置", f"{alert.get('區間位置', 0):.2f}" if isinstance(alert.get('區間位置', 0), (int, float)) else str(alert.get('區間位置', 0)))
                lu_col3.metric("近期漲停數", f"{alert.get('近期漲停數', 0)}")
                st.write(f"- **漲停結構判讀**: {get_limitup_structure(alert)}")
                if false_breakout_risk:
                    st.error("🚨 前高附近縮量或假突破風險偏高，短線不宜追價，需等補量或回測支撐確認。")

                st.markdown("#### 📌 七法則短線濾網")
                rule_cols = st.columns(4)
                rule_cols[0].metric("上升趨勢", "✅" if trend_up_strong else "—")
                rule_cols[1].metric("紅肥綠瘦", "✅" if strong_candle_structure else "—")
                rule_cols[2].metric("短線資格", "✅" if short_term_eligible else "—")
                rule_cols[3].metric("新鮮度分數", f"{fresh_theme_score}")
                st.write(f"- **七法則標籤**: {get_rule7_tags(alert)}")

                if ai_success:
                    st.write(f"- **GMM 市場分群**: 狀態 {regime_idx}（編號無固定多空意義）")
                    st.write(f"- **AI 模型正類機率**: **{meta_prob*100:.1f}%**")
                    st.caption("模型正類機率未經機率校準，不能視為交易勝率或未來獲利保證。")
                    validation = ai_engine.validation_metrics
                    st.markdown("#### AI 時序留出驗證")
                    st.dataframe(pd.DataFrame([{
                        "驗證起日": validation['validation_start'],
                        "訓練樣本": validation['train_samples'],
                        "驗證樣本": validation['test_samples'],
                        "正確率 (%)": round(validation['accuracy'] * 100, 2),
                        "平衡正確率 (%)": round(validation['balanced_accuracy'] * 100, 2),
                        "正類精確率 (%)": round(validation['precision'] * 100, 2),
                        "全部判正類基準 (%)": round(validation['always_positive_accuracy'] * 100, 2),
                    }]), use_container_width=True, hide_index=True)
                    st.caption("以上評估三重屏障標籤的分類表現，與扣成本交易報酬分開解讀。")
                else:
                    st.write("- **AI 統計**: 時序切割後樣本不足或類別不足，未提供模型機率。")

                st.markdown("#### 🧠 TD(0) + Q-Learning 決策層")
                rl_c1, rl_c2, rl_c3, rl_c4 = st.columns(4)
                rl_c1.metric("TD 折現期待", f"{alert.get('TD期待值', 0):+.2f}%", f"樣本支持 {alert.get('TD樣本支持', 0)}", delta_color="off")
                rl_c2.metric("RL 原始動作", rl_policy, "持有模型" if is_held else "空手模型", delta_color="off")
                rl_c3.metric("RL 信心", f"{rl_confidence:.1f}%")
                rl_c4.metric("監控狀態", "已列入監控" if is_held else "尚未列入")
                if is_held:
                    st.write(f"- **Q值比較**: SELL = **{alert.get('Q賣出', 0):.3f}** ｜ HOLD = **{alert.get('Q續抱', 0):.3f}**")
                else:
                    st.write(f"- **Q值比較**: BUY = **{alert.get('Q買入', 0):.3f}** ｜ CASH/HOLD = **{alert.get('Q空手等待', 0):.3f}**")
                st.write(f"- **TD/RL 仲裁理由**: {rl_reason}")
                st.caption("監控清單是訊號追蹤紀錄；模型的持有／空手情境依清單切換，不代表券商實際部位。")
                if alert.get('TD_RL錯誤'):
                    st.caption(f"⚠️ TD/RL 補算失敗，已安全回退原策略：{alert.get('TD_RL錯誤')}")

                st.markdown("---")

                # --- 6. 核心判定：TD/RL 為最終仲裁，原技術面保留為硬性風控與狀態特徵 ---
                st.markdown("### 🎯 最終系統判定｜TD/RL 仲裁")
                add_to_watchlist_flag = (rl_decision == "BUY")

                if rl_decision == "BUY":
                    st.success(f"👉 最終判定: 🟢 **【買入】**  {rl_reason}")
                elif rl_decision == "SELL":
                    st.error(f"👉 最終判定: 🔴 **【賣出】**  {rl_reason}")
                elif rl_decision == "WATCH":
                    hold_text = "／續抱" if is_held else ""
                    st.warning(f"👉 最終判定: 🟡 **【關注期待{hold_text}】**  {rl_reason}")
                else:
                    st.info(f"👉 最終判定: ⚪ **【不理會】**  {rl_reason}")

                # Meta-Labeling 保留為交叉驗證提示，不覆蓋 TD/RL 最終策略
                if ai_success and meta_prob < 0.6 and rl_decision == "BUY":
                    st.caption(f"⚠️ 交叉提醒：Meta-Labeling 模型正類機率為 {meta_prob*100:.1f}%，雖 TD/RL 判為買入，仍建議降低初始部位。")

                # --- 7. 同步訊號監控狀態，保留原始參考成本與日期 ---
                watchlist = load_watchlist()
                old_entry = watchlist.get(ticker)
                if sync_watchlist(watchlist, ticker, stock_name, alert, rl_decision):
                    save_watchlist(watchlist)
                    if old_entry is None and ticker in watchlist:
                        st.success(f"📌 已將 {stock_name} ({ticker}) 納入訊號監控，參考價: {alert['收盤價']}")
                    elif old_entry is not None and ticker not in watchlist:
                        st.warning(f"📤 已將 {stock_name} ({ticker}) 移出訊號監控；原參考成本: {old_entry.get('加入價格', 'N/A')}")

                st.markdown("---")

                # --- 8. 主力行為細節與歷史紀錄 ---
                col_l, col_r = st.columns(2)
                with col_l:
                    st.markdown("### 🏹 主力洗盤辨識")
                    if false_breakout_risk:
                        st.error("🚨 **警告：【前高縮量假突破風險】**\n\n價格接近前高但量能不足，可能尚未真正消化套牢賣壓，需等補量續攻或回測不破。")
                    elif is_top_divergent:
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

                    st.markdown("### 📌 七法則細節")
                    if trend_up_strong and strong_candle_structure and short_term_eligible:
                        st.success("✅ **短線結構完整**：同時具備上升趨勢、紅肥綠瘦與近期漲停/新高/新量資格。")
                    elif trend_up_strong or strong_candle_structure or short_term_eligible:
                        st.info(f"📊 **部分條件成立**：{get_rule7_tags(alert)}")
                    elif panic_reversal:
                        st.info("🔄 **逆向觀察**：連續下跌後出現止跌收紅，適合觀察，不宜直接重倉。")
                    else:
                        st.write("目前七法則短線濾網尚未形成完整共振。")

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
    st.write("分析固定觀察名單的規則策略：收盤訊號於次日開盤執行，扣除買入 0.08%／賣出 0.38% 的研究成本。")
    st.caption("此頁不是完整 TD/RL 仲裁策略回測；勝率只計已平倉交易，尚無平倉時留白。漲跌停與成交限制未模擬。")
    
    if st.button("執行回測", type="primary"):
        with st.spinner("正在計算歷史回測數據..."):
            STATIC_YF_MAP = {k: v for k, v in STOCK_MAP.items()}
            system = TaiwanStockTradingSystem(tickers=list(STATIC_YF_MAP.keys()), start_date="2024-01-01")
            
            summary, alerts, logs = run_system_analysis(system)
            if not summary:
                st.info("目前沒有可回測資料，請稍後重試。")
                st.stop()
            
            st.subheader("📊 回測結果")
            st.dataframe(pd.DataFrame(performance_rows(summary, STATIC_YF_MAP)), use_container_width=True, hide_index=True)

# ==========================================
# 4️⃣ 使用者指定紀錄的歷史追蹤分析
# ==========================================
elif menu == "4. 🗂️ 歷史追蹤績效":
    st.header("🗂️ 歷史追蹤績效")
    st.write("依 LINE 推播的監控清單快照與目前監控清單，檢視參考報酬和獲利回吐。")
    st.caption("這些數值是觀察價，並非已實現成交；清單消失不等於賣出，缺失日期與盤中價格不會補造。")
    try:
        root = Path(__file__).resolve().parent
        log_text = (root / "line_push_log.txt").read_text(encoding="utf-8")
        records = json.loads((root / "long_term_watchlist.json").read_text(encoding="utf-8"))
        report = tracking_report(log_text, records)
        c1, c2, c3 = st.columns(3)
        c1.metric("監控快照", report['watchlist_snapshot_count'])
        c2.metric("追蹤段數", report['tracked_episodes'])
        c3.metric("目前清單對上筆數", report['current_episodes_matched'])
        if report['current_episodes_matched'] < len(records):
            st.info("部分目前清單尚無相符推播紀錄，沒有將其報酬補成零。")
        scope = st.radio("顯示範圍", ("全部追蹤", "目前監控"), horizontal=True)
        minimum = st.number_input("最少觀察交易日", min_value=1, value=1, step=1)
        episodes = [e for e in report['episodes'] if e['observed_sessions'] >= minimum
                    and (scope == "全部追蹤" or e['status'] == 'current_watchlist')]
        if episodes:
            columns = {
                'code': '代碼', 'name': '名稱', 'entry_date': '加入日期',
                'reference_cost': '參考成本', 'observed_sessions': '觀察日數',
                'last_observed': '最後觀察時間', 'last_price': '最後觀察價',
                'last_mark_return_pct': '最後參考報酬 (%)',
                'peak_mark_return_pct': '最高參考報酬 (%)',
                'observed_max_drawdown_pct': '觀察最大回撤 (%)',
                'peak_to_last_pct': '高點至最後觀察跌幅 (%)', 'status': '追蹤狀態',
            }
            table = pd.DataFrame(episodes)[list(columns)].rename(columns=columns)
            table['追蹤狀態'] = table['追蹤狀態'].map({
                'current_watchlist': '目前監控',
                'historical_tracking_exit_unconfirmed': '歷史追蹤，出場未確認',
            })
            st.dataframe(table.sort_values('高點至最後觀察跌幅 (%)'), use_container_width=True, hide_index=True)
        else:
            st.info("所選範圍沒有相符紀錄。")
        st.caption("以代碼、加入日期及參考成本區分追蹤段；同一推播日期只保留最後觀察，缺漏可能低估回撤。")
        st.download_button("下載完整追蹤分析 JSON", json.dumps(report, ensure_ascii=False, indent=2),
                           file_name="performance_history.json", mime="application/json")
    except (OSError, ValueError, TypeError) as exc:
        st.error(f"無法讀取追蹤紀錄：{exc}")

# ==========================================
# 5️⃣ 檢查大盤現況
# ==========================================
elif menu == "5. 📊 檢查大盤現況":
    st.header("📊 大盤即時診斷")
    
    # 🌟 新增選項，讓使用者可以選擇美股或台股大盤
    mkt_option = st.radio("請選擇要診斷的大盤:", ("🇹🇼 台股加權指數 (^TWII)", "🇺🇸 美股標普 500 (^GSPC)"), horizontal=True)
    market_ticker = "^TWII" if "TWII" in mkt_option else "^GSPC"
    
    if st.button("開始診斷", type="primary"):
        with st.spinner(f"獲取 {market_ticker} 大盤數據中..."):
            try:
                # 本頁只用當次下載，不寫回跨頁大盤快取。
                df = yf.download(market_ticker, period="3mo", progress=False, auto_adjust=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                
                if df.empty or len(df) < 25:
                    st.warning("大盤資料不足，請稍後重試。")
                    st.stop()
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
                    st.success("🔥 **多頭強勢** (站上月線且月線走揚) \n\n **💡 操作建議:** 適度加碼精選個股")
                elif is_above_ma20 and not is_up_trend:
                    st.warning("⚖️ **高檔震盪** (站上月線但均線走平) \n\n **💡 操作建議:** 挑選獨立強勢股")
                elif not is_above_ma20 and is_up_trend:
                    st.info("🛡️ **支撐測試** (跌破月線但均線仍上揚) \n\n **💡 操作建議:** 觀察是否出現假跌破破底翻")
                else:
                    st.error("❄️ **空頭架構** (跌破月線且均線下彎) \n\n **💡 操作建議:** 嚴控倉位，保留現金")
                    
            except Exception as e:
                st.error(f"無法獲取大盤數據: {e}")
