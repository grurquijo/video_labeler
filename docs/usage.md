# Usage

## Opening a video

Use **Open video...** at the top of the side panel, **File > Open...**, or
`Ctrl`+`O`. A path can also be passed on the command line:

```bash
python video_player.py path/to/clip.mp4
```

Playback starts automatically, and the clip opens with **a marker already on
its first frame** so the run from the start of the video is covered without
marking `00:00` by hand.

## Playing

| Control | Where |
|---|---|
| Play / pause | Button on the time line, or `Space` |
| Stop | Button — rewinds and holds on the first frame |
| Scrub | Drag the bar; the position applies when you release |
| Skip 5 seconds | `←` and `→` |
| Volume / mute | Bottom row |

## Marking a spot

Press `M` or the **Mark (M)** button. The marker is placed at the frame
currently on screen and appears in two places:

- as a **salmon dot** on the strip directly beneath the scrub bar
- as a row in **Marked spots**, e.g. ` 3.  01:12.480  Kitchen | prep, wide`

Marks closer together than 250 ms are treated as the same moment, so a double
press does not stack two dots on top of each other.

## Location and task

Selecting a marker opens it in the two boxes below the list:

- **Location** — free text, saved as typed
- **Task** — one or more tasks separated by commas; whitespace is trimmed,
  duplicates are dropped case-insensitively, and a leading `#` is ignored

Both save when you press `Enter` or when the box loses focus, so clicking
away to another marker or back to the video never drops what you typed.
Single-letter shortcuts are suppressed while either box has focus.

## Moving around by marker

| Action | How |
|---|---|
| Jump to a marker | Double-click its row, press `Enter` on it, or click its dot |
| Select without jumping | Single-click its row |
| Delete one | Select it and press `Delete`, or the Delete button |
| Remove all | Clear all (asks first) |

The selected marker's dot is drawn in a lighter fill with a heavier outline.

## Exporting

**File > Export markers to CSV**, `Ctrl`+`E`, or the **Export CSV...** button.

The file defaults to `<video's folder>/<folder name>.csv` and the save dialog
lets you confirm or change that before anything is written. See
[csv-format.md](csv-format.md) for what the columns contain.

## Losing markers

Markers exist only in memory. They are cleared when another video is loaded
and are gone when the app closes — **exporting is how you keep them.**

Loading a new video while unexported markers exist raises a three-way prompt:

- **Yes** — export to CSV first, then open the new video
- **No** — discard them
- **Cancel** — stay on the current video

If you pick Yes and then cancel the save dialog, the load is abandoned rather
than proceeding silently. A clip holding nothing but its untouched automatic
`00:00` marker does not trigger the prompt.
