"""Make the repo root importable for the test suite.

Fifteen test modules do `from analysis import ...` / `from lab import ...`.
That works under `python -m pytest` (cwd is prepended to sys.path) but NOT
under the `pytest` console script, which is what CI runs -- without this
file every one of those modules errors at collection (exit code 2). This
conftest puts the root on sys.path explicitly so both invocations behave
identically.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
