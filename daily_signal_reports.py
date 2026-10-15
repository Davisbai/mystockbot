"""Persist daily signal lists independently of mutable monitoring positions."""
import copy
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile

from app_support import source_digest

RUNTIME_SOURCE_SHA256 = source_digest(__file__)
REPORT_DIRECTORY = Path('daily_reports')
CATEGORIES = {'watch': '關注', 'buy': '當日買入', 'hold': '續抱', 'sell': '當日賣出'}
TAIPEI = datetime.timezone(datetime.timedelta(hours=8))


def _date(value):
    return datetime.date.fromisoformat(str(value)).isoformat()


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _root(directory):
    return REPORT_DIRECTORY if directory is None else Path(directory)


def list_report_dates(directory=None):
    result = []
    for file in _root(directory).glob('*.json'):
        try:
            result.append(_date(file.stem))
        except ValueError:
            continue
    return sorted(result, reverse=True)


def load_daily_report(report_date, directory=None):
    file = _root(directory) / f'{_date(report_date)}.json'
    if not file.exists():
        return None
    report = json.loads(file.read_text(encoding='utf-8'))
    if (not isinstance(report, dict) or report.get('schema_version') != 1 or report.get('report_date') != _date(report_date)
            or any(not isinstance(report.get(key), list) for key in CATEGORIES)
            or not isinstance(report.get('unavailable'), list)
            or not isinstance(report.get('delivery'), dict)):
        raise ValueError('每日清單格式不完整')
    return report


def save_daily_report(report, directory=None):
    root = _root(directory)
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{_date(report['report_date'])}.json"
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=root,
                                         suffix='.tmp', delete=False) as output:
            temporary = Path(output.name)
            json.dump(report, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write('\n')
        os.replace(temporary, target)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return target


def _row(ticker, name, alert, result, holding):
    action, reason, meta = result
    price, cost = _number(alert.get('收盤價')), _number((holding or {}).get('加入價格'))
    return {
        'ticker': ticker, 'name': name, 'data_date': str(alert.get('日期', '')),
        'close': price, 'action': action, 'reason': str(reason),
        'raw_action': str(meta.get('raw_action', 'UNAVAILABLE')),
        'score': _number(alert.get('今日評分')), 'td_expected_pct': _number(alert.get('TD期待值')),
        'q_preference': _number(meta.get('confidence')), 'chip_status': alert.get('籌碼資料狀態', 'unavailable'),
        'state_support': _number(meta.get('state_support')), 'support_kind': meta.get('support_kind', 'unavailable'),
        'model_version': str(alert.get('模型版本', meta.get('model_version', '未提供'))),
        'training_start': str(alert.get('訓練起日', meta.get('training_start', '未提供'))),
        'entry_date': str((holding or {}).get('加入日期', '')), 'reference_cost': cost,
        'reference_return_pct': round((price / cost - 1) * 100, 2) if price is not None and cost and cost > 0 else None,
        'risk_reasons': [str(value) for value in (alert.get('硬性風控原因') or [])],
        'bar_closed': alert.get('日線已收盤') is not False,
    }


def build_daily_report(alerts, names, holdings, decisions, previous=None, now=None):
    """Classify from pre-scan holdings; preserve today's confirmed action events."""
    now = datetime.datetime.now(TAIPEI) if now is None else now.astimezone(TAIPEI)
    report_date = now.date().isoformat()
    dates = []
    for alert in alerts.values():
        try:
            dates.append(_date(alert.get('日期')))
        except (ValueError, TypeError):
            continue
    market_date = max(dates, default=None)
    previous = previous if previous and previous.get('report_date') == report_date else None
    report = {'schema_version': 1, 'report_date': report_date,
              'generated_at': now.isoformat(timespec='seconds'), 'market_date': market_date,
              'price_basis': '收盤參考價；非券商成交',
              **{key: [] for key in CATEGORIES}, 'unavailable': []}
    # Only actual reports generated on this day establish today's action events.
    prior_buys = {row['ticker']: row for row in previous.get('buy', [])} if previous else {}
    prior_sells = {row['ticker']: copy.deepcopy(row) for row in previous.get('sell', [])} if previous else {}
    current_buys = {}
    for ticker in sorted(set(alerts) | set(holdings)):
        alert, holding = alerts.get(ticker), holdings.get(ticker)
        name = names.get(ticker, (holding or {}).get('名稱', ticker))
        if not alert or ticker not in decisions:
            report['unavailable'].append({'ticker': ticker, 'name': name, 'reason': '本次無可用分析資料'})
            continue
        row = _row(ticker, name, alert, decisions[ticker], holding)
        # Never call a previous trading day's/unfinished bar's signal a new BUY/SELL.
        if (row['data_date'] != report_date or not row['bar_closed']
                or row['close'] is None or row['close'] <= 0):
            row['reason'] = '資料非執行日、日線未完成或價格無效；本次不確認新的買賣訊號。 ' + row['reason']
            report['unavailable'].append(row)
            continue
        if holding is not None:
            if row['action'] == 'SELL':
                row['signal_recorded_at'] = prior_sells.get(ticker, {}).get('signal_recorded_at', report['generated_at'])
                prior_sells[ticker] = row
            elif ticker in prior_buys:
                current_buys[ticker] = prior_buys[ticker]
            else:
                row['status'] = '續抱' if row['action'] in ('BUY', 'WATCH') else '未觸發退出，續抱觀察'
                report['hold'].append(row)
        elif row['action'] == 'BUY':
            row.update(entry_date=row['data_date'], reference_cost=row['close'], reference_return_pct=0.0)
            row['signal_recorded_at'] = prior_buys.get(ticker, {}).get('signal_recorded_at', report['generated_at'])
            current_buys[ticker] = row
        elif row['action'] == 'WATCH' or row['raw_action'] == 'BUY':
            row['status'] = '關注（風控阻擋，禁止介入）' if row['action'] == 'IGNORE' else '關注，尚未確認進場'
            report['watch'].append(row)
    # BUY/SELL are daily signal events, HOLD/WATCH are the latest scan state.
    # Earlier events remain visible even if a later scan cannot download a stock.
    for ticker, row in prior_buys.items():
        current_buys.setdefault(ticker, row)
    report['buy'] = [copy.deepcopy(current_buys[key]) for key in sorted(current_buys)]
    report['sell'] = [prior_sells[key] for key in sorted(prior_sells)]
    content = {key: report[key] for key in ('report_date', 'market_date', *CATEGORIES, 'unavailable')}
    report['content_hash'] = hashlib.sha256(json.dumps(content, ensure_ascii=False, sort_keys=True,
                                                     allow_nan=False).encode('utf-8')).hexdigest()
    report['delivery'] = (copy.deepcopy(previous['delivery'])
                          if previous and previous.get('content_hash') == report['content_hash']
                          else {'status': 'pending', 'attempted_at': None, 'sent_at': None})
    return report


def mark_report_delivery(report, delivered, directory=None):
    report['delivery'] = {'status': 'sent' if delivered else 'failed',
                          'attempted_at': datetime.datetime.now(TAIPEI).isoformat(timespec='seconds'),
                          'sent_at': datetime.datetime.now(TAIPEI).isoformat(timespec='seconds') if delivered else None}
    save_daily_report(report, directory)


def format_daily_report(report):
    lines = [f"📋 每日訊號清單｜{report['report_date']}",
             f"行情日期：{report['market_date'] or '無可用資料'}", '系統訊號與收盤參考價，非券商成交。']
    for key, label in CATEGORIES.items():
        lines.append(f'\n【{label}】{len(report[key])} 檔')
        if not report[key]:
            lines.append('無')
        for row in report[key]:
            price = f"{row['close']:.2f}" if row.get('close') is not None else '未提供'
            lines.extend([f"{row['name']} ({row['ticker']})｜參考價 {price}",
                          f"{row.get('status', row['action'])}｜{row['reason']}"])
            if row.get('signal_recorded_at'):
                lines.append('訊號首次記錄：' + row['signal_recorded_at'])
    if report['unavailable']:
        lines.append('\n資料待確認：' + '、'.join(row['name'] for row in report['unavailable']))
    return '\n'.join(lines)
