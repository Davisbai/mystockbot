import sys
import yfinance as yf
import warnings
import pandas as pd
import numpy as np
import datetime
import pytz
import requests
import re
import time
import json
import os
from bs4 import BeautifulSoup
from io import StringIO
from sklearn.mixture import GaussianMixture
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import classification_report

# 引入 rich 套件以支援終端機 UI
from rich.console import Console
from rich.panel import Panel
from rich import print as rprint
# 引入 rich 套件以支援終端機 UI
from rich.table import Table
from rich.progress import track

console = Console()

try:
    import twstock
except ImportError:
    pass

# ==========================================
# 📂 本地資料庫設定 (用於記錄長期監控清單)
# ==========================================
WATCHLIST_FILE = "long_term_watchlist.json"

def load_watchlist():
    if os.path.exists(WATCHLIST_FILE):
        with open(WATCHLIST_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_watchlist(watchlist):
    with open(WATCHLIST_FILE, 'w', encoding='utf-8') as f:
        json.dump(watchlist, f, ensure_ascii=False, indent=4)

# ==========================================
# 📱 LINE 推播模組 (強化版：自動分段發送 + 本地日誌記錄)
# ==========================================
def send_line_message(text_content):
    # ⚠️ 建議未來將憑證移至 .env 檔案中以提高安全性
    line_access_token = '/2ubptsBfLObWol5cufqQGqplAv1aNCg/1fsfhKgTf3DZZzyqrjyPh2qhc1C9IGbGxMbUUe0RX3epQsAlcew7sqCrtFGedCpL3UK3FGtsjjxkgKXtT/PuPQWr0hRyP3h6uc4VmmoX5p3jWzWKl4Z3wdB04t89/1O/w1cDnyilFU='
    line_user_id = 'U98822ea2b4b6b353b3dade3ea64b5360'
    url = "https://api.line.me/v2/bot/message/push"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {line_access_token}"
    }

    # 🌟 核心修正：將超長訊息分割成多個區塊 (每塊安全上限抓 4500 字)
    MAX_LENGTH = 4500
    
    # 利用 Python 列表推導式進行字串分割
    chunks = [text_content[i:i+MAX_LENGTH] for i in range(0, len(text_content), MAX_LENGTH)]

    success_count = 0 # 記錄成功發送的段數

    for idx, chunk in enumerate(chunks):
        # 如果訊息被切成了多段，在開頭加上提示，方便你在手機上閱讀
        if len(chunks) > 1:
            chunk = f"📄 【台股獵手報告 第 {idx+1}/{len(chunks)} 頁】\n\n" + chunk
            
        data = {
            "to": line_user_id,
            "messages": [
                {
                    "type": "text",
                    "text": chunk
                }
            ]
        }
        
        try:
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status() # 檢查 HTTP 錯誤
            
            if len(chunks) > 1:
                print(f"[系統] 成功發送 LINE 推播 (第 {idx+1}/{len(chunks)} 頁)")
            else:
                print("[系統] 成功發送 LINE 推播。")
                
            success_count += 1
            time.sleep(1) # 🌟 避免連續發送太快被 LINE 官方判定為機器人攻擊而封鎖
            
        except requests.exceptions.RequestException as e:
            print(f"❌ [系統提示] 發送 LINE 訊息失敗：{e}")
            if response is not None:
                print(f"詳細錯誤內容: {response.text}")

    # ======== 📝 新增：記錄推播訊息到本地檔案 ========
    if success_count > 0:
        try:
            import datetime
            # 確保寫入 log 的時間戳記對齊台北時間 (UTC+8)
            tw_tz = datetime.timezone(datetime.timedelta(hours=8))
            now_str = datetime.datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')
            
            with open("line_push_log.txt", "a", encoding="utf-8") as f:
                f.write(f"[{now_str}] 推播紀錄 (成功發送 {success_count}/{len(chunks)} 段)\n")
                f.write(text_content + "\n")
                f.write("="*60 + "\n")
            print('[系統] 📝 推播內容已同步記錄至 line_push_log.txt')
        except Exception as log_e:
            print(f"⚠️ [系統提示] 寫入 log 檔案失敗: {log_e}")
    # ===================================================

    
# 全域的股票代碼對應表
STOCK_MAP = {
        "2303.TW": "聯電", "3481.TW": "群創", "2344.TW": "華邦電",
        "2408.TW": "南亞科", "2603.TW": "長榮", "2609.TW": "陽明",
        "2308.TW": "台達電", "2313.TW": "華通", "6770.TW": "力積電",
        "3231.TW": "緯創", "2014.TW": "中鴻"
}

# ==========================================
# 🕷️ 爬蟲模組：擷取當日強勢股與外資籌碼
# ==========================================
class YahooMarketScanner:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': 'Mozilla/5.0'})
        self.scan_limit = 15

    def get_chinese_name(self, code):
        check_code = f"{code}.TW"
        if check_code in STOCK_MAP: return STOCK_MAP[check_code]
        try:
            if 'twstock' in globals() and code in twstock.codes:
                return twstock.codes[code].name
        except: pass
        return code

    def get_foreign_buying(self, code):
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0',
                'Referer': f'https://fubon-ebrokerdj.fbs.com.tw/z/zc/zcl/zcl.djhtm?a={code}'
            }
            url = f"https://fubon-ebrokerdj.fbs.com.tw/z/zc/zcl/zcl.djhtm?a={code}"
            
            res = self.session.get(url, headers=headers, timeout=10)
            res.encoding = 'cp950'
            dfs = pd.read_html(StringIO(res.text))
            
            for df in dfs:
                if df.shape[1] < 2: continue
                combined_text = "".join([str(x) for x in df.values.flatten()])
                if '外資' in combined_text and '買賣超' in combined_text:
                    for i in range(len(df)):
                        cell_date = str(df.iloc[i, 0])
                        if '/' in cell_date and len(cell_date) <= 10:
                            raw_val = str(df.iloc[i, 1])
                            clean_val = re.sub(r'[^-0-9]', '', raw_val)
                            if clean_val: return int(clean_val), cell_date
            return 0, "無數據"
        except: return 0, "錯誤"

    def fetch_top_gainers(self):
        url = "https://tw.stock.yahoo.com/rank/change-up?exchange=TAI"
        try:
            res = self.session.get(url, timeout=10)
            soup = BeautifulSoup(res.text, 'html.parser')
            links = soup.find_all('a', href=re.compile(r'/quote/\d{4}\.TW$'))
            candidates, seen = [], set()
            for link in links:
                match = re.search(r'/quote/(\d{4})\.TW', link.get('href'))
                if match:
                    code = match.group(1)
                    if code not in seen:
                        seen.add(code)
                        candidates.append({'code': code, 'name': self.get_chinese_name(code)})
                if len(candidates) >= self.scan_limit: break
            return candidates
        except: return []

    def scan(self):
        candidates = self.fetch_top_gainers()
        qualified = []
        print(f"\n🔍 --- 掃描熱門股 (前 {len(candidates)} 名) ---")
        for item in candidates:
            code, name = item['code'], item['name']
            fb, date = self.get_foreign_buying(code)
            if fb > 0:
                print(f"{code} {name:<4}: 外資買 {fb:>5} 張 -> ✅")
                qualified.append(item)
                check_code = f"{code}.TW"
                if check_code not in STOCK_MAP: STOCK_MAP[check_code] = name
            else:
                print(f"{code} {name:<4}: 外資賣超或無資料 -> ❌")
            time.sleep(0.1)
        return qualified

# ==========================================
# 📈 策略回測與訊號分析模組 (最終整合版)
# ==========================================
class TaiwanStockTradingSystem:
    def __init__(self, tickers, start_date="2023-01-01"):
        self.tickers = tickers
        self.start_date = start_date
        self.market_ticker = "^TWII"
        self.market_data = None
        
    def fetch_market_data(self):
        print(f"\n正在獲取大盤({self.market_ticker})數據...")
        self.market_data = yf.download(self.market_ticker, start=self.start_date, progress=False, auto_adjust=False)
        if isinstance(self.market_data.columns, pd.MultiIndex):
            self.market_data.columns = self.market_data.columns.get_level_values(0)
            
        # 強制時間歸零，確保與個股完美對齊
        self.market_data.index = pd.to_datetime(self.market_data.index).tz_localize(None).normalize()
        
        self.market_data['Market_MA20'] = self.market_data['Close'].rolling(window=20).mean()
        self.market_data['Market_OK'] = self.market_data['Close'] > self.market_data['Market_MA20']

    def fetch_real_chip_data(self, df, ticker):
        code = ticker.replace('.TW', '').replace('.TWO', '')
        start_date_str = df.index[0].strftime('%Y-%m-%d')
        
        df['Foreign_Buy'] = 0.0
        df['Trust_Buy'] = 0.0
        df['Margin_Balance'] = 0.0
        
        try:
            url_inst = f"https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInstitutionalInvestorsBuySell&data_id={code}&start_date={start_date_str}"
            res_inst = requests.get(url_inst, timeout=10).json()
            
            if res_inst.get('msg') == 'success' and res_inst.get('data'):
                df_inst = pd.DataFrame(res_inst['data'])
                
                is_foreign = df_inst['name'].str.contains('外資', na=False)
                df_foreign = df_inst[is_foreign]
                if not df_foreign.empty:
                    foreign_buy = df_foreign.groupby('date').apply(lambda x: x['buy'].sum() - x['sell'].sum())
                    foreign_buy.index = pd.to_datetime(foreign_buy.index).normalize() # 確保籌碼時間也歸零
                    df['Foreign_Buy'] = foreign_buy / 1000

                is_trust = df_inst['name'] == '投信'
                df_trust = df_inst[is_trust]
                if not df_trust.empty:
                    trust_buy = df_trust.groupby('date').apply(lambda x: x['buy'].sum() - x['sell'].sum())
                    trust_buy.index = pd.to_datetime(trust_buy.index).normalize()
                    df['Trust_Buy'] = trust_buy / 1000
                    
            time.sleep(0.5)
        except Exception as e:
            pass # 略過錯誤，直接使用預設值 0
            
        df['Foreign_Buy'] = df['Foreign_Buy'].fillna(0)
        df['Trust_Buy'] = df['Trust_Buy'].fillna(0)
        return df

    def calculate_indicators(self, df):
        # 1. KD 隨機指標
        low_min = df['Low'].rolling(window=9).min()
        high_max = df['High'].rolling(window=9).max()
        df['RSV'] = 100 * (df['Close'] - low_min) / (high_max - low_min)
        df['K'] = df['RSV'].ewm(com=2, adjust=False).mean()
        df['D'] = df['K'].ewm(com=2, adjust=False).mean()
        
        # 2. MACD 指標
        exp1 = df['Close'].ewm(span=12, adjust=False).mean()
        exp2 = df['Close'].ewm(span=26, adjust=False).mean()
        df['MACD'] = exp1 - exp2
        df['Signal'] = df['MACD'].ewm(span=9, adjust=False).mean()
        
        # 3. 均線與籌碼輔助
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['Inst_Consecutive'] = ((df['Foreign_Buy'] > 0) | (df['Trust_Buy'] > 0)).rolling(window=3).sum() >= 2
        return df

    def process_stock(self, ticker):
        # 🟢 強制使用台北時間對齊 (UTC+8)
        tw_tz = datetime.timezone(datetime.timedelta(hours=8))
        tomorrow = (datetime.datetime.now(tw_tz) + datetime.timedelta(days=1)).strftime('%Y-%m-%d')
        
        df = yf.download(ticker, start=self.start_date, end=tomorrow, progress=False, auto_adjust=False)
        if df.empty: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
            
        df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
            
        df = self.fetch_real_chip_data(df, ticker)
        df = self.calculate_indicators(df)
        df = df.join(self.market_data[['Close', 'Market_OK']], how='left', rsuffix='_Mkt').ffill()
        df['Market_OK'] = df['Market_OK'].fillna(False)

        # ==========================================
        # 🚀 [一般起漲點偵測指標]
        # ==========================================
        df['Price_Breakout'] = df['Close'] >= df['Close'].rolling(window=10).max()
        df['Volume_Surge'] = df['Volume'] > (df['Volume'].rolling(window=5).mean() * 1.5)
        
        ma5 = df['Close'].rolling(5).mean()
        ma10 = df['Close'].rolling(10).mean()
        ma_max = pd.concat([ma5, ma10, df['MA20']], axis=1).max(axis=1)
        ma_min = pd.concat([ma5, ma10, df['MA20']], axis=1).min(axis=1)
        df['MA_Squeeze'] = (ma_max - ma_min) / ma_min < 0.03
        
        macd_gold_cross = (df['MACD'] > df['Signal']) & (df['MACD'].shift(1) <= df['Signal'].shift(1))
        df['Early_Start'] = macd_gold_cross & (df['MACD'] < 0)

        # ==========================================
        # 🌊 [專業版：VCP 深潭與湧泉 - 量價與波動率結構偵測]
        # ==========================================
        exp1 = df['Close'].ewm(span=10, adjust=False).mean()
        exp2 = df['Close'].ewm(span=20, adjust=False).mean()
        df['MACD_Custom'] = exp1 - exp2
        df['Signal_Custom'] = df['MACD_Custom'].ewm(span=8, adjust=False).mean()

        df['BB_Mid'] = df['Close'].rolling(window=20).mean()
        df['BB_Std'] = df['Close'].rolling(window=20).std()
        df['BB_Upper'] = df['BB_Mid'] + 2 * df['BB_Std']
        df['BB_Lower'] = df['BB_Mid'] - 2 * df['BB_Std']
        df['BBW'] = (df['BB_Upper'] - df['BB_Lower']) / df['BB_Mid'] 
        df['BBW_Min_120'] = df['BBW'].rolling(window=120).min()
        df['Is_Squeezing'] = df['BBW'] <= (df['BBW_Min_120'] * 1.3) 

        df['Up_Volume'] = np.where(df['Close'] > df['Close'].shift(1), df['Volume'], 0)
        df['Down_Volume'] = np.where(df['Close'] < df['Close'].shift(1), df['Volume'], 0)
        df['Acc_Vol_Ratio'] = df['Up_Volume'].rolling(60).sum() / (df['Down_Volume'].rolling(60).sum() + 1e-5)
        df['Smart_Money_Accumulating'] = df['Acc_Vol_Ratio'] > 1.25 

        df['Volume_Breakout_Pro'] = df['Volume'] > df['Volume'].rolling(20).mean() * 2.5
        df['Price_Breakout_BB'] = (df['Close'] > df['BB_Upper']) & (df['Close'] > df['Open'])
        df['MACD_Gold_Cross_Pro'] = (df['MACD_Custom'] > df['Signal_Custom']) & (df['MACD_Custom'].shift(1) <= df['Signal_Custom'].shift(1))
        df['MACD_Near_Zero'] = df['MACD_Custom'].abs() < (df['Close'] * 0.015) 

        df['Pro_Bottom_Breakout'] = df['Is_Squeezing'].shift(1) & \
                                    df['Smart_Money_Accumulating'] & \
                                    df['Volume_Breakout_Pro'] & \
                                    df['Price_Breakout_BB'] & \
                                    (df['MACD_Gold_Cross_Pro'] | df['MACD_Near_Zero'])

        # ==========================================
        # 🥷 [精髓：跌不動與縮量洗盤特徵 (平台埋伏)]
        # ==========================================
        df['MA5'] = df['Close'].rolling(5).mean()
        df['Volume_Dry_Up'] = df['Volume'].rolling(5).mean() < (df['Volume'].rolling(60).mean() * 0.5)
        
        df['Low_Recent_10'] = df['Low'].rolling(window=10).min()
        df['Low_Prev_10'] = df['Low'].shift(10).rolling(window=10).min()
        df['No_New_Lows'] = df['Low_Recent_10'] >= df['Low_Prev_10']
        
        big_green_candle = (df['Close'] / df['Open'] > 1.04) & (df['Volume'] > df['Volume'].rolling(20).mean() * 1.5)
        df['Has_Recent_Action'] = big_green_candle.rolling(window=20).max() == 1
        
        df['Ambush_Setup'] = df['No_New_Lows'] & df['Has_Recent_Action'] & df['Volume_Dry_Up'] & (df['Close'] > df['MA5'])

        # ==========================================
        # 🚨 [精髓：快漲完了 (逃頂/避險特徵)]
        # ==========================================
        high_vol_warning = df['Volume'] > (df['Volume'].rolling(20).mean() * 2)
        price_stagnant = df['Close'].pct_change() <= 0.01 
        high_level = df['Close'] > (df['MA20'] * 1.10)
        df['Top_Divergence'] = high_vol_warning & price_stagnant & high_level
        
        df['Overextended_MA5'] = (df['Close'] - df['MA5']) / df['MA5'] > 0.08
        
        upper_shadow = df['High'] - df[['Open', 'Close']].max(axis=1)
        candle_body = df[['Open', 'Close']].max(axis=1) - df[['Open', 'Close']].min(axis=1)
        hit_resistance = (df['High'] >= df['High'].rolling(60).max().shift(1)) & (upper_shadow > candle_body * 2)

        # ==========================================
        # 🛡️ [強化：主力洗盤與假跌破偵測]
        # ==========================================
        df['Lowest_5'] = df['Low'].rolling(window=5).min()
        # 加入 (df['Close'] > df['Open'])，確保這是一個收紅 K 的強勢拉抬日，而非下跌回檔日
        df['Fake_Break'] = (df['Close'] > df['MA20']) & (df['Lowest_5'] < df['MA20']) & (df['Close'] > df['Open']) & (df['Volume'] < df['Volume'].rolling(20).mean() * 1.2)
        
        # ==========================================
        # ⚡ [強化：沉寂多時與即將噴發偵測]
        # ==========================================
        # 40日震幅小於 10%
        df['Price_Max_40'] = df['High'].rolling(window=40).max()
        df['Price_Min_40'] = df['Low'].rolling(window=40).min()
        df['Long_Quiet'] = (df['Price_Max_40'] - df['Price_Min_40']) / df['Price_Min_40'] < 0.10
        
        # 沉寂後的成交量異動 (量增 1.5 倍)
        df['Quiet_Momentum'] = df['Long_Quiet'].shift(1) & (df['Volume'] > df['Volume'].rolling(20).mean() * 1.5) & (df['Close'] > df['Open'])

        # ==========================================
        # 🎯 [核心邏輯補回]：計算 Independent_Alpha
        # ==========================================
        df['RS_Line'] = df['Close'] / df['Close_Mkt']
        df['RS_Slope'] = df['RS_Line'].pct_change(5) 
        stock_ma20_up = df['MA20'] > df['MA20'].shift(1)
        
        df['Independent_Alpha'] = (
            (~df['Market_OK']) & 
            (df['Close'] > df['MA20']) & 
            (stock_ma20_up) & 
            (df['RS_Slope'] > 0)
        )

        # ==========================================
        # ⚖️ [評分邏輯強化]
        # ==========================================
        df['Raw_Score'] = 0
        df.loc[df['Close'] > df['MA20'], 'Raw_Score'] += 25
        df.loc[df['MACD'] > df['Signal'], 'Raw_Score'] += 25
        df.loc[df['K'] > df['D'], 'Raw_Score'] += 10
        df.loc[df['Inst_Consecutive'], 'Raw_Score'] += 20
        
        df.loc[df['Price_Breakout'] & df['Volume_Surge'], 'Raw_Score'] += 15
        df.loc[df['Price_Breakout'] & df['Volume_Surge'] & df['MA_Squeeze'].shift(1), 'Raw_Score'] += 10
        df.loc[df['Early_Start'], 'Raw_Score'] += 5
        
        # 專業級起漲與洗盤埋伏加分 (具備決定性權重)
        df.loc[df['Pro_Bottom_Breakout'], 'Raw_Score'] += 35
        df.loc[df['Ambush_Setup'], 'Raw_Score'] += 25

        df['Score'] = df['Raw_Score']
        df.loc[df['Independent_Alpha'], 'Score'] = df['Raw_Score'] 
        df.loc[(~df['Market_OK']) & (~df['Independent_Alpha']), 'Score'] = df['Raw_Score'] * 0.6
        
        # ==========================================
        # 買賣訊號與部位計算
        # ==========================================
        # ==========================================
        # ⚖️ [新增：當日動能與 K 線濾網]
        # ==========================================
        df['Is_Green_Candle'] = df['Close'] >= df['Open'] # 收紅或平盤
        df['Is_Up_Today'] = df['Returns'] > 0             # 今日上漲
        df['Is_Heavy_Drop'] = df['Returns'] < -0.02       # 跌幅超過 2% 的實體黑K

        # ==========================================
        # 買賣訊號與部位計算 (嚴格版)
        # ==========================================
        # 買進條件：分數達標 + 不能是大跌日 + 必須收紅K (防禦下跌刀子)
        df['Buy_Signal'] = (df['Score'] >= 60) & (~df['Is_Heavy_Drop']) & df['Is_Green_Candle']
        
        # 針對縮量埋伏，要求更加嚴格，跌幅不能超過 1%
        df.loc[df['Ambush_Setup'] & (df['Returns'] < -0.01), 'Buy_Signal'] = False
        
        macd_death_cross = (df['MACD'] < df['Signal']) & (df['MACD'].shift(1) >= df['Signal'].shift(1))
        break_ma20 = df['Close'] < (df['MA20'] * 0.98)
        
        # 整合逃頂訊號：原本是破月線才賣，現在加入高檔量價背離、乖離過大、假突破壓力位
        df['Sell_Signal'] = macd_death_cross | break_ma20 | df['Top_Divergence'] | df['Overextended_MA5'] | hit_resistance
        df.loc[df['Buy_Signal'], 'Sell_Signal'] = False 

        df['Position'] = np.nan
        df.loc[df['Buy_Signal'], 'Position'] = 1
        df.loc[df['Sell_Signal'], 'Position'] = 0
        df['Position'] = df['Position'].ffill().fillna(0)
        
        df['Trade_Action'] = df['Position'].diff()
        df['Returns'] = df['Close'].pct_change()
        df['Strategy_Returns'] = df['Position'].shift(1) * df['Returns']
        
        # 🌟 新增：判斷今日是否「剛」站上月線 (今日收盤 > 月線 且 昨日收盤 <= 昨日月線)
        df['Just_Crossed_MA20'] = (df['Close'] > df['MA20']) & (df['Close'].shift(1) <= df['MA20'].shift(1))
        
        return df

    def run_analysis(self):
        self.fetch_market_data()
        results_summary, daily_alerts, trade_logs = {}, {}, {}
        
        for ticker in self.tickers:
            df = self.process_stock(ticker)
            if df is None: continue
                
            trades = df[df['Strategy_Returns'] != 0]['Strategy_Returns']
            win_rate = (trades > 0).sum() / len(trades) if len(trades) > 0 else 0
            
            actions = df[df['Trade_Action'] != 0].dropna(subset=['Trade_Action'])
            trade_logs[ticker] = [
                f"{date.strftime('%Y-%m-%d')} | {'🟢 買進' if row['Trade_Action'] == 1 else '🔴 賣出'} | 價格: {row['Close']:.2f} | 觸發評分: {int(row['Score'])}"
                for date, row in actions.iterrows()
            ]

            results_summary[ticker] = {
                "總交易天數": len(trades),
                "勝率 (%)": round(win_rate * 100, 2),
                "策略累積報酬 (%)": round(((1 + df['Strategy_Returns']).prod() - 1) * 100, 2)
            }
            
            last_day = df.iloc[-1]
            daily_alerts[ticker] = {
                "日期": df.index[-1].strftime("%Y-%m-%d"),
                "收盤價": round(float(last_day['Close']), 2),
                "月線價": round(float(last_day['MA20']), 2),
                "今日漲幅": round(float(last_day['Returns']) * 100, 2) if not pd.isna(last_day['Returns']) else 0,
                "剛過月線": bool(last_day.get('Just_Crossed_MA20', False)),
                "大盤安全": bool(last_day['Market_OK']),
                "今日評分": int(last_day['Score']),
                "個股原始評分": int(last_day['Raw_Score']),
                "是否觸發賣出": bool(last_day['Sell_Signal']),
                "獨立行情": bool(last_day['Independent_Alpha']),
                "RS斜率": round(float(last_day['RS_Slope']), 4),
                "沉寂發動": bool(last_day.get('Quiet_Momentum', False)),
                "沉寂多時": bool(last_day.get('Long_Quiet', False)),
                "假跌破": bool(last_day.get('Fake_Break', False)),
                "專業起漲": bool(last_day.get('Pro_Bottom_Breakout', False)),
                "縮量埋伏": bool(last_day.get('Ambush_Setup', False)),
                "高檔背離": bool(last_day.get('Top_Divergence', False)),
                "乖離過大": bool(last_day.get('Overextended_MA5', False)),
                "收紅K": bool(last_day.get('Is_Green_Candle', False)), # 新增傳出
                "今日大跌": bool(last_day.get('Is_Heavy_Drop', False)), # 新增傳出
                
                # 🌟 新增：傳出 MACD (10, 20, 8) 的數值與訊號線
                "MACD_數值": float(last_day.get('MACD_Custom', 0.0)),
                "MACD_訊號": float(last_day.get('Signal_Custom', 0.0))
            }
            
        return results_summary, daily_alerts, trade_logs

# ==========================================
# 1️⃣ 完整掃描模組 (整合原本的自動化邏輯)
# ==========================================
import datetime
import re

def run_test(scanner):# 顯示策略回測結果 (簡版)
    console.print("\n[bold green]🚀 啟動回測分析...[/bold green]")

    tw_tz = datetime.timezone(datetime.timedelta(hours=8))
    now_str = datetime.datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')
    print(f"--- 系統啟動時間 (台北): {now_str} ---")

    # 1. 讀取目前的長期監控清單
    watchlist = load_watchlist()
    watchlist_updated = False

    # 2. 整合所有需要掃描的標的 (熱門 + 固定 + 監控中)
#    hot_stocks = scanner.scan()
#    DYNAMIC_MAP = {f"{item['code']}.TW": item['name'] for item in hot_stocks}
    STATIC_YF_MAP = {k: v for k, v in STOCK_MAP.items()}
    # 關鍵：強制將 watchlist 內的標的加入掃描，解決「現價抓不到」的問題
    WATCHLIST_MAP = {k: v.get("名稱", "") for k, v in watchlist.items()}
    
    COMBINED_MAP = {**STATIC_YF_MAP, **WATCHLIST_MAP}

    # 3. 執行回測分析 (涵蓋所有相關標的)
    system = TaiwanStockTradingSystem(
        tickers=list(COMBINED_MAP.keys()),
        start_date="2025-09-01"
    )
    summary, alerts, logs = system.run_analysis()

    print("\n" + "="*60)
    print("📋 【個股歷史進出點交易明細】")
    print("="*60)

    for stock, trade_list in logs.items():
        if not trade_list:
            continue
        print(f"📂 標的: {stock} ({COMBINED_MAP.get(stock, '')})")
        for trade in trade_list[-5:]:
            print(f"   -> {trade}")
        print("-" * 30)

    print("\n" + "="*60)
    print("📈 【策略回測結果摘要】")
    print("="*60)
    for stock, data in summary.items():
        if stock in STATIC_YF_MAP:
            print(f"🔹 {stock} {COMBINED_MAP.get(stock, ''):<4} | 勝率: {data['勝率 (%)']:>5}% | 總報酬: {data['策略累積報酬 (%)']:>6}%")
    console.print("\n[bold cyan]✅ 掃描與狀態同步完成[/bold cyan]")
    console.input("\n[dim]按 Enter 鍵返回主選單...[/dim]")

def run_full_scan_gui(scanner):
    console.print("\n[bold green]🚀 啟動全自動策略掃描 (核心同步強化版)...[/bold green]")

    tw_tz = datetime.timezone(datetime.timedelta(hours=8))
    now_str = datetime.datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M:%S')
    print(f"--- 系統啟動時間 (台北): {now_str} ---")

    watchlist = load_watchlist()
    watchlist_updated = False

    # 1. 執行掃描 (scanner.scan 內部已設定 scan_limit=30)
    hot_stocks = scanner.scan()
    DYNAMIC_MAP = {f"{item['code']}.TW": item['name'] for item in hot_stocks}
    STATIC_YF_MAP = {k: v for k, v in STOCK_MAP.items()}
    WATCHLIST_MAP = {k: v.get("名稱", "") for k, v in watchlist.items()}
    
    COMBINED_MAP = {**STATIC_YF_MAP, **DYNAMIC_MAP, **WATCHLIST_MAP}

    # 2. 執行回測分析
    system = TaiwanStockTradingSystem(
        tickers=list(COMBINED_MAP.keys()),
        start_date="2025-09-01"
    )
    summary, alerts, logs = system.run_analysis()

    # 🌟 第一段 LINE 訊息陣列 (只放今日交易提示)
    line_message_1 = [f"📊 Davis，今日台股策略掃描已完成\n時間: {now_str}\n"]

    # 3. 自動清理邏輯
    for stock in list(watchlist.keys()):
        stock_trade_history = logs.get(stock, [])
        if stock_trade_history:
            last_action = stock_trade_history[-1]
            if "🔴 賣出" in last_action or "🔴 停損" in last_action:
                print(f"♻️ [自動清理] 偵測到 {stock} 已於歷史回測結案，移出監控清單。")
                del watchlist[stock]
                watchlist_updated = True

    print("\n" + "="*60)
    print("📈 【策略回測結果摘要】")
    print("="*60)
    for stock, data in summary.items():
        if stock in DYNAMIC_MAP or stock in STATIC_YF_MAP:
            print(f"🔹 {stock} {COMBINED_MAP.get(stock, ''):<4} | 勝率: {data['勝率 (%)']:>5}% | 總報酬: {data['策略累積報酬 (%)']:>6}%")

    print("\n" + "="*60)
    print("🔔 【今日交易提示】")
    print("="*60)
    line_message_1.append("🔔 【今日交易提示】")
    
    # 4. 核心輸出與判斷迴圈
    for stock, alert in alerts.items():
        stock_name = COMBINED_MAP.get(stock, "")
        is_in_watchlist = stock in watchlist
        
        # 🌟 漲幅過濾：若非庫存且漲幅 < 3%，則不顯示 (保持清爽)
        if stock in DYNAMIC_MAP and not is_in_watchlist and alert.get('今日漲幅', 0) < 3.0:
            continue

        tag = "[熱門]" if stock in DYNAMIC_MAP else "[固定]"
        
        # 🌟 指標標籤
        crossed_ma20_tag = " 🌟[bold yellow]【剛站上月線】[/bold yellow]" if alert.get('剛過月線') else ""
        crossed_ma20_line_msg = " 🌟【剛站上月線】" if alert.get('剛過月線') else ""
        
        score = alert['今日評分']
        raw_score = alert['個股原始評分']
        market_ok = alert['大盤安全']
        
        last_trade_msg = logs[stock][-1] if stock in logs and logs[stock] else "無近期紀錄"
        display_log_msg = f"🕒 最後紀錄: {last_trade_msg}"

        # ... (前面保留) ...
        is_rebel = (not market_ok and raw_score >= 75)
        
        # 提取新訊號
        pro_bottom_breakout = alert.get('專業起漲', False)
        ambush_setup = alert.get('縮量埋伏', False)
        is_top_divergent = alert.get('高檔背離', False) or alert.get('乖離過大', False)
        fake_break = alert.get('假跌破', False)
        
        # 🌟 取得專用的 MACD (10, 20, 8) 數值
        macd_val = alert.get('MACD_數值', 0.0)
        macd_sig = alert.get('MACD_訊號', 0.0)
        
        # 🌟 判斷是否符合「水上」或「水下黃金交叉」
        macd_pass = (macd_val > 0) or (macd_val > macd_sig)

        # ==========================================
        # 🛠️ 修正點：在這裡預先給定變數初始值，防止報錯
        final_entry_date = ""
        final_entry_price = 0.0
        # ==========================================

        if alert["是否觸發賣出"]:
            if is_top_divergent:
                status = "🚨 【高檔警報：獲利了結】"
                raw_advice = "🚨 【建議賣出】 (快漲完了，短線風險極高)"
            else:
                status = "🔴 【強制賣出/停損訊號】"
                raw_advice = "🔴 【建議賣出】 (指標轉弱或破線)"
            
            if stock in watchlist:
                del watchlist[stock]
                watchlist_updated = True
                
        elif score >= 65 or is_rebel or pro_bottom_breakout or ambush_setup or fake_break:
            
            # 🛑 核心邏輯：防守濾網 (收黑或大跌的處置)
            if not alert.get("收紅K", True) or alert.get('今日漲幅', 0) < 0:
                status = "🟡 【滿足條件：等待轉強】"
                if ambush_setup:
                    raw_advice = "⚪ 【埋伏區觀察】 指標進入洗盤尾聲，但今日收黑，切勿猜底，等收紅再進場。"
                else:
                    raw_advice = "⚪ 【建議觀望】 籌碼達標但今日動能轉弱，建議等待帶量紅K確認。"
                
                # 強制清空 entry 紀錄，避免被判定為第一天發動
                final_entry_date = "" 

            # 🛑 核心邏輯：實作「降級判定」與「嚴格把關」
            elif fake_break and not macd_pass:
                status = "🟡 【列入觀察/少量試單】"
                raw_advice = "🟡 【降級判定】 觸發假跌破，但 MACD(10,20,8) 仍在水下，動能未確認"
            elif fake_break and macd_pass:
                status = "🟢 【強力買進】 (假跌破 + 動能確認)"
                raw_advice = "🔥 【綠燈放行】 假跌破真拉抬，且 MACD(10,20,8) 已翻轉，可強力試單"
            elif ambush_setup:
                status = "🥷 【縮量黃金：右側埋伏】"
                raw_advice = "🔥 【絕佳試單點】 (主力洗盤接近尾聲，今日確認收紅表態)"
            elif pro_bottom_breakout:
                status = "🌊 【VCP 波動收斂突破】"
                raw_advice = "🔥 【強力買進】 MACD 零軸啟動，建議建立核心部位"
            elif is_rebel:
                status = "⚡ 【無視大盤：獨立強勢】"
                raw_advice = "🔥 【建議進場/續抱】 (個股展現獨立特質)"
            else:
                status = "🟢 【強力買進】"
                raw_advice = "🟢 【可進場試單】 (量價與籌碼共振)"
            
            # 🌟 防追高警示濾網
            if alert.get('今日漲幅', 0) >= 7.0:
                 raw_advice = "⚠️ 【切勿追高】(今日已大漲表態，請耐心等待量縮回檔再佈局)"

            # 從回測紀錄抓取真實進場點
            final_entry_date = alert["日期"]
            final_entry_price = alert["收盤價"]

            if stock in logs and logs[stock]:
                for log_entry in reversed(logs[stock]):
                    if "🟢 買進" in log_entry:
                        parts = log_entry.split('|')
                        final_entry_date = parts[0].strip()
                        p_match = re.search(r"價格:\s*([\d\.]+)", parts[2])
                        if p_match:
                            final_entry_price = float(p_match.group(1))
                        break
                    elif "🔴 賣出" in log_entry:
                        break

            # 更新本機 Watchlist
            if stock not in watchlist or watchlist[stock].get("加入日期") != final_entry_date:
                watchlist[stock] = {"名稱": stock_name, "加入日期": final_entry_date, "加入價格": final_entry_price}
                watchlist_updated = True

            # 顯示訊息處理
            if final_entry_date == alert["日期"]:
                display_log_msg = f"🕒 動作紀錄: {final_entry_date} | 🟢 今日觸發進場 | 價格: {final_entry_price}"
            else:
                display_log_msg = f"🕒 動作紀錄: 持股續抱中 (原入場日: {final_entry_date} | 成本: {final_entry_price})"
        else:
            status = f"⚪ 【觀望】 (評分: {score}分)"
            raw_advice = f"⚪ 【建議觀望】 (評分 {raw_score} 分)"
        
        # 🌟 第一天發動 Highlight
        is_first_day = (alert.get("日期") == final_entry_date)
        first_day_term_tag = " 🚨[bold white on red]【🔥第一天發動🔥】[/bold white on red]" if is_first_day else ""
        first_day_line_tag = " 🚨【🔥第一天發動🔥】" if is_first_day else ""

        # 輸出到終端機
        print(f"{tag} {stock:<7} {stock_name:<4} | 漲幅: {alert.get('今日漲幅', 0):>5.1f}% | 收盤: {alert['收盤價']:>6.1f} | 月線: {alert['月線價']:>6.1f} | 評分: {score:>3}分{crossed_ma20_tag}{first_day_term_tag}")
        print(display_log_msg)
        print(f"👉 系統判定: {status}")
        print(f"💡 建議提示: {raw_advice}\n")
        
        # 加入第一段 LINE 訊息
        line_prefix = "🔥" if "獨立" in status else tag
        line_message_1.append(f"{line_prefix} {stock_name} ({stock.replace('.TW', '')}){crossed_ma20_line_msg}{first_day_line_tag}")
        line_message_1.append(f"漲幅: {alert.get('今日漲幅', 0)}% | 收盤: {alert['收盤價']} | 月線: {alert['月線價']}")
        line_message_1.append(display_log_msg)
        line_message_1.append(f"👉 {status}")
        if not market_ok: line_message_1.append(f"💡 獨立建議: {raw_advice}")
        line_message_1.append("")
        
    if watchlist_updated:
        save_watchlist(watchlist)

    # 🚀 推播第一段：交易提示
    if len(line_message_1) > 2:
        print("\n[系統] 準備發送第一段 LINE 推播 (今日交易提示)...")
        send_line_message("\n".join(line_message_1))
        time.sleep(1.5)
    else:
        print("\n[系統] 今日無符合條件的熱門股提示。")

    # 🌟 第二段 LINE 訊息陣列 (只放監控清單)
    line_message_2 = []
    print("\n" + "="*60)
    print("📌 【目前長期監控清單 - 狀態同步版】")
    print("="*60)
    line_message_2.append("📌 【長期監控清單】")

    if not watchlist:
        print("目前無持股標的")
        line_message_2.append("目前無持股標的")
    else:
        for stock, data in watchlist.items():
            join_price = data.get("加入價格", 0)
            join_date = data.get("加入日期", "未知")
            stock_name = data.get("名稱", "")
            
            # 同步最新成本
            if stock in logs and logs[stock]:
                for log_entry in reversed(logs[stock]):
                    if "🟢 買進" in log_entry:
                        parts = log_entry.split('|')
                        join_date = parts[0].strip()
                        p_match = re.search(r"價格:\s*([\d\.]+)", parts[2])
                        if p_match: join_price = float(p_match.group(1))
                        break
                    elif "🔴 賣出" in log_entry: break 
            
            current_price = alerts.get(stock, {}).get('收盤價', 0)
            if current_price == 0: current_price = join_price
            roi = round((current_price - join_price) / join_price * 100, 2) if join_price > 0 else 0
            emoji = "🔥" if roi >= 0 else "📉"

            print(f"📂 {stock:<7} {stock_name:<4} | 買入日期: {join_date} | 成本: {join_price:>7.1f} | 現價: {current_price:>7.1f} | 報酬: {roi:>6}%")
            
            line_message_2.append(f"{stock_name} ({stock.replace('.TW', '')})")
            line_message_2.append(f"📅 買入日期: {join_date}")
            line_message_2.append(f"💰 成本: {join_price} ➔ 現價: {current_price}")
            line_message_2.append(f"{emoji} 報酬率: {roi}%")
            line_message_2.append("") 
            
    if watchlist_updated:
        save_watchlist(watchlist)

    # 🚀 推播第二段：監控清單
    if len(line_message_2) > 1:
        print("[系統] 準備發送第二段 LINE 推播 (長期監控清單)...")
        send_line_message("\n".join(line_message_2))

    console.print("\n[bold cyan]✅ 掃描與狀態同步完成[/bold cyan]")
    if os.environ.get('GITHUB_ACTIONS') == 'true': return 
    console.input("\n[dim]按 Enter 鍵返回主選單...[/dim]")
    
# ==========================================
# 2️⃣ 單股查詢模組 (獨立呼叫回測系統)
# ==========================================
# ==========================================
# 2️⃣ 單股查詢模組 (整合 GOD_SYSTEM_V2 AI 診斷)
# ==========================================
# ==========================================
# 2️⃣ 單股查詢模組 (整合 AI 診斷 + 名稱辨識 + 連續查詢)
# ==========================================
# ==========================================
# 2️⃣ 單股查詢模組 (整合 AI 診斷 + 市場狀態文字說明)
# ==========================================
# ==========================================
# 2️⃣ 單股查詢模組 (修正名稱識別與代碼轉換)
# ==========================================
def run_single_query_mode_gui():
    # GMM 狀態說明
    REGIME_DESC = {
        0: "🟢 0 [bold green]低波動穩定期[/bold green] (多頭特徵，價格緩步推升)",
        1: "🔴 1 [bold red]高波動混亂期[/bold red] (空頭或洗盤，價格起伏巨大)",
        2: "🟡 2 [bold yellow]轉折過渡期[/bold yellow] (動能改變中，趨勢尚未明確)"
    }

    while True:
        console.print("\n" + "="*60)
        console.print("[bold yellow]🔎 進入 AI 深度診斷模式 (Meta-Labeling v3.0)[/bold yellow]")
        console.print("[dim]提示：輸入「2884」、「玉山金」或美股代碼「AAPL」皆可；輸入 'q' 返回[/dim]")
        user_input = console.input("👉 [bold cyan]請輸入股票代碼或名稱:[/bold cyan] ").strip()
        
        if not user_input or user_input.lower() == 'q':
            break
            
        ticker = ""
        stock_name = ""
        mkt_ticker = "^TWII" # 預設台股大盤

        # --- 1. 強化版代碼與市場自動辨識 (加入美股支援) ---
        user_upper = user_input.upper()
        if re.match(r'^[A-Z]+$', user_upper):  # 判斷為純英文字母 (美股代碼)
            ticker = user_upper
            stock_name = ticker
            mkt_ticker = "^GSPC"  # 美股對標 S&P 500 大盤
        else:
            try:
                import twstock
                if user_input.isdigit():
                    if user_input in twstock.codes:
                        stock_info = twstock.codes[user_input]
                        suffix = ".TW" if "上市" in stock_info.market else ".TWO"
                        ticker = f"{user_input}{suffix}"
                        stock_name = stock_info.name
                    else:
                        ticker = f"{user_input}.TW"
                        stock_name = user_input
                else:
                    found = False
                    for code, info in twstock.codes.items():
                        if user_input == info.name:
                            suffix = ".TW" if "上市" in info.market else ".TWO"
                            ticker = f"{code}{suffix}"
                            stock_name = info.name
                            found = True
                            break
                    if not found:
                        for k, v in STOCK_MAP.items():
                            if user_input in v:
                                ticker = k
                                stock_name = v
                                found = True
                                break
                    if not found:
                        console.print(f"[bold red]❌ 錯誤：無法辨識「{user_input}」。[/bold red]")
                        continue
            except Exception as e:
                ticker = f"{user_input}.TW" if user_input.isdigit() else user_input
                console.print(f"[dim red]注意：twstock 運作異常，採用預設模式...[/dim red]")

        console.print(f"\n[bold green]✅ 已識別：{stock_name} ({ticker})[/bold green]")

        # --- 2. 執行分析 ---
        try:
            with console.status(f"[bold green]正在下載 {stock_name} 數據並執行 AI 診斷...[/bold green]"):
                system = TaiwanStockTradingSystem(tickers=[ticker], start_date="2023-01-01")
                system.market_ticker = mkt_ticker  # 動態切換對標大盤
                system.fetch_market_data() 
                
                # 獲取大盤具體數值
                mkt_close = float(system.market_data['Close'].iloc[-1])
                mkt_ma20 = float(system.market_data['Market_MA20'].iloc[-1])
                
                summary, alerts, logs = system.run_analysis()
                
                if ticker not in alerts:
                    console.print(f"[bold red]❌ Yahoo Finance 無法取得 {ticker} 的歷史資料。[/bold red]")
                    continue

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

            # --- 3. 提取所有訊號與狀態 ---
            alert = alerts[ticker]
            score = alert['今日評分']
            raw_score = alert['個股原始評分']
            market_ok = alert['大盤安全']
            today_return = alert.get('今日漲幅', 0.0)
            
            is_rebel = (not market_ok and raw_score >= 75)
            pro_bottom_breakout = alert.get('專業起漲', False)
            ambush_setup = alert.get('縮量埋伏', False)
            is_top_divergent = alert.get('高檔背離', False) or alert.get('乖離過大', False)
            fake_break = alert.get('假跌破', False)
            
            macd_val = alert.get('MACD_數值', 0.0)
            macd_sig = alert.get('MACD_訊號', 0.0)
            is_water_above = (macd_val > 0)
            macd_golden_cross = (macd_val > macd_sig)

            # --- 4. 顯示結果面板 ---
            console.print(f"\n📊 [bold white on blue] {ticker} ({stock_name}) 深度診斷報告 [/bold white on blue]")
          
            diag_table = Table(show_header=False, box=None)
            diag_table.add_row("[bold]最新收盤價[/bold]", f"{alert['收盤價']} (個股月線: {alert['月線價']})")
            
            mkt_status = "✅ 站上月線" if market_ok else "❌ 跌破月線"
            mkt_color = "green" if market_ok else "red"
            
            # 根據大盤代碼顯示對應名稱
            mkt_name = "標普500" if mkt_ticker == "^GSPC" else "加權指數"
            diag_table.add_row(
                f"[bold]{mkt_name}狀態[/bold]", 
                f"[{mkt_color}]{mkt_status}[/{mkt_color}] (指數: [bold]{mkt_close:.0f}[/bold] | 月線: {mkt_ma20:.0f})"
            )
            
            diag_table.add_row("[bold]技術籌碼評分[/bold]", f"{score} 分")
            
            macd_str = "🟢 水上" if is_water_above else "🔴 水下"
            macd_cross_str = "金叉" if macd_golden_cross else "死叉"
            diag_table.add_row("[bold]MACD(10,20,8)[/bold]", f"{macd_str} ({macd_cross_str})")

            if ai_success:
                regime_text = REGIME_DESC.get(regime_idx, f"狀態 {regime_idx}")
                diag_table.add_row("[bold]GMM 市場狀態[/bold]", regime_text)
                diag_table.add_row("[bold]AI 預測勝率[/bold]", f"[bold cyan]{meta_prob*100:.1f}%[/bold cyan]")
            
            console.print(diag_table)
            console.print("-" * 40)

            # ==========================================
            # 🌟 5. 核心判定邏輯
            # ==========================================
            is_chasing_high = today_return >= 7.0
            add_to_watchlist_flag = False

            if alert.get("是否觸發賣出", False):
                if is_top_divergent:
                    console.print("👉 最終判定: [bold red]🚨 【高檔警報：獲利了結】[/bold red] (快漲完了，短線風險極高)")
                else:
                    console.print("👉 最終判定: [bold red]🔴 【強制賣出/停損訊號】[/bold red] (指標轉弱或破線)")
            
            elif score >= 65 or is_rebel or pro_bottom_breakout or ambush_setup or fake_break:
                
                if ambush_setup: base_status = "🥷 【縮量黃金：右側埋伏】"
                elif pro_bottom_breakout: base_status = "🌊 【VCP 波動收斂突破】"
                elif fake_break: base_status = "🟢 【假跌破真拉抬】 (洗盤結束)"
                elif is_rebel: base_status = "⚡ 【無視大盤：獨立強勢】"
                else: base_status = "🟢 【強力買進】"

                if is_water_above or macd_golden_cross:
                    if not ai_success or meta_prob >= 0.6:
                        if is_chasing_high:
                            console.print(f"👉 最終判定: [bold yellow]⚠️ 【切勿追高】[/bold yellow] (今日大漲 {today_return:.2f}%, 請耐心等待量縮回檔)")
                        else:
                            console.print(f"👉 最終判定: [bold green]{base_status}[/bold green] (型態與 MACD 雙重確認)")
                            add_to_watchlist_flag = True
                    else:
                        if is_chasing_high:
                            console.print("👉 最終判定: [bold yellow]🟡 【建議觀望 / ⚠️ 切勿追高】[/bold yellow] (漲幅大且 AI 勝率過低，慎防假突破)")
                        else:
                            console.print(f"👉 最終判定: [bold yellow]🟡 【建議觀望】[/bold yellow] (技術達標，但 AI 勝率僅 {meta_prob*100:.1f}%)")
                else:
                    console.print(f"👉 最終判定: [bold yellow]🟡 【降級觀望】[/bold yellow] 型態為 {base_status}，但 MACD 水下且未金叉，動能不足。")
            else:
                console.print("👉 最終判定: [bold white]⚪ 【建議觀望】[/bold white] (綜合評分與動能不足，且無特殊洗盤型態)")
                
            # --- 6. 自動收錄至長期監控清單 ---
            if add_to_watchlist_flag:
                watchlist = load_watchlist()
                entry_date = alert["日期"]
                entry_price = alert["收盤價"]
                
                if ticker in logs and logs[ticker]:
                    for log_entry in reversed(logs[ticker]):
                        if "🟢 買進" in log_entry:
                            parts = log_entry.split('|')
                            entry_date = parts[0].strip()
                            p_match = re.search(r"價格:\s*([\d\.]+)", parts[2])
                            if p_match:
                                entry_price = float(p_match.group(1))
                            break 
                        elif "🔴 賣出" in log_entry:
                            break
                
                if ticker not in watchlist or watchlist[ticker].get("加入日期") != entry_date:
                    watchlist[ticker] = {
                        "名稱": stock_name,
                        "加入日期": entry_date,
                        "加入價格": entry_price
                    }
                    save_watchlist(watchlist)
                    console.print(f"🌟 [bold cyan]【自動收錄】已將 {stock_name} ({ticker}) 納入長期監控清單！(紀錄成本: {entry_price})[/bold cyan]")

            if logs.get(ticker):
                console.print("\n📋 [dim]最近交易紀錄:[/dim]")
                for log in logs[ticker][-3:]:
                    console.print(f"   {log}")
        except Exception as e:
            console.print(f"[bold red]執行分析時發生錯誤: {e}[/bold red]")
    
    console.print("\n[bold red]已離開查詢模式。[/bold red]")

# ==========================================
# 📊 大盤現況診斷模組 (新增)
# ==========================================
def run_market_health_check_gui():
    console.print("\n[bold magenta]🌐 正在診斷台股大盤 (加權指數 ^TWII) 現況...[/bold magenta]")
    
    # 下載最近 40 天數據確保均線計算準確
    market_ticker = "^TWII"
    try:
        df = yf.download(market_ticker, period="3mo", progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        
        # 計算指標
        df['MA20'] = df['Close'].rolling(window=20).mean()
        df['MA5'] = df['Close'].rolling(window=5).mean()
        
        last_close = float(df['Close'].iloc[-1])
        ma20 = float(df['MA20'].iloc[-1])
        ma5 = float(df['MA5'].iloc[-1])
        prev_close = float(df['Close'].iloc[-2])
        
        change = last_close - prev_close
        pct_change = (change / prev_close) * 100
        dist_to_ma20 = ((last_close - ma20) / ma20) * 100
        
        # 狀態判斷
        is_above_ma20 = last_close > ma20
        is_up_trend = ma20 > df['MA20'].iloc[-5] # 月線是否上揚
        
        status_text = ""
        if is_above_ma20 and is_up_trend:
            status_text = "[bold green]🔥 多頭強勢 (站上月線且月線標高)[/bold green]"
        elif is_above_ma20 and not is_up_trend:
            status_text = "[bold yellow]⚖️ 高檔震盪 (站上月線但均線走平)[/bold yellow]"
        elif not is_above_ma20 and is_up_trend:
            status_text = "[bold cyan]🛡️ 支撐測試 (跌破月線但均線仍上揚)[/bold cyan]"
        else:
            status_text = "[bold red]❄️ 空頭架構 (跌破月線且均線下彎)[/bold red]"

        # 顯示面板
        market_panel = Panel(
            f"📍 [bold]目前指數:[/bold] {last_close:.2f} ({'+' if change>0 else ''}{change:.2f} / {pct_change:.2f}%)\n"
            f"📈 [bold]月線位置 (MA20):[/bold] {ma20:.2f} (乖離率: {dist_to_ma20:.2f}%)\n"
            f"📏 [bold]週線位置 (MA5) :[/bold] {ma5:.2f}\n"
            f"------------------------------------------\n"
            f"🛡️ [bold]大盤體質判定:[/bold] {status_text}\n"
            f"💡 [bold]操作建議:[/bold] {'適度加碼精選個股' if is_above_ma20 else '嚴控倉位，保留現金'}",
            title="🇹🇼 台股大盤即時診斷",
            border_style="magenta"
        )
        console.print(market_panel)
        
    except Exception as e:
        console.print(f"[bold red]❌ 無法獲取大盤數據: {e}[/bold red]")
    
    console.input("\n[dim]按 Enter 鍵返回主選單...[/dim]")

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
    console.print(f"\\n[bold cyan]🔍 啟動高階量化深度分析：{ticker}[/bold cyan]")
    
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
    console.print("\\n[bold white on blue] 📊 系統診斷報告 [/bold white on blue]")
    
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
        do_trade = console.input("\\n[bold cyan]❓ 是否將此訂單傳送至券商 API 進行實盤模擬? (y/n): [/bold cyan]")
        if do_trade.lower() == 'y':
            api = ShioajiMockAPI()
            api.connect()
            api.place_order(ticker, "BUY", current_price, 1000)

import datetime
from FinMind.data import DataLoader


    # 建議修改方向
def is_taiwan_stock_open():
    tw_tz = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(tw_tz)
    
    # A. 先判斷是否為週末
    if now.weekday() >= 5: # 5 是週六, 6 是週日
        return False
        
    # B. 檢查是否在 09:00 - 14:00 執行，此時 yf 可能還沒更新今日日期
    # 如果你的 GitHub Action 是在晚上 19:00 跑，則原有的比對法通常有效
    # 但若要更保險，可以改用以下邏輯：
    try:
        df = yf.download("^TWII", period="5d", progress=False)
        if df.empty: return False
        
        # 只要「最後一個交易日」跟「今天」差距在 3 天內，且今天不是週末
        # 基本上就可以視為交易日循環中
        last_trade_date = df.index[-1].date()
        delta = (now.date() - last_trade_date).days
        
        # 如果差距超過 3 天 (且排除週末)，通常代表遇到了長假
        if delta > 3:
            return False
            
        return True
    except:
        return now.weekday() < 5 # 發生錯誤時，預設週一至週五皆開市


    # ... 原有的選單與執行邏輯 ...
# ==========================================
# 🏠 主程式入口
# ==========================================
def main():
    tw_tz = datetime.timezone(datetime.timedelta(hours=8))
    rprint(f"\n🚀 啟動【台股獵手 - 專業終端版】 {datetime.datetime.now(tw_tz).strftime('%Y-%m-%d %H:%M')}")
    
    scanner = YahooMarketScanner()

    # 偵測是否為自動化環境
    is_github_action = os.environ.get('GITHUB_ACTIONS') == 'true'

    if is_github_action:
        print("偵測到 GitHub Actions 自動化環境，將執行完整策略掃描 (選項 1)...")
        # 直接執行功能，不需要經過 input
        run_full_scan_gui(scanner)
        print("✅ 自動化任務完成。")
        return # 執行完直接結束程式，避免進入無意義的迴圈

    # 如果是本地開發環境，則顯示選單
    while True:
        os.system('cls' if os.name == 'nt' else 'clear')
        
        menu = Panel(
            "1. 🚀 [bold cyan]執行完整策略掃描[/bold cyan] (大盤監控 + 庫存更新 + LINE推播)\n"
            "2. 🔎 [bold yellow]單股深度診斷[/bold yellow]\n"
            "3. 🔎 [bold yellow]回測[/bold yellow]\n"
            "5. 📊 [bold magenta]檢查大盤現況[/bold magenta]\n"
            "q. [bold red]退出系統[/bold red]",
            title="🎯 台股獵手 v2.0 - GUI Terminal",
            border_style="bright_blue"
        )
        console.print(menu)
        
        choice = console.input("\n[bold]請選擇功能: [/bold]").strip().lower()
        
        if choice == '1':
            run_full_scan_gui(scanner)
        elif choice == '2':
            run_single_query_mode_gui()
        elif choice == '3':
            run_test(scanner)
        elif choice == '5':
            run_market_health_check_gui()
        elif choice == 'q':
            console.print("\n[bold red]👋 系統已退出，祝您投資順利！[/bold red]\n")
            break
        else:
            console.print("[bold red]❌ 無效的選擇，請重新輸入。[/bold red]")
            time.sleep(1)

if __name__ == "__main__":
    main()
