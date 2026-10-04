import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from strategy_performance import backtest_signals, watchlist_risk
from analyze_push_history import analyze
from STOCK_GOD import AdvancedQuantEngine, TDRLDecisionEngine, TaiwanStockTradingSystem, resolve_td_rl_strategy


class PerformanceTests(unittest.TestCase):
    def frame(self):
        return pd.DataFrame({'Open': [100., 110., 121., 100.],
                             'Close': [100., 121., 110., 100.],
                             'Buy_Signal': [True, False, False, False],
                             'Sell_Signal': [False, True, False, False]},
                            index=pd.date_range('2026-01-01', periods=4))

    def test_next_open_costs_and_completed_trade(self):
        result = backtest_signals(self.frame())
        expected = 121 / 110 * (1 - .0008) * (1 - .0038) - 1
        self.assertEqual(result.Trade_Action.tolist(), [0, 1, -1, 0])
        self.assertAlmostEqual(result.attrs['completed_trades'][0]['net_return'], expected)
        self.assertAlmostEqual((1 + result.Strategy_Returns).prod() - 1, expected)
        self.assertEqual(result.attrs['performance']['勝率 (%)'], 100.)

    def test_sell_priority_and_unknown_win_rate(self):
        data = self.frame()
        data.loc[data.index[0], 'Sell_Signal'] = True
        result = backtest_signals(data)
        self.assertFalse(result.Position.any())
        self.assertTrue(np.isnan(result.attrs['performance']['勝率 (%)']))

    def test_open_trade_excluded_and_first_day_drawdown(self):
        data = self.frame()
        data['Sell_Signal'] = False
        data['Open'] = 100.
        data['Close'] = 100.
        result = backtest_signals(data)
        self.assertTrue(result.attrs['performance']['未平倉'])
        self.assertEqual(result.attrs['performance']['完成交易筆數'], 0)
        self.assertLess(result.attrs['performance']['最大回撤 (%)'], 0)

    def test_future_prices_do_not_change_prior_equity(self):
        data = self.frame()
        before = backtest_signals(data)
        data.loc[data.index[-1], ['Open', 'Close']] = [500., 10.]
        after = backtest_signals(data)
        pd.testing.assert_series_equal(before.Strategy_Returns.iloc[:-1], after.Strategy_Returns.iloc[:-1])

    def test_reference_risk_opt_in(self):
        self.assertEqual(watchlist_risk(90, 100, 100), 'REFERENCE_STOP_LOSS')
        self.assertEqual(watchlist_risk(120, 100, 150), 'REFERENCE_TRAILING_STOP')
        self.assertIsNone(watchlist_risk(108, 100, 112))
        alert = {'收盤價': 90, '今日評分': 90, 'RL可用': False}
        with patch.dict('os.environ', {'STOCK_ENABLE_REFERENCE_STOPS': '1'}):
            decision = resolve_td_rl_strategy(alert, True, {'加入價格': 100})
        self.assertEqual(decision[0], 'SELL')

    def test_missing_rl_never_overrides_hard_risk(self):
        decision = resolve_td_rl_strategy({'RL可用': False, '今日評分': 95,
                                           '是否觸發賣出': True}, False)
        self.assertEqual(decision[0], 'IGNORE')

    def test_process_stock_keeps_performance_and_risk_priority(self):
        rng = np.random.RandomState(21)
        dates = pd.bdate_range('2024-01-01', periods=240)
        close = 100 * np.exp(np.cumsum(rng.normal(.001, .02, len(dates))))
        prices = pd.DataFrame({'Open': close * .997, 'Close': close,
                               'High': close * 1.025, 'Low': close * .975,
                               'Volume': rng.randint(1000000, 4000000, len(dates))}, index=dates)
        system = TaiwanStockTradingSystem(['2330.TW'])
        system.market_data = pd.DataFrame({'Close': close * 100, 'Market_OK': True}, index=dates)
        def chip_data(frame, ticker):
            return frame.assign(Foreign_Buy=0., Trust_Buy=0., Margin_Balance=0.)
        with patch('STOCK_GOD.yf.download', return_value=prices.copy()), \
                patch.object(system, 'fetch_real_chip_data', side_effect=chip_data):
            result = system.process_stock('2330.TW')
        self.assertIn('performance', result.attrs)
        self.assertFalse((result.Buy_Signal & result.Sell_Signal).any())
        self.assertTrue(np.isfinite(result.Strategy_Returns).all())

    def test_rl_epochs_do_not_inflate_sample_count(self):
        data = pd.DataFrame({'Close': [100., 101., 102., 103.]})
        engine = TDRLDecisionEngine(min_rows=2, epochs=3)
        engine.fit_predict(data)
        self.assertEqual(sum(engine.v_visits.values()), 3)
        self.assertEqual(sum(engine.q_visits.values()), 6)
        engine.fit_predict(data)
        self.assertEqual(sum(engine.v_visits.values()), 3)

    def test_immature_labels_and_purged_validation(self):
        rng = np.random.RandomState(8)
        close = 100 * np.exp(np.cumsum(rng.normal(.002, .015, 400)))
        engine = AdvancedQuantEngine()
        engine.data = pd.DataFrame({'Close': close}, index=pd.date_range('2024-01-01', periods=400))
        engine.data['Return'] = engine.data.Close.pct_change()
        for window in (20, 50):
            engine.data[f'Volatility_{window}'] = engine.data.Return.rolling(window).std() * np.sqrt(252)
        for window in (10, 20):
            engine.data[f'Momentum_{window}'] = engine.data.Close.pct_change(window)
        engine.data = engine.data.dropna()
        engine.detect_market_regime()
        engine.apply_triple_barrier()
        self.assertTrue(engine.data.label.iloc[-10:].isna().all())
        self.assertTrue(engine.train_meta_labeling_model())
        selected = engine.data[(engine.data.Primary_Signal == 1) &
                               (engine.data.index < engine.validation_start) &
                               (engine.data.end_date < engine.validation_start)].dropna()
        self.assertEqual(engine.validation_metrics['train_samples'], len(selected))

    def test_log_deduplicates_same_session_and_matches_cost(self):
        block = '[2026-01-02 {time}] 推播紀錄\n📌 【長期監控清單】\n測試 (2330)\n📅 買入日期: 2026-01-01\n💰 成本: 100 ➔ 現價: {price}\n'
        log = block.format(time='19:00:00', price=120) + block.format(time='20:00:00', price=110)
        report = analyze(log, {'2330.TW': {'加入日期': '2026-01-01', '加入價格': 100}})
        self.assertEqual(report['current_episodes_matched'], 1)
        self.assertEqual(report['episodes'][0]['observed_sessions'], 1)
        self.assertEqual(report['episodes'][0]['last_price'], 110)


if __name__ == '__main__':
    unittest.main()
