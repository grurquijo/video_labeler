# CSV format

One row per marker, in time order.

```csv
session,minute,location,task,lastFrame
Session12,00:00,Kitchen,setup,1799.jpg
Session12,01:00,Kitchen,"prep, wide shot",3599.jpg
Session12,02:00,Yard,cleanup,4500.jpg
```

## Columns

| Column | Contents |
|---|---|
| `session` | Name of the **folder the video is in**, not the video's filename |
| `minute` | When the marker starts, as `mm:ss` (or `h:mm:ss` past an hour) |
| `location` | Free text from the Location box, saved as typed |
| `task` | Every task for that marker in **one cell**, comma-separated |
| `lastFrame` | The frame the marker's span ends on, as `<number>.jpg` |

## How `lastFrame` is derived

Each marker owns the stretch of video from its own timestamp until the next
marker begins. `lastFrame` is the final frame of that stretch:

- **Any marker but the last** — the frame immediately before the next marker's
  frame
- **The last marker** — the video's final frame
- **If the duration is unknown** (FFmpeg has not reported one yet) — the span
  collapses onto the marker's own frame, since there is nothing to measure
  against

Because spans are contiguous, consecutive rows tile the video with no gaps and
no overlap.

## Frame-numbering conventions

Two choices are baked into `frame_number()` in
[`src/videomarker/export.py`](../src/videomarker/export.py):

- **1-based** — the first frame of the video is `1.jpg`, matching how FFmpeg
  numbers exported stills by default
- **Unpadded** — `47.jpg`, not `00047.jpg`

If the frames you extract are padded to a fixed width, change the format in
`build_rows`:

```python
f"{end_frame:05d}.jpg"     # 00047.jpg
```

For 0-based numbering, drop the `+ 1` in `frame_number()` — but note it also
clamps to a minimum of 1, which would need removing too.

The frame rate comes from the stream's own metadata, falling back to 30 fps
when FFmpeg does not report a usable rate. Variable-frame-rate sources will be
approximate, since a single nominal rate cannot describe them exactly.

## Encoding

UTF-8 without a byte-order mark. That reads correctly in pandas, R, Numbers and
LibreOffice. Excel on Windows can mangle accented characters in a plain UTF-8
file; if that matters, switch the encoding in `write_csv()` to `utf-8-sig`,
which is harmless everywhere else.

## Multiple tasks in one cell

Several tasks stay in a single field rather than splitting into extra columns
or rows. Python's `csv` writer quotes the field when it contains a comma, so
`prep, wide shot` reads back as one value:

```python
import csv
with open("Session12.csv", newline="", encoding="utf-8") as handle:
    for row in csv.DictReader(handle):
        tasks = [t.strip() for t in row["task"].split(",") if t.strip()]
```
