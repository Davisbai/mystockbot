"""Start Streamlit in a project environment rather than the system Python.

Usage: python run_app.py [--check] [--headless] [--port 8501]
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import venv

ROOT = Path(__file__).resolve().parent


def environment_python():
    directory = ROOT / '.venv-app'
    return directory / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def check_environment(python):
    if not python.is_file():
        print('Project environment missing. Run: python run_app.py', flush=True)
        return False
    # Version check runs before importing Streamlit: incompatible protobuf may
    # otherwise crash the import before the app can display any diagnosis.
    check = r"""
from importlib.metadata import version
import re
release = tuple(int(p) for p in re.match(r'^(\d+)\.(\d+)', version('streamlit')).groups())
if not (1, 32) <= release < (2, 0):
    raise RuntimeError('Streamlit >=1.32,<2 is required')
import streamlit, pandas, numpy, yfinance, twstock, STOCK_GOD, app_support
print('App dependencies OK; Streamlit ' + version('streamlit'))
"""
    return subprocess.run([str(python), '-c', check], cwd=ROOT).returncode == 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Check environment without installing or starting a server')
    parser.add_argument('--headless', action='store_true', help='Do not open a browser automatically')
    parser.add_argument('--port', type=int, default=8501)
    args = parser.parse_args(argv)
    if not 1 <= args.port <= 65535:
        parser.error('--port must be between 1 and 65535')
    python = environment_python()
    if args.check:
        return 0 if check_environment(python) else 1
    if not python.is_file():
        print('Creating .venv-app project environment...', flush=True)
        venv.EnvBuilder(with_pip=True).create(str(python.parent.parent))
    if not check_environment(python):
        print('Installing compatible project dependencies...', flush=True)
        result = subprocess.run([str(python), '-m', 'pip', 'install', '--upgrade',
                                 '-r', str(ROOT / 'requirements.txt')], cwd=ROOT)
        if result.returncode:
            print('Dependency installation failed; see the pip error above.', flush=True)
            return result.returncode
        if not check_environment(python):
            return 1
    command = [str(python), '-m', 'streamlit', 'run', str(ROOT / 'app.py'),
               '--server.port', str(args.port), '--browser.gatherUsageStats', 'false']
    if args.headless:
        command += ['--server.headless', 'true']
    print(f'Starting app at http://localhost:{args.port}', flush=True)
    try:
        return subprocess.run(command, cwd=ROOT).returncode
    except KeyboardInterrupt:
        return 0


if __name__ == '__main__':
    sys.exit(main())
