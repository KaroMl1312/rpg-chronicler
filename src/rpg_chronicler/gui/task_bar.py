"""Pasek zadania na dole okna: tytuł, bieżący etap, postęp z szacowanym czasem, Log i Przerwij."""
import time

from gi.repository import GLib, Gtk, Pango

from .text import estimate_remaining, format_minutes


class TaskBar(Gtk.Revealer):
    def __init__(self):
        super().__init__(reveal_child=False, transition_type=Gtk.RevealerTransitionType.SLIDE_UP)
        self._started = 0.0
        self._stage_key = None
        self._stage_started = 0.0
        self._pulse_id = 0

        self.title = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.title.add_css_class("heading")
        self.detail = Gtk.Label(xalign=0, ellipsize=Pango.EllipsizeMode.END)
        self.detail.add_css_class("dim-label")
        self.detail.add_css_class("caption")
        self.progress = Gtk.ProgressBar(valign=Gtk.Align.CENTER, hexpand=True)

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER, width_request=320)
        labels.append(self.title)
        labels.append(self.detail)

        log_button = Gtk.Button(label="Log", action_name="win.show-log", valign=Gtk.Align.CENTER)
        cancel_button = Gtk.Button(label="Przerwij", action_name="win.cancel", valign=Gtk.Align.CENTER)
        cancel_button.add_css_class("destructive-action")

        box = Gtk.Box(spacing=12, margin_top=8, margin_bottom=8, margin_start=12, margin_end=12)
        box.append(labels)
        box.append(self.progress)
        box.append(log_button)
        box.append(cancel_button)
        self.set_child(box)

    def start(self, title: str) -> None:
        self._started = time.monotonic()
        self._stage_key = None
        self.title.set_text(title)
        self.detail.set_text("Uruchamianie…")
        self.progress.set_fraction(0)
        self._start_pulse()
        self.set_reveal_child(True)

    def finish(self) -> str:
        """Chowa pasek; zwraca czas trwania zadania do komunikatu."""
        self._stop_pulse()
        self.set_reveal_child(False)
        return format_minutes(time.monotonic() - self._started)

    def set_detail(self, text: str) -> None:
        self.detail.set_text(text)

    def show_line(self, line: str) -> None:
        if line.strip() and not line.startswith("$ "):
            self.detail.set_text(line.strip())

    def show_progress(self, stage: str, session: str, fraction: float) -> None:
        key = (stage, session)
        now = time.monotonic()
        if key != self._stage_key:
            self._stage_key, self._stage_started = key, now
        label = f"{stage.capitalize()} · {session}" if session else stage.capitalize()
        if fraction < 0:
            self._start_pulse()
            self.detail.set_text(label + "…")
            return
        self._stop_pulse()
        self.progress.set_fraction(fraction)
        remaining = estimate_remaining(now - self._stage_started, fraction)
        eta = f" · zostało ok. {format_minutes(max(60, remaining))}" if remaining is not None else ""
        self.detail.set_text(f"{label} · {fraction:.0%}{eta}")

    def _start_pulse(self) -> None:
        if not self._pulse_id:
            self._pulse_id = GLib.timeout_add(120, lambda: self.progress.pulse() or True)

    def _stop_pulse(self) -> None:
        if self._pulse_id:
            GLib.source_remove(self._pulse_id)
            self._pulse_id = 0
