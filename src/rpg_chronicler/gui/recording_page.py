"""Panel nagrania przed transkrypcją: wykrywanie ciszy, przycinanie i start transkrypcji."""
import math
import os
from typing import Callable

from gi.repository import Adw, GLib, Gtk

from .. import audio_trim
from ..audio_trim import format_timestamp
from ..session import Session
from .player import SnippetPlayer
from .text import format_minutes

PLAY_ICON = "media-playback-start-symbolic"
STOP_ICON = "media-playback-stop-symbolic"
LISTEN_SECONDS = 15
SENSITIVITY = [(-45.0, "Tylko całkowita cisza"), (-40.0, "Standardowa"),
               (-35.0, "Cisza z szumem w tle"), (-30.0, "Głośne tło (wentylator, ulica)")]

StartTask = Callable[[str, list[str]], None]


class RecordingPanel(Adw.Bin):
    def __init__(self, session: Session, player: SnippetPlayer, start_task: StartTask,
                 register_task_button: Callable[[Gtk.Button], None], busy: bool):
        super().__init__()
        self.session = session
        self._busy = busy
        self._trim_changes = False
        self._trim_button: Gtk.Button | None = None
        self._player = player
        self._start_task = start_task
        self._register = register_task_button
        self._play_buttons: list[tuple[object, Gtk.Button]] = []
        self._ffmpeg_error = None
        try:
            audio_trim.require_ffmpeg()
        except audio_trim.TrimError as e:
            self._ffmpeg_error = str(e)
        self._header_ok = audio_trim.has_duration_header(session.audio_path)
        self.analysis = audio_trim.load_analysis(session.name, session.audio_path) if not self._ffmpeg_error else None
        if self.analysis:
            self.start, self.end = audio_trim.suggest_range(self.analysis)
        self.cut_gaps = 0
        self._player_handler = player.connect("changed", lambda _p: self._update_play_buttons())
        self.connect("unrealize", lambda _w: self._disconnect_player())

        page = Adw.PreferencesPage()
        page.add(self._recording_group())
        if not self._ffmpeg_error:
            page.add(self._silence_group())
            if self.analysis and (self.analysis.silences or not self._header_ok):
                page.add(self._trim_group())
        page.add(self._transcribe_group())
        self.set_child(page)

    def _disconnect_player(self) -> None:
        if self._player_handler:
            self._player.disconnect(self._player_handler)
            self._player_handler = 0

    # ------------------------------------------------------------ grupy

    def _recording_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Nagranie")
        try:
            size = f"{os.path.getsize(self.session.audio_path) / 1e9:.2f} GB"
        except OSError:
            size = "?"
        details = [size]
        if self.analysis:
            details.insert(0, format_minutes(self.analysis.duration))
        group.add(Adw.ActionRow(title=os.path.basename(self.session.audio_path), subtitle=" · ".join(details),
                                use_markup=False, subtitle_selectable=True))
        if not self._header_ok:
            warning = Adw.ActionRow(
                title="Plik nie ma zapisanej długości",
                subtitle="Tak zapisują niektóre dyktafony. Rozpoznawanie głosów nie odczyta takiego pliku - "
                         "wykryj ciszę i przytnij nagranie (nawet bez zmiany granic), żeby zapisać je od nowa.")
            icon = Gtk.Image(icon_name="dialog-warning-symbolic")
            icon.add_css_class("warning")
            warning.add_prefix(icon)
            group.add(warning)
        return group

    def _silence_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Cisza w nagraniu")
        current_noise = self.analysis.noise_db if self.analysis else audio_trim.DEFAULT_NOISE_DB
        values = [value for value, _ in SENSITIVITY]
        self._sensitivity = Adw.ComboRow(title="Czułość", subtitle="Co uznawać za ciszę",
                                         model=Gtk.StringList.new([label for _, label in SENSITIVITY]))
        self._sensitivity.set_selected(values.index(current_noise) if current_noise in values else 1)

        detect = Gtk.Button(label="Wykryj ponownie" if self.analysis else "Wykryj ciszę", valign=Gtk.Align.CENTER)
        detect.add_css_class("flat" if self.analysis else "suggested-action")
        detect.connect("clicked", lambda _b: self._detect())
        self._register(detect)
        group.set_header_suffix(detect)

        if self.analysis is None:
            group.set_description("Sprawdź, czy nagranie ma długie fragmenty ciszy - np. dyktafon włączony "
                                  "długo przed sesją albo zostawiony po niej. Analiza trwa kilkanaście sekund, "
                                  "a przycięcie przed transkrypcją może ją znacznie skrócić.")
        elif not self.analysis.silences:
            group.set_description(f"Nie znaleziono ciszy dłuższej niż {self.analysis.min_silence:g} s - "
                                  "nie ma czego przycinać. Przy szumach w tle spróbuj innej czułości.")
        else:
            group.set_description(f"Cisza łącznie: {format_minutes(self.analysis.silence_total)} "
                                  f"w {len(self.analysis.silences)} fragmentach (≥ {self.analysis.min_silence:g} s).")
            group.add(self._timeline())
        group.add(self._sensitivity)
        if self.analysis and self.analysis.silences:
            group.add(self._silences_expander())
        elif self.analysis and not self._header_ok:
            group.add(self._timeline())
        return group

    def _trim_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Przycięcie",
                                     description="Zostaje fragment od początku do końca. Odsłuchaj granice, "
                                                 "żeby nie uciąć rozmowy.")
        self._start_row = self._time_row("Początek", self.start, ("trim", "start"),
                                         lambda: (self.start, self.start + LISTEN_SECONDS),
                                         f"Odsłuchaj {LISTEN_SECONDS} s od początku")
        self._end_row = self._time_row("Koniec", self.end, ("trim", "end"),
                                       lambda: (max(0.0, self.end - LISTEN_SECONDS), self.end),
                                       f"Odsłuchaj {LISTEN_SECONDS} s przed końcem")
        group.add(self._start_row)
        group.add(self._end_row)

        self._gaps_row = Adw.SpinRow.new_with_range(0, 600, 1)
        self._gaps_row.set_title("Wytnij przerwy w środku dłuższe niż (min)")
        self._gaps_row.set_value(0)
        self._gaps_row.connect("notify::value", lambda row, _p: self._set_cut_gaps(int(row.get_value())))
        group.add(self._gaps_row)

        self._plan_row = Adw.ActionRow(title="Po przycięciu", use_markup=False)
        group.add(self._plan_row)

        self._trim_button = Gtk.Button(label="Przytnij nagranie", halign=Gtk.Align.CENTER, margin_top=12)
        self._trim_button.add_css_class("pill")
        self._trim_button.add_css_class("suggested-action")
        self._trim_button.connect("clicked", lambda _b: self._confirm_trim())
        group.add(self._trim_button)
        self._update_plan()
        return group

    def _transcribe_group(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(
            title="Transkrypcja",
            description="Transkrypcja z rozpoznawaniem głosów działa na procesorze i trwa zwykle około czasu "
                        "trwania nagrania. Jeśli chcesz przyciąć ciszę, zrób to wcześniej - po transkrypcji "
                        "czasy przestałyby pasować do nagrania.")
        button = Gtk.Button(label="Transkrybuj", halign=Gtk.Align.CENTER, margin_top=12)
        button.add_css_class("pill")
        if not (self.analysis and self.analysis.silences):  # przy wykrytej ciszy główną akcją jest przycięcie
            button.add_css_class("suggested-action")
        button.connect("clicked", lambda _b: self._start_task(
            f"Transkrypcja {self.session.name}", ["transcribe", self.session.name]))
        self._register(button)
        group.add(button)
        return group

    # ------------------------------------------------------------ widżety

    def _timeline(self) -> Gtk.Widget:
        self._timeline_area = Gtk.DrawingArea(content_height=64, hexpand=True,
                                              margin_top=12, margin_bottom=8, margin_start=12, margin_end=12)
        self._timeline_area.set_draw_func(self._draw_timeline)
        legend = Gtk.Label(label="niebieskie – zostaje · szare – cisza · przyciemnione – zostanie wycięte",
                           xalign=0, margin_start=12, margin_bottom=10, wrap=True)
        legend.add_css_class("dim-label")
        legend.add_css_class("caption")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.add_css_class("card")
        box.append(self._timeline_area)
        box.append(legend)
        return box

    def _draw_timeline(self, area, cr, width, height) -> None:
        duration = self.analysis.duration or 1
        x = lambda t: width * t / duration
        bar_top, bar_height = 4, 30
        fg = area.get_color()

        cr.set_source_rgb(0.21, 0.52, 0.89)  # mowa
        cr.rectangle(0, bar_top, width, bar_height)
        cr.fill()
        cr.set_source_rgba(0.6, 0.6, 0.6, 1)  # cisza
        for start, end in self.analysis.silences:
            cr.rectangle(x(start), bar_top, max(1, x(end) - x(start)), bar_height)
        cr.fill()

        try:
            segments = self._segments()
        except audio_trim.TrimError:
            segments = []
        cr.set_source_rgba(0, 0, 0, 0.55)  # wycinane fragmenty
        previous = 0.0
        for start, end in segments + [(duration, duration)]:
            if start > previous:
                cr.rectangle(x(previous), bar_top, x(start) - x(previous), bar_height)
            previous = end
        cr.fill()
        cr.set_source_rgb(0.88, 0.11, 0.14)  # granice
        cr.set_line_width(2)
        for t in (self.start, self.end):
            cr.move_to(x(t), bar_top - 2)
            cr.line_to(x(t), bar_top + bar_height + 2)
        cr.stroke()

        # podziałka co godzinę (co 15 min dla krótkich nagrań)
        step = 3600 if duration > 2 * 3600 else 900
        cr.set_source_rgba(fg.red, fg.green, fg.blue, 0.7)
        cr.set_font_size(11)
        cr.set_line_width(1)
        for i in range(0, math.floor(duration / step) + 1):
            t = i * step
            cr.move_to(x(t) + 0.5, bar_top + bar_height + 2)
            cr.line_to(x(t) + 0.5, bar_top + bar_height + 7)
            cr.stroke()
            label = f"{t // 3600} h" if step == 3600 else format_timestamp(t)[:-3]
            extents = cr.text_extents(label)
            cr.move_to(min(max(0, x(t) - extents.width / 2), width - extents.width), height - 6)
            cr.show_text(label)

    def _silences_expander(self) -> Adw.ExpanderRow:
        expander = Adw.ExpanderRow(title="Wykryte fragmenty ciszy",
                                   subtitle="Odsłuchaj, czy to na pewno cisza, a nie np. cicha rozmowa")
        for index, (start, end) in enumerate(self.analysis.silences):
            row = Adw.ActionRow(title=f"{format_timestamp(start)} – {format_timestamp(end)}",
                                subtitle=format_minutes(end - start) if end - start >= 60 else f"{round(end - start)} s",
                                use_markup=False)
            middle = start + (end - start) / 2
            row.add_prefix(self._play_button(("silence", index), lambda m=middle: (m, m + LISTEN_SECONDS),
                                             f"Odsłuchaj {LISTEN_SECONDS} s ze środka"))
            expander.add_row(row)
        return expander

    def _time_row(self, title: str, value: float, key, span: Callable[[], tuple[float, float]],
                  tooltip: str) -> Adw.EntryRow:
        row = Adw.EntryRow(title=f"{title} (gg:mm:ss)", text=format_timestamp(value), show_apply_button=True)
        row.connect("apply", lambda r: self._apply_time(r))
        row.add_suffix(self._play_button(key, span, tooltip))
        return row

    def _play_button(self, key, span: Callable[[], tuple[float, float]], tooltip: str) -> Gtk.Button:
        button = Gtk.Button(icon_name=PLAY_ICON, valign=Gtk.Align.CENTER, tooltip_text=tooltip)
        button.add_css_class("flat")
        button.add_css_class("circular")
        full_key = (self.session.name, *key) if isinstance(key, tuple) else (self.session.name, key)

        def clicked(_b):
            start, end = span()
            self._player.toggle(self.session.audio_path, start, end, full_key)

        button.connect("clicked", clicked)
        self._play_buttons.append((full_key, button))
        return button

    def _update_play_buttons(self) -> None:
        for key, button in self._play_buttons:
            button.set_icon_name(STOP_ICON if key == self._player.current_key else PLAY_ICON)

    # ------------------------------------------------------------ logika

    def _segments(self) -> list[tuple[float, float]]:
        return audio_trim.keep_segments(self.analysis, self.start, self.end, self.cut_gaps)

    def _apply_time(self, row: Adw.EntryRow) -> None:
        try:
            value = min(max(0.0, audio_trim.parse_timestamp(row.get_text())), self.analysis.duration)
        except ValueError:
            row.add_css_class("error")
            return
        row.remove_css_class("error")
        if row is self._start_row:
            self.start = value
        else:
            self.end = value
        row.set_text(format_timestamp(value))
        self._update_plan()

    def _set_cut_gaps(self, minutes: int) -> None:
        self.cut_gaps = minutes
        self._update_plan()

    def _update_plan(self) -> None:
        try:
            segments = self._segments()
        except audio_trim.TrimError as e:
            self._plan_row.set_subtitle(str(e))
            self._trim_button.set_sensitive(False)
            self._timeline_area.queue_draw()
            return
        self._plan_row.set_subtitle(audio_trim.describe_plan(self.analysis, segments))
        changes = not self._header_ok or not (len(segments) == 1 and segments[0][0] <= 0.5
                                              and segments[0][1] >= self.analysis.duration - 0.5)
        self._trim_changes = changes
        self._trim_button.set_sensitive(changes and not self._busy)

        internal = [s for s in self.analysis.silences if s[0] > self.start and s[1] < self.end]
        longest = max((e - s for s, e in internal), default=0)
        self._gaps_row.set_subtitle("0 = nie wycinaj" + (f" · najdłuższa przerwa w środku: {format_minutes(longest)}"
                                                         if longest >= 60 else ""))
        self._timeline_area.queue_draw()

    def _detect(self) -> None:
        noise = SENSITIVITY[self._sensitivity.get_selected()][0]
        self._start_task(f"Wykrywanie ciszy {self.session.name}",
                         ["silence", self.session.name, "--force", "--noise", f"{noise:g}"])

    def _confirm_trim(self) -> None:
        segments = self._segments()
        dialog = Adw.AlertDialog(
            heading="Przyciąć nagranie?",
            body=audio_trim.describe_plan(self.analysis, segments) + "\n\n"
                 f"Oryginał zostanie przeniesiony do folderu „{audio_trim.BACKUP_DIR_NAME}” obok nagrania. "
                 "Na Google Drive nic się nie zmienia, a synchronizacja nie nadpisze przyciętego pliku.")
        dialog.add_response("cancel", "Anuluj")
        dialog.add_response("trim", "Przytnij")
        dialog.set_response_appearance("trim", Adw.ResponseAppearance.SUGGESTED)

        def on_response(_d, response):
            if response != "trim":
                return
            self._player.stop()
            self._start_task(f"Przycinanie {self.session.name}", [
                "trim", self.session.name,
                "--start", format_timestamp(self.start), "--end", format_timestamp(self.end),
                "--cut-gaps", str(self.cut_gaps),
                "--noise", f"{self.analysis.noise_db:g}", "--min-silence", f"{self.analysis.min_silence:g}"])

        dialog.connect("response", on_response)
        dialog.present(self.get_root())

    def set_busy(self, busy: bool) -> None:
        """Przycisk „Przytnij” jest aktywny tylko bez zadania w toku i gdy plan coś zmienia."""
        self._busy = busy
        if self._trim_button is not None:
            self._trim_button.set_sensitive(self._trim_changes and not busy)
