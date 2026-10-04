"""Reproduce signal tracking evidence; no inferred executions or portfolio P&L."""
import argparse
import hashlib
import json
import re
from pathlib import Path


def analyze(log_text, watchlist):
    episodes = {}
    snapshots = 0
    pattern = re.compile(
        r'([^\n]+?)\s*\((\d+)\)\s*\n[^\n]*買入日期:\s*(\d{4}-\d{2}-\d{2})\s*\n'
        r'[^\n]*成本:\s*([\d.]+)\s*➔\s*現價:\s*([\d.]+)')
    for block in re.split(r'(?=\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\])', log_text):
        stamp = re.match(r'\[([^]]+)\]', block)
        if not stamp or '【長期監控清單】' not in block:
            continue
        snapshots += 1
        for match in pattern.finditer(block):
            name, code, joined, cost, price = match.groups()
            cost, price = float(cost), float(price)
            if cost <= 0 or price <= 0:
                continue
            key = (code, joined, cost)
            episode = episodes.setdefault(key, {
                'code': code, 'name': name.strip(), 'entry_date': joined,
                'reference_cost': cost, 'observations': {},
            })
            # Same session: retain last published observation, not every push.
            episode['observations'][stamp[1][:10]] = (stamp[1], price)
    rows = []
    for (code, joined, cost), episode in episodes.items():
        observations = sorted(episode.pop('observations').values())
        prices = [cost] + [p for _, p in observations]
        peak, max_dd = cost, 0.0
        for price in prices:
            peak = max(peak, price)
            max_dd = min(max_dd, price / peak - 1)
        current = next((v for k, v in watchlist.items() if k.split('.')[0] == code), {})
        is_current = current.get('加入日期') == joined and float(current.get('加入價格', 0)) == cost
        episode.update({
            'observed_sessions': len(observations), 'first_observed': observations[0][0],
            'last_observed': observations[-1][0], 'last_price': prices[-1],
            'observed_peak_price': peak,
            'last_mark_return_pct': round((prices[-1] / cost - 1) * 100, 2),
            'peak_mark_return_pct': round((peak / cost - 1) * 100, 2),
            'observed_max_drawdown_pct': round(max_dd * 100, 2),
            'peak_to_last_pct': round((prices[-1] / peak - 1) * 100, 2),
            'status': 'current_watchlist' if is_current else 'historical_tracking_exit_unconfirmed',
        })
        rows.append(episode)
    rows.sort(key=lambda r: (r['entry_date'], r['code']))
    return {
        'log_sha256': hashlib.sha256(log_text.encode('utf-8')).hexdigest(),
        'watchlist_snapshot_count': snapshots, 'tracked_episodes': len(rows),
        'current_episodes_matched': sum(r['status'] == 'current_watchlist' for r in rows),
        'limitations': [
            'Reference prices are push observations, not executions.',
            'Missing observations and intraday extremes are unknown.',
            'Historical absence does not confirm an exit or realized return.',
            'No quantities, dividends or costs: no portfolio return or realized win rate.',
        ],
        'episodes': rows,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--log', default='line_push_log.txt')
    parser.add_argument('--watchlist', default='long_term_watchlist.json')
    parser.add_argument('--output', default='performance_history.json')
    args = parser.parse_args()
    result = analyze(Path(args.log).read_text(encoding='utf-8'),
                     json.loads(Path(args.watchlist).read_text(encoding='utf-8')))
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"Tracked episodes: {result['tracked_episodes']}; current matched: {result['current_episodes_matched']}")
