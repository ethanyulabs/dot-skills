#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "pillow>=11",
#   "pillow-heif>=0.20",
#   "numpy>=1.26",
#   "opencv-contrib-python-headless>=4.10,<5",
# ]
# ///
"""dot photo command line entry point.

Run with:  uv run --script <SKILL_DIR>/photo/scripts/dphoto.py <command> ...
Every command prints exactly one JSON line on stdout; progress goes to stderr.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dphoto_lib.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
