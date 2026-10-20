"""Causality, exit preservation and cost checks for offline entry research."""
import unittest

import numpy as np
import pandas as pd

from research_entry_quality import (VARIANTS, cooldown_signals, entry_candidates,
                                    entry_evidence, evaluate, trade_audit)
from strategy_performance import backtest_signals


def frame():
    index = pd.bdate_range('2025-01-01', periods=12)
    return pd.DataFrame({'Open': 100., 'Close': 100., 'Score': 65.,
                         'Buy_Signal': True, 'Sell_Signal': False,
                         'MA20': np.arange(12) + 90.,
                         'Inst_Consecutive': [False, True] * 6}, index=index)


class EntryQualityResearchTests(unittest.TestCase):
    def test_every_candidate_is_causal(self):
        data = frame()
        for variant in VARIANTS:
            full = entry_candidates(data, variant)
            for length in range(1, len(data) + 1):
                with self.subTest(variant=variant, length=length):
                    pd.testing.assert_series_equal(
                        full.iloc[:length], entry_candidates(data.iloc[:length], variant))

    def test_entry_filters_never_add_an_originally_absent_buy(self):
        data = frame()
        data.iloc[5, data.columns.get_loc('Buy_Signal')] = False
        for variant in VARIANTS:
            self.assertFalse((entry_candidates(data, variant) & ~data.Buy_Signal).any())

    def test_missing_evidence_is_not_confirmation(self):
        data = frame().drop(columns='Inst_Consecutive')
        data['Pro_Bottom_Breakout'] = np.nan
        self.assertFalse(entry_evidence(data).any())
        self.assertFalse(entry_candidates(data, 'evidence').any())

    def test_price_breakout_needs_volume(self):
        data = frame().drop(columns='Inst_Consecutive')
        data['Price_Breakout'] = True
        data['Volume_Surge'] = False
        self.assertFalse(entry_evidence(data).any())
        data.iloc[2, data.columns.get_loc('Volume_Surge')] = True
        self.assertEqual(list(np.flatnonzero(entry_evidence(data))), [2])

    def test_two_day_confirmation_uses_prior_original_signal(self):
        data = frame()
        data['Buy_Signal'] = [True, True, False, True, True, True] * 2
        self.assertEqual(list(entry_candidates(data, 'confirm_2').iloc[:6]),
                         [False, True, False, False, True, True])

    def test_cooldown_does_not_delay_an_exit(self):
        data = frame()
        data.iloc[2, data.columns.get_loc('Sell_Signal')] = True
        original = backtest_signals(data)
        candidate = data.copy()
        candidate['Buy_Signal'] = cooldown_signals(data)
        result = backtest_signals(candidate)
        self.assertEqual(original.attrs['completed_trades'][0]['exit_date'],
                         result.attrs['completed_trades'][0]['exit_date'])
        self.assertEqual(list(result.Trade_Action.iloc[:8]), [0, 1, 0, -1, 0, 0, 0, 1])

    def test_filters_preserve_all_sell_flags_and_input(self):
        data = frame()
        data.iloc[2, data.columns.get_loc('Sell_Signal')] = True
        before = data.copy(deep=True)
        for variant in VARIANTS:
            result, _ = evaluate(data, variant, '2025-01-01', '2025-01-31')
            pd.testing.assert_series_equal(result.Sell_Signal, data.Sell_Signal)
        pd.testing.assert_frame_equal(data, before)

    def test_net_and_gross_separate_cost_only_loss(self):
        data = frame().iloc[:4].copy()
        data['Buy_Signal'] = [True, False, False, False]
        data['Sell_Signal'] = [False, True, False, False]
        data['Open'] = [100., 100., 100.2, 100.2]
        data['Close'] = data.Open
        data['Inst_Consecutive'] = np.nan
        result, metrics = evaluate(data, 'baseline', '2025-01-01', '2025-01-31')
        self.assertAlmostEqual(metrics['gross_return_pct'], .2, places=4)
        self.assertLess(metrics['net_return_pct'], 0)
        audit = trade_audit(result)
        self.assertEqual(audit['gross_winners_lost_to_cost'], 1)
        self.assertEqual(audit['short_trade_losses'], 1)
        self.assertFalse(audit['trades'][0]['independent_evidence'])

    def test_invalid_prices_fail_instead_of_filling(self):
        data = frame()
        data.iloc[-1, data.columns.get_loc('Open')] = np.nan
        with self.assertRaisesRegex(ValueError, 'positive and complete'):
            evaluate(data, 'baseline', '2025-01-01', '2025-01-31')

    def test_unknown_variant_is_rejected(self):
        with self.assertRaises(ValueError):
            entry_candidates(frame(), 'guaranteed_profit')


if __name__ == '__main__':
    unittest.main()
