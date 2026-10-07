"""The ffpyplayer side of the player: decoding, audio and frame conversion.

``ffpyplayer.player.MediaPlayer`` is a binding of ffplay. It plays the audio
track itself and hands back video frames along with the delay to wait before
showing the next one, so audio/video synchronisation is the library's job
rather than ours.

Nothing here imports Tkinter. The only thing this module knows about display
is that the caller wants pixels in a shape Tk can read, which FrameScaler
produces as a PPM byte string.
"""

from ffpyplayer.pic import SWScale
from ffpyplayer.player import MediaPlayer

# Used when the stream does not report a usable frame rate.
DEFAULT_FRAME_RATE = 30.0

# 'paused' so the first frame can be shown before playback starts; 'rgb24'
# so frames arrive in a layout PPM can consume directly.
FF_OPTS = {"paused": True, "out_fmt": "rgb24", "sync": "audio"}


class FrameScaler:
    """Scales frames to a target size and renders them as PPM bytes.

    The SWScale object is cached: rebuilding it per frame would be wasteful,
    and it only changes when the source format or either size changes.
    """

    def __init__(self):
        self._scaler = None
        self._key = None

    @property
    def is_primed(self):
        """True once a frame has been converted at the current geometry."""
        return self._key is not None

    def reset(self):
        self._scaler = None
        self._key = None

    def to_ppm(self, image, target_width, target_height):
        """Return the frame as a binary PPM (header plus raw RGB)."""
        source_w, source_h = image.get_size()
        source_fmt = image.get_pixel_format()

        key = (source_w, source_h, source_fmt, target_width, target_height)
        if key != self._key:
            self._scaler = SWScale(source_w, source_h, source_fmt,
                                   ow=target_width, oh=target_height,
                                   ofmt="rgb24")
            self._key = key

        pixels = bytes(self._scaler.scale(image).to_bytearray()[0])
        # Tk's PhotoImage reads binary PPM natively, so raw RGB plus a short
        # header is all it takes -- no Pillow, no numpy.
        return b"P6 %d %d 255 " % (target_width, target_height) + pixels


class Playback:
    """A thin, typo-proof wrapper over the bits of MediaPlayer we use."""

    def __init__(self, path):
        self._player = MediaPlayer(path, ff_opts=dict(FF_OPTS))

    # --------------------------------------------------------------- frames --

    def get_frame(self, force_refresh=False):
        """``(frame, val)`` straight from ffpyplayer.

        ``frame`` is ``(image, pts)`` or None when nothing is ready; ``val``
        is either the seconds to wait before the next frame, or one of the
        status strings ffplay uses, notably ``"eof"`` and ``"paused"``.
        """
        return self._player.get_frame(force_refresh=force_refresh)

    # ------------------------------------------------------------- transport --

    def set_pause(self, paused):
        self._player.set_pause(bool(paused))

    def seek(self, seconds, relative=False):
        self._player.seek(seconds, relative=relative, accurate=False)

    def close(self):
        self._player.close_player()

    # ---------------------------------------------------------------- audio --

    def set_volume(self, fraction):
        """Volume as 0.0-1.0, the scale ffpyplayer expects."""
        self._player.set_volume(max(0.0, min(1.0, float(fraction))))

    def get_mute(self):
        return bool(self._player.get_mute())

    def set_mute(self, muted):
        self._player.set_mute(bool(muted))

    # ------------------------------------------------------------- metadata --

    def duration_ms(self):
        """Duration in ms, or -1 while FFmpeg has not reported one yet."""
        try:
            duration = self._player.get_metadata().get("duration")
        except Exception:
            return -1
        if duration:
            return int(duration * 1000)
        return -1

    def frame_rate(self):
        """Frames per second, when the stream reports a usable rate."""
        try:
            rate = self._player.get_metadata().get("frame_rate")
        except Exception:
            return DEFAULT_FRAME_RATE
        if (isinstance(rate, (tuple, list)) and len(rate) == 2
                and rate[0] and rate[1]):
            return float(rate[0]) / float(rate[1])
        return DEFAULT_FRAME_RATE
