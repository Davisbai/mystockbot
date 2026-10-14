"""Shared, testable view transformations; no Streamlit or external requests."""
import math

APP_SUPPORT_API_VERSION = 1


def normalize_decision(result, alert, is_held=False):
    """Accept older core metadata without inventing audit evidence or new BUYs."""
    action, reason, metadata = result
    metadata = dict(metadata or {})
    compatible = all(key in metadata for key in (
        'state_support', 'support_kind', 'raw_action', 'hard_risk', 'exit_filter'))
    raw = (str(alert.get('RL持有策略' if is_held else 'RL空手策略', 'HOLD'))
           if alert.get('RL可用') else 'UNAVAILABLE')
    defaults = {
        'confidence': 50.0, 'raw_action': raw,
        'hard_risk': alert.get('硬性風控'),
        'exit_filter': alert.get('是否觸發賣出'),
        'extension_warning': bool(alert.get('乖離過大') or alert.get('高位過熱')),
        'state_support': alert.get('RL持有樣本' if is_held else 'RL空手樣本'),
        'support_kind': alert.get('RL樣本類型', '未提供'),
    }
    normalized = {**defaults, **metadata}
    if not compatible and action == 'BUY':
        action = 'WATCH'
        reason = '核心版本缺少完整仲裁資訊，暫列預警；請同步更新程式並重新啟動服務。'
    expected = {'HOLD': 'WATCH', 'BUY': 'BUY', 'SELL': 'SELL'}.get(normalized['raw_action'])
    normalized['final_action'] = action
    normalized['overridden'] = expected is not None and expected != action
    normalized['override_reason'] = reason if normalized['overridden'] else ''
    normalized['schema_compatible'] = compatible
    return action, reason, normalized


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
    # The diagnostic page can start even if the optional history module cannot
    # be loaded; the history page reports its own import/read errors.
    from analyze_push_history import analyze
    return analyze(log_text, watchlist)
