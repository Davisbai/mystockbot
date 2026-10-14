"""Counterfactual diagnostic variants; never changes the production strategy."""
import json
import warnings
from types import SimpleNamespace
from unittest.mock import patch
import pandas as pd
from diagnostic_baseline import load_baseline
from diagnose_tdrl_cases import OUT, primitive

baseline = load_baseline()
TaiwanStockTradingSystem = baseline.TaiwanStockTradingSystem
resolve_td_rl_strategy = baseline.resolve_td_rl_strategy


def corrected_chip_fields(df, ticker):
    raw = json.loads((OUT / (ticker + '_chips.json')).read_text(encoding='utf-8'))
    chips = pd.DataFrame(raw['data'])
    for field, name in [('Foreign_Buy', 'Foreign_Investor'), ('Trust_Buy', 'Investment_Trust')]:
        selected = chips.loc[chips['name'] == name].copy()
        selected['net'] = selected['buy'] - selected['sell']
        series = selected.groupby('date')['net'].sum() / 1000
        series.index = pd.to_datetime(series.index)
        df[field] = series.reindex(df.index).fillna(0)
    df['Margin_Balance'] = 0.
    return df


def main():
    market = pd.read_csv(OUT / 'TWII_prices.csv', index_col=0, parse_dates=True)
    result = []
    for ticker in ('1312.TW', '1326.TW'):
        prices = pd.read_csv(OUT / (ticker + '_prices.csv'), index_col=0, parse_dates=True)
        response = json.loads((OUT / (ticker + '_chips.json')).read_text(encoding='utf-8'))
        for start, corrected in [('2025-01-01', False), ('2025-09-01', False), ('2023-01-01', True)]:
            for date in ('2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08', '2026-10-12', '2026-10-13', '2026-10-14'):
                if pd.Timestamp(date) not in prices.index:
                    continue
                system = TaiwanStockTradingSystem([ticker], start_date=start)
                m = market.loc[start:date].copy()
                m['Market_MA20'] = m.Close.rolling(20).mean()
                m['Market_OK'] = m.Close > m.Market_MA20
                system.market_data = m
                with patch('STOCK_GOD.yf.download', return_value=prices.loc[start:date].copy()), \
                        patch('STOCK_GOD.requests.get', return_value=SimpleNamespace(json=lambda: response)), \
                        patch('STOCK_GOD.time.sleep'):
                    if corrected:
                        with patch.object(system, 'fetch_real_chip_data', side_effect=corrected_chip_fields):
                            frame = system.process_stock(ticker)
                    else:
                        frame = system.process_stock(ticker)
                row = frame.iloc[-1]
                alert = {'RL可用': bool(row.TD_RL_Available), '今日評分': float(row.Score),
                         'TD期待值': float(row.TD_Expected_Pct), 'RL空手策略': row.RL_Flat_Action,
                         'RL空手信心': float(row.RL_Flat_Confidence), '是否觸發賣出': bool(row.Sell_Signal)}
                mapping = {'專業起漲': 'Pro_Bottom_Breakout', '縮量埋伏': 'Ambush_Setup',
                    '假跌破': 'Fake_Break', '漲停低吸': 'Limit_Up_Pullback_Buy',
                    '恐慌反轉': 'Panic_Reversal', '獨立行情': 'Independent_Alpha',
                    '高檔背離': 'Top_Divergence', '乖離過大': 'Overextended_MA5',
                    '高位過熱': 'High_Position_Overheat', '假突破風險': 'False_Breakout_Risk'}
                alert.update({key: bool(row.get(column, False)) for key, column in mapping.items()})
                decision, reason, _ = resolve_td_rl_strategy(alert)
                result.append({'ticker': ticker, 'date': date, 'start': start, 'corrected_chip_names': corrected,
                               'score': float(row.Score), 'td': float(row.TD_Expected_Pct),
                               'raw': row.RL_Flat_Action, 'confidence': float(row.RL_Flat_Confidence),
                               'final': decision, 'reason': reason,
                               'foreign_nonzero': int((frame.Foreign_Buy != 0).sum()),
                               'trust_nonzero': int((frame.Trust_Buy != 0).sum())})
            print(ticker, start, 'corrected chips' if corrected else 'original chips', flush=True)
    (OUT / 'sensitivity.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, default=primitive), encoding='utf-8')
    print('Sensitivity analysis complete', flush=True)


if __name__ == '__main__':
    warnings.simplefilter('ignore', FutureWarning)
    main()
