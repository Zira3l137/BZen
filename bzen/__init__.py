"""
Import helper.

The modules in this package import each other by bare name (e.g.
``from utils import ...``) because zen_to_blend.py is run by Blender as a
standalone script, not as part of the package. This adds the package
directory itself to sys.path so those imports also resolve when the
package is imported normally (e.g. by the ``bzen`` console script).

It runs once, when the package is first imported; it is not intended for
external use.
"""

import sys
from pathlib import Path

script_dir = Path(__file__).parent
if str(script_dir) not in sys.path:
    sys.path.append(str(script_dir))
