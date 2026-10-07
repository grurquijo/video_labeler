"""Entry point: ``python -m videomarker [video]`` or the ``video-marker``
console script.

The ffpyplayer import is allowed to fail here and is reported in a dialog as
well as on stderr, because the app is often launched by double-clicking on
Windows, where a traceback goes nowhere the user will see it.
"""

import sys
import tkinter as tk
from tkinter import messagebox

MISSING_DEPENDENCY = (
    "Could not import ffpyplayer.\n\n"
    "{error}\n\n"
    "Install it with:  pip install ffpyplayer\n\n"
    "See docs/installation.md for per-platform instructions."
)


def _report_missing_dependency(exc):
    message = MISSING_DEPENDENCY.format(error=exc)
    print(message, file=sys.stderr)
    try:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Missing dependency", message)
        root.destroy()
    except tk.TclError:
        pass


def main(argv=None):
    """Run the player. Returns a process exit code."""
    argv = list(sys.argv[1:] if argv is None else argv)

    try:
        from .app import VideoPlayer
    except ImportError as exc:
        # Only ffpyplayer's absence gets the friendly dialog; anything else
        # is a real bug and should surface as a traceback.
        if not (getattr(exc, "name", "") or "").startswith("ffpyplayer"):
            raise
        _report_missing_dependency(exc)
        return 1

    app = VideoPlayer()
    if argv:
        app.load(argv[0])
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
