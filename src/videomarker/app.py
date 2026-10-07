"""The Tkinter window: layout, marker editing and the frame loop.

Everything display-related lives here. Marker data, CSV shaping and the
media engine sit in sibling modules, which keeps this file about the UI and
lets the rest be tested without a screen.
"""

import base64
import bisect
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .export import (CSV_COLUMNS, DEFAULT_FRAME_RATE, build_rows,
                     session_name, write_csv)
from .markers import (MARKER_MIN_GAP_MS, Marker, format_marker_time,
                      format_time, parse_tags)
from .playback import FrameScaler, Playback

VIDEO_FILETYPES = [
    ("Video files", "*.mp4 *.mkv *.avi *.mov *.wmv *.flv *.webm *.m4v *.mpg "
                    "*.mpeg *.ts *.m2ts *.3gp *.ogv"),
    ("Audio files", "*.mp3 *.wav *.flac *.aac *.ogg *.m4a *.wma"),
    ("All files", "*.*"),
]

# How far the arrow keys jump, in seconds.
SEEK_STEP_S = 5.0

# How often the clock, seek bar and duration are refreshed, in milliseconds.
UI_REFRESH_MS = 200

# Bounds on the gap between frame-fetch ticks, in milliseconds. The upper
# bound keeps the loop responsive while paused or stalled.
MIN_TICK_MS = 1
MAX_TICK_MS = 100

# --- Marker appearance -------------------------------------------------------
MARKER_COLOR = "#FA8072"           # salmon
MARKER_COLOR_SELECTED = "#FFD5CE"  # lighter fill for the selected marker
MARKER_OUTLINE = "#8C3F35"
MARKER_STRIP_HEIGHT = 16
MARKER_RADIUS = 5
MARKER_STRIP_BG = "#f0f0f0"

# ttk.Scale insets the thumb's travel from the widget edge; shifting the strip
# by the same amount keeps each dot under the point the thumb actually reaches.
TROUGH_INSET = 9

# Clicks land within this many pixels of a dot to count as hitting it.
MARKER_HIT_SLOP = 7

# Window sizing. The real minimum is measured from the side panel at startup
# (see _apply_min_size); these are the floor and the preferred opening size.
DEFAULT_WIDTH = 1150
DEFAULT_HEIGHT = 700
MIN_WIDTH = 760
MIN_HEIGHT = 480

# Width left for the video once the side panel has taken its share.
MIN_VIDEO_WIDTH = 480


class VideoPlayer(tk.Tk):
    """Main application window."""

    def __init__(self):
        super().__init__()
        self.title("Video Marker")
        self.configure(bg="black")

        self.playback = None        # Playback, once a file loads
        self.current_path = None
        self.is_paused = True
        self.duration_ms = -1       # -1 until FFmpeg reports it
        self.position_ms = 0
        self.user_is_seeking = False

        # Marker objects, kept sorted ascending by time.
        self.markers = []
        # Set by any edit, cleared by a successful export -- drives the
        # warning shown before markers would be discarded.
        self._markers_dirty = False
        # Which marker the location/task boxes are currently editing, if any.
        # Held separately from the list selection so text typed for one marker
        # is never written onto another when the selection moves.
        self._editor_index = None
        # Last duration the strip was drawn against, so it can be repainted
        # once the real duration turns up.
        self._strip_length = 0

        # Frame-display scratch state.
        self.scaler = FrameScaler()
        self._photo = None          # keeps the current PhotoImage alive
        self._shown_pts = None      # avoids redrawing an unchanged frame
        self._force_refresh = False
        self._photo_needs_base64 = False
        self._tick_job = None

        self._build_ui()
        self._bind_events()
        self._apply_min_size()
        self.after(UI_REFRESH_MS, self._refresh)

    def _apply_min_size(self):
        """Never let the window shrink past the side panel's full height.

        The panel's Delete and Clear all buttons are packed last, so they are
        the first thing a short window clips. Measuring what the panel asks
        for -- rather than hard-coding a number -- keeps this correct across
        platforms, where font metrics and widget padding differ.
        """
        self.update_idletasks()

        min_height = max(MIN_HEIGHT,
                         self.marker_panel.winfo_reqheight()
                         + self.controls.winfo_reqheight() + 24)
        min_width = max(MIN_WIDTH,
                        self.marker_panel.winfo_reqwidth() + MIN_VIDEO_WIDTH)

        self.minsize(min_width, min_height)
        self.geometry(f"{max(min_width, DEFAULT_WIDTH)}x"
                      f"{max(min_height, DEFAULT_HEIGHT)}")

    # ------------------------------------------------------------------ UI --

    def _build_ui(self):
        menubar = tk.Menu(self)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open...", accelerator="Ctrl+O",
                              command=self.open_file)
        file_menu.add_command(label="Export markers to CSV...",
                              accelerator="Ctrl+E", command=self.export_csv)
        file_menu.add_separator()
        file_menu.add_command(label="Quit", accelerator="Ctrl+Q",
                              command=self.quit_app)
        menubar.add_cascade(label="File", menu=file_menu)

        marker_menu = tk.Menu(menubar, tearoff=0)
        marker_menu.add_command(label="Mark current position",
                                accelerator="M", command=self.add_marker)
        marker_menu.add_command(label="Go to selected marker",
                                command=self.goto_selected_marker)
        marker_menu.add_separator()
        marker_menu.add_command(label="Delete selected marker",
                                accelerator="Del",
                                command=self.delete_selected_marker)
        marker_menu.add_command(label="Clear all markers",
                                command=self.clear_markers)
        menubar.add_cascade(label="Markers", menu=marker_menu)

        self.config(menu=menubar)

        # Bottom control bar is packed first so it keeps its height and the
        # body simply fills whatever is left.
        self.controls = ttk.Frame(self, padding=(8, 6))
        self.controls.pack(fill=tk.X, side=tk.BOTTOM)
        self._build_controls(self.controls)

        body = tk.Frame(self, bg="black")
        body.pack(fill=tk.BOTH, expand=True)

        self.marker_panel = ttk.Frame(body, padding=(8, 8))
        self.marker_panel.pack(side=tk.RIGHT, fill=tk.Y)
        self._build_marker_panel(self.marker_panel)

        self.video_panel = tk.Frame(body, bg="black", highlightthickness=0)
        self.video_panel.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # Video frames are shown as the image of this label, centred so the
        # unused area of the panel letterboxes in black.
        self.video_label = tk.Label(self.video_panel, bg="black", bd=0,
                                    highlightthickness=0)
        self.video_label.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        self.placeholder = tk.Label(
            self.video_panel,
            text="No video loaded\n\nFile > Open...  (Ctrl+O)",
            fg="#9a9a9a", bg="black", font=("TkDefaultFont", 14),
            justify=tk.CENTER,
        )
        self.placeholder.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

    def _build_controls(self, parent):
        # Seek row: the scrub bar and the marker strip share one grid column
        # so a dot always sits directly under its point on the bar.
        seek_row = ttk.Frame(parent)
        seek_row.pack(fill=tk.X)
        seek_row.columnconfigure(2, weight=1)

        # Play/pause shares the line with the clock and the scrub bar.
        self.play_button = ttk.Button(seek_row, text="Play", width=8,
                                      command=self.toggle_play)
        self.play_button.grid(row=0, column=0, rowspan=2, padx=(0, 10))

        self.time_label = ttk.Label(seek_row, text="--:--", width=8,
                                    anchor=tk.E)
        self.time_label.grid(row=0, column=1, rowspan=2, padx=(0, 8))

        self.seek_var = tk.DoubleVar(value=0.0)
        self.seek_scale = ttk.Scale(seek_row, from_=0.0, to=1000.0,
                                    orient=tk.HORIZONTAL,
                                    variable=self.seek_var)
        self.seek_scale.grid(row=0, column=2, sticky="ew")

        self.marker_strip = tk.Canvas(
            seek_row, height=MARKER_STRIP_HEIGHT, bg=MARKER_STRIP_BG,
            highlightthickness=0, cursor="hand2",
        )
        self.marker_strip.grid(row=1, column=2, sticky="ew", pady=(2, 0))

        self.duration_label = ttk.Label(seek_row, text="--:--", width=8,
                                        anchor=tk.W)
        self.duration_label.grid(row=0, column=3, rowspan=2, padx=(8, 0))

        # Button row.
        button_row = ttk.Frame(parent)
        button_row.pack(fill=tk.X, pady=(6, 0))

        ttk.Button(button_row, text="Stop", width=8,
                   command=self.stop).pack(side=tk.LEFT)

        ttk.Button(button_row, text="Mark  (M)", width=10,
                   command=self.add_marker).pack(side=tk.LEFT, padx=(18, 0))

        self.mute_button = ttk.Button(button_row, text="Mute", width=8,
                                      command=self.toggle_mute)
        self.mute_button.pack(side=tk.LEFT, padx=(18, 0))

        self.volume_scale = ttk.Scale(button_row, from_=0, to=100,
                                      orient=tk.HORIZONTAL, length=120,
                                      command=self.on_volume_change)
        self.volume_scale.set(80)
        self.volume_scale.pack(side=tk.LEFT, padx=(6, 0))

        self.status_label = ttk.Label(parent, text="Ready", anchor=tk.W,
                                      foreground="#555555")
        self.status_label.pack(fill=tk.X, pady=(6, 0))

    def _build_marker_panel(self, parent):
        ttk.Button(parent, text="Open video...",
                   command=self.open_file).pack(fill=tk.X)
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X,
                                                         pady=(8, 8))

        header = ttk.Frame(parent)
        header.pack(fill=tk.X)
        ttk.Label(header, text="Marked spots",
                  font=("TkDefaultFont", 10, "bold")).pack(side=tk.LEFT)

        # A salmon swatch tying the list to the dots on the strip.
        swatch = tk.Canvas(header, width=14, height=14, highlightthickness=0)
        swatch.create_oval(2, 2, 12, 12, fill=MARKER_COLOR,
                           outline=MARKER_OUTLINE)
        swatch.pack(side=tk.RIGHT)

        list_frame = ttk.Frame(parent)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(6, 6))

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL)
        # A shortish default: the list stretches with the window, and its
        # requested height sets the window's minimum (see _apply_min_size).
        self.marker_list = tk.Listbox(
            list_frame, width=30, height=6, activestyle="none",
            exportselection=False,
            yscrollcommand=scrollbar.set, selectbackground=MARKER_COLOR,
            selectforeground="#2b2b2b", font=("TkFixedFont", 10),
        )
        scrollbar.config(command=self.marker_list.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.marker_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.marker_count_label = ttk.Label(parent, text="No markers yet",
                                            foreground="#555555")
        self.marker_count_label.pack(fill=tk.X)

        # Details for whichever marker is selected above.
        self.selection_label = ttk.Label(parent, text="No marker selected",
                                         foreground="#777777")
        self.selection_label.pack(fill=tk.X, pady=(8, 0))

        location_frame = ttk.LabelFrame(parent, text="Location",
                                        padding=(6, 4))
        location_frame.pack(fill=tk.X, pady=(4, 0))

        self.location_var = tk.StringVar()
        self.location_entry = ttk.Entry(location_frame,
                                        textvariable=self.location_var,
                                        state=tk.DISABLED)
        self.location_entry.pack(fill=tk.X, pady=(0, 2))

        ttk.Label(location_frame, text="Enter to save.",
                  foreground="#777777").pack(fill=tk.X)

        tag_frame = ttk.LabelFrame(parent, text="Task", padding=(6, 4))
        tag_frame.pack(fill=tk.X, pady=(8, 0))

        self.tag_var = tk.StringVar()
        self.tag_entry = ttk.Entry(tag_frame, textvariable=self.tag_var,
                                   state=tk.DISABLED)
        self.tag_entry.pack(fill=tk.X, pady=(4, 2))

        ttk.Label(tag_frame, text="Separate with commas.\nEnter to save.",
                  foreground="#777777",
                  justify=tk.LEFT).pack(fill=tk.X)

        buttons = ttk.Frame(parent)
        buttons.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(buttons, text="Delete",
                   command=self.delete_selected_marker).pack(fill=tk.X)
        ttk.Button(buttons, text="Clear all",
                   command=self.clear_markers).pack(fill=tk.X, pady=(4, 0))
        ttk.Button(buttons, text="Export CSV...",
                   command=self.export_csv).pack(fill=tk.X, pady=(8, 0))

        ttk.Label(parent, text="Double-click a time\nto jump there.",
                  foreground="#777777", justify=tk.LEFT).pack(fill=tk.X,
                                                              pady=(8, 0))

    def _bind_events(self):
        self.seek_scale.bind("<ButtonPress-1>", self.on_seek_press)
        self.seek_scale.bind("<ButtonRelease-1>", self.on_seek_release)

        self.marker_strip.bind("<Configure>", lambda _e: self.draw_markers())
        self.marker_strip.bind("<Button-1>", self.on_strip_click)

        self.marker_list.bind("<<ListboxSelect>>", self._on_marker_select)
        self.marker_list.bind("<Double-Button-1>",
                              lambda _e: self.goto_selected_marker())
        self.marker_list.bind("<Return>",
                              lambda _e: self.goto_selected_marker())
        self.marker_list.bind("<Delete>",
                              lambda _e: self.delete_selected_marker())

        self.location_entry.bind("<Return>", self._on_details_entered)
        self.location_entry.bind("<FocusOut>", lambda _e: self.commit_edits())
        self.tag_entry.bind("<Return>", self._on_details_entered)
        self.tag_entry.bind("<FocusOut>", lambda _e: self.commit_edits())

        # Single-letter shortcuts are suppressed while a text box has focus,
        # so typing "mark, wide" does not also drop a marker mid-word.
        self.bind("<space>", self._shortcut(self.toggle_play))
        self.bind("<Left>", self._shortcut(lambda: self.skip(-SEEK_STEP_S)))
        self.bind("<Right>", self._shortcut(lambda: self.skip(SEEK_STEP_S)))
        self.bind("<Control-o>", lambda _e: self.open_file())
        self.bind("<Control-e>", lambda _e: self.export_csv())
        self.bind("<Control-q>", lambda _e: self.quit_app())
        self.bind("<m>", self._shortcut(self.add_marker))
        self.bind("<M>", self._shortcut(self.add_marker))
        # Redraw the held frame at the new size when the window is resized.
        self.video_panel.bind("<Configure>", lambda _e: self.request_redraw())
        self.protocol("WM_DELETE_WINDOW", self.quit_app)

    def _shortcut(self, handler):
        """Wrap a key shortcut so it is ignored while typing in a text box."""
        def wrapper(_event):
            try:
                focused = self.focus_get()
            except KeyError:  # Tk can report a widget it no longer knows
                focused = None
            if isinstance(focused, (ttk.Entry, tk.Entry)):
                return None
            handler()
            return "break"
        return wrapper

    # --------------------------------------------------------------- files --

    def open_file(self):
        path = filedialog.askopenfilename(
            title="Choose a video file",
            filetypes=VIDEO_FILETYPES,
        )
        if path:
            self.load(path)

    def load(self, path):
        if not os.path.isfile(path):
            messagebox.showerror("File not found", f"No such file:\n{path}")
            return

        # Loading replaces the marker list, so give the current one a chance
        # to be exported first.
        if not self._confirm_discard_markers():
            self.status_label.config(text="Kept the current video.")
            return

        self._close_player()

        try:
            self.playback = Playback(path)
        except Exception as exc:  # ffpyplayer raises a variety of errors here
            messagebox.showerror(
                "Playback error",
                f"Could not open this file:\n\n{exc}\n\n"
                "The format may be unsupported or the file may be damaged.",
            )
            return

        self.current_path = path
        self.is_paused = True
        self.duration_ms = -1
        self.position_ms = 0
        self._shown_pts = None
        self._strip_length = 0
        self.scaler.reset()
        self.title(f"{os.path.basename(path)} - Video Marker")
        self.placeholder.place_forget()
        self.status_label.config(text=path)

        self.on_volume_change(self.volume_scale.get())

        # Markers belong to the clip they were made in. Every clip opens with
        # one on its first frame, so the run from the start of the video is
        # covered without having to mark 00:00 by hand.
        self._editor_index = None
        self.markers = [Marker(0)]
        self._markers_dirty = False
        self._sync_marker_views()
        self.select_marker(0)

        # self.play()
        # self._schedule_tick(0)
        self.is_paused = True
        self.play_button.config(text="Play")
        self.request_redraw()
        self._schedule_tick(0)

    def _close_player(self):
        if self._tick_job is not None:
            self.after_cancel(self._tick_job)
            self._tick_job = None
        if self.playback is not None:
            self.playback.close()
            self.playback = None

    # ------------------------------------------------ frame decode/display --

    def _schedule_tick(self, delay_ms):
        if self._tick_job is not None:
            self.after_cancel(self._tick_job)
        delay_ms = min(MAX_TICK_MS, max(MIN_TICK_MS, int(delay_ms)))
        self._tick_job = self.after(delay_ms, self._tick)

    def _tick(self):
        """Pull the next frame from ffpyplayer and show it when it is due."""
        self._tick_job = None
        if self.playback is None:
            return

        try:
            frame, val = self.playback.get_frame(
                force_refresh=self._force_refresh)
        except Exception:
            # A transient decode hiccup: back off briefly rather than die.
            self._schedule_tick(MAX_TICK_MS)
            return
        self._force_refresh = False

        if val == "eof":
            self.on_end_reached()
            return

        delay_ms = MAX_TICK_MS
        if frame is not None:
            image, pts = frame
            self.position_ms = int(pts * 1000)
            if pts != self._shown_pts or not self.scaler.is_primed:
                self._display(image)
                self._shown_pts = pts
            # While paused ffpyplayer hands back the same frame with a status
            # string; only a numeric value is a real inter-frame delay.
            if isinstance(val, (int, float)):
                delay_ms = val * 1000
            else:
                delay_ms = MAX_TICK_MS
        elif isinstance(val, (int, float)):
            # No frame ready yet; val is how long to wait before asking again.
            delay_ms = max(1.0, val * 1000)

        self._schedule_tick(delay_ms)

    def request_redraw(self):
        """Re-show the current frame, e.g. after the window changed size."""
        self._shown_pts = None
        self._force_refresh = True

    def _target_size(self, source_width, source_height):
        """Largest size fitting the video panel while keeping the aspect."""
        panel_w = max(1, self.video_panel.winfo_width())
        panel_h = max(1, self.video_panel.winfo_height())
        if source_width <= 0 or source_height <= 0:
            return panel_w, panel_h
        scale = min(panel_w / source_width, panel_h / source_height)
        return (max(16, int(source_width * scale)),
                max(16, int(source_height * scale)))

    def _display(self, image):
        """Scale a frame and push it into the Tk label."""
        source_w, source_h = image.get_size()
        target_w, target_h = self._target_size(source_w, source_h)
        ppm = self.scaler.to_ppm(image, target_w, target_h)
        self._photo = self._make_photo(ppm)
        self.video_label.configure(image=self._photo)

    def _make_photo(self, ppm):
        """Build a PhotoImage from PPM bytes, base64-encoding if Tk insists."""
        if not self._photo_needs_base64:
            try:
                return tk.PhotoImage(master=self, data=ppm, format="ppm")
            except tk.TclError:
                # Some Tcl builds only accept the data option as text.
                self._photo_needs_base64 = True
        return tk.PhotoImage(master=self, data=base64.b64encode(ppm),
                             format="ppm")

    # ------------------------------------------------------------- markers --

    def add_marker(self):
        """Mark the frame currently on screen."""
        if self.playback is None:
            self.status_label.config(text="Open a video before marking it.")
            return

        # Save any text being typed before the list shifts underneath it.
        self.commit_edits()
        time_ms = max(0, self.position_ms)

        index = bisect.bisect_left([m.time_ms for m in self.markers], time_ms)
        for offset, neighbour in enumerate(
                self.markers[max(0, index - 1):index + 1],
                start=max(0, index - 1)):
            if abs(neighbour.time_ms - time_ms) < MARKER_MIN_GAP_MS:
                self.status_label.config(
                    text="Already marked at "
                         f"{format_marker_time(neighbour.time_ms)}.")
                self.select_marker(offset)
                return

        self.markers.insert(index, Marker(time_ms))
        self._markers_dirty = True
        # Positions after the insert have all shifted, so the editor's old
        # index no longer means anything.
        self._editor_index = None
        self._sync_marker_views()
        self.select_marker(index)
        self.status_label.config(
            text=f"Marked {format_marker_time(time_ms)}  "
                 f"({len(self.markers)} total) - add details on the right")

    def delete_selected_marker(self):
        index = self.selected_marker_index()
        if index is None:
            self.status_label.config(text="Select a marker to delete.")
            return
        # Drop any pending edit: the marker it belonged to is going away.
        self._editor_index = None
        removed = self.markers.pop(index)
        self._markers_dirty = True
        self._sync_marker_views()
        if self.markers:
            self.select_marker(min(index, len(self.markers) - 1))
        else:
            self._load_editor(None)
        self.status_label.config(
            text=f"Removed marker at {format_marker_time(removed.time_ms)}")

    def clear_markers(self):
        if not self.markers:
            return
        if not messagebox.askyesno(
                "Clear markers",
                f"Remove all {len(self.markers)} markers?"):
            return
        self._editor_index = None
        self.markers = []
        self._markers_dirty = True
        self._sync_marker_views()
        self._load_editor(None)
        self.status_label.config(text="All markers cleared.")

    def goto_selected_marker(self):
        index = self.selected_marker_index()
        if index is None:
            self.status_label.config(text="Select a marker to jump to it.")
            return
        self.goto_marker(index)

    def goto_marker(self, index):
        marker = self.markers[index]
        self.seek_to(marker.time_ms / 1000.0)
        self.select_marker(index)
        tags = f"  [{', '.join(marker.tags)}]" if marker.tags else ""
        self.status_label.config(
            text=f"Jumped to {format_marker_time(marker.time_ms)}{tags}")

    def selected_marker_index(self):
        selection = self.marker_list.curselection()
        return selection[0] if selection else None

    def select_marker(self, index):
        self.commit_edits()
        self.marker_list.selection_clear(0, tk.END)
        if 0 <= index < len(self.markers):
            self.marker_list.selection_set(index)
            self.marker_list.see(index)
            self._load_editor(index)
        else:
            self._load_editor(None)
        self.draw_markers()

    def _sync_marker_views(self):
        """Rebuild the timestamp list and repaint the dots."""
        self.marker_list.delete(0, tk.END)
        for number, marker in enumerate(self.markers, start=1):
            self.marker_list.insert(tk.END, marker.label(number))

        count = len(self.markers)
        if count == 0:
            self.marker_count_label.config(text="No markers yet")
        else:
            self.marker_count_label.config(
                text=f"{count} marker{'s' if count != 1 else ''}")

        self.draw_markers()

    # -------------------------------------------------------------- export --

    def _unsaved_marker_count(self):
        """How many markers would actually be lost.

        A clip that has only its automatic 00:00 marker, with nothing typed
        into it, has nothing worth warning about.
        """
        if not self._markers_dirty:
            return 0
        return sum(1 for marker in self.markers
                   if marker.time_ms > 0 or marker.location or marker.tags)

    def _confirm_discard_markers(self):
        """Ask before markers are thrown away. True means carry on."""
        count = self._unsaved_marker_count()
        if count == 0:
            return True

        answer = messagebox.askyesnocancel(
            "Unsaved markers",
            f"{count} marker{'s' if count != 1 else ''} on the current video "
            "have not been exported.\n\n"
            "Yes  -  export them to CSV first\n"
            "No  -  discard them\n"
            "Cancel  -  stay on the current video",
        )
        if answer is None:      # Cancel
            return False
        if answer:              # Yes: only proceed if the export succeeded
            return self.export_csv()
        return True             # No: discard

    def export_csv(self):
        """Write the markers to a CSV named after the video's folder.

        Returns True only when a file was actually written, so the
        discard warning can tell a real export from a cancelled one.
        """
        if self.current_path is None:
            messagebox.showinfo("Nothing to export",
                                "Open a video and mark some spots first.")
            return False
        # Flush anything still sitting in the location or task boxes.
        self.commit_edits()
        if not self.markers:
            messagebox.showinfo("Nothing to export",
                                "This video has no marked spots yet.")
            return False

        folder = os.path.dirname(os.path.abspath(self.current_path))
        session = session_name(self.current_path)

        # Defaults to <folder>/<folder name>.csv, but the dialog lets the
        # location be confirmed or changed before anything is written.
        path = filedialog.asksaveasfilename(
            title="Export markers to CSV",
            initialdir=folder,
            initialfile=f"{session}.csv",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not path:
            self.status_label.config(text="Export cancelled.")
            return False

        fps = (self.playback.frame_rate() if self.playback is not None
               else DEFAULT_FRAME_RATE)
        rows = build_rows(self.markers, session, self.duration_ms, fps)
        try:
            write_csv(path, rows)
        except OSError as exc:
            messagebox.showerror("Export failed",
                                 f"Could not write to:\n{path}\n\n{exc}")
            return False

        self._markers_dirty = False
        self.status_label.config(
            text=f"Exported {len(rows)} markers to {path}")
        messagebox.showinfo(
            "Export complete",
            f"{len(rows)} marker{'s' if len(rows) != 1 else ''} written to:"
            f"\n\n{path}\n\nColumns: {', '.join(CSV_COLUMNS)}")
        return True

    # -------------------------------------------------- location and tasks --

    def _on_marker_select(self, _event=None):
        """Selection moved: save the old marker's details, load the new."""
        self.commit_edits()
        self._load_editor(self.selected_marker_index())
        self.draw_markers()

    def _load_editor(self, index):
        """Point the detail boxes at a marker, or disable them if none."""
        if index is None or not 0 <= index < len(self.markers):
            self._editor_index = None
            self.location_var.set("")
            self.tag_var.set("")
            self.location_entry.config(state=tk.DISABLED)
            self.tag_entry.config(state=tk.DISABLED)
            self.selection_label.config(text="No marker selected")
            return

        marker = self.markers[index]
        self._editor_index = index
        self.location_entry.config(state=tk.NORMAL)
        self.tag_entry.config(state=tk.NORMAL)
        self.location_var.set(marker.location)
        self.tag_var.set(", ".join(marker.tags))
        self.selection_label.config(
            text=f"Marker {index + 1} at "
                 f"{format_marker_time(marker.time_ms)}")

    def commit_edits(self):
        """Write the detail boxes onto the marker they were opened for."""
        index = self._editor_index
        if index is None or not 0 <= index < len(self.markers):
            return

        marker = self.markers[index]
        location = self.location_var.get().strip()
        tags = parse_tags(self.tag_var.get())
        if location == marker.location and tags == marker.tags:
            return
        marker.location = location
        marker.tags = tags
        self._markers_dirty = True

        # Refresh just this row, keeping the selection where it was.
        was_selected = self.selected_marker_index() == index
        self.marker_list.delete(index)
        self.marker_list.insert(index, marker.label(index + 1))
        if was_selected:
            self.marker_list.selection_set(index)

    def _on_details_entered(self, _event):
        self.commit_edits()
        index = self._editor_index
        if index is not None:
            marker = self.markers[index]
            self.status_label.config(
                text=f"Saved {format_marker_time(marker.time_ms)} - "
                     f"location: {marker.location or '(none)'}, "
                     f"task: {', '.join(marker.tags) or '(none)'}")
        return "break"

    # ------------------------------------------------------- marker strip --

    def _marker_x(self, time_ms, width, length):
        """Pixel position on the strip for a marker time."""
        span = max(1, width - 2 * TROUGH_INSET)
        return TROUGH_INSET + (time_ms / length) * span

    def draw_markers(self):
        """Repaint the salmon dots under the scrub bar."""
        self.marker_strip.delete("all")
        width = self.marker_strip.winfo_width()
        if width <= 1:
            return

        # A hairline so the strip reads as part of the scrub bar even when
        # nothing has been marked yet.
        centre_y = MARKER_STRIP_HEIGHT / 2
        self.marker_strip.create_line(TROUGH_INSET, centre_y,
                                      width - TROUGH_INSET, centre_y,
                                      fill="#d5d5d5")

        length = self._strip_length
        if not self.markers or length <= 0:
            return

        selected = self.selected_marker_index()
        for index, marker in enumerate(self.markers):
            x = self._marker_x(min(marker.time_ms, length), width, length)
            is_selected = index == selected
            self.marker_strip.create_oval(
                x - MARKER_RADIUS, centre_y - MARKER_RADIUS,
                x + MARKER_RADIUS, centre_y + MARKER_RADIUS,
                fill=MARKER_COLOR_SELECTED if is_selected else MARKER_COLOR,
                outline=MARKER_OUTLINE, width=2 if is_selected else 1,
            )

    def on_strip_click(self, event):
        """Clicking a dot jumps to that marker."""
        width = self.marker_strip.winfo_width()
        length = self._strip_length
        if not self.markers or length <= 0 or width <= 1:
            return

        def dot_x(index):
            return self._marker_x(min(self.markers[index].time_ms, length),
                                  width, length)

        nearest = min(range(len(self.markers)),
                      key=lambda i: abs(dot_x(i) - event.x))
        if abs(dot_x(nearest) - event.x) <= MARKER_RADIUS + MARKER_HIT_SLOP:
            self.goto_marker(nearest)

    # ------------------------------------------------------------ playback --

    def play(self):
        if self.playback is None:
            self.open_file()
            return
        self.playback.set_pause(False)
        self.is_paused = False
        self.play_button.config(text="Pause")
        self._schedule_tick(0)

    def pause(self):
        if self.playback is None:
            return
        self.playback.set_pause(True)
        self.is_paused = True
        self.play_button.config(text="Play")

    def toggle_play(self):
        if self.playback is None:
            self.open_file()
        elif self.is_paused:
            self.play()
        else:
            self.pause()

    def stop(self):
        """No true stop in ffpyplayer -- rewind and hold on the first frame."""
        if self.playback is None:
            return
        self.pause()
        self.seek_to(0.0)
        self.seek_var.set(0.0)
        self.time_label.config(text="00:00")

    def seek_to(self, seconds):
        if self.playback is None:
            return
        seconds = max(0.0, seconds)
        self.playback.seek(seconds)
        # Move the thumb now rather than waiting for the next decoded frame,
        # so a jump to a marker is reflected on the scrub bar immediately.
        self.position_ms = int(seconds * 1000)
        self._update_scrub_position()
        self.request_redraw()
        self._schedule_tick(0)

    def skip(self, delta_seconds):
        if self.playback is None:
            return
        self.playback.seek(delta_seconds, relative=True)
        target = self.position_ms + int(delta_seconds * 1000)
        if self.duration_ms > 0:
            target = min(target, self.duration_ms)
        self.position_ms = max(0, target)
        self._update_scrub_position()
        self.request_redraw()
        self._schedule_tick(0)

    def _update_scrub_position(self):
        """Put the clock and the scrub thumb on the current position."""
        self.time_label.config(text=format_time(self.position_ms))
        if self.duration_ms > 0:
            fraction = min(1.0, max(0.0, self.position_ms / self.duration_ms))
            self.seek_var.set(fraction * 1000.0)

    def on_end_reached(self):
        self.pause()
        self.seek_to(0.0)
        self.seek_var.set(0.0)
        self.time_label.config(text="00:00")
        self.status_label.config(text="End of video.")

    # -------------------------------------------------------------- seeking --

    def on_seek_press(self, _event):
        self.user_is_seeking = True

    def on_seek_release(self, _event):
        self.user_is_seeking = False
        if self.playback is not None and self.duration_ms > 0:
            fraction = self.seek_var.get() / 1000.0
            self.seek_to(fraction * self.duration_ms / 1000.0)

    # --------------------------------------------------------------- audio --

    def on_volume_change(self, value):
        if self.playback is not None:
            self.playback.set_volume(float(value) / 100.0)

    def toggle_mute(self):
        if self.playback is None:
            return
        muted = not self.playback.get_mute()
        self.playback.set_mute(muted)
        self.mute_button.config(text="Unmute" if muted else "Mute")

    # -------------------------------------------------------------- ticker --

    def _refresh(self):
        """Slow loop: clock, seek bar and duration. Frames have their own."""
        if self.playback is not None:
            if self.duration_ms <= 0:
                # FFmpeg only reports the duration once the stream is read.
                self.duration_ms = self.playback.duration_ms()

            self.duration_label.config(text=format_time(self.duration_ms))
            if self.user_is_seeking:
                self.time_label.config(text=format_time(self.position_ms))
            else:
                self._update_scrub_position()

            if self.duration_ms != self._strip_length:
                self._strip_length = self.duration_ms
                self.draw_markers()

        self.after(UI_REFRESH_MS, self._refresh)

    # ----------------------------------------------------------- shutdown --

    def quit_app(self):
        self.commit_edits()
        self._close_player()
        self.destroy()
