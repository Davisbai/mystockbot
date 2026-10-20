import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import streamlit as st
from streamlit.testing.v1 import AppTest
from STOCK_GOD import TaiwanStockTradingSystem
from app_support import observed_holding, performance_rows, sync_watchlist, tracking_report, normalize_decision, backtest_history_view

ROOT = Path(__file__).resolve().parent


class AppSupportTests(unittest.TestCase):
    def test_old_rule_actions_are_not_mislabelled_as_recent_quotes(self):
        logs = ['2024-11-22 | SELL', '2024-10-30 | BUY', 'not a dated trade']
        view = backtest_history_view(logs, '2026-10-20')
        self.assertEqual(view['recent'], [])
        self.assertEqual(view['latest_trade_date'], '2024-11-22')
        self.assertEqual(view['historical'], ['2024-10-30 | BUY', '2024-11-22 | SELL'])
        self.assertEqual(backtest_history_view([], '2026-10-20')['latest_trade_date'], None)

    def test_recent_rule_actions_use_the_analyzed_data_date(self):
        view = backtest_history_view(['2026-10-20 | SELL', '2026-10-01 | BUY',
                                      '2026-11-01 | future', '2024-11-22 | old'], '2026-10-20')
        self.assertEqual(view['recent'], ['2026-10-01 | BUY', '2026-10-20 | SELL'])

    def test_legacy_metadata_is_unknown_and_cannot_confirm_new_buy(self):
        action, reason, meta = normalize_decision(('BUY', 'old reason', {'confidence': 61}), {'RL可用': True, 'RL空手策略': 'BUY'})
        self.assertEqual(action, 'WATCH')
        self.assertIsNone(meta['state_support'])
        self.assertIsNone(meta['hard_risk'])
        self.assertEqual(meta['support_kind'], '未提供')
        self.assertFalse(meta['schema_compatible'])
        self.assertTrue(meta['overridden'])
        self.assertEqual(meta['override_reason'], reason)
        self.assertEqual(meta['confidence'], 61)
        self.assertEqual(normalize_decision(('SELL', 'risk', {}), {}, True)[0], 'SELL')

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
        st.cache_data.clear()
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

    def assert_diagnosis_ok(self, app):
        self.assertEqual(len(app.exception), 0)
        self.assertFalse(any('執行分析時發生錯誤' in item.value for item in app.error))
        self.assertTrue(any('最終系統判定' in item.value for item in app.markdown))

    def fake_analysis(self, system):
        system.market_data = self.prices.copy()
        return self.summary, {'2330.TW': dict(self.alert)}, {'2330.TW': []}

    def stale_support(self):
        import app_support
        stale = ModuleType('app_support')
        stale.__file__ = app_support.__file__
        for name in ('performance_rows', 'observed_holding', 'sync_watchlist', 'tracking_report'):
            setattr(stale, name, getattr(app_support, name))
        return stale

    def test_warm_deployment_reloads_cached_old_support_and_can_diagnose(self):
        for version in (None, 1, 2):
            with self.subTest(version=version):
                stale = self.stale_support()
                if version is not None:
                    stale.APP_SUPPORT_API_VERSION = version
                with patch.dict(sys.modules, {'app_support': stale}), \
                        patch('importlib.reload', wraps=__import__('importlib').reload) as reload_module, \
                        patch.object(TaiwanStockTradingSystem, 'run_analysis', autospec=True, side_effect=self.fake_analysis), \
                        patch('STOCK_GOD.load_watchlist', return_value={}), \
                        patch('STOCK_GOD.save_watchlist'):
                    app = self.app('2. 🔎 單股深度診斷')
                    app.button[0].click().run()
                    self.assert_diagnosis_ok(app)
                    reload_module.assert_called_once_with(stale)
                    self.assertTrue(callable(stale.normalize_decision))

    def test_current_support_does_not_reload_on_normal_reruns(self):
        with patch('importlib.reload', side_effect=AssertionError('unnecessary reload')) as reload_module:
            app = self.app('2. 🔎 單股深度診斷')
            app.text_input[0].set_value('1312').run()
            self.assertEqual(len(app.exception), 0)
            reload_module.assert_not_called()

    def test_core_loading_failure_stops_before_any_diagnosis(self):
        with patch('app_support.load_current_core', side_effect=ImportError('incompatible core')):
            app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('已停止分析' in item.value for item in app.error))
        self.assertEqual(len(app.sidebar.radio), 0)

    def test_runtime_change_invalidates_snapshot_and_calculation_cache(self):
        import STOCK_GOD
        from app_support import runtime_fingerprint
        revision = runtime_fingerprint()
        app = self.app('2. 🔎 單股深度診斷')
        with patch.object(TaiwanStockTradingSystem, 'run_analysis', autospec=True, side_effect=self.fake_analysis) as analysis, \
                patch('STOCK_GOD.load_watchlist', return_value={}), \
                patch('STOCK_GOD.save_watchlist'), \
                patch('app_support.load_current_core', return_value=(STOCK_GOD, revision)) as runtime:
            app.button[0].click().run()
            self.assert_diagnosis_ok(app)
            runtime.return_value = STOCK_GOD, 'changed-dependency-revision'
            app.run()
            self.assertFalse(any('最終系統判定' in item.value for item in app.markdown))
            app.button[0].click().run()
            self.assert_diagnosis_ok(app)
            self.assertEqual(analysis.call_count, 2)

    def test_incomplete_deployment_reports_reboot_without_uncaught_importerror(self):
        stale = self.stale_support()
        with patch.dict(sys.modules, {'app_support': stale}), \
                patch('importlib.reload', return_value=stale):
            app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('Reboot app' in item.value and 'app_support.py' in item.value for item in app.error))
        self.assertEqual(len(app.sidebar.radio), 0)

    def test_reload_importerror_reports_recovery_instead_of_crashing(self):
        stale = self.stale_support()
        with patch.dict(sys.modules, {'app_support': stale}), \
                patch('importlib.reload', side_effect=ImportError('test failure')):
            app = AppTest.from_file(str(ROOT / 'app.py'), default_timeout=30).run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('Reboot app' in item.value for item in app.error))

    def test_unavailable_history_module_does_not_break_diagnostic_startup(self):
        with patch.dict(sys.modules, {'analyze_push_history': None}):
            app = self.app('2. 🔎 單股深度診斷')
            self.assertEqual(len(app.error), 0)
            app.sidebar.radio[0].set_value('4. 🗂️ 歷史追蹤績效').run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any('無法載入或讀取追蹤紀錄' in item.value for item in app.error))

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
            app.checkbox(key='extra_ai').check().run()
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

    def test_old_backtest_actions_are_explicit_and_can_be_viewed_without_retraining(self):
        app = self.app('2. 🔎 單股深度診斷')
        def analysis(system):
            summary, alerts, logs = self.fake_analysis(system)
            logs['2330.TW'] = ['2024-11-22 | historical simulated SELL']
            return summary, alerts, logs
        with patch.object(TaiwanStockTradingSystem, 'run_analysis', autospec=True, side_effect=analysis) as computed, \
                patch('STOCK_GOD.load_watchlist', return_value={}), patch('STOCK_GOD.save_watchlist'):
            app.button[0].click().run()
            self.assert_diagnosis_ok(app)
            self.assertTrue(any('近 90 日沒有規則回測交易' in item.value for item in app.info))
            self.assertTrue(any('行情截止日：2026-10-02｜最後規則交易日：2024-11-22' in item.value for item in app.caption))
            self.assertFalse(any('historical simulated SELL' in item.value for item in app.text))
            app.checkbox(key='show_full_rule_history').check().run()
            self.assert_diagnosis_ok(app)
            self.assertTrue(any('historical simulated SELL' in item.value for item in app.text))
            self.assertEqual(computed.call_count, 1)

    def test_daily_list_page_reads_archives_and_filters_without_network_or_writes(self):
        import datetime
        import daily_signal_reports as reports
        now = datetime.datetime(2026, 10, 15, 19, tzinfo=reports.TAIPEI)
        alert = {'日期': '2026-10-15', '收盤價': 110., '今日評分': 80, '日線已收盤': True}
        with tempfile.TemporaryDirectory() as directory:
            report = reports.build_daily_report(
                {'2330.TW': alert}, {'2330.TW': '台積電'}, {},
                {'2330.TW': ('BUY', 'entry reason', {'raw_action': 'BUY'})}, now=now)
            archive = reports.save_daily_report(report, directory)
            before = archive.read_bytes()
            with patch.object(reports, 'REPORT_DIRECTORY', Path(directory)), \
                    patch('STOCK_GOD.yf.download', side_effect=AssertionError('unexpected network request')), \
                    patch('STOCK_GOD.save_watchlist', side_effect=AssertionError('unexpected write')):
                app = self.app('6. 📋 每日訊號清單')
                self.assertEqual(len(app.exception), 0)
                self.assertEqual(app.selectbox[0].value, '2026-10-15')
                self.assertEqual(app.dataframe[0].value.iloc[0]['類別'], '當日買入')
                next(r for r in app.radio if r.label == '清單類別').set_value('當日賣出').run()
                self.assertEqual(len(app.dataframe), 0)
                self.assertTrue(any('本類無股票' in item.value for item in app.info))
                self.assertEqual(archive.read_bytes(), before)

    def test_daily_list_page_handles_missing_and_corrupt_archives(self):
        import daily_signal_reports as reports
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(reports, 'REPORT_DIRECTORY', Path(directory)):
            app = self.app('6. 📋 每日訊號清單')
            self.assertTrue(any('尚無每日清單' in item.value for item in app.info))
            (Path(directory) / '2026-10-15.json').write_text('{}', encoding='utf-8')
            app.run()
            self.assertEqual(len(app.exception), 0)
            self.assertTrue(any('無法讀取每日清單' in item.value for item in app.error))

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
            app.checkbox(key='extra_ai').check().run()
        self.assertEqual(len(app.exception), 0)
        self.assertTrue(any('AI 模型目前無可用結果' in item.value for item in app.caption))
        self.assertTrue(any('已完成交易筆數' in frame.value.columns for frame in app.dataframe))

    def test_fast_default_skips_extras_and_reruns_preserve_decision(self):
        self.alert.update({'RL可用': True, 'RL空手策略': 'BUY', 'RL持有策略': 'HOLD',
                           'RL空手信心': 60, 'TD期待值': 1., '籌碼資料狀態': 'available',
                           '日線已收盤': True})
        app = self.app('2. 🔎 單股深度診斷')
        with patch.object(TaiwanStockTradingSystem, 'run_analysis', autospec=True, side_effect=self.fake_analysis) as analysis, \
                patch('STOCK_GOD.AdvancedQuantEngine', side_effect=AssertionError('extra AI must be opt-in')) as extra, \
                patch('STOCK_GOD.yf.Ticker', return_value=SimpleNamespace(info={})) as info, \
                patch('STOCK_GOD.load_watchlist', return_value={}) as watchlist, \
                patch('STOCK_GOD.save_watchlist') as saved:
            app.button[0].click().run()
            self.assert_diagnosis_ok(app)
            self.assertTrue(any('【買入】' in item.value for item in app.success))
            self.assertEqual(saved.call_count, 1)
            extra.assert_not_called()
            info.assert_not_called()
            # The preceding BUY may have changed the on-disk list. Supplementary UI
            # must retain the analyzed flat-position decision and never write again.
            watchlist.return_value = {'2330.TW': {'加入日期': '2026-10-02', '加入價格': 110}}
            app.checkbox(key='extra_fundamentals').check().run()
            self.assert_diagnosis_ok(app)
            self.assertEqual(analysis.call_count, 1)
            self.assertEqual(saved.call_count, 1)
            self.assertEqual(info.call_count, 1)
            extra.assert_not_called()
            self.assertTrue(any('【買入】' in item.value for item in app.success))
            self.assertTrue(any(item.label == '每股淨值 (NAV)' and item.value == '—' for item in app.metric))
            app.checkbox(key='extra_fundamentals').uncheck().run()
            app.text_input[0].set_value('1326').run()
            self.assert_diagnosis_ok(app)
            self.assertEqual(analysis.call_count, 1)
            self.assertTrue(any('2330.TW' in item.value for item in app.success))
            app.sidebar.button[0].click().run()
            self.assertFalse(any('最終系統判定' in item.value for item in app.markdown))

    def test_legacy_core_metadata_renders_single_and_scan_without_key_errors(self):
        legacy = ('WATCH', 'legacy reason', {'confidence': 55})
        with patch.object(TaiwanStockTradingSystem, 'run_analysis', autospec=True, side_effect=self.fake_analysis), \
                patch('STOCK_GOD.resolve_td_rl_strategy', return_value=legacy), \
                patch('STOCK_GOD.load_watchlist', return_value={}), \
                patch('STOCK_GOD.save_watchlist'), \
                patch('STOCK_GOD.YahooMarketScanner.scan', return_value=[]):
            app = self.app('2. 🔎 單股深度診斷')
            app.button[0].click().run()
            self.assert_diagnosis_ok(app)
            self.assertTrue(any('狀態支持 未提供' in item.value for item in app.caption))
            self.assertTrue(any('核心回傳欄位不完整' in item.value for item in app.warning))
            app.sidebar.radio[0].set_value('1. 🚀 執行完整策略掃描').run()
            app.button[0].click().run()
            self.assertEqual(len(app.exception), 0)
            self.assertEqual(app.dataframe[0].value.iloc[0]['樣本類型'], '未提供')

    def test_session_snapshot_expires_without_network_or_watchlist_writes(self):
        app = self.app('2. 🔎 單股深度診斷')
        with patch.object(TaiwanStockTradingSystem, 'run_analysis', autospec=True, side_effect=self.fake_analysis) as analysis, \
                patch('STOCK_GOD.load_watchlist', return_value={}), \
                patch('STOCK_GOD.save_watchlist') as saved:
            app.button[0].click().run()
            self.assert_diagnosis_ok(app)
            snapshot = dict(app.session_state['single_diagnosis'])
            snapshot['saved_at'] -= 301
            app.session_state['single_diagnosis'] = snapshot
            app.run()
            self.assertEqual(analysis.call_count, 1)
            saved.assert_not_called()
            self.assertTrue(any('請重新按開始診斷' in item.value for item in app.info))
            self.assertFalse(any('最終系統判定' in item.value for item in app.markdown))

    def test_repeated_scan_reuses_calculation_but_reads_fresh_watchlist(self):
        app = self.app('1. 🚀 執行完整策略掃描')
        with patch.object(TaiwanStockTradingSystem, 'run_analysis', autospec=True, side_effect=self.fake_analysis) as analysis, \
                patch('STOCK_GOD.STOCK_MAP', {'2330.TW': '台積電'}), \
                patch('STOCK_GOD.YahooMarketScanner.scan', return_value=[]), \
                patch('STOCK_GOD.load_watchlist', return_value={}) as watchlist:
            app.button[0].click().run()
            self.assertEqual(app.dataframe[0].value.iloc[0]['列入監控'], '—')
            watchlist.return_value = {'2330.TW': {'名稱': '台積電', '加入日期': '2026-01-01', '加入價格': 100}}
            app.button[0].click().run()
            self.assertEqual(app.dataframe[0].value.iloc[0]['列入監控'], '✅')
            self.assertEqual(analysis.call_count, 1)
            app.sidebar.button[0].click().run()
            app.button[0].click().run()
            self.assertEqual(analysis.call_count, 2)
        self.assertEqual(len(app.exception), 0)


if __name__ == '__main__':
    unittest.main()
