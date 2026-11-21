import sys
import types
import unittest

try:
    import FinMind  # noqa: F401
except Exception:  # optional data dependency is irrelevant to this rule
    module, data = types.ModuleType('FinMind'), types.ModuleType('FinMind.data')
    data.DataLoader = object
    sys.modules.update({'FinMind': module, 'FinMind.data': data})

from STOCK_GOD import resolve_td_rl_strategy
from strategy_config import MIN_ENTRY_SUPPORT, MIN_ENTRY_TD_PCT


def alert(support, td):
    return {'RL可用': True, '今日評分': 70, 'RL空手策略': 'BUY', 'RL空手信心': 60,
            '日線已收盤': True, '籌碼資料狀態': 'available', 'RL空手樣本': support, 'TD期待值': td}


class EntryFloorTests(unittest.TestCase):
    def test_low_support_is_watch(self):
        self.assertEqual(resolve_td_rl_strategy(alert(MIN_ENTRY_SUPPORT - 1, 5.0))[0], 'WATCH')

    def test_low_td_is_watch(self):
        self.assertEqual(resolve_td_rl_strategy(alert(20, MIN_ENTRY_TD_PCT - 0.01))[0], 'WATCH')

    def test_meeting_both_floors_is_buy(self):
        self.assertEqual(resolve_td_rl_strategy(alert(MIN_ENTRY_SUPPORT, MIN_ENTRY_TD_PCT))[0], 'BUY')

    def test_held_stock_unaffected(self):
        self.assertNotEqual(resolve_td_rl_strategy(alert(1, 0.1), is_held=True)[0], 'IGNORE-NEVER')


if __name__ == '__main__':
    unittest.main()
