"""Read-only, point-in-time investigation of 1312/1326; never trades/pushes."""
import datetime
import hashlib
import json
import re
import warnings
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import requests
import yfinance as yf
from diagnostic_baseline import load_baseline

baseline = load_baseline()
TaiwanStockTradingSystem = baseline.TaiwanStockTradingSystem
TDRLDecisionEngine = baseline.TDRLDecisionEngine
resolve_td_rl_strategy = baseline.resolve_td_rl_strategy

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'diagnostics' / 'tdrl_20261014'
OUT.mkdir(parents=True, exist_ok=True)
AS_OF = pd.Timestamp('2026-10-14')


def primitive(value):
    if isinstance(value, (np.integer, np.floating, np.bool_)):
        return value.item()
    raise TypeError(str(type(value)))


def load_prices(ticker):
    path = OUT / (ticker.replace('^', '') + '_prices.csv')
    if path.exists():
        return pd.read_csv(path, index_col=0, parse_dates=True)
    df = yf.download(ticker, start='2023-01-01', end='2026-10-15',
                     auto_adjust=True, progress=False, threads=False, timeout=15)
    if df.empty:
        raise ValueError(f'{ticker}: no prices from provider')
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df.index = pd.to_datetime(df.index).tz_localize(None).normalize()
    df.to_csv(path)
    return df


def load_chips(ticker):
    path = OUT / (ticker + '_chips.json')
    if path.exists():
        return json.loads(path.read_text(encoding='utf-8'))
    try:
        response = requests.get('https://api.finmindtrade.com/api/v4/data', params={
            'dataset': 'TaiwanStockInstitutionalInvestorsBuySell',
            'data_id': ticker.split('.')[0], 'start_date': '2023-01-01',
            'end_date': '2026-10-14'}, timeout=15)
        result = response.json()
    except Exception as exc:
        result = {'msg': str(exc), 'data': []}
    path.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return result


def audit_log(text):
    pattern = re.compile(r'TD/RL:\s*(\w+)\s*\|\s*TD期待:\s*([+\-\d.]+)%\s*\|\s*RL原始:\s*(\w+)\s*\|\s*(?:信心|Q偏好):\s*([\d.]+)(?:%|/100)')
    rows = [m.groups() for m in pattern.finditer(text)]
    return {'raw_vs_final_counts': dict(Counter(f'{raw}->{final}' for final, td, raw, confidence in rows)),
            'sell_overridden_while_td_positive': sum(raw == 'SELL' and final == 'WATCH' and float(td) > 0 for final, td, raw, confidence in rows),
            'case_mentions': {name: len(re.findall(name, text)) for name in ('國喬', '台化')},
            'parsed_decisions': len(rows)}


def structural_probes():
    base = {'Score': 65, 'Close': 100, 'MA20': 99, 'MACD': 1, 'Signal': 0, 'Market_OK': True}
    detailed = dict(base, Strong_Candle_Structure=True, Pre_Big_Red_Setup=True,
                    Fresh_60D_High=True, Fresh_Volume_Breakout=True, Short_Term_Eligible=True)
    engine = TDRLDecisionEngine()
    alert = {'RL可用': True, '今日評分': 65, 'TD期待值': 1.,
             'RL持有策略': 'SELL', 'RL持有信心': 90.}
    decision = resolve_td_rl_strategy(alert, is_held=True)
    return {'seven_rule_details_same_state': engine._market_state(base) == engine._market_state(detailed),
            'base_state': engine._market_state(base),
            'raw_sell_positive_td_final': decision,
            'confidence_gap5_support20': engine._confidence_from_q(np.array([0., 5., 0.]), (0, 1), 20)}


def main():
    report = {'source_main_sha': '6a9702f9c3c31cea420648f4c731e99cc934174a',
              'baseline_ref': '6a9702f9c3c31cea420648f4c731e99cc934174a:STOCK_GOD.py',
              'cutoff': str(AS_OF.date()), 'structural_probes': structural_probes(),
              'log_audit': audit_log((ROOT / 'line_push_log.txt').read_text(encoding='utf-8')),
              'cases': {}, 'limitations': ['Reconstruction, not a saved original model.',
              'Latest provider-adjusted history may differ from historical releases.',
              'No future return is used as an entry label; no orders or watchlist writes.']}
    try:
        market = load_prices('^TWII')
    except Exception as exc:
        report['market_data_error'] = str(exc)
        market = None
    for ticker in ('1312.TW', '1326.TW'):
        print('Investigating', ticker, flush=True)
        try:
            if market is None:
                raise ValueError('Market prices unavailable; cannot reconstruct cases')
            prices = load_prices(ticker)
            chip_response = load_chips(ticker)
            names = sorted({str(row.get('name')) for row in chip_response.get('data', [])})
            rows = []
            days = prices.index[(prices.index >= '2026-10-01') & (prices.index <= AS_OF)]
            if len(days) == 0:
                raise ValueError(f'No October case data; latest provider date is {prices.index.max()}')
            for day in days:
                history = prices.loc[:day].copy()
                market_history = market.loc[:day].copy()
                market_history['Market_MA20'] = market_history.Close.rolling(20).mean()
                market_history['Market_OK'] = market_history.Close > market_history.Market_MA20
                system = TaiwanStockTradingSystem([ticker])
                system.market_data = market_history
                with patch('STOCK_GOD.yf.download', return_value=history), \
                        patch('STOCK_GOD.requests.get', return_value=SimpleNamespace(json=lambda: chip_response)), \
                        patch('STOCK_GOD.time.sleep'):
                    frame = system.process_stock(ticker)
                last = frame.iloc[-1]
                engine = TDRLDecisionEngine()
                states = Counter(engine._market_state(row) for row in frame.iloc[:-1].to_dict('records'))
                alert = {
                    'RL可用': bool(last.TD_RL_Available), '今日評分': float(last.Score),
                    'TD期待值': float(last.TD_Expected_Pct), 'RL空手策略': last.RL_Flat_Action,
                    'RL空手信心': float(last.RL_Flat_Confidence), '是否觸發賣出': bool(last.Sell_Signal),
                }
                mapping = {'專業起漲': 'Pro_Bottom_Breakout', '縮量埋伏': 'Ambush_Setup',
                    '假跌破': 'Fake_Break', '漲停低吸': 'Limit_Up_Pullback_Buy',
                    '恐慌反轉': 'Panic_Reversal', '獨立行情': 'Independent_Alpha',
                    '高檔背離': 'Top_Divergence', '乖離過大': 'Overextended_MA5',
                    '高位過熱': 'High_Position_Overheat', '假突破風險': 'False_Breakout_Risk'}
                alert.update({key: bool(last.get(col, False)) for key, col in mapping.items()})
                final, reason, meta = resolve_td_rl_strategy(alert, is_held=False)
                rows.append(dict(date=str(day.date()), close=float(last.Close), score=float(last.Score),
                    state=engine._market_state(last), state_exact_transitions=states[engine._market_state(last)],
                    raw_rl=last.RL_Flat_Action, td=float(last.TD_Expected_Pct),
                    confidence=float(last.RL_Flat_Confidence), q_buy=float(last.RL_Q_Buy_Flat),
                    q_wait=float(last.RL_Q_Hold_Flat), final=final, reason=reason,
                    hard_sell=bool(last.Sell_Signal), flags={col: bool(last.get(col, False)) for col in [
                        'Trend_Up_Strong', 'Strong_Candle_Structure', 'Pre_Big_Red_Setup',
                        'Short_Term_Eligible', 'Fresh_60D_High', 'Fresh_Volume_Breakout',
                        'High_Position_Overheat', 'Overextended_MA5', 'Top_Divergence',
                        'False_Breakout_Risk', 'Panic_Reversal']},
                    foreign_nonzero_days=int((frame.Foreign_Buy != 0).sum()),
                    trust_nonzero_days=int((frame.Trust_Buy != 0).sum())))
            report['cases'][ticker] = {'provider_chip_names': names, 'chip_message': chip_response.get('msg'), 'days': rows}
        except Exception as exc:
            report['cases'][ticker] = {'error': str(exc)}
    path = OUT / 'diagnosis.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=primitive), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, default=primitive), flush=True)


if __name__ == '__main__':
    warnings.simplefilter('ignore', FutureWarning)
    main()
