"""Convenience launcher: ``python video_player.py [video]``.

The application itself lives in ``src/videomarker``. This shim exists so the
player can be started from a clone without installing anything, which is how
it was run before the package layout; it simply puts ``src`` on the import
path and hands over to the package entry point.

Installed users can run ``video-marker`` or ``python -m videomarker`` instead.
"""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from videomarker.__main__ import main  # noqa: E402  (path set up above)

if __name__ == "__main__":
    sys.exit(main())
