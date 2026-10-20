import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from STOCK_GOD import recent_limit_up_support, TaiwanStockTradingSystem


class SupportExpiryTests(unittest.TestCase):
    def frame(self):
        frame = pd.DataFrame({'Open': 100., 'High': 110., 'Is_Limit_Up': False},
                             index=pd.bdate_range('2024-01-01', periods=70))
        frame.iloc[20, frame.columns.get_loc('Is_Limit_Up')] = True
        return frame

    def test_support_expires_with_the_existing_twenty_session_gene(self):
        frame = self.frame()
        result = recent_limit_up_support(frame)
        self.assertEqual(result.Limit_Up_Support.iloc[20], 100.)
        self.assertTrue(result.Limit_Up_Valid.iloc[39])
        self.assertFalse(result.Limit_Up_Valid.iloc[40])
        self.assertTrue(result.Limit_Up_Support.iloc[40:].isna().all())
        self.assertTrue(result.Limit_Up_Anchor.iloc[40:].isna().all())
        self.assertTrue(result.Limit_Up_Type.iloc[40:].eq('NONE').all())

    def test_new_anchor_and_four_limitups_never_inherit_old_support(self):
        frame = self.frame()
        frame.iloc[21:24, frame.columns.get_loc('Is_Limit_Up')] = True
        frame.iloc[21, frame.columns.get_loc('High')] = 120.
        result = recent_limit_up_support(frame)
        self.assertEqual(result.Limit_Up_Type.iloc[22], 'MULTI')
        self.assertEqual(result.Limit_Up_Support.iloc[22], 110.)
        self.assertFalse(result.Limit_Up_Valid.iloc[23])
        self.assertTrue(pd.isna(result.Limit_Up_Support.iloc[23]))
        self.assertEqual(result.Limit_Up_Anchor.iloc[40], frame.index[21])
        self.assertEqual(result.Limit_Up_Support.iloc[40], 120.)

    def test_future_limitups_do_not_change_prior_support(self):
        frame = self.frame()
        before = recent_limit_up_support(frame.iloc[:35])
        frame.iloc[50, frame.columns.get_loc('Is_Limit_Up')] = True
        after = recent_limit_up_support(frame)
        pd.testing.assert_frame_equal(before, after.iloc[:35])

    def test_invalid_anchor_prices_do_not_become_support(self):
        for value in (0., float('nan'), float('inf')):
            frame = self.frame()
            frame.iloc[20, frame.columns.get_loc('Open')] = value
            self.assertFalse(recent_limit_up_support(frame).Limit_Up_Valid.any())

    def test_process_keeps_valid_exit_but_drops_expired_anchor(self):
        dates = pd.bdate_range('2024-01-01', periods=120)
        close = np.full(len(dates), 100.)
        close[60], close[61:] = 110., 95.
        prices = pd.DataFrame({'Open': close * .995, 'High': close * 1.01,
                               'Low': close * .99, 'Close': close, 'Volume': 1_000_000.}, index=dates)
        prices.iloc[60, prices.columns.get_loc('Open')] = 100.
        system = TaiwanStockTradingSystem(['6561.TWO'])
        system.market_data = pd.DataFrame({'Close': 100., 'Market_OK': True}, index=dates)
        with patch('STOCK_GOD.yf.download', return_value=prices), \
                patch.object(system, 'fetch_real_chip_data', side_effect=lambda frame, ticker: frame.assign(
                    Foreign_Buy=0., Trust_Buy=0., Margin_Balance=np.nan)):
            result = system.process_stock('6561.TWO')
        self.assertTrue(result.Is_Limit_Up.iloc[60])
        self.assertTrue(result.Limit_Up_Support_Broken.iloc[62])
        self.assertTrue(result.Sell_Signal.iloc[62])
        self.assertFalse(result.Limit_Up_Support_Broken.iloc[80:].any())
        self.assertFalse(result.Sell_Signal.iloc[-1])


if __name__ == '__main__':
    unittest.main()
