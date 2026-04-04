import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import os
import warnings
from sklearn.mixture import GaussianMixture
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

# 引入 rich 套件以支援終端機 UI
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint
from rich.progress import track

warnings.filterwarnings('ignore')
console = Console()

# ==========================================\
# 📊 核心量化引擎：現代量化交易系統
# ==========================================\
class AdvancedQuantEngine:
    def __init__(self, ticker="2330.TW", target_vol=0.15):
        self.ticker = ticker
        self.target_vol = target_vol  # 目標年化波動率 15%
        self.data = pd.DataFrame()
        self.gmm_model = None
        self.meta_classifier = None
        
    def fetch_data(self, period="3y"):
        """取得歷史資料並計算基礎特徵"""
        console.print(f"[dim]📥 正在獲取 {self.ticker} 的市場數據...[/dim]")
        df = yf.download(self.ticker, period=period, progress=False)
        if df.empty:
            return False
            
        # 如果 yfinance 回傳 MultiIndex 欄位 (新版 yfinance 行為)，進行展平處理
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df['Return'] = df['Close'].pct_change()
        df['Log_Return'] = np.log(df['Close'] / df['Close'].shift(1))
        # 滾動波動率 (20日)
        df['Volatility_20'] = df['Return'].rolling(window=20).std() * np.sqrt(252)
        # 滾動波動率 (50日)
        df['Volatility_50'] = df['Return'].rolling(window=50).std() * np.sqrt(252)
        # 動能特徵
        df['Momentum_10'] = df['Close'] / df['Close'].shift(10) - 1
        df['Momentum_20'] = df['Close'] / df['Close'].shift(20) - 1
        
        self.data = df.dropna().copy()
        return True

    def detect_market_regime(self):
        """1. 市場狀態識別 (高斯混合模型 GMM)"""
        if len(self.data) < 100:
            return
            
        # 使用報酬率與波動率作為觀察特徵
        features = self.data[['Return', 'Volatility_20']].dropna()
        
        # 假設市場有 3 種狀態 (穩態、高波動、極端風險)
        self.gmm_model = GaussianMixture(n_components=3, covariance_type="full", random_state=42)
        self.gmm_model.fit(features)
        
        # 預測每日狀態
        self.data['Regime'] = self.gmm_model.predict(features)
        
    def apply_triple_barrier(self, pt_multiplier=1.5, sl_multiplier=1.0, t_max=10):
        """2. 三重屏障法 (Triple Barrier Method) - 生成動態標籤"""
        df = self.data.copy()
        events = []
        
        # 迭代每一天 (實務上應向量化或使用 CUSUM 過濾，此為簡化版)
        for i in range(len(df) - t_max):
            start_price = df['Close'].iloc[i]
            daily_vol = df['Volatility_20'].iloc[i] / np.sqrt(252)  # 日波動率
            
            if pd.isna(daily_vol) or daily_vol == 0:
                continue
                
            # 計算上下屏障
            upper_barrier = start_price * (1 + pt_multiplier * daily_vol * np.sqrt(t_max))
            lower_barrier = start_price * (1 - sl_multiplier * daily_vol * np.sqrt(t_max))
            
            hit_upper = False
            hit_lower = False
            
            # 尋找未來 t_max 天內最先觸及哪一個屏障
            for j in range(1, t_max + 1):
                future_price = df['Close'].iloc[i + j]
                
                if future_price >= upper_barrier:
                    hit_upper = True
                    events.append({'date': df.index[i], 'label': 1, 'end_date': df.index[i+j]})  # 獲利標籤
                    break
                elif future_price <= lower_barrier:
                    hit_lower = True
                    events.append({'date': df.index[i], 'label': 0, 'end_date': df.index[i+j]})  # 虧損標籤
                    break
                    
            if not hit_upper and not hit_lower:
                # 觸及時間屏障
                final_price = df['Close'].iloc[i + t_max]
                label = 1 if final_price > start_price else 0
                events.append({'date': df.index[i], 'label': label, 'end_date': df.index[i+t_max]})
                
        events_df = pd.DataFrame(events).set_index('date')
        self.data = self.data.join(events_df['label'], how='left')
        self.data['label'] = self.data['label'].fillna(0) # 未知部分先填0
        
    def train_meta_labeling_model(self):
        """3. 元標籤技術：解耦架構中的次階分類器"""
        # 初階模型：簡單的均線突破 (假設)
        self.data['SMA_20'] = self.data['Close'].rolling(window=20).mean()
        self.data['Primary_Signal'] = np.where(self.data['Close'] > self.data['SMA_20'], 1, -1)
        
        # 僅提取初階模型發出做多訊號的日子進行訓練
        trade_days = self.data[self.data['Primary_Signal'] == 1].dropna()
        
        if len(trade_days) < 50:
            console.print("[yellow]⚠️ 訊號樣本數過少，跳過元模型訓練。[/yellow]")
            return False
            
        # 特徵矩陣 X (市場特徵) 與標籤 y (三重屏障標籤)
        features = ['Volatility_20', 'Volatility_50', 'Momentum_10', 'Momentum_20', 'Regime']
        X = trade_days[features]
        y = trade_days['label']
        
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, shuffle=False)
        
        # 次階分類器：隨機森林 (決定是否要過濾掉該筆交易)
        self.meta_classifier = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
        self.meta_classifier.fit(X_train, y_train)
        
        return True
        
    def calculate_position_size(self, current_vol):
        """4. 動態部位規模調整 (Volatility-Based Position Sizing)"""
        # W_t = min(sigma_target / sigma_t, W_max)
        if pd.isna(current_vol) or current_vol == 0:
            return 0.0
        
        w_max = 1.0 # 最大資金權重 100%
        weight = min(self.target_vol / current_vol, w_max)
        return round(weight, 4)

    def simulate_twse_frictions(self, price, qty, action="BUY", is_day_trade=False):
        """5. 台股微觀摩擦成本計算 (證交稅 0.3% / 當沖 0.15% + 手續費)"""
        nominal_value = price * qty
        # 假設券商手續費 0.1425%，折扣 5 折
        fee_rate = 0.001425 * 0.5 
        fee = nominal_value * fee_rate
        
        tax = 0.0
        if action == "SELL":
            tax_rate = 0.0015 if is_day_trade else 0.003
            tax = nominal_value * tax_rate
            
        total_friction = fee + tax
        return total_friction

# ==========================================\
# 🛠️ 實盤 API 整合框架 (Mock Shioaji)
# ==========================================\
class ShioajiMockAPI:
    def __init__(self):
        self.connected = False
        
    def connect(self):
        console.print("[dim]🔄 正在與券商伺服器 (Shioaji) 建立加密連線...[/dim]")
        self.connected = True
        return True
        
    def place_order(self, ticker, action, price, qty, order_type="LMT"):
        """實盤非同步下單框架"""
        if not self.connected:
            console.print("[red]❌ 尚未連線至券商 API。[/red]")
            return
            
        console.print(f"[bold green]✅ 訂單已送出:[/bold green] {action} {ticker} | 數量: {qty} | 價格: {price} | 類型: {order_type}")
        console.print("[dim]   > 狀態: [Submitted] 正在等待交易所撮合...[/dim]")

# ==========================================\
# 🏠 主程式入口
# ==========================================\
def run_analysis(ticker):
    console.print(f"\n[bold cyan]🔍 啟動高階量化深度分析：{ticker}[/bold cyan]")
    
    engine = AdvancedQuantEngine(ticker=ticker)
    if not engine.fetch_data(period="2y"):
        console.print("[red]❌ 無法獲取資料。[/red]")
        return
        
    # 執行量化管道
    with console.status("[bold green]正在執行市場狀態識別 (GMM)...[/bold green]"):
        engine.detect_market_regime()
        
    with console.status("[bold green]正在運算三重屏障動態標籤 (TBM)...[/bold green]"):
        engine.apply_triple_barrier()
        
    with console.status("[bold green]正在訓練元標籤次階分類器 (Meta-Labeling)...[/bold green]"):
        model_trained = engine.train_meta_labeling_model()
        
    # 取得最新一天的狀態
    latest_data = engine.data.iloc[-1]
    prev_data = engine.data.iloc[-2]
    
    # 判斷今日初階訊號
    current_price = latest_data['Close']
    sma_20 = latest_data['SMA_20']
    primary_signal = 1 if current_price > sma_20 else -1
    
    # 元標籤過濾
    meta_prob = 0.0
    execute_trade = False
    
    if primary_signal == 1 and model_trained:
        features = latest_data[['Volatility_20', 'Volatility_50', 'Momentum_10', 'Momentum_20', 'Regime']].values.reshape(1, -1)
        # 次階分類器預測是否會獲利 (機率)
        meta_prob = engine.meta_classifier.predict_proba(features)[0][1] 
        execute_trade = meta_prob > 0.6  # 信心度大於 60% 才執行
        
    # 計算動態部位規模
    volatility = latest_data['Volatility_20']
    target_weight = engine.calculate_position_size(volatility)
    
    # 計算摩擦成本範例 (假設買入 1000 股)
    friction = engine.simulate_twse_frictions(current_price, 1000, "BUY")
    
    # 輸出分析結果
    console.print("\n[bold white on blue] 📊 系統診斷報告 [/bold white on blue]")
    
    table = Table(show_header=False, box=None)
    table.add_row("[bold]最新收盤價[/bold]", f"{current_price:.2f}")
    table.add_row("[bold]GMM 市場狀態[/bold]", f"狀態 {int(latest_data['Regime'])} (可反映動能或波動特徵)")
    table.add_row("[bold]20日年化波動率[/bold]", f"{volatility*100:.2f}%")
    table.add_row("[bold]初階策略訊號[/bold]", "[green]做多 (均線之上)[/green]" if primary_signal == 1 else "[red]觀望 (均線之下)[/red]")
    
    if primary_signal == 1:
        table.add_row("[bold]次階 AI 勝率預測[/bold]", f"{meta_prob*100:.1f}%")
        table.add_row("[bold]系統最終決策[/bold]", "[bold green]✅ 建議執行[/bold green]" if execute_trade else "[bold yellow]🚫 過濾偽陽性 (拒絕執行)[/bold yellow]")
        table.add_row("[bold]動態建議資金權重[/bold]", f"{target_weight*100:.1f}% (基於波動率目標)")
        table.add_row("[bold]台股單筆預估摩擦成本[/bold]", f"{friction:.1f} TWD (以1000股計，含手續費)")
        
    console.print(table)
    
    if execute_trade:
        do_trade = console.input("\n[bold cyan]❓ 是否將此訂單傳送至券商 API 進行實盤模擬? (y/n): [/bold cyan]")
        if do_trade.lower() == 'y':
            api = ShioajiMockAPI()
            api.connect()
            api.place_order(ticker, "BUY", current_price, 1000)

def main():
    os.system('cls' if os.name == 'nt' else 'clear')
    rprint(f"\n🚀 啟動【現代量化交易終端機 - Meta-Labeling 核心版】 {datetime.datetime.now().date()}")
    
    while True:
        menu = Panel(
            "1. 🔬 [bold cyan]執行高階策略分析[/bold cyan] (GMM 狀態 + 三重屏障 + 元標籤過濾)\n"
            "q. [bold red]退出系統[/bold red]",
            title="🎯 量化核心 v3.0",
            border_style="bright_blue"
        )
        console.print(menu)
        
        choice = console.input("[bold cyan]請選擇功能 (1/q): [/bold cyan]").strip()
        
        if choice == '1':
            ticker = console.input("[bold yellow]請輸入台股代號 (例如 2330.TW): [/bold yellow]").strip()
            if ticker:
                if not ticker.endswith(".TW") and not ticker.endswith(".TWO"):
                    ticker += ".TW"
                run_analysis(ticker)
                console.input("\n[dim]按 Enter 鍵返回主選單...[/dim]")
        elif choice.lower() == 'q':
            console.print("👋 系統已退出。")
            break

if __name__ == "__main__":
    main()
