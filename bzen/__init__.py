"""
Import helper.

This module exists solely to inject the parent directory into sys.path
so that sibling packages (e.g., the parent of bzen) can import
modules from bzen without manual PYTHONPATH manipulation.

It is imported by every module in this package, not intended for
external use.
"""

import sys
from pathlib import Path

script_dir = Path(__file__).parent
if str(script_dir) not in sys.path:
    sys.path.append(str(script_dir))
