"""Frozen-data diagnostic comparison; no push, orders, or watchlist writes."""
import json
import hashlib
import warnings
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import STOCK_GOD as current
from strategy_performance import backtest_signals
from diagnose_tdrl_cases import OUT, load_prices, load_chips, primitive
from diagnostic_baseline import load_baseline, json_safe
from strategy_config import MODEL_VERSION, TRAINING_START_DATE


def alert_from_row(row, rl):
    alert = {'RL可用': rl['available'], '今日評分': float(row.Score),
             'TD期待值': rl['td_expected_pct'], 'RL空手策略': rl['flat_action'],
             'RL空手信心': rl['flat_confidence'], 'RL持有策略': rl['held_action'],
             'RL持有信心': rl['held_confidence'], '籌碼資料狀態': row.get('Chip_Data_Status', 'unavailable')}
    mapping = {'專業起漲': 'Pro_Bottom_Breakout', '縮量埋伏': 'Ambush_Setup',
               '假跌破': 'Fake_Break', '漲停低吸': 'Limit_Up_Pullback_Buy',
               '恐慌反轉': 'Panic_Reversal', '獨立行情': 'Independent_Alpha',
               '高檔背離': 'Top_Divergence', '乖離過大': 'Overextended_MA5',
               '高位過熱': 'High_Position_Overheat', '假突破風險': 'False_Breakout_Risk'}
    alert.update({key: bool(row.get(column, False)) for key, column in mapping.items()})
    return alert


def walk_forward(frame, baseline, start='2026-09-01', end='2026-09-30'):
    period = frame.loc[start:end].copy()
    records = []
    positions = {'old_extension_exit': 0, 'extension_warning': 0}
    targets = dict(positions)
    signals = {key: [] for key in positions}
    for date, row in period.iterrows():
        # Both policies see the same strictly prefix-only, corrected inputs.
        history = frame.loc[:date]
        rl = current.TDRLDecisionEngine().fit_predict(history)
        base_alert = alert_from_row(row, rl)
        for variant in positions:
            positions[variant] = targets[variant]  # yesterday's signal fills at this open
            alert = dict(base_alert)
            alert['價格延伸退出政策'] = 'legacy_exit' if variant == 'old_extension_exit' else 'warning'
            alert['是否觸發賣出'] = bool(row.Sell_Signal) or (variant == 'old_extension_exit' and bool(row.Overextended_MA5))
            resolver = baseline.resolve_td_rl_strategy if variant == 'old_extension_exit' else current.resolve_td_rl_strategy
            action, reason, _ = resolver(alert, is_held=bool(positions[variant]))
            if action == 'BUY' and alert['籌碼資料狀態'] not in ('available', 'not_applicable'):
                action, reason = 'WATCH', 'Common input-quality gate: institutional data incomplete'
            signals[variant].append((action == 'BUY', action == 'SELL'))
            targets[variant] = 1 if action == 'BUY' else 0 if action == 'SELL' else positions[variant]
            records.append({'date': str(date.date()), 'variant': variant, 'action': action,
                            'held_at_close': positions[variant], 'raw_flat': rl['flat_action'],
                            'raw_held': rl['held_action'], 'td': rl['td_expected_pct'], 'reason': reason})
    result = {}
    for variant, values in signals.items():
        data = period.copy()
        data['Buy_Signal'] = [buy for buy, sell in values]
        data['Sell_Signal'] = [sell for buy, sell in values]
        evaluated = backtest_signals(data)
        result[variant] = evaluated.attrs['performance']
    return result, records


def main():
    baseline = load_baseline()
    market = load_prices('^TWII')
    report = {'period': ['2026-09-01', '2026-09-30'],
              'baseline_commit': '6a9702f9c3c31cea420648f4c731e99cc934174a',
              'model_version': MODEL_VERSION, 'training_start': TRAINING_START_DATE,
              'core_sha256': hashlib.sha256(Path('STOCK_GOD.py').read_bytes()).hexdigest(),
              'comparison': 'Both variants use corrected data and identical entry data-quality gates; compare extension exit policies.',
              'controls': ['2330.TW', '2303.TW', '2603.TW', '2884.TW', '2014.TW', '1216.TW'],
              'cases': ['1312.TW', '1326.TW'], 'results': {},
              'limitations': ['Research reconstruction on latest adjusted historical data.',
                             'September controls precede October examples but this is not a broad untouched validation set.',
                             'Daily prefix refit; next-open execution; 0.08% buy and 0.38% sell research costs.',
                             'No liquidity/limit-up fill simulation; open trades marked to close.']}
    for ticker in report['cases'] + report['controls']:
        print('Validating', ticker, flush=True)
        try:
            prices = load_prices(ticker)
            response = load_chips(ticker)
            system = current.TaiwanStockTradingSystem([ticker], extension_exit_mode='warning')
            system.market_data = market.assign(Market_OK=market.Close > market.Close.rolling(20).mean())
            with patch('STOCK_GOD.yf.download', return_value=prices.copy()), \
                    patch('STOCK_GOD.requests.get', return_value=SimpleNamespace(json=lambda: response)):
                frame = system.process_stock(ticker)
            rule_results = {}
            for variant in ('old_extension_exit', 'extension_warning'):
                data = frame.loc['2025-01-01':'2026-09-30'].copy()
                data['Sell_Signal'] = data.Hard_Sell_Signal | (data.Overextended_MA5 if variant == 'old_extension_exit' else False)
                data['Buy_Signal'] = (data.Score >= 60) & ~data.Sell_Signal
                if variant == 'extension_warning':
                    data['Buy_Signal'] &= ~data.Extension_Warning
                rule_results[variant] = backtest_signals(data).attrs['performance']
            decisions, traces = walk_forward(frame, baseline)
            report['results'][ticker] = {'rule_comparison': rule_results, 'full_arbiter': decisions,
                                         'chip_available_days': int(frame.Chip_Data_Available.sum()),
                                         'decisions': traces}
        except Exception as exc:
            report['results'][ticker] = {'error': str(exc)}
        (OUT / 'adjustment_validation.json').write_text(json.dumps(json_safe(report), ensure_ascii=False, indent=2, default=primitive, allow_nan=False), encoding='utf-8')
    print('Validation saved', flush=True)


if __name__ == '__main__':
    warnings.simplefilter('ignore', FutureWarning)
    main()
