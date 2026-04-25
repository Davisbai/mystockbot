import pandas as pd
import numpy as np
import yfinance as yf

# ==========================================
# 🛡️ 模組 1：風控系統 (Risk Management)
# ==========================================
class RiskManager:
    def __init__(self, stop_loss_pct=0.08, trailing_stop_pct=0.15):
        self.stop_loss_pct = stop_loss_pct        # 固定停損 8%
        self.trailing_stop_pct = trailing_stop_pct # 移動停利 15% (從高點回落)

    def apply_risk_control(self, df):
        """向量化計算停損與移動停利訊號"""
        df['Entry_Price'] = np.nan
        df['Highest_Since_Entry'] = np.nan
        df['Risk_Sell_Signal'] = False

        in_position = False
        entry_p = 0.0
        highest_p = 0.0

        # 這裡使用迴圈來精準模擬真實部位狀態 (雖然較慢，但在日K級別絕對夠用且精準)
        for i in range(len(df)):
            if df['Buy_Signal'].iloc[i] and not in_position:
                in_position = True
                entry_p = df['Close'].iloc[i]
                highest_p = entry_p
            
            if in_position:
                current_p = df['Close'].iloc[i]
                highest_p = max(highest_p, current_p)
                
                df.iloc[i, df.columns.get_loc('Entry_Price')] = entry_p
                df.iloc[i, df.columns.get_loc('Highest_Since_Entry')] = highest_p
                
                # 觸發固定停損 或 移動停利
                if current_p < entry_p * (1 - self.stop_loss_pct) or \
                   current_p < highest_p * (1 - self.trailing_stop_pct):
                    df.iloc[i, df.columns.get_loc('Risk_Sell_Signal')] = True
                    in_position = False
                    entry_p = 0.0
                    highest_p = 0.0
            
            # 若原始策略觸發賣出，也重置部位
            elif df['Sell_Signal'].iloc[i] and in_position:
                in_position = False
                entry_p = 0.0
                highest_p = 0.0

        return df

# ==========================================
# 📊 模組 2：績效評估 (Performance Metrics)
# ==========================================
class PerformanceMetrics:
    @staticmethod
    def calculate(df):
        """計算機構級別的績效指標"""
        if 'Strategy_Returns' not in df.columns:
            return {}
            
        returns = df['Strategy_Returns'].fillna(0)
        
        # 1. 總報酬率
        cum_returns = (1 + returns).cumprod()
        total_return = (cum_returns.iloc[-1] - 1) * 100 if len(cum_returns) > 0 else 0
        
        # 2. Sharpe Ratio (假設無風險利率 2%)
        daily_rf = 0.02 / 252
        excess_returns = returns - daily_rf
        sharpe_ratio = (excess_returns.mean() / returns.std()) * np.sqrt(252) if returns.std() > 0 else 0
        
        # 3. 最大回撤 (Max Drawdown)
        rolling_max = cum_returns.cummax()
        drawdown = (cum_returns - rolling_max) / rolling_max
        max_drawdown = drawdown.min() * 100
        
        # 4. 勝率
        win_rate = (returns > 0).sum() / (returns != 0).sum() * 100 if (returns != 0).sum() > 0 else 0

        return {
            "總報酬 (%)": round(total_return, 2),
            "勝率 (%)": round(win_rate, 2),
            "Sharpe Ratio": round(sharpe_ratio, 2),
            "最大回撤 (%)": round(max_drawdown, 2)
        }

# ==========================================
# 🧠 模組 3：精簡版策略引擎 (Strategy Layer)
# ==========================================
class CoreStrategy:
    def __init__(self):
        # 保留最核心的 MACD 參數設定 (10, 20, 8)
        self.macd_fast = 10
        self.macd_slow = 20
        self.macd_signal = 8

    def generate_signals(self, df):
        # 1. 基礎均線 (MA20 是核心濾網)
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA5'] = df['Close'].rolling(window=5).mean()
        
        # 2. 客製化 MACD (10, 20, 8)
        exp1 = df['Close'].ewm(span=self.macd_fast, adjust=False).mean()
        exp2 = df['Close'].ewm(span=self.macd_slow, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal'] = df['MACD'].ewm(span=self.macd_signal, adjust=False).mean()
        
        # 3. 核心買點：VCP / 縮量埋伏 / MACD 零軸金叉
        macd_gold_cross = (df['MACD'] > df['Signal']) & (df['MACD'].shift(1) <= df['Signal'].shift(1))
        df['Volume_Dry_Up'] = df['Volume'].rolling(5).mean() < (df['Volume'].rolling(60).mean() * 0.5)
        
        # 買進訊號：站上月線 + MACD 金叉 + (可選加入縮量埋伏邏輯)
        df['Buy_Signal'] = (df['Close'] > df['MA20']) & macd_gold_cross
        
        # 4. 基礎賣點：破月線 或 高檔爆量背離 (逃頂)
        df['Top_Divergence'] = (df['Volume'] > df['Volume'].rolling(20).mean() * 2) & \
                               (df['Close'].pct_change() <= 0.01) & \
                               (df['Close'] > df['MA20'] * 1.10)
                               
        df['Sell_Signal'] = (df['Close'] < df['MA20'] * 0.98) | df['Top_Divergence']
        
        return df

# ==========================================
# ⚙️ 模組 4：執行與回測大腦 (Execution Layer)
# ==========================================
class V3TradingSystem:
    def __init__(self, ticker, start_date="2023-01-01"):
        self.ticker = ticker
        self.start_date = start_date
        self.strategy = CoreStrategy()
        self.risk_manager = RiskManager(stop_loss_pct=0.08, trailing_stop_pct=0.15)
        self.metrics = PerformanceMetrics()
        
    def run(self):
        # 1. 獲取資料
        df = yf.download(self.ticker, start=self.start_date, progress=False, auto_adjust=True)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        # 2. 生成策略訊號
        df = self.strategy.generate_signals(df)
        
        # 3. 套用風控系統 (強制覆寫賣出訊號)
        df = self.risk_manager.apply_risk_control(df)
        df['Final_Sell'] = df['Sell_Signal'] | df['Risk_Sell_Signal']
        
        # 4. 計算部位與真實報酬 (嚴格依據系統買入日期與價格計算)
        df['Position'] = np.nan
        df.loc[df['Buy_Signal'], 'Position'] = 1
        df.loc[df['Final_Sell'], 'Position'] = 0
        df['Position'] = df['Position'].ffill().fillna(0)
        
        df['Returns'] = df['Close'].pct_change()
        df['Strategy_Returns'] = df['Position'].shift(1) * df['Returns']
        
        # 5. 輸出績效
        performance = self.metrics.calculate(df)
        return df, performance

# 測試運行範例
if __name__ == "__main__":
    system = V3TradingSystem(ticker="2330.TW")
    df, stats = system.run()
    print("V3 系統回測結果：", stats)