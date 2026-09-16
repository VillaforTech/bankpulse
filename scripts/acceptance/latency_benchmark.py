#!/usr/bin/env python3
"""Run 100 sequential close-to-render measurements in real Chromium."""
import argparse
import subprocess
from pathlib import Path

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', default='http://localhost:8080')
    p.add_argument('--out', default='artifacts/acceptance/latency.json')
    args = p.parse_args()
    raise SystemExit(subprocess.call(['node', str(Path(__file__).with_name('panel-benchmark.cjs')), args.base_url, args.out]))
