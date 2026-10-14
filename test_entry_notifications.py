import copy
import os
import unittest
from unittest.mock import patch, mock_open, MagicMock
import requests
from entry_notifications import plan_entry_notices, deliver_entry_report
from STOCK_GOD import resolve_td_rl_strategy, send_line_message


class EntryNotificationTests(unittest.TestCase):
    def setUp(self):
        self.alert = {'日期': '2026-10-12', '收盤價': 16.05, '月線價': 14.5,
                      '今日評分': 85, 'RL可用': True, 'RL空手策略': 'BUY',
                      'RL空手信心': 70, 'TD期待值': 1., '上升趨勢': True,
                      '籌碼資料狀態': 'available', 'Q買入': 2., 'Q空手等待': 1.}
        self.state = {'pending': {}, 'sent': {}}

    def plan(self, state=None, holding=None):
        return plan_entry_notices({'1312.TW': self.alert}, {'1312.TW': '國喬'}, holding or {},
                                  self.state if state is None else state, resolve_td_rl_strategy)

    def test_entry_is_clear_and_does_not_mutate_holdings(self):
        holdings = {}
        state, pending = self.plan(holding=holdings)
        self.assertEqual(pending[0][1]['level'], 'ENTRY')
        self.assertIn('16.05', pending[0][1]['message'])
        self.assertIn('非收盤價成交保證', pending[0][1]['message'])
        self.assertEqual(holdings, {})
        self.assertEqual(self.state, {'pending': {}, 'sent': {}})

    def test_turning_up_gets_setup_even_if_ai_not_buying(self):
        self.alert.update({'今日評分': 55, 'RL空手策略': 'HOLD', 'TD期待值': -.05})
        state, pending = self.plan()
        self.assertEqual(pending[0][1]['level'], 'SETUP')
        self.assertIn('不等於買進', pending[0][1]['message'])

    def test_risk_blocked_buy_is_not_mislabelled_as_entry(self):
        self.alert.update({'是否觸發賣出': True, '乖離過大': True})
        _, pending = self.plan()
        self.assertEqual(pending[0][1]['level'], 'BLOCKED')

    def test_missing_data_downgrades_notice_without_changing_model(self):
        self.alert['籌碼資料狀態'] = 'unavailable'
        _, pending = self.plan()
        self.assertEqual(pending[0][1]['level'], 'SETUP')
        self.assertEqual(self.alert['RL空手策略'], 'BUY')

    def test_partial_bar_cannot_produce_confirmed_entry(self):
        self.alert['日線已收盤'] = False
        _, pending = self.plan()
        self.assertEqual(pending[0][1]['level'], 'SETUP')
        self.assertIn('等待收盤確認', pending[0][1]['message'])

    def test_delivered_same_bar_not_resent_but_setup_can_upgrade(self):
        self.alert['RL空手策略'] = 'HOLD'
        state, pending = self.plan()
        self.assertTrue(deliver_entry_report('test', state, pending, lambda _: True, lambda _: None))
        _, again = self.plan(state)
        self.assertEqual(again, [])
        self.alert['RL空手策略'] = 'BUY'
        _, upgraded = self.plan(state)
        self.assertEqual(upgraded[0][1]['level'], 'ENTRY')

    def test_failed_delivery_remains_pending_even_after_watchlist_updated(self):
        state, pending = self.plan()
        saved = []
        self.assertFalse(deliver_entry_report('test', state, pending, lambda _: False, saved.append))
        self.assertEqual(saved, [])
        retry_state, retry = self.plan(state, {'1312.TW': {'加入價格': 16.05}})
        self.assertEqual(len(retry), 1)
        self.assertEqual(retry[0][1]['level'], 'ENTRY')

    def test_expired_or_now_blocked_pending_entry_is_not_sent(self):
        state, pending = self.plan()
        self.alert['是否觸發賣出'] = True
        _, blocked = self.plan(copy.deepcopy(state))
        self.assertTrue(all(item['level'] != 'ENTRY' for _, item in blocked))
        self.alert.update({'日期': '2026-10-13', 'RL空手策略': 'HOLD', '上升趨勢': False})
        _, expired = self.plan(state)
        self.assertEqual(expired, [])

    def test_no_market_data_does_not_replay_pending_entry(self):
        state, pending = self.plan()
        _, empty = plan_entry_notices({}, {}, {}, state, resolve_td_rl_strategy)
        self.assertEqual(empty, [])

    def test_held_model_sell_invalidates_unsent_entry(self):
        state, pending = self.plan()
        self.alert.update({'RL持有策略': 'SELL', 'RL持有信心': 90, 'TD期待值': -1.})
        _, retry = self.plan(state, {'1312.TW': {'加入價格': 16.05}})
        self.assertEqual(retry, [])

    def test_partial_line_delivery_is_not_acknowledged(self):
        response = MagicMock()
        with patch.dict(os.environ, {'LINE_CHANNEL_ACCESS_TOKEN': 'test-only', 'LINE_USER_ID': 'test-only'}), \
                patch('STOCK_GOD.requests.post', side_effect=[response, requests.Timeout()]), \
                patch('STOCK_GOD.time.sleep'), patch('builtins.open', mock_open()):
            self.assertFalse(send_line_message('x' * 4600))


if __name__ == '__main__':
    unittest.main()
