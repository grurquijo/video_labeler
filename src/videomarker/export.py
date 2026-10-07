"""Turning markers into CSV rows, and writing them out.

Standard library only: no Tk, no media engine. Every decision that shapes the
exported file lives here so it can be tested directly.
"""

import csv
import os

from .markers import format_time

CSV_COLUMNS = ["session", "minute", "location", "task", "lastFrame"]

# Used when the stream does not report a usable frame rate.
DEFAULT_FRAME_RATE = 30.0


def session_name(video_path):
    """The session is the name of the folder the video sits in."""
    folder = os.path.dirname(os.path.abspath(video_path))
    return os.path.basename(folder) or "session"


def frame_number(time_ms, fps):
    """1-based index of the frame containing this time.

    Frame 1 is the first frame of the video, matching how FFmpeg numbers
    exported stills by default.
    """
    return max(1, int(time_ms / 1000.0 * fps) + 1)


def build_rows(markers, session, duration_ms, fps=DEFAULT_FRAME_RATE):
    """One row per marker, each running until the next marker begins.

    ``lastFrame`` is the frame just before the following marker starts, or
    the video's final frame for the last marker. When the duration is unknown
    (``duration_ms`` <= 0) the last marker's span collapses onto its own
    frame, since there is nothing to measure the end against.
    """
    if duration_ms > 0:
        final_frame = max(1, int(duration_ms / 1000.0 * fps))
    else:
        final_frame = None

    rows = []
    for index, marker in enumerate(markers):
        start_frame = frame_number(marker.time_ms, fps)
        if index + 1 < len(markers):
            end_frame = frame_number(markers[index + 1].time_ms, fps) - 1
        elif final_frame is not None:
            end_frame = final_frame
        else:
            end_frame = start_frame
        end_frame = max(start_frame, end_frame)

        rows.append([
            session,
            format_time(marker.time_ms),
            marker.location,
            ", ".join(marker.tags),
            f"{end_frame}.jpg",
        ])
    return rows


def write_csv(path, rows):
    """Write the header and rows to ``path``.

    Several tasks share one cell, comma-separated; the csv writer quotes that
    field so it survives as a single value when read back.
    """
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(rows)
