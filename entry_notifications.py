"""Prioritized entry notices; observation, confirmed entry, and blocked entry."""
import copy
import json
from pathlib import Path
from app_support import source_digest
RUNTIME_SOURCE_SHA256 = source_digest(__file__)


def load_entry_candidates(path='entry_watchlist.json'):
    file = Path(path)
    return json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}


def load_signal_state(path='entry_signal_state.json'):
    file = Path(path)
    return json.loads(file.read_text(encoding='utf-8')) if file.exists() else {'pending': {}, 'sent': {}}


def save_signal_state(state, path='entry_signal_state.json'):
    file = Path(path)
    temporary = file.with_suffix(file.suffix + '.tmp')
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(file)


def entry_notice(ticker, name, alert, action, reason, meta, is_held=False):
    if is_held or not alert.get('日期'):
        return None
    raw = meta.get('raw_action', 'UNAVAILABLE')
    blocked = bool(alert.get('是否觸發賣出') or alert.get('乖離過大') or alert.get('高位過熱'))
    quality = alert.get('籌碼資料狀態', 'unavailable')
    setup = any(alert.get(key, False) for key in ('上升趨勢', '專業起漲', '縮量埋伏', '假跌破', '剛過月線'))
    if action == 'BUY' and raw == 'BUY' and alert.get('RL可用') and not blocked and quality in ('available', 'not_applicable') and alert.get('日線已收盤', True):
        level, title = 'ENTRY', '🟢 確認進場訊號'
    elif blocked and raw == 'BUY':
        level, title = 'BLOCKED', '⛔ 模型偏買但風控禁止進場'
    elif not blocked and (setup or action == 'BUY'):
        level, title = 'SETUP', '🟡 轉強預警，尚未確認進場'
    else:
        return None
    conditions = [key for key in ('上升趨勢', '紅肥綠瘦', '連續小陽', '新高', '新量', '剛過月線', '專業起漲', '縮量埋伏') if alert.get(key)]
    close, ma20 = float(alert.get('收盤價', 0)), float(alert.get('月線價', 0))
    model_text = f"原始模型 {raw} → 最終 {action}"
    lines = [f'{title}｜{name} ({ticker})', f"訊號日期：{alert['日期']}｜收盤參考價 {close:.2f}",
             '觸發條件：' + ('、'.join(conditions) or '策略評分達標'), model_text,
             f"評分 {alert.get('今日評分', 0)}｜TD {float(alert.get('TD期待值', 0)):+.2f}%",
             f"Q買入 {float(alert.get('Q買入', 0)):.3f}／等待 {float(alert.get('Q空手等待', 0)):.3f}",
             f"狀態樣本 {meta.get('state_support', 0)}（{meta.get('support_kind', 'unavailable')}）｜籌碼 {quality}",
             '判定依據：' + reason]
    if ma20 > 0:
        lines.append(f'既有風控參考：月線×98% = {ma20 * .98:.2f}；日線收盤確認')
    if level == 'SETUP':
        lines.append('預警僅供追蹤，不等於買進，不會因此記為持股。')
    elif level == 'ENTRY':
        lines.append('收盤確認訊號；後續成交價與能否成交仍須確認，非收盤價成交保證。')
    else:
        lines.append('此訊息不是買進通知，風控條件解除前不介入。')
    return {'ticker': ticker, 'date': alert['日期'], 'level': level, 'message': '\n'.join(lines)}


def plan_entry_notices(alerts, names, watchlist, state, resolver):
    result = copy.deepcopy(state)
    result.setdefault('pending', {})
    result.setdefault('sent', {})
    latest = max((alert.get('日期', '') for alert in alerts.values()), default='')
    if not latest:
        return result, []
    # Never resend an expired entry as if it were a current opportunity.
    result['pending'] = {key: value for key, value in result['pending'].items() if value['date'] >= latest}
    for key, notice in list(result['pending'].items()):
        alert = alerts.get(notice['ticker'], {})
        if notice['level'] == 'ENTRY' and alert:
            held = notice['ticker'] in watchlist
            action, _, meta = resolver(alert, is_held=held, holding=watchlist.get(notice['ticker']))
            invalid = any(alert.get(flag) for flag in ('是否觸發賣出', '乖離過大', '高位過熱'))
            invalid |= alert.get('日線已收盤') is False
            invalid |= alert.get('籌碼資料狀態', 'unavailable') not in ('available', 'not_applicable')
            invalid |= action == 'SELL' or meta.get('raw_action') == 'SELL' or (not held and action != 'BUY')
            if invalid:
                result['pending'].pop(key)
    if latest:
        # Keep acknowledgement keys for the current and recent bars only.
        import datetime
        cutoff = (datetime.date.fromisoformat(latest) - datetime.timedelta(days=60)).isoformat()
        result['sent'] = {key: date for key, date in result['sent'].items() if date >= cutoff}
    for ticker, alert in alerts.items():
        action, reason, meta = resolver(alert, is_held=ticker in watchlist, holding=watchlist.get(ticker))
        notice = entry_notice(ticker, names.get(ticker, ticker), alert, action, reason, meta, ticker in watchlist)
        if notice is None:
            continue
        key = f"{ticker}|{notice['date']}|{notice['level']}"
        for prior_key, prior in list(result['pending'].items()):
            if prior['ticker'] == ticker and prior['date'] == notice['date'] and prior['level'] != notice['level']:
                result['pending'].pop(prior_key)
        if key not in result['sent']:
            result['pending'][key] = notice
    rank = {'ENTRY': 0, 'SETUP': 1, 'BLOCKED': 2}
    pending = sorted(((key, notice) for key, notice in result['pending'].items() if notice['ticker'] in alerts),
                     key=lambda item: (rank[item[1]['level']], item[0]))
    return result, pending


def acknowledge_notices(state, keys):
    for key in keys:
        notice = state['pending'].pop(key, None)
        if notice:
            state['sent'][key] = notice['date']


def deliver_entry_report(text, state, pending, sender, saver=save_signal_state):
    delivered = bool(sender(text))
    if delivered:
        acknowledge_notices(state, [key for key, notice in pending])
        saver(state)
    return delivered
