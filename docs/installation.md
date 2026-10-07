# Installation

**One package: `ffpyplayer`.** Nothing else is installed, and nothing is
installed outside pip.

```bash
pip install ffpyplayer
```

That is the whole setup on Windows and macOS. Linux needs one system package
for Tkinter (see below), because most distributions ship it separately from
Python.

---

## What's used, and why nothing more is needed

| Piece | Where it comes from | Cost |
|---|---|---|
| Window, menus, buttons, file dialog, seek bar, marker list | `tkinter` | Standard library |
| Marker dots under the scrub bar | `tkinter.Canvas` | Standard library |
| Video decoding, scaling, audio playback, A/V sync | `ffpyplayer` | **1 pip package** |
| Displaying frames on screen | `tkinter.PhotoImage` fed raw PPM bytes | Standard library |
| CSV export, sorted markers, timestamps | `csv`, `bisect`, `os` | Standard library |

Three dependencies a video player would normally pull in are avoided outright:

- **No VLC, no system codec install.** The `ffpyplayer` wheels bundle FFmpeg
  and SDL, so the media engine arrives with the pip package rather than as a
  separate desktop application.
- **No Pillow.** Frames become a short PPM header plus raw RGB bytes and go
  straight to `tk.PhotoImage`, which reads PPM natively. Pillow's `ImageTk` is
  the usual way to do this and is not required.
- **No numpy.** `ffpyplayer`'s own `SWScale` does the colour conversion and
  resizing, and `to_bytearray()` returns plain bytes.

`ffpyplayer` itself is not optional: the standard library cannot decode a video
file, and Tkinter has no video widget. This is the floor.

---

## Quick check

```bash
python -c "import tkinter, ffpyplayer; print('tkinter', tkinter.TkVersion); print('ffpyplayer', ffpyplayer.__version__)"
```

Two version lines means you are ready to run:

```bash
python video_player.py
```

---

## Windows

Python from python.org or Anaconda already includes Tkinter, so:

```bash
pip install ffpyplayer
```

From the Anaconda Prompt, activate your environment first:

```bash
conda activate myenv
```

```bash
pip install ffpyplayer
```

---

## macOS

```bash
pip3 install ffpyplayer
```

Python from python.org includes Tkinter. If you use Homebrew Python, add
`brew install python-tk` — Homebrew splits Tkinter out. On Apple Silicon,
install into an arm64 Python so the wheel matches.

```bash
python3 video_player.py
```

---

## Linux

Tkinter is packaged separately here — this is the only system-level install
the player needs:

```bash
sudo apt install python3-tk python3-pip        # Debian / Ubuntu
```

```bash
sudo dnf install python3-tkinter python3-pip   # Fedora
```

```bash
sudo pacman -S tk python-pip                   # Arch
```

Then:

```bash
pip install ffpyplayer
```

```bash
python3 video_player.py
```

---

## Anaconda / conda users

`ffpyplayer` is also on conda-forge, which avoids pip inside a conda
environment if you prefer:

```bash
conda create -n videomarker python=3.12
```

```bash
conda activate videomarker
```

```bash
conda install -c conda-forge ffpyplayer
```

Tkinter comes with the conda Python build on all three platforms.

---

## Installing the package itself

Optional. Running `python video_player.py` from a clone needs no install — the
launcher puts `src` on the import path itself. To get the `video-marker`
command instead:

```bash
pip install .
```

Or, for development, an editable install plus the test tools:

```bash
pip install -e ".[dev]"
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'ffpyplayer'` | Installed into a different interpreter | `pip install ffpyplayer` **in the environment you run the script from** |
| `ModuleNotFoundError: No module named 'tkinter'` | Linux Tkinter package missing | `sudo apt install python3-tk` (or distro equivalent) |
| pip tries to build from source and fails | No wheel for your Python version — usually a Python release newer than the current `ffpyplayer` build | Use a Python version with published wheels (3.9–3.12 at time of writing), or `conda install -c conda-forge ffpyplayer` |
| Video plays but is choppy on large files | Frames are scaled and copied in Python | Make the window smaller — cost scales with the window, not the source |
| No audio | The file's audio codec isn't in the bundled FFmpeg build, or no output device | Check the file plays elsewhere; confirm the system default audio device |

---

## The trade-off, stated plainly

Fewest dependencies is not the same as best playback. Because the video is
drawn by Python rather than by a native video output layer, each frame is
scaled, copied into a byte string and uploaded to Tk on the main thread. The
cost tracks the **window size**, not the source resolution, so a 4K file in a
960-pixel-wide window is fine, while a maximised 4K window on a modest machine
will drop frames.

If smooth playback of large files at full screen matters more than a lean
install, the alternative is `python-vlc`, which hands a native window handle to
libVLC and keeps the video entirely out of Python — at the price of requiring
the VLC desktop application on every machine. Audio/video synchronisation is
handled by the library in both cases; `ffpyplayer` is a binding of ffplay and
manages its own audio clock.
