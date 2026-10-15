"""Exercise warm core replacement in isolation so other tests retain class bindings."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import app_support
import STOCK_GOD

ROOT = Path(__file__).resolve().parent


class CoreRuntimeTests(unittest.TestCase):
    def test_matching_runtime_does_not_reload(self):
        with patch('app_support.importlib.reload', side_effect=AssertionError('unnecessary reload')):
            core, revision = app_support.load_current_core()
            self.assertIs(core, STOCK_GOD)
            self.assertEqual(revision, app_support.runtime_fingerprint())

    def test_dependency_content_changes_fingerprint_without_model_label_change(self):
        names = (*app_support._CORE_DEPENDENCIES, 'app_support', 'STOCK_GOD')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in names:
                (root / f'{name}.py').write_bytes((ROOT / f'{name}.py').read_bytes())
            with patch.object(app_support, '__file__', str(root / 'app_support.py')):
                before = app_support.runtime_fingerprint()
                config = root / 'strategy_config.py'
                config.write_bytes(config.read_bytes() + b'\n# changed dependency\n')
                self.assertNotEqual(before, app_support.runtime_fingerprint())

    def test_core_that_remains_incompatible_after_reload_is_rejected(self):
        from types import SimpleNamespace
        stale = SimpleNamespace()
        with patch.object(app_support.importlib, 'import_module', return_value=stale), \
                patch.object(app_support.importlib, 'reload', side_effect=lambda module: module):
            with self.assertRaisesRegex(ImportError, 'does not match'):
                app_support.load_current_core()

    def test_warm_stale_core_and_dependencies_reload_and_render_complete_audit(self):
        script = r'''
import sys
from types import ModuleType
from unittest.mock import patch
import pandas as pd
import requests
import yfinance
import STOCK_GOD
import strategy_config
import institutional_data
from app_support import load_current_core
from streamlit.testing.v1 import AppTest

stale = ModuleType('STOCK_GOD')
stale.__file__ = STOCK_GOD.__file__
stale.resolve_td_rl_strategy = lambda *a, **k: ('IGNORE', 'old reason', {'confidence': 60})
sys.modules['STOCK_GOD'] = stale
strategy_config.TRAINING_START_DATE = '1900-01-01'
institutional_data.parse_institutional_flows = None
with patch.object(requests, 'get', side_effect=AssertionError('network request')), \
     patch.object(yfinance, 'download', side_effect=AssertionError('market request')):
    core, revision = load_current_core()
    assert core is stale
    assert strategy_config.TRAINING_START_DATE == '2023-01-01'
    assert callable(institutional_data.parse_institutional_flows)
    alert = {'日期': '2026-10-14', '收盤價': 110., '月線價': 100., '今日漲幅': 1.,
             '今日評分': 90, '個股原始評分': 90, '大盤安全': True,
             'RL可用': True, 'RL空手策略': 'BUY', 'RL空手信心': 70.,
             'TD期待值': 2., 'RL空手樣本': 17, 'RL樣本類型': 'exact',
             '是否觸發賣出': True, '硬性風控': False, '乖離過大': True,
             '硬性風控原因': ['五日乖離超標（維持原退出政策）'],
             '籌碼資料狀態': 'unavailable', '日線已收盤': True}
    action, reason, meta = core.resolve_td_rl_strategy(alert)
    assert action == 'IGNORE' and meta['raw_action'] == 'BUY'
    assert meta['state_support'] == 17 and meta['support_kind'] == 'exact'
    assert '五日乖離' in reason
    assert not meta['hard_risk'] and meta['exit_filter']
    summary = {'2330.TW': {'總交易天數': 20, '完成交易筆數': 2, '勝率 (%)': 50.,
                           '策略累積報酬 (%)': 3., '最大回撤 (%)': -4., '未平倉': False}}
    def analysis(system):
        system.market_data = pd.DataFrame({'Close': [100., 110.], 'Market_MA20': [99., 100.]})
        return summary, {'2330.TW': alert}, {'2330.TW': []}
    with patch.object(core.TaiwanStockTradingSystem, 'run_analysis', analysis), \
         patch.object(core, 'load_watchlist', return_value={}), \
         patch.object(core, 'save_watchlist') as saved:
        app = AppTest.from_file('app.py', default_timeout=30).run()
        app.button[0].click().run()
        assert not app.exception
        assert not any('核心回傳欄位不完整' in item.value for item in app.warning)
        assert any('狀態支持 17' in item.value for item in app.caption)
        assert any('最終系統判定' in item.value for item in app.markdown)
        assert any('五日乖離' in item.value for item in app.markdown)
        saved.assert_not_called()
    # A newly imported core can also have picked up an older cached dependency.
    # Its own source token alone must not certify that dependency as current.
    strategy_config.RUNTIME_SOURCE_SHA256 = 'old-dependency-source'
    strategy_config.TRAINING_START_DATE = '1900-01-01'
    core, updated_revision = load_current_core()
    assert updated_revision == revision
    assert strategy_config.TRAINING_START_DATE == '2023-01-01'
    print('warm core recovery OK')
'''
        environment = dict(os.environ, PYTHONIOENCODING='utf-8')
        result = subprocess.run([sys.executable, '-c', script], cwd=ROOT, env=environment,
                                capture_output=True, text=True, encoding='utf-8', timeout=60)
        self.assertEqual(result.returncode, 0, (result.stdout + result.stderr)[-6000:])
        self.assertIn('warm core recovery OK', result.stdout)


if __name__ == '__main__':
    unittest.main()
