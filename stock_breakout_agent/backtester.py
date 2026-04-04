import yfinance as yf
import pandas as pd
import pandas_ta as ta
import numpy as np
import warnings
from stock_scanner import DEFAULT_SYMBOLS

warnings.filterwarnings('ignore')

def fetch_historical_data(symbol, period="5y"):
    """
    抓取指定股票的歷史資料，用於回測
    """
    try:
        stock = yf.download(symbol, period=period, progress=False)
        if stock.empty:
            return None
        if isinstance(stock.columns, pd.MultiIndex):
            stock.columns = stock.columns.get_level_values(0)
        return stock
    except Exception as e:
        print(f"[{symbol}] 獲取資料失敗: {e}")
        return None

def calculate_indicators_and_signals(df):
    """
    計算指標並找出歷史中符合起漲條件的日子
    """
    if df is None or len(df) < 50:
        return pd.DataFrame()

    # 計算技術指標
    df.ta.sma(length=20, append=True)
    df.ta.sma(close="Volume", length=5, append=True)
    df.ta.macd(append=True)
    
    # 指標名稱可能因 pandas_ta 版本略有不同
    ma20_cols = [c for c in df.columns if c.startswith('SMA_20')]
    vol_ma5_cols = [c for c in df.columns if c == 'SMA_5' or c.startswith('SMA_5')]
    macd_cols = [c for c in df.columns if c.startswith('MACD_')]
    macds_cols = [c for c in df.columns if c.startswith('MACDs_')]
    
    if not (ma20_cols and vol_ma5_cols and macd_cols and macds_cols):
        return pd.DataFrame()
        
    ma20 = ma20_cols[0]
    vol_ma5 = vol_ma5_cols[0]
    macd = macd_cols[0]
    macd_signal = macds_cols[0]

    # 建立訊號條件
    df['Cond_MA20'] = df['Close'] > df[ma20]
    df['Cond_Vol'] = df['Volume'] > (df[vol_ma5] * 1.5)
    df['Cond_MACD'] = df[macd] > df[macd_signal]
    
    # 判斷是否符合起漲條件
    df['Signal'] = df['Cond_MA20'] & df['Cond_Vol'] & df['Cond_MACD']
    
    return df

def run_backtest(symbols=DEFAULT_SYMBOLS, period="5y", forward_days=[5, 10, 20]):
    """
    執行回測，計算訊號發生後的未來報酬率
    """
    print(f"開始回測 {len(symbols)} 檔股票 (期間: {period})...")
    
    all_trades = []
    
    for sym in symbols:
        df = fetch_historical_data(sym, period)
        if df is None:
            continue
            
        df = calculate_indicators_and_signals(df)
        if df.empty or 'Signal' not in df.columns:
            continue
            
        # 計算未來 N 天的報酬率
        for days in forward_days:
            # 未來 N 天的收盤價相較於今天的收盤價的報酬率
            df[f'Return_{days}d'] = df['Close'].shift(-days) / df['Close'] - 1
            
        # 選出有訊號的日子
        signals = df[df['Signal'] == True].copy()
        
        # 為了避免連續好幾天都觸發訊號導致重複計算，我們可以設定一個冷卻期(例如訊號發生後5天內不重複進場)
        # 這裡先簡單全部記錄，後續可以優化
        
        for date, row in signals.iterrows():
            trade = {
                'Symbol': sym,
                'Date': date.strftime('%Y-%m-%d'),
                'Close': row['Close'],
            }
            for days in forward_days:
                trade[f'Return_{days}d'] = row[f'Return_{days}d']
            all_trades.append(trade)
            
    trades_df = pd.DataFrame(all_trades)
    
    if trades_df.empty:
        print("沒有找到符合條件的歷史訊號。")
        return pd.DataFrame()
        
    print(f"\n找出總共 {len(trades_df)} 筆交易訊號。")
    print("-" * 50)
    
    # 統計結果
    metrics = []
    for days in forward_days:
        ret_col = f'Return_{days}d'
        valid_trades = trades_df.dropna(subset=[ret_col])
        if len(valid_trades) == 0:
            continue
            
        win_rate = (valid_trades[ret_col] > 0).mean() * 100
        avg_return = valid_trades[ret_col].mean() * 100
        
        print(f"持有 {days} 天統計:")
        print(f"  勝率: {win_rate:.2f}%")
        print(f"  平均報酬率: {avg_return:.2f}%")
        print(f"  樣本數: {len(valid_trades)}")
        print()
        
    return trades_df

if __name__ == "__main__":
    run_backtest()
