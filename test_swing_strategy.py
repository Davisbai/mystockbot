import unittest

import pandas as pd

from swing_strategy import evaluate_swing


class SwingStrategyTests(unittest.TestCase):
    def prices(self):
        closes = ([100 + i * .25 for i in range(80)] +
                  [119.75 - i * .4 for i in range(10)] +
                  [116.15 + i * .7 for i in range(25)] +
                  [132.95 - i * 1.2 for i in range(30)])
        dates = pd.bdate_range('2025-01-01', periods=len(closes))
        return pd.DataFrame({'Open': closes, 'Close': closes}, index=dates)

    def test_signals_fill_next_day_and_costs_affect_result(self):
        prices = self.prices()
        result = evaluate_swing(prices)
        self.assertGreaterEqual(result['summary']['已平倉筆數'], 1)
        self.assertTrue(all(t['賣出日'] > t['買入日'] for t in result['trades']))
        self.assertTrue(all(t['股數'] > 0 for t in result['trades']))
        self.assertLess(result['summary']['扣成本報酬 (%)'],
                        evaluate_swing(prices, fee=0, min_fee=0, slippage=0)['summary']['扣成本報酬 (%)'])
        signal = evaluate_swing(prices.iloc[:90])
        if signal['signal'] == 'BUY':
            extended = evaluate_swing(prices.iloc[:91])
            self.assertGreater(extended['summary']['模擬持股數'], 0)

    def test_future_prices_do_not_change_earlier_signal(self):
        prices = self.prices()
        previous = evaluate_swing(prices.iloc[:115])
        prices.loc[prices.index[115]:, 'Close'] *= 1.8
        self.assertEqual(previous['signal'], evaluate_swing(prices.iloc[:115])['signal'])

    def test_no_history_and_unfinished_values_are_rejected(self):
        with self.assertRaisesRegex(ValueError, '65'):
            evaluate_swing(self.prices().iloc[:60])
        bad = self.prices()
        bad.loc[bad.index[-1], 'Close'] = float('nan')
        with self.assertRaisesRegex(ValueError, '完整'):
            evaluate_swing(bad)


if __name__ == '__main__':
    unittest.main()
