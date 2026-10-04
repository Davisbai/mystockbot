import copy
import json
import math
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
from streamlit.testing.v1 import AppTest
from STOCK_GOD import TaiwanStockTradingSystem
from app_support import observed_holding, performance_rows, sync_watchlist, tracking_report

ROOT = Path(__file__).resolve().parent


class AppSupportTests(unittest.TestCase):
    def test_performance_keeps_days_separate_from_completed_trades(self):
        summary = {'2330.TW': {'總交易天數': 20, '完成交易筆數': 2,
                              '勝率 (%)': 50., '策略累積報酬 (%)': 3.,
                              '最大回撤 (%)': -4., '未平倉': True}}
        row = performance_rows(summary, {'2330.TW': '台積電'})[0]
        self.assertEqual(row['持倉交易日數'], 20)
        self.assertEqual(row['已完成交易筆數'], 2)
        self.assertEqual(row['最大回撤 (%)'], -4.)

    def test_existing_entry_is_preserved_on_buy(self):
        watchlist = {'2330.TW': {'名稱': '台積電', '加入日期': '2026-01-01', '加入價格': 100}}
        sync_watchlist(watchlist, '2330.TW', '台積電', {'日期': '2026-02-01', '收盤價': 130}, 'BUY')
        self.assertEqual(watchlist['2330.TW']['加入價格'], 100)
        self.assertEqual(watchlist['2330.TW']['加入日期'], '2026-01-01')
        self.assertEqual(watchlist['2330.TW']['觀察最高價'], 130)

    def test_peak_rejects_stale_and_nonfinite_prices(self):
        record = {'加入日期': '2026-01-01', '加入價格': 100, '觀察最高價': 120}
        for alert in ({'日期': '2025-12-01', '收盤價': 500},
                      {'日期': '2026-02-01', '收盤價': float('nan')}):
            self.assertEqual(observed_holding(record, alert), record)

    def test_sync_ignores_bad_entries_and_removes_on_sell(self):
        watchlist = {}
        self.assertFalse(sync_watchlist(watchlist, '2330.TW', '台積電', {'日期': '2026-01-01', '收盤價': 0}, 'BUY'))
        sync_watchlist(watchlist, '2330.TW', '台積電', {'日期': '2026-01-01', '收盤價': 100}, 'BUY')
        self.assertTrue(sync_watchlist(watchlist, '2330.TW', '台積電', {'收盤價': 90}, 'SELL'))
        self.assertEqual(watchlist, {})

    def test_no_finished_trade_stays_missing(self):
        row = performance_rows({'X': {'總交易天數': 3, '完成交易筆數': 0,
                                     '勝率 (%)': float('nan'), '策略累積報酬 (%)': 0,
                                     '最大回撤 (%)': 0, '未平倉': True}}, {})[0]
        self.assertTrue(math.isnan(row['已平倉勝率 (%)']))


class StreamlitTests(unittest.TestCase):
    def setUp(self):
        self.prices = pd.DataFrame({'Close': [100., 110.], 'Market_MA20': [99., 100.]})
        self.alert = {'日期': '2026-10-02', '收盤價': 110., '月線價': 100.,
                      '今日漲幅': 1., '今日評分': 70, '個股原始評分': 70,
                      '大盤安全': True, 'RL可用': False, 'TD期待值': 0.}
        self.summary = {'2330.TW': {'總交易天數': 20, '完成交易筆數': 2,
                                    '勝率 (%)': 50., '策略累積報酬 (%)': 3.,
                                    '最大回撤 (%)': -4., '未平倉': True}}

    def app(self, menu):
        app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
        app.sidebar.radio[0].set_value(menu).run()
        self.assertEqual(len(app.exception), 0)
        return app

    def fake_analysis(self, system):
        system.market_data = self.prices.copy()
        return self.summary, {'2330.TW': dict(self.alert)}, {'2330.TW': []}

    def test_all_menu_pages_start_without_network(self):
        with patch('STOCK_GOD.yf.download', side_effect=AssertionError('unexpected external request')):
            app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
            options = list(app.sidebar.radio[0].options)
            for option in options:
                app.sidebar.radio[0].set_value(option).run()
                self.assertEqual(len(app.exception), 0, option)

    def test_history_filter_survives_rerun_and_does_not_modify_sources(self):
        before = {name: (ROOT / name).read_bytes() for name in ('line_push_log.txt', 'long_term_watchlist.json')}
        expected = tracking_report(before['line_push_log.txt'].decode('utf-8'),
                                   json.loads(before['long_term_watchlist.json']))
        app = self.app('4. 🗂️ 歷史追蹤績效')
        self.assertEqual(len(app.dataframe[0].value), expected['tracked_episodes'])
        next(r for r in app.radio if r.label == '顯示範圍').set_value('目前監控').run()
        self.assertEqual(len(app.dataframe[0].value), expected['current_episodes_matched'])
        app.number_input[0].set_value(10000).run()
        self.assertEqual(len(app.dataframe), 0)
        for name, data in before.items():
            self.assertEqual((ROOT / name).read_bytes(), data)

    def test_backtest_ui_renders_completed_trades_and_drawdown(self):
        app = self.app('3. 📈 策略回測')
        with patch.object(TaiwanStockTradingSystem, 'run_analysis', lambda system: self.fake_analysis(system)):
            app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.dataframe[0].value.iloc[0]['已完成交易筆數'], 2)
        self.assertEqual(app.dataframe[0].value.iloc[0]['最大回撤 (%)'], -4.)

    def test_scan_uses_core_risk_priority_without_extra_market_fetch(self):
        self.alert['是否觸發賣出'] = True
        self.alert['今日評分'] = 95
        app = self.app('1. 🚀 執行完整策略掃描')
        with patch.object(TaiwanStockTradingSystem, 'run_analysis', lambda system: self.fake_analysis(system)), \
                patch.object(TaiwanStockTradingSystem, 'fetch_market_data', side_effect=AssertionError('duplicate fetch')), \
                patch('STOCK_GOD.YahooMarketScanner.scan', return_value=[]), \
                patch('STOCK_GOD.load_watchlist', return_value={}):
            app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(app.dataframe[0].value.iloc[0]['策略'], '⚪ 不理會')

    def test_single_diagnosis_renders_ai_validation_and_retains_entry(self):
        watchlist = {'2330.TW': {'名稱': '台積電', '加入日期': '2026-01-01', '加入價格': 100}}
        ai = SimpleNamespace(
            fetch_data=lambda **kwargs: True, detect_market_regime=lambda: None,
            apply_triple_barrier=lambda: None, train_meta_labeling_model=lambda: True,
            data=pd.DataFrame({'Volatility_20': [.2], 'Volatility_50': [.2],
                               'Momentum_10': [.1], 'Momentum_20': [.2], 'Regime': [2]}),
            meta_classifier=SimpleNamespace(predict_proba=lambda _: np.array([[.3, .7]])),
            validation_metrics={'validation_start': '2026-06-01', 'train_samples': 100,
                                'test_samples': 30, 'accuracy': .6, 'balanced_accuracy': .55,
                                'precision': .7, 'always_positive_accuracy': .65},
        )
        app = self.app('2. 🔎 單股深度診斷')
        with patch.object(TaiwanStockTradingSystem, 'run_analysis', lambda system: self.fake_analysis(system)), \
                patch('STOCK_GOD.AdvancedQuantEngine', return_value=ai), \
                patch('STOCK_GOD.load_watchlist', side_effect=lambda: copy.deepcopy(watchlist)), \
                patch('STOCK_GOD.save_watchlist') as saved, \
                patch('STOCK_GOD.yf.Ticker', return_value=SimpleNamespace(info={})):
            app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertEqual(saved.call_args[0][0]['2330.TW']['加入日期'], '2026-01-01')
        self.assertEqual(saved.call_args[0][0]['2330.TW']['加入價格'], 100)
        self.assertTrue(any('AI 模型正類機率' in item.value for item in app.markdown))
        self.assertTrue(any('平衡正確率 (%)' in frame.value.columns for frame in app.dataframe))

    def test_market_download_empty_is_reported_without_exception(self):
        app = self.app('5. 📊 檢查大盤現況')
        with patch('STOCK_GOD.yf.download', return_value=pd.DataFrame()):
            app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('大盤資料不足' in item.value for item in app.warning))

    def test_analysis_failure_is_reported_without_page_crash(self):
        app = self.app('3. 📈 策略回測')
        with patch.object(TaiwanStockTradingSystem, 'run_analysis', side_effect=RuntimeError('unavailable')):
            app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('行情分析失敗' in item.value for item in app.error))

    def test_ai_failure_keeps_rule_diagnosis(self):
        app = self.app('2. 🔎 單股深度診斷')
        ai = SimpleNamespace(fetch_data=lambda **kwargs: (_ for _ in ()).throw(RuntimeError('model unavailable')))
        with patch.object(TaiwanStockTradingSystem, 'run_analysis', lambda system: self.fake_analysis(system)), \
                patch('STOCK_GOD.AdvancedQuantEngine', return_value=ai), \
                patch('STOCK_GOD.load_watchlist', return_value={}), \
                patch('STOCK_GOD.save_watchlist'), \
                patch('STOCK_GOD.yf.Ticker', return_value=SimpleNamespace(info={})):
            app.button[0].click().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('AI 模型目前無可用結果' in item.value for item in app.caption))
        self.assertTrue(any('已完成交易筆數' in frame.value.columns for frame in app.dataframe))


if __name__ == '__main__':
    unittest.main()
