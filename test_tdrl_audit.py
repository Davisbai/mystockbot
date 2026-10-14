import ast
import datetime
from pathlib import Path
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np
import pandas as pd
from institutional_data import parse_institutional_flows
from strategy_config import TRAINING_START_DATE, EXTENSION_EXIT_MODE
from STOCK_GOD import TaiwanStockTradingSystem, resolve_td_rl_strategy
from market_clock import daily_bar_closed


def payload(names=('Foreign_Investor', 'Investment_Trust')):
    return {'msg': 'success', 'data': [
        {'date': '2026-10-06', 'name': names[0], 'buy': '3000', 'sell': '1000'},
        {'date': '2026-10-06', 'name': names[1], 'buy': 0, 'sell': 0},
        {'date': '2026-10-06', 'name': 'Foreign_Dealer_Self', 'buy': 999000, 'sell': 0},
    ]}


class InstitutionalDataTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.to_datetime(['2026-10-06', '2026-10-07'])

    def test_english_fields_real_zero_and_missing_day_are_distinct(self):
        result = parse_institutional_flows(payload(), self.dates)
        self.assertEqual(result.Foreign_Buy.iloc[0], 2.)
        self.assertEqual(result.Trust_Buy.iloc[0], 0.)
        self.assertTrue(result.Chip_Data_Available.iloc[0])
        self.assertTrue(np.isnan(result.Foreign_Buy.iloc[1]))
        self.assertFalse(result.Chip_Data_Available.iloc[1])

    def test_chinese_aliases_still_supported(self):
        result = parse_institutional_flows(payload(('外資', '投信')), self.dates)
        self.assertEqual(result.Foreign_Buy.iloc[0], 2.)

    def test_unknown_schema_or_quota_does_not_become_zero_flow(self):
        for data in ({'msg': 'quota exceeded', 'data': []},
                     {'msg': 'success', 'data': [{'wrong': 1}]}):
            result = parse_institutional_flows(data, self.dates)
            self.assertTrue(result.Foreign_Buy.isna().all())
            self.assertFalse(result.Chip_Data_Available.any())

    def test_bad_numbers_and_duplicate_categories_are_not_counted(self):
        data = payload()
        data['data'][0]['buy'] = 'not a number'
        result = parse_institutional_flows(data, self.dates)
        self.assertEqual(result.Chip_Data_Status.iloc[0], 'partial')
        data = payload()
        data['data'].append(dict(data['data'][0]))
        result = parse_institutional_flows(data, self.dates)
        self.assertTrue(np.isnan(result.Foreign_Buy.iloc[0]))

    def test_future_flow_does_not_change_past(self):
        data = payload()
        before = parse_institutional_flows(data, self.dates[:1])
        data['data'].append({'date': '2026-10-08', 'name': 'Foreign_Investor', 'buy': 900000, 'sell': 0})
        pd.testing.assert_frame_equal(before, parse_institutional_flows(data, self.dates[:1]))

    def test_network_failure_is_explicit(self):
        import requests
        system = TaiwanStockTradingSystem(['1312.TW'])
        with patch('STOCK_GOD.requests.get', side_effect=requests.Timeout()):
            result = system.fetch_real_chip_data(pd.DataFrame(index=self.dates), '1312.TW')
        self.assertTrue(result.Foreign_Buy.isna().all())
        self.assertFalse(result.Chip_Data_Available.any())


class DecisionAuditTests(unittest.TestCase):
    def test_daily_bar_completion_boundary(self):
        zone = datetime.timezone(datetime.timedelta(hours=8))
        self.assertFalse(daily_bar_closed('1312.TW', '2026-10-14', datetime.datetime(2026, 10, 14, 13, 20, tzinfo=zone)))
        self.assertTrue(daily_bar_closed('1312.TW', '2026-10-14', datetime.datetime(2026, 10, 14, 13, 40, tzinfo=zone)))
        self.assertTrue(daily_bar_closed('1312.TW', '2026-10-13', datetime.datetime(2026, 10, 14, 9, 0, tzinfo=zone)))

    def process_fixture(self, mode='legacy_exit'):
        dates = pd.bdate_range('2024-01-01', periods=240)
        close = np.linspace(100., 130., len(dates))
        close[-1] *= 1.15
        prices = pd.DataFrame({'Open': close * .99, 'Close': close, 'High': close * 1.01,
                               'Low': close * .98, 'Volume': 1_000_000.}, index=dates)
        prices.iloc[-1, prices.columns.get_loc('Volume')] = 20_000_000.
        data = payload()
        for record in data['data']:
            record['date'] = dates[0].strftime('%Y-%m-%d')
        system = TaiwanStockTradingSystem(['1312.TW'], extension_exit_mode=mode)
        system.market_data = pd.DataFrame({'Close': close * 100, 'Market_OK': True}, index=dates)
        with patch('STOCK_GOD.yf.download', return_value=prices), \
                patch('STOCK_GOD.requests.get', return_value=SimpleNamespace(json=lambda: data)):
            return system.process_stock('1312.TW')

    def test_missing_chip_days_are_not_forward_filled_by_market_join(self):
        frame = self.process_fixture()
        self.assertEqual(frame.Foreign_Buy.iloc[0], 2.)
        self.assertTrue(np.isnan(frame.Foreign_Buy.iloc[1]))
        self.assertFalse(frame.Chip_Data_Available.iloc[1])

    def test_warning_mode_requires_explicit_opt_in_and_preserves_structural_exits(self):
        legacy = self.process_fixture()
        warning = self.process_fixture('warning')
        self.assertTrue(legacy.Overextended_MA5.iloc[-1])
        self.assertFalse(legacy.Hard_Sell_Signal.iloc[-1])
        self.assertTrue(legacy.Sell_Signal.iloc[-1])
        self.assertFalse(warning.Sell_Signal.iloc[-1])
        self.assertFalse(warning.Buy_Signal.iloc[-1])
        self.assertTrue((warning.Sell_Signal[warning.Hard_Sell_Signal]).all())

    def test_raw_sell_is_never_explained_as_model_hold(self):
        action, reason, meta = resolve_td_rl_strategy({
            'RL可用': True, 'RL持有策略': 'SELL', 'RL持有信心': 90.,
            'TD期待值': 1., '今日評分': 70,
        }, is_held=True)
        self.assertEqual(action, 'WATCH')
        self.assertIn('原判 SELL', reason)
        self.assertNotIn('Q-Learning 偏向續抱', reason)
        self.assertTrue(meta['overridden'])
        self.assertEqual(meta['raw_action'], 'SELL')
        self.assertFalse(meta['confidence_is_probability'])

    def test_missing_model_or_chips_cannot_confirm_new_entry(self):
        action, _, _ = resolve_td_rl_strategy({'RL可用': False, '今日評分': 90})
        self.assertEqual(action, 'WATCH')
        action, reason, _ = resolve_td_rl_strategy({
            'RL可用': True, 'RL空手策略': 'BUY', 'RL空手信心': 80,
            '今日評分': 90, 'TD期待值': 2., '籌碼資料狀態': 'partial',
        })
        self.assertEqual(action, 'WATCH')
        self.assertIn('資料缺失或不完整', reason)

    def test_price_extension_override_names_actual_condition(self):
        action, reason, meta = resolve_td_rl_strategy({
            'RL可用': True, 'RL空手策略': 'BUY', 'RL空手信心': 80.,
            'TD期待值': 2., '今日評分': 90, '是否觸發賣出': True,
            '硬性風控': False, '乖離過大': True,
            '硬性風控原因': ['五日乖離超標（維持原退出政策）'],
        })
        self.assertEqual(action, 'IGNORE')
        self.assertIn('五日乖離', reason)
        self.assertFalse(meta['hard_risk'])
        self.assertTrue(meta['exit_filter'])
        self.assertTrue(meta['extension_warning'])

    def test_all_production_call_sites_use_shared_period(self):
        root = Path(__file__).resolve().parent
        for filename in ('app.py', 'STOCK_GOD.py'):
            tree = ast.parse((root / filename).read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'TaiwanStockTradingSystem':
                    for keyword in node.keywords:
                        if keyword.arg == 'start_date':
                            self.assertIsInstance(keyword.value, ast.Name)
                            # The cache adapter forwards the caller's start_date.
                            allowed = ('TRAINING_START_DATE', 'start_date') if filename == 'app.py' else ('TRAINING_START_DATE',)
                            self.assertIn(keyword.value.id, allowed)
        self.assertEqual(TaiwanStockTradingSystem([]).start_date, TRAINING_START_DATE)
        self.assertEqual(TaiwanStockTradingSystem([]).extension_exit_mode, EXTENSION_EXIT_MODE)


if __name__ == '__main__':
    unittest.main()
