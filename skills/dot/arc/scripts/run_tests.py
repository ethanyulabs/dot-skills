#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "websockets>=13",
#   "pytest>=8",
# ]
# ///
"""Run the dot arc test suite:  uv run --script skills/dot/arc/scripts/run_tests.py [pytest args]"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pytest  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:] or ["-q"]
    sys.exit(pytest.main([os.path.join(HERE, "tests"), "-p", "no:cacheprovider", *args]))
