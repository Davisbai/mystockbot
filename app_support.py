"""Shared, testable view transformations; no Streamlit or external requests."""
import math
from analyze_push_history import analyze


def performance_rows(summary, names):
    return [{
        '代碼': ticker.replace('.TW', '').replace('.TWO', ''),
        '名稱': names.get(ticker, ''),
        '持倉交易日數': data['總交易天數'],
        '已完成交易筆數': data['完成交易筆數'],
        '已平倉勝率 (%)': data['勝率 (%)'],
        '扣成本累積報酬 (%)': data['策略累積報酬 (%)'],
        '最大回撤 (%)': data['最大回撤 (%)'],
        '尚有未平倉': '是' if data['未平倉'] else '否',
    } for ticker, data in summary.items()]


def observed_holding(record, alert):
    """Retain entry metadata and only update a valid, non-stale observed peak."""
    result = dict(record)
    cost = float(record.get('加入價格', 0))
    peak = float(record.get('觀察最高價', cost))
    price = float(alert.get('收盤價', 0))
    if (all(math.isfinite(value) and value > 0 for value in (cost, peak, price))
            and str(alert.get('日期', '')) >= str(record.get('加入日期', ''))):
        result['觀察最高價'] = max(cost, peak, price)
    return result


def sync_watchlist(watchlist, ticker, name, alert, decision):
    """Apply signal-tracking changes, preserving existing entry date/cost."""
    before = {key: dict(value) for key, value in watchlist.items()}
    if ticker in watchlist:
        watchlist[ticker] = observed_holding(watchlist[ticker], alert)
    if decision == 'BUY' and ticker not in watchlist:
        price = float(alert.get('收盤價', 0))
        if math.isfinite(price) and price > 0 and alert.get('日期'):
            watchlist[ticker] = {
                '名稱': name, '加入日期': alert['日期'], '加入價格': price,
                '觀察最高價': price, '來源': 'TD_RL',
                'TD期待值': alert.get('TD期待值', 0),
            }
    elif decision == 'SELL':
        watchlist.pop(ticker, None)
    return before != watchlist


def tracking_report(log_text, watchlist):
    return analyze(log_text, watchlist)
