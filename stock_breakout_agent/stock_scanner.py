import yfinance as yf
import pandas as pd
import pandas_ta as ta
import warnings

warnings.filterwarnings('ignore')

# 預設掃描的台灣 50 與中型 100 部分權值股 (以 .TW 結尾)
DEFAULT_SYMBOLS = [
    "2330.TW", "2303.TW", "2317.TW", "2454.TW", "2308.TW", 
    "2881.TW", "2882.TW", "3481.TW", "2409.TW", "2603.TW",
    "2609.TW", "2615.TW", "2382.TW", "3231.TW", "2356.TW",
    "2324.TW"
]

def fetch_stock_data(symbol, period="6mo"):
    """
    抓取指定股票的歷史資料，預設抓取過去 6 個月
    """
    try:
        stock = yf.download(symbol, period=period, progress=False)
        if stock.empty:
            return None
        # 確保只有單一股票時的 column format 正確 (yfinance 某些版本回傳 MultiIndex)
        if isinstance(stock.columns, pd.MultiIndex):
            stock.columns = stock.columns.get_level_values(0)
        return stock
    except Exception as e:
        print(f"[{symbol}] 獲取資料失敗: {e}")
        return None

def check_breakout(df):
    """
    檢查是否符合起漲條件：
    1. 收盤價突破 20 日均線 (MA20)
    2. 當日成交量大於過去 5 日平均成交量的 2 倍 或 大幅放量
    3. MACD 黃金交叉 (MACD > MACD_Signal)
    """
    if df is None or len(df) < 30:
        return False, None
    
    # 計算技術指標
    df.ta.sma(length=20, append=True) # 產生 SMA_20
    df.ta.sma(close="Volume", length=5, append=True) # 產生 SMA_5 (對應 Volume)
    df.ta.macd(append=True) # 產生 MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
    
    # 清理缺失值
    df = df.dropna()
    if len(df) < 2:
        return False, None

    # 取得最新一天與前一天的資料
    latest = df.iloc[-1]
    prev = df.iloc[-2]
    
    try:
        # 指標名稱可能因 pandas_ta 版本略有不同
        ma20_cols = [c for c in df.columns if c.startswith('SMA_20')]
        vol_ma5_cols = [c for c in df.columns if c == 'SMA_5' or c.startswith('SMA_5')]
        
        if not ma20_cols or not vol_ma5_cols:
            return False, None
            
        ma20 = latest[ma20_cols[0]]
        vol_ma5 = latest[vol_ma5_cols[0]]
        
        macd_cols = [c for c in df.columns if c.startswith('MACD_')]
        macds_cols = [c for c in df.columns if c.startswith('MACDs_')]
        
        if not macd_cols or not macds_cols:
            return False, None
            
        macd = latest[macd_cols[0]]
        macd_signal = latest[macds_cols[0]]
        prev_macd = prev[macd_cols[0]]
        prev_macd_signal = prev[macds_cols[0]]

        # 條件 1: 收盤價大於 20 日均線 (站上月線)
        cond1 = latest['Close'] > ma20
        
        # 條件 2: 成交量爆量 (大於 5日均量 1.5倍以上視為放量，這裡設為 1.5 倍較容易掃到)
        cond2 = latest['Volume'] > (vol_ma5 * 1.5)
        
        # 條件 3: MACD 多頭 (MACD > Signal)
        cond3 = (macd > macd_signal) 
        
        # 額外條件: 近日剛發生 MACD 黃金交叉 (前兩日 MACD <= Signal，今日或昨日 > Signal)
        cond_golden_cross = (prev_macd <= prev_macd_signal) and (macd > macd_signal)

        # 這裡的邏輯：只要站上20日線，且出量，且MACD是多頭，我們就當作候選
        # 如果要非常嚴格，可以把 cond_golden_cross 加入
        is_breakout = cond1 and cond2 and cond3
        
        return is_breakout, latest
        
    except Exception as e:
        print(f"指標計算錯誤: {e}")
        return False, None

def scan_stocks(symbols=DEFAULT_SYMBOLS):
    """
    掃描多檔股票，回傳符合起漲條件的清單
    """
    results = []
    print(f"開始掃描 {len(symbols)} 檔股票，尋找起漲特徵...")
    for sym in symbols:
        df = fetch_stock_data(sym)
        is_breakout, latest_data = check_breakout(df)
        if is_breakout:
            print(f"[★ 發現起漲特徵 ★] {sym} (收盤價: {latest_data['Close']:.2f}, 成交量: {latest_data['Volume']})")
            results.append({
                "symbol": sym,
                "close": latest_data['Close'],
                "volume": latest_data['Volume'],
                "dataframe": df # 保留完整的 df 供後續分析
            })
    return results

if __name__ == "__main__":
    found = scan_stocks()
    print(f"\n掃描結束，共找到 {len(found)} 檔符合條件的起漲候選股。")
