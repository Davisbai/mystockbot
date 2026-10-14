"""Load the pinned pre-adjustment code for reproducible comparisons."""
import math
from pathlib import Path
import subprocess
import types

BASELINE_SHA = '6a9702f9c3c31cea420648f4c731e99cc934174a'


def load_baseline():
    root = Path(__file__).resolve().parent
    result = subprocess.run(['git', '-c', f'safe.directory={root.as_posix()}',
                             'show', f'{BASELINE_SHA}:STOCK_GOD.py'],
                            cwd=root, check=True, capture_output=True,
                            text=True, encoding='utf-8')
    module = types.ModuleType('tdrl_diagnostic_baseline')
    exec(compile(result.stdout, f'{BASELINE_SHA}/STOCK_GOD.py', 'exec'), module.__dict__)
    return module


def json_safe(value):
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value
