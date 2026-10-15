import copy
import datetime
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd
import daily_signal_reports as reports
import STOCK_GOD as core


class DailyReportTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime.datetime(2026, 10, 15, 19, tzinfo=reports.TAIPEI)
        self.alerts = {ticker: {'日期': '2026-10-15', '收盤價': 110., '今日評分': 80,
                                'TD期待值': 1., '日線已收盤': True, '籌碼資料狀態': 'available'}
                       for ticker in ('B.TW', 'W.TW', 'H.TW', 'S.TW', 'X.TW')}
        self.names = {ticker: ticker[0] for ticker in self.alerts}
        self.holdings = {ticker: {'名稱': ticker[0], '加入日期': '2026-10-01', '加入價格': 100.}
                         for ticker in ('H.TW', 'S.TW')}
        self.decisions = {ticker: (action, f'{action} reason', {'raw_action': raw, 'state_support': 10,
                                                               'support_kind': 'exact', 'confidence': 70})
                          for ticker, action, raw in (('B.TW', 'BUY', 'BUY'), ('W.TW', 'WATCH', 'HOLD'),
                                                    ('H.TW', 'WATCH', 'HOLD'), ('S.TW', 'SELL', 'SELL'),
                                                    ('X.TW', 'IGNORE', 'BUY'))}

    def build(self, previous=None, now=None):
        return reports.build_daily_report(self.alerts, self.names, self.holdings, self.decisions,
                                          previous, self.now if now is None else now)

    def test_four_categories_retain_pre_exit_cost_and_do_not_mutate_inputs(self):
        before = copy.deepcopy(self.holdings)
        report = self.build()
        self.assertEqual([row['ticker'] for row in report['buy']], ['B.TW'])
        self.assertEqual([row['ticker'] for row in report['watch']], ['W.TW', 'X.TW'])
        self.assertEqual([row['ticker'] for row in report['hold']], ['H.TW'])
        self.assertEqual(report['sell'][0]['reference_cost'], 100)
        self.assertEqual(report['sell'][0]['reference_return_pct'], 10.)
        self.assertIn('禁止介入', report['watch'][1]['status'])
        self.assertEqual(self.holdings, before)

    def test_same_day_rerun_keeps_buy_and_sell_events_and_delivery_ack(self):
        first = self.build()
        first['delivery'] = {'status': 'sent', 'attempted_at': 'before', 'sent_at': 'before'}
        self.holdings.pop('S.TW')
        self.holdings['B.TW'] = {'加入日期': '2026-10-15', '加入價格': 110}
        self.decisions['S.TW'] = 'IGNORE', 'no longer held', {'raw_action': 'HOLD'}
        self.decisions['B.TW'] = 'WATCH', 'now held', {'raw_action': 'HOLD'}
        again = self.build(first, self.now + datetime.timedelta(minutes=5))
        self.assertEqual(again['buy'], first['buy'])
        self.assertEqual(again['sell'], first['sell'])
        self.assertEqual(again['content_hash'], first['content_hash'])
        self.assertEqual(again['delivery']['status'], 'sent')

    def test_buy_then_sell_same_day_keeps_both_signal_events(self):
        first = self.build()
        self.holdings['B.TW'] = {'加入日期': '2026-10-15', '加入價格': 110}
        self.decisions['B.TW'] = 'SELL', 'risk changed', {'raw_action': 'SELL'}
        again = self.build(first)
        self.assertIn('B.TW', [row['ticker'] for row in again['buy']])
        self.assertIn('B.TW', [row['ticker'] for row in again['sell']])
        self.assertEqual(again['delivery']['status'], 'pending')

    def test_missing_stale_and_unfinished_prices_are_not_confirmed_actions(self):
        self.alerts.pop('H.TW')
        self.alerts['S.TW']['日期'] = '2026-10-14'
        self.alerts['B.TW']['日線已收盤'] = False
        report = self.build()
        self.assertEqual(report['buy'], [])
        self.assertEqual(report['sell'], [])
        self.assertEqual(report['hold'], [])
        self.assertEqual({row['ticker'] for row in report['unavailable']}, {'H.TW', 'S.TW', 'B.TW'})

    def test_empty_or_next_day_scan_does_not_relabel_yesterday_events_as_today(self):
        report = reports.build_daily_report({}, {}, self.holdings, {}, self.build(),
                                           self.now + datetime.timedelta(days=1))
        self.assertTrue(all(not report[key] for key in reports.CATEGORIES))
        self.assertEqual(len(report['unavailable']), 2)
        self.assertIsNone(report['market_date'])

    def test_changed_reason_requires_new_delivery(self):
        first = self.build()
        first['delivery'] = {'status': 'sent'}
        self.decisions['W.TW'] = 'WATCH', 'changed reason', {'raw_action': 'HOLD'}
        self.assertEqual(self.build(first)['delivery']['status'], 'pending')

    def test_atomic_storage_failed_delivery_and_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            report = self.build()
            reports.save_daily_report(report, directory)
            reports.mark_report_delivery(report, False, directory)
            loaded = reports.load_daily_report('2026-10-15', directory)
            self.assertEqual(loaded['delivery']['status'], 'failed')
            self.assertEqual(self.build(loaded)['delivery']['status'], 'failed')
            reports.mark_report_delivery(report, True, directory)
            self.assertEqual(reports.load_daily_report('2026-10-15', directory)['delivery']['status'], 'sent')
            before = (Path(directory) / '2026-10-15.json').read_bytes()
            report['buy'][0]['close'] = float('nan')
            with self.assertRaises(ValueError):
                reports.save_daily_report(report, directory)
            self.assertEqual((Path(directory) / '2026-10-15.json').read_bytes(), before)
            self.assertFalse(list(Path(directory).glob('*.tmp')))

    def test_date_listing_invalid_schema_and_path_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            reports.save_daily_report(self.build(), directory)
            (Path(directory) / 'latest.json').write_text('{}', encoding='utf-8')
            self.assertEqual(reports.list_report_dates(directory), ['2026-10-15'])
            self.assertIsNone(reports.load_daily_report('2026-10-14', directory))
            with self.assertRaises(ValueError):
                reports.load_daily_report('../../secret', directory)
            (Path(directory) / '2026-10-14.json').write_text('{}', encoding='utf-8')
            with self.assertRaises(ValueError):
                reports.load_daily_report('2026-10-14', directory)

    def test_line_format_has_all_four_categories_and_is_explicit_about_prices(self):
        text = reports.format_daily_report(self.build())
        for label in reports.CATEGORIES.values():
            self.assertIn(f'【{label}】', text)
        self.assertIn('非券商成交', text)
        self.assertIn('參考價 110.00', text)
        self.assertIn('S (S.TW)', text)

    def test_full_scan_archives_before_exit_and_sends_four_lists_with_mock_sender(self):
        self._full_scan(True)

    def test_failed_full_scan_delivery_keeps_complete_archive(self):
        self._full_scan(False)

    def _full_scan(self, delivered):
        date = datetime.datetime.now(reports.TAIPEI).date().isoformat()
        template = {'日期': date, '收盤價': 110., '月線價': 100., '今日漲幅': 1.,
                    '今日評分': 80, '個股原始評分': 80, '大盤安全': True,
                    'TD期待值': 1., 'RL可用': True, 'RL空手策略': 'BUY',
                    'RL持有策略': 'HOLD', 'RL空手信心': 70., 'RL持有信心': 70.,
                    '籌碼資料狀態': 'available', '日線已收盤': True}
        alerts = {ticker: dict(template) for ticker in ('1101.TW', '1102.TW', '1103.TW', '1104.TW')}
        alerts['1102.TW'].update(RL空手策略='HOLD', TD期待值=.5)
        alerts['1104.TW']['是否觸發賣出'] = True
        holdings = {ticker: {'名稱': ticker, '加入日期': '2026-01-01', '加入價格': 100.}
                    for ticker in ('1103.TW', '1104.TW')}
        system = SimpleNamespace(run_analysis=lambda: ({}, alerts, {key: [] for key in alerts}),
                                 market_data=pd.DataFrame({'Close': [100.] * 120}))
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(reports, 'REPORT_DIRECTORY', Path(directory)), \
                patch.object(core, 'load_watchlist', return_value=copy.deepcopy(holdings)), \
                patch.object(core, 'save_watchlist') as save_holdings, \
                patch.object(core, 'load_signal_state', return_value={'pending': {}, 'sent': {}}), \
                patch.object(core, 'save_signal_state'), \
                patch.object(core, 'load_entry_candidates', return_value={}), \
                patch.object(core, 'STOCK_MAP', {ticker: ticker for ticker in alerts}), \
                patch.object(core, 'TaiwanStockTradingSystem', return_value=system), \
                patch.object(core, 'send_line_message', return_value=delivered) as sender, \
                patch.object(core.time, 'sleep'), \
                patch.dict('os.environ', {'GITHUB_ACTIONS': 'true'}), \
                patch('sys.stdout', new_callable=io.StringIO):
            scanner = SimpleNamespace(scan=lambda: [{'code': '1101', 'name': '低漲幅熱門股'}])
            core.run_full_scan_gui(scanner)
            report = reports.load_daily_report(date, directory)
            self.assertEqual(report['delivery']['status'], 'sent' if delivered else 'failed')
            self.assertEqual(report['buy'][0]['ticker'], '1101.TW')
            self.assertEqual(report['sell'][0]['ticker'], '1104.TW')
            self.assertEqual(report['sell'][0]['reference_cost'], 100.)
            self.assertNotIn('1104.TW', save_holdings.call_args[0][0])
            first_message = sender.call_args_list[0].args[0]
            for label in reports.CATEGORIES.values():
                self.assertIn(f'【{label}】', first_message)
            json.dumps(report, allow_nan=False)


if __name__ == '__main__':
    unittest.main()
