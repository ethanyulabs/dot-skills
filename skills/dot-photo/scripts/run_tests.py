#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "pillow>=11",
#   "pillow-heif>=0.20",
#   "numpy>=1.26",
#   "opencv-contrib-python-headless>=4.10,<5",
#   "pytest>=8",
# ]
# ///
"""Run the dot-photo test suite:  uv run --script scripts/run_tests.py [pytest args]"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import pytest  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:] or ["-q"]
    sys.exit(pytest.main([os.path.join(HERE, "tests"), "-p", "no:cacheprovider", *args]))
