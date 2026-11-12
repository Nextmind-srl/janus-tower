#!/usr/bin/env python3
"""Command line entry point for the invented demo data generator (the code lives in backend/demo_data.py).

Usage: python tools/demo_data.py --output /path/outside/the/repo/demo_scan.json [--days 30] [--seed N] [--no-enrich]
"""

import os
import runpy
import sys

if __name__ == "__main__":
    runpy.run_path(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "demo_data.py"), run_name="__main__")
    sys.exit(0)
