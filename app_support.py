"""Shared, testable view transformations; no Streamlit or external requests."""
import math
import hashlib
import importlib
from pathlib import Path
from threading import RLock
from datetime import date, timedelta

APP_SUPPORT_API_VERSION = 2
APP_SUPPORT_SOURCE_SHA256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
CORE_API_VERSION = 1
_RUNTIME_LOCK = RLock()
_CORE_DEPENDENCIES = ('strategy_config', 'strategy_performance', 'institutional_data',
                      'market_clock', 'entry_notifications', 'daily_signal_reports')


def source_digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _dependencies_match_sources():
    root = Path(__file__).resolve().parent
    return all(getattr(importlib.import_module(name), 'RUNTIME_SOURCE_SHA256', None)
               == source_digest(root / f'{name}.py') for name in _CORE_DEPENDENCIES)


def runtime_fingerprint():
    """Version the complete local computation graph, independent of model labels."""
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for name in (*_CORE_DEPENDENCIES, 'app_support', 'STOCK_GOD'):
        digest.update(name.encode('utf-8') + b'\0')
        digest.update((root / f'{name}.py').read_bytes() + b'\0')
    return digest.hexdigest()


def load_current_core():
    """Refresh dependencies and core once on deployment; reuse normal reruns."""
    with _RUNTIME_LOCK:
        expected = runtime_fingerprint()
        core = importlib.import_module('STOCK_GOD')
        if (getattr(core, 'CORE_API_VERSION', None) != CORE_API_VERSION or
                getattr(core, 'CORE_RUNTIME_FINGERPRINT', None) != expected or
                not _dependencies_match_sources()):
            importlib.invalidate_caches()
            for name in _CORE_DEPENDENCIES:
                importlib.reload(importlib.import_module(name))
            core = importlib.reload(core)
        if (getattr(core, 'CORE_API_VERSION', None) != CORE_API_VERSION or
                getattr(core, 'CORE_RUNTIME_FINGERPRINT', None) != expected or
                not _dependencies_match_sources()):
            raise ImportError('Core runtime version does not match local sources')
        if Path(core.__file__).resolve() != Path(__file__).resolve().with_name('STOCK_GOD.py'):
            raise ImportError('Core runtime loaded from an unexpected location')
        required = ('TaiwanStockTradingSystem', 'AdvancedQuantEngine', 'YahooMarketScanner',
                    'load_watchlist', 'save_watchlist', 'TDRLDecisionEngine', 'resolve_td_rl_strategy')
        if any(not callable(getattr(core, name, None)) for name in required):
            raise ImportError('Core runtime exports are incomplete')
        return core, expected


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


def backtest_history_view(logs, data_date, days=90):
    """Separate simulated historical actions from the current quote/signal date."""
    end = date.fromisoformat(data_date)
    cutoff = end - timedelta(days=days)
    dated = []
    for log in logs:
        try:
            stamp = date.fromisoformat(str(log)[:10])
        except ValueError:
            continue
        if stamp <= end:
            dated.append((stamp, str(log)))
    dated.sort(key=lambda item: item[0])
    return {
        'cutoff': cutoff.isoformat(), 'data_date': end.isoformat(),
        'latest_trade_date': dated[-1][0].isoformat() if dated else None,
        'recent': [log for stamp, log in dated if stamp >= cutoff][-5:],
        'historical': [log for _, log in dated][-5:],
    }
