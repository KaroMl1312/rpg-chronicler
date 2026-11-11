"""Odsłuch fragmentów nagrania (Gtk.MediaFile, backend GStreamer)."""
from gi.repository import GLib, GObject, Gtk

CHECK_INTERVAL_MS = 100


class SnippetPlayer(GObject.Object):
    """Odtwarza fragment [start, end] nagrania; jeden fragment naraz.

    Sygnał `changed` po starcie/zatrzymaniu - widoki aktualizują ikony przycisków wg `current_key`.
    """

    __gsignals__ = {
        "changed": (GObject.SignalFlags.RUN_FIRST, None, ()),
        "error": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
    }

    def __init__(self):
        super().__init__()
        self.current_key = None
        self._media: Gtk.MediaFile | None = None
        self._path: str | None = None
        self._pending: tuple[float, float] | None = None
        self._end = 0.0
        self._watch_id = 0

    def toggle(self, path: str, start: float, end: float, key) -> None:
        if self.current_key == key:
            self.stop()
        else:
            self.play(path, start, end, key)

    def play(self, path: str, start: float, end: float, key) -> None:
        self.stop()
        if self._path != path:
            self._media = Gtk.MediaFile.new_for_filename(path)
            self._media.connect("notify::prepared", self._on_prepared)
            self._media.connect("notify::error", self._on_error)
            self._path = path
        self.current_key = key
        self._pending = (start, end)
        if self._media.is_prepared():
            self._start_pending()
        self.emit("changed")

    def stop(self) -> None:
        if self._watch_id:
            GLib.source_remove(self._watch_id)
            self._watch_id = 0
        if self._media is not None:
            self._media.pause()
        self._pending = None
        if self.current_key is not None:
            self.current_key = None
            self.emit("changed")

    def _on_prepared(self, media, _pspec) -> None:
        if media is self._media and media.is_prepared() and self._pending:
            self._start_pending()

    def _on_error(self, media, _pspec) -> None:
        error = media.get_error()
        if error is not None:
            self.stop()
            self._media, self._path = None, None
            self.emit("error", error.message)

    def _start_pending(self) -> None:
        start, self._end = self._pending
        self._pending = None
        self._media.seek(int(start * 1_000_000))
        self._media.play()
        self._watch_id = GLib.timeout_add(CHECK_INTERVAL_MS, self._check_end)

    def _check_end(self) -> bool:
        media = self._media
        if media is None:
            self._watch_id = 0
            return GLib.SOURCE_REMOVE
        if media.is_seeking():
            return GLib.SOURCE_CONTINUE
        if media.get_ended() or media.get_timestamp() / 1_000_000 >= self._end:
            self._watch_id = 0
            self.stop()
            return GLib.SOURCE_REMOVE
        return GLib.SOURCE_CONTINUE
