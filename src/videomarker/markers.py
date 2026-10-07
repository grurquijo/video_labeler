"""Marker data and time formatting.

Standard library only, and free of any Tk or media-engine import, so these
can be exercised by the test suite without a display.
"""

# Two marks closer together than this are treated as the same moment.
MARKER_MIN_GAP_MS = 250


def format_time(milliseconds):
    """Render a time in ms (or a negative value when unknown) as mm:ss."""
    if milliseconds is None or milliseconds < 0:
        return "--:--"
    seconds, _ = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes:02d}:{seconds:02d}"


def format_marker_time(milliseconds):
    """Like format_time, but keeps milliseconds -- markers want precision."""
    milliseconds = max(0, int(milliseconds))
    seconds, millis = divmod(milliseconds, 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}.{millis:03d}"
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


def parse_tags(text):
    """Split a comma-separated string into clean, de-duplicated tags.

    Commas are the only separator, so a task may contain spaces. A leading
    ``#`` is dropped, and duplicates are removed case-insensitively with the
    first spelling kept.
    """
    tags = []
    seen = set()
    for raw in text.split(","):
        tag = raw.strip().lstrip("#").strip()
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            tags.append(tag)
    return tags


class Marker:
    """A marked spot in the clip: a timestamp, a location and its tasks."""

    __slots__ = ("time_ms", "location", "tags")

    def __init__(self, time_ms, location="", tags=None):
        self.time_ms = int(time_ms)
        self.location = location
        self.tags = list(tags or [])

    def label(self, number):
        """The row as it appears in the marker list."""
        text = f"{number:>2}.  {format_marker_time(self.time_ms)}"
        if self.location:
            text += f"  {self.location}"
        if self.tags:
            text += " | " + ", ".join(self.tags)
        return text

    def __repr__(self):
        return (f"Marker(time_ms={self.time_ms!r}, "
                f"location={self.location!r}, tags={self.tags!r})")
