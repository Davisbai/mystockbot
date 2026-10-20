"""Offline rule-entry research. Never used by app.py, scheduling, or LINE."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from strategy_performance import backtest_signals

CASES = ('6561.TWO', '1312.TW', '1326.TW')
CONTROLS = ('2330.TW', '2303.TW', '2603.TW', '2884.TW', '2014.TW', '1216.TW')
# Fixed structural hypotheses, declared before downloading comparison data.
VARIANTS = ('baseline', 'cooldown_3', 'confirm_2', 'ma20_rising', 'evidence', 'evidence_confirm_2')
EVIDENCE = ('Inst_Consecutive', 'Pro_Bottom_Breakout', 'Ambush_Setup', 'Limit_Up_Pullback_Buy')
EXIT_REASONS = ('MACD_Death_Cross', 'MA20_Broken', 'Top_Divergence', 'Resistance_Rejection',
                'Limit_Up_Support_Broken', 'False_Breakout_Risk', 'Overextended_MA5')


def flag(frame, column):
    return frame[column].astype('boolean').fillna(False).astype(bool) if column in frame else pd.Series(False, index=frame.index)


def entry_evidence(frame):
    evidence = flag(frame, 'Price_Breakout') & flag(frame, 'Volume_Surge')
    for name in EVIDENCE:
        evidence |= flag(frame, name)
    return evidence


def entry_candidates(frame, variant):
    buy = flag(frame, 'Buy_Signal')
    if variant in ('confirm_2', 'evidence_confirm_2'):
        buy = buy & buy.shift(1, fill_value=False)
    if variant == 'ma20_rising':
        buy &= frame['MA20'] > frame['MA20'].shift(5)
    if variant in ('evidence', 'evidence_confirm_2'):
        buy &= entry_evidence(frame)
    if variant not in VARIANTS:
        raise ValueError('Unknown research variant')
    return buy


def cooldown_signals(frame, sessions=3):
    """Suppress fresh entries for three complete closes after an executed exit."""
    buy = flag(frame, 'Buy_Signal').copy()
    sell = flag(frame, 'Sell_Signal').to_numpy()
    position, pending, last_exit = 0, 0, -sessions - 1
    for i in range(len(frame)):
        if position == 1 and pending == 0:
            last_exit = i
        position = pending
        if not position and i - last_exit < sessions:
            buy.iloc[i] = False
        pending = 0 if sell[i] else (1 if buy.iloc[i] else position)
    return buy


def evaluate(frame, variant, start, end):
    data = frame.copy()
    data['Buy_Signal'] = entry_candidates(data, variant)
    data = data.loc[start:end].copy()
    if variant == 'cooldown_3':
        data['Buy_Signal'] = cooldown_signals(data)
    result = backtest_signals(data)
    trades = result.attrs['completed_trades']
    net = float((1 + result.Strategy_Returns).prod())
    gross = net / ((1 - .0008) ** int(result.Trade_Action.eq(1).sum())
                   * (1 - .0038) ** int(result.Trade_Action.eq(-1).sum()))
    return result, {
        'net_return_pct': round((net - 1) * 100, 4),
        'gross_return_pct': round((gross - 1) * 100, 4),
        'max_drawdown_pct': result.attrs['performance']['最大回撤 (%)'],
        'completed_trades': len(trades), 'held_sessions': int(result.Position.sum()),
        'win_rate_pct': round(100 * sum(t['net_return'] > 0 for t in trades) / len(trades), 2) if trades else None,
        'chip_available_fraction': round(float(flag(data, 'Chip_Data_Available').mean()), 4) if len(data) else None,
    }


def trade_audit(result):
    rows, reason_counts = [], Counter()
    evidence = entry_evidence(result)
    for trade in result.attrs['completed_trades']:
        i, j = result.index.get_loc(trade['entry_date']), result.index.get_loc(trade['exit_date'])
        signal = result.iloc[i - 1]
        reasons = [name for name in EXIT_REASONS if name in result and flag(result, name).iloc[j - 1]]
        if trade['net_return'] < 0:
            reason_counts.update(reasons)
        gross = trade['exit_price'] / trade['entry_price'] - 1
        rows.append({
            'entry_date': trade['entry_date'].strftime('%Y-%m-%d'),
            'exit_date': trade['exit_date'].strftime('%Y-%m-%d'), 'held_sessions': int(j - i),
            'gross_return_pct': round(100 * gross, 4),
            'net_return_pct': round(100 * trade['net_return'], 4),
            'entry_score': float(signal.Score), 'exit_reasons': reasons,
            'independent_evidence': bool(evidence.iloc[i - 1]),
        })
    losses = [row for row in rows if row['net_return_pct'] < 0]
    short = [row for row in rows if row['held_sessions'] <= 3]
    return {
        'trades': rows, 'losing_trades': len(losses),
        'short_trades_at_most_3_sessions': len(short),
        'short_trade_losses': sum(row['net_return_pct'] < 0 for row in short),
        'gross_winners_lost_to_cost': sum(row['gross_return_pct'] > 0 and row['net_return_pct'] <= 0 for row in rows),
        'losing_exit_reason_counts': dict(reason_counts),
    }


def comparison(rows, period, variant):
    base = [rows[ticker][period]['baseline'] for ticker in CONTROLS]
    candidate = [rows[ticker][period][variant] for ticker in CONTROLS]
    deltas = [a['net_return_pct'] - b['net_return_pct'] for a, b in zip(candidate, base)]
    dd = [a['max_drawdown_pct'] - b['max_drawdown_pct'] for a, b in zip(candidate, base)]
    return {'median_return_delta_pp': round(float(np.median(deltas)), 4),
            'median_drawdown_delta_pp': round(float(np.median(dd)), 4),
            'improved_stocks': sum(value > 0 for value in deltas),
            'completed_trades': sum(row['completed_trades'] for row in candidate)}


def run(directory, download=False, as_of='2026-10-19'):
    import STOCK_GOD as core
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    # The calendar cutoff is explicit; rerunning later never adds future bars.
    end = pd.Timestamp(as_of)
    system = core.TaiwanStockTradingSystem(list(CASES + CONTROLS))
    provider_download = core.yf.download
    def cutoff_download(*args, **kwargs):
        # Apply the research cutoff BEFORE computing indicators/backtests. A new
        # unfinished session must not enter a retrospective comparison.
        kwargs['end'] = (end + pd.Timedelta(days=1)).date().isoformat()
        data = provider_download(*args, **kwargs)
        return data.loc[:as_of].copy()
    if download:
        with patch.object(core.yf, 'download', side_effect=cutoff_download):
            system.fetch_market_data()
        system.market_data = system.market_data.loc[:as_of].copy()
    rows, audits, input_hashes, coverage = {}, {}, {}, {}
    for ticker in CASES + CONTROLS:
        file = directory / f'{ticker}_adjusted_frame.pkl'
        if download:
            with patch.object(core.yf, 'download', side_effect=cutoff_download):
                frame = system.process_stock(ticker)
            if frame is None:
                raise ValueError(f'Missing data for {ticker}')
            # Features use past/current bars; cut off provider data before evaluation.
            frame = frame.loc[:as_of].copy()
            frame.to_pickle(file)
        else:
            frame = pd.read_pickle(file).loc[:as_of].copy()
        input_hashes[ticker] = hashlib.sha256(frame.to_csv().encode('utf-8')).hexdigest()
        coverage[ticker] = {'first': frame.index[0].date().isoformat(),
                            'last': frame.index[-1].date().isoformat(), 'sessions': len(frame)}
        rows[ticker] = {}
        for period, start, stop in (('development_2023_2024', '2023-01-01', '2024-12-31'),
                                    ('comparison_2025', '2025-01-01', '2025-12-31'),
                                    ('reviewed_2026', '2026-01-01', as_of),
                                    ('all', '2023-01-01', as_of)):
            rows[ticker][period] = {}
            for variant in VARIANTS:
                result, metrics = evaluate(frame, variant, start, stop)
                rows[ticker][period][variant] = metrics
                if ticker == '6561.TWO' and period == 'all' and variant == 'baseline':
                    audits[ticker] = trade_audit(result)
        print(f"Evaluated {ticker} through {frame.index[-1].date()}", flush=True)
    controls = {period: {name: comparison(rows, period, name) for name in VARIANTS[1:]}
                for period in ('comparison_2025', 'reviewed_2026')}
    report = {'as_of': end.date().isoformat(), 'cases': CASES, 'controls': CONTROLS,
              'variants_declared_before_download': VARIANTS, 'input_hashes': input_hashes, 'coverage': coverage,
              'rows': rows, 'trade_audit': audits, 'control_comparison': controls,
              'scope': 'Rule strategy only; not a TD/Q-Learning policy backtest.',
              'validation_limit': '2026 has already been reviewed; this is retrospective comparison, not untouched out-of-sample proof.',
              'core_model_version': core.MODEL_VERSION,
              'source_sha256': {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                for name in ('STOCK_GOD.py', 'strategy_config.py', 'strategy_performance.py', 'institutional_data.py')},
              'execution_assumption': 'Close signal, next-session open; buy cost 0.08%, sell cost 0.38%.'}
    (directory / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', default='diagnostics/entry_quality_20261019')
    parser.add_argument('--download', action='store_true', help='Download and replace local research inputs; never send notifications')
    parser.add_argument('--as-of', default='2026-10-19')
    arguments = parser.parse_args()
    run(arguments.directory, arguments.download, arguments.as_of)
