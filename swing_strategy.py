"""Independent daily swing research using the app's already adjusted OHLC bars.

This module has no broker interface and does not alter production BUY/SELL.
Signals form at close; simulated fills occur at the next session's open.
"""

import pandas as pd


def evaluate_swing(frame, *, etf=False, capital=100000, allocation=.20,
                   fee=.001425, min_fee=20, slippage=.001, stop=.07):
    """Return a standalone cash-and-shares simulation and next-session signal."""
    if not (capital > 0 and 0 < allocation <= 1 and 0 <= fee < 1 and
            min_fee >= 0 and 0 <= slippage < 1 and 0 < stop < 1):
        raise ValueError('模擬參數不合理')
    if frame is None or not {'Open', 'Close'}.issubset(frame.columns):
        raise ValueError('缺少開盤價或收盤價')
    data = frame[['Open', 'Close']].copy()
    if len(data) < 65 or not data.index.is_unique or not data.index.is_monotonic_increasing:
        raise ValueError('需要至少 65 筆日期遞增且不重複的交易日')
    if data.isna().any().any() or not (data > 0).all().all():
        raise ValueError('開盤價與收盤價必須完整且大於零')
    closes = data['Close'].astype(float).tolist()
    opens = data['Open'].astype(float).tolist()
    ma20 = data['Close'].rolling(20).mean().tolist()
    ma60 = data['Close'].rolling(60).mean().tolist()
    tax = .001 if etf else .003
    cash, shares, paid = float(capital), 0, 0.0
    entry_total, entry_date = 0.0, None
    pending, reason = None, None
    trades = []
    peak, drawdown = float(capital), 0.0
    for i, day in enumerate(data.index):
        if pending == 'SELL' and shares:
            sell = opens[i] * (1 - slippage)
            gross = sell * shares
            proceeds = gross - max(min_fee, gross * fee) - gross * tax
            cash += proceeds
            trades.append({'買入日': str(entry_date.date() if hasattr(entry_date, 'date') else entry_date),
                           '賣出日': str(day.date() if hasattr(day, 'date') else day),
                           '股數': shares, '買入模擬價': round(paid, 3),
                           '賣出模擬價': round(sell, 3),
                           '已扣成本損益': round(proceeds - entry_total, 2), '出場原因': reason})
            shares, paid, entry_total, entry_date = 0, 0.0, 0.0, None
        elif pending == 'BUY' and not shares:
            buy = opens[i] * (1 + slippage)
            budget = cash * allocation
            shares = max(0, int((budget - min_fee) / (buy * (1 + fee))))
            while shares and shares * buy + max(min_fee, shares * buy * fee) > budget:
                shares -= 1
            if shares:
                entry_total = shares * buy + max(min_fee, shares * buy * fee)
                cash -= entry_total
                paid, entry_date = buy, day
        pending, reason = None, None
        equity = cash + shares * closes[i]
        peak = max(peak, equity)
        drawdown = max(drawdown, (peak - equity) / peak)
        if shares:
            if closes[i] <= paid * (1 - stop):
                pending, reason = 'SELL', '收盤跌破模擬買價 7%'
            elif i >= 20 and closes[i] < ma20[i] and closes[i - 1] < ma20[i - 1]:
                pending, reason = 'SELL', '連續兩日收盤低於 20 日均線'
        elif (i >= 60 and ma20[i] > ma60[i] and
              closes[i - 1] <= ma20[i - 1] and closes[i] > ma20[i]):
            pending, reason = 'BUY', '20 日線高於 60 日線，收盤由下往上突破 20 日線'

    labels = {'BUY': '🟢 觀察買入', 'SELL': '🔴 觀察賣出',
              None: '🟡 模擬續抱' if shares else '⚪ 等待訊號'}
    equity = cash + shares * closes[-1]
    closed = len(trades)
    summary = {'起始模擬資金': round(capital, 2), '期末模擬資產': round(equity, 2),
               '扣成本報酬 (%)': round((equity / capital - 1) * 100, 2),
               '最大回撤 (%)': round(-drawdown * 100, 2),
               '已平倉筆數': closed,
               '已平倉勝率 (%)': round(100 * sum(t['已扣成本損益'] > 0 for t in trades) / closed, 2) if closed else float('nan'),
               '模擬持股數': shares}
    return {'date': str(data.index[-1].date() if hasattr(data.index[-1], 'date') else data.index[-1]),
            'signal': pending or ('HOLD' if shares else 'WAIT'),
            'signal_label': labels[pending],
            'signal_reason': reason or ('模擬部位尚在持有' if shares else '尚未形成新的進場條件'),
            'summary': summary, 'trades': trades}
