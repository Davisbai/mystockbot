"""Daily, long-only research backtest; close signals execute next session open."""
import numpy as np
import pandas as pd


def watchlist_risk(price, cost, peak, stop_loss=0.08, trailing=0.12, activation=0.15):
    """Research defaults, not optimized parameters. Uses observed reference prices."""
    if not all(np.isfinite(x) and x > 0 for x in (price, cost, peak)):
        return None
    if not all(0 < x < 1 for x in (stop_loss, trailing, activation)):
        raise ValueError('Risk thresholds must be in (0, 1)')
    peak = max(peak, cost, price)
    if price <= cost * (1 - stop_loss):
        return 'REFERENCE_STOP_LOSS'
    if peak >= cost * (1 + activation) and price <= peak * (1 - trailing):
        return 'REFERENCE_TRAILING_STOP'
    return None


def backtest_signals(frame, buy_cost=0.0008, sell_cost=0.0038):
    """Costs are configurable assumptions including fees/tax/slippage, not quotes.

    Stop signals take priority. Open positions are marked to close but excluded
    from completed-trade win rate. This is not an exchange fill simulator.
    """
    df = frame.copy()
    if not df.index.is_monotonic_increasing or not df.index.is_unique:
        raise ValueError("Price dates must be sorted and unique")
    if not 0 <= buy_cost < 1 or not 0 <= sell_cost < 1:
        raise ValueError("Costs must be in [0, 1)")
    if df[['Open', 'Close']].isna().any().any() or (df[['Open', 'Close']] <= 0).any().any():
        raise ValueError("Open/Close must be positive and complete")
    position, pending, wealth, entry = 0, 0, 1.0, None
    returns, positions, actions, fills, trades = [], [], [], [], []
    for i, (date, row) in enumerate(df.iterrows()):
        previous_wealth = wealth
        if position and i:
            wealth *= row['Open'] / df['Close'].iloc[i - 1]
        action = pending - position
        if action == 1:
            wealth *= 1 - buy_cost
            entry = (date, float(row['Open']))
        elif action == -1:
            wealth *= 1 - sell_cost
            trades.append({'entry_date': entry[0], 'exit_date': date,
                           'entry_price': entry[1], 'exit_price': float(row['Open']),
                           'net_return': row['Open'] / entry[1] * (1 - buy_cost) * (1 - sell_cost) - 1})
            entry = None
        position = pending
        if position:
            wealth *= row['Close'] / row['Open']
        returns.append(wealth / previous_wealth - 1)
        positions.append(position)
        actions.append(action)
        fills.append(float(row['Open']) if action else np.nan)
        pending = 0 if bool(row['Sell_Signal']) else (1 if bool(row['Buy_Signal']) else position)
    df['Position'] = positions
    df['Trade_Action'] = actions
    df['Fill_Price'] = fills
    df['Returns'] = df['Close'].pct_change()
    df['Strategy_Returns'] = returns
    equity = (1 + df['Strategy_Returns']).cumprod()
    peak = equity.cummax().clip(lower=1.0)
    summary = {
        '總交易天數': int(sum(positions)),
        '完成交易筆數': len(trades),
        '勝率 (%)': round(100 * sum(t['net_return'] > 0 for t in trades) / len(trades), 2) if trades else float('nan'),
        '策略累積報酬 (%)': round((wealth - 1) * 100, 2),
        '最大回撤 (%)': round(float((equity / peak - 1).min()) * 100, 2) if len(df) else 0.0,
        '未平倉': bool(position),
        '待執行部位': int(pending),
    }
    df.attrs['performance'] = summary
    df.attrs['completed_trades'] = trades
    return df
