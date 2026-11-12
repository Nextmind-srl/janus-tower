"""Test session setup.

Demo mode (backend/demo_mode.py) switches itself on when no Google OAuth client is configured, which is the normal
situation of a test run. The existing suites exercise the real application (OAuth fail-closed, 429 handling, the
data directory...), so the whole session runs with the demo explicitly off. The demo tests (tests/test_demo_*.py)
start their own isolated processes or private namespaces with the switch they need.
"""

import os

os.environ["JANUSTOWER_DEMO"] = "0"
