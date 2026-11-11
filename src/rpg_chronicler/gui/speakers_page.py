"""Zakładka „Mówcy”: sugestia AI, imiona dla SPEAKER_XX i odsłuch próbek głosu."""
import os
from typing import Callable

from gi.repository import Adw, Gtk

from ..session import Session
from ..transcript import Transcript, load_speaker_mapping, save_speaker_mapping
from .player import SnippetPlayer
from .text import format_minutes, format_timestamp

PLAY_ICON = "media-playback-start-symbolic"
STOP_ICON = "media-playback-stop-symbolic"
SAMPLE_COUNT = 5
SAMPLE_TEXT_LIMIT = 220


class SpeakersPage(Adw.Bin):
    def __init__(self, player: SnippetPlayer, on_suggest: Callable[[Session], None],
                 on_saved: Callable[[Session], None]):
        super().__init__()
        self._player = player
        self._on_suggest = on_suggest
        self._on_saved = on_saved
        self._session: Session | None = None
        self._entries: dict[str, Adw.EntryRow] = {}
        self._saved: dict[str, str] = {}
        self._play_buttons: list[tuple[object, Gtk.Button]] = []
        self._save_button: Gtk.Button | None = None
        self._suggest_button: Gtk.Button | None = None
        player.connect("changed", lambda _p: self._update_play_buttons())

    # --- stan edycji ---

    @property
    def session(self) -> Session | None:
        return self._session

    def edits(self) -> dict[str, str]:
        return {spk: entry.get_text().strip() for spk, entry in self._entries.items()}

    @property
    def dirty(self) -> bool:
        return bool(self._entries) and self.edits() != self._saved

    def save(self, notify: bool = True) -> bool:
        if self._session is None or not self.dirty:
            return False
        mapping = {spk: name for spk, name in self.edits().items() if name}
        if not mapping:
            return False
        save_speaker_mapping(self._session.txt_path, mapping)
        self._saved = self.edits()
        self._update_save_button()
        if notify:
            self._on_saved(self._session)
        return True

    def set_busy(self, busy: bool) -> None:
        if self._suggest_button is not None:
            self._suggest_button.set_sensitive(not busy)

    # --- budowa widoku ---

    def show_session(self, session: Session, transcript: Transcript | None,
                     keep_edits: dict[str, str] | None = None) -> None:
        self._session = session
        self._entries, self._saved, self._play_buttons = {}, {}, []
        self._save_button = self._suggest_button = None

        if transcript is None:
            self.set_child(Adw.StatusPage(
                icon_name="system-users-symbolic", title="Brak transkrypcji",
                description="Mówców można nazwać po transkrypcji nagrania."))
            return
        if not transcript.speakers:
            self.set_child(Adw.StatusPage(
                icon_name="system-users-symbolic", title="Brak rozpoznanych mówców",
                description="Ta transkrypcja powstała bez rozpoznawania głosów, więc nie ma kogo nazywać."))
            return

        page = Adw.PreferencesPage()
        page.add(self._suggestion_group(session))

        mapping = load_speaker_mapping(session.txt_path)
        stats = transcript.speaker_stats()
        # Najpierw najdłużej mówiący (MG i gracze), na końcu przypadkowe głosy i szumy
        for spk in sorted(transcript.speakers, key=lambda spk: -stats.get(spk, (0, 0.0))[1]):
            count, seconds = stats.get(spk, (0, 0.0))
            page.add(self._speaker_group(session, transcript, spk, mapping.get(spk, ""), count, seconds))
        self._saved = self.edits()

        if keep_edits:
            for spk, text in keep_edits.items():
                if spk in self._entries:
                    self._entries[spk].set_text(text)

        save_group = Adw.PreferencesGroup()
        self._save_button = Gtk.Button(label="Zapisz mówców", halign=Gtk.Align.CENTER)
        self._save_button.add_css_class("pill")
        self._save_button.add_css_class("suggested-action")
        self._save_button.connect("clicked", lambda _b: self.save())
        save_group.add(self._save_button)
        page.add(save_group)

        self._update_save_button()
        self.set_child(page)

    def _suggestion_group(self, session: Session) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title="Sugestia AI")
        suggestion = _read_text(session.speaker_suggestion_path)

        self._suggest_button = Gtk.Button(label="Zapytaj ponownie" if suggestion else "Zapytaj AI",
                                          valign=Gtk.Align.CENTER)
        self._suggest_button.add_css_class("flat")
        self._suggest_button.connect("clicked", lambda _b: self._on_suggest(session))
        group.set_header_suffix(self._suggest_button)

        if suggestion:
            label = Gtk.Label(label=suggestion, wrap=True, xalign=0, selectable=True,
                              margin_top=12, margin_bottom=12, margin_start=12, margin_end=12)
            card = Gtk.Box()
            card.add_css_class("card")
            card.append(label)
            group.add(card)
        else:
            group.set_description("AI przeczyta transkrypcję i opisze każdego mówcę: kto jest MG, "
                                  "jakie postacie prowadzą gracze. Trwa to zwykle 1–3 minuty.")
        return group

    def _speaker_group(self, session: Session, transcript: Transcript, spk: str, name: str,
                       count: int, seconds: float) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup(title=spk, description=f"{count} wypowiedzi · {format_minutes(seconds)} mówienia")

        entry = Adw.EntryRow(title="Imię postaci lub rola (np. MG, Hans)", text=name)
        entry.connect("changed", lambda _e: self._update_save_button())
        entry.connect("entry-activated", lambda _e: self.save())
        self._entries[spk] = entry
        entry.add_suffix(_names_menu(session, entry))

        samples = transcript.speaker_samples(spk, SAMPLE_COUNT)
        if samples:
            first = samples[0]
            entry.add_suffix(self._play_button(session, (session.name, spk, 0), first.start, first.end,
                                               "Odsłuchaj najdłuższą wypowiedź"))
        group.add(entry)

        if samples:
            expander = Adw.ExpanderRow(title="Próbki głosu", subtitle="najdłuższe wypowiedzi tego mówcy")
            for index, sample in enumerate(samples):
                text = sample.text if len(sample.text) <= SAMPLE_TEXT_LIMIT else sample.text[:SAMPLE_TEXT_LIMIT] + "…"
                row = Adw.ActionRow(title=text, subtitle=f"{format_timestamp(sample.start)} · "
                                                         f"{round(sample.end - sample.start)} s",
                                    use_markup=False, title_lines=3)
                row.add_prefix(self._play_button(session, (session.name, spk, index), sample.start, sample.end,
                                                 "Odsłuchaj"))
                expander.add_row(row)
            group.add(expander)
        return group

    def _play_button(self, session: Session, key, start: float, end: float, tooltip: str) -> Gtk.Button:
        button = Gtk.Button(icon_name=PLAY_ICON, valign=Gtk.Align.CENTER)
        button.add_css_class("flat")
        button.add_css_class("circular")
        if session.audio_path and os.path.exists(session.audio_path):
            button.set_tooltip_text(tooltip)
            button.connect("clicked", lambda _b: self._player.toggle(session.audio_path, start, end, key))
        else:
            button.set_sensitive(False)
            button.set_tooltip_text("Brak lokalnego nagrania")
        self._play_buttons.append((key, button))
        return button

    def _update_play_buttons(self) -> None:
        for key, button in self._play_buttons:
            button.set_icon_name(STOP_ICON if key == self._player.current_key else PLAY_ICON)

    def _update_save_button(self) -> None:
        if self._save_button is not None:
            self._save_button.set_sensitive(self.dirty and any(self.edits().values()))


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _names_menu(session: Session, entry: Adw.EntryRow) -> Gtk.MenuButton:
    """Lista do wyboru: MG i postacie graczy z kampanii (okno „Kampanie”)."""
    names = ["MG", *session.campaign.player_characters]
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    popover = Gtk.Popover(child=box)
    for name in names:
        player = session.campaign.player_characters.get(name, "")
        button = Gtk.Button(label=f"{name} ({player})" if player else name)
        button.add_css_class("flat")
        button.get_child().set_xalign(0)

        def choose(_b, n=name):
            entry.set_text(n)
            popover.popdown()

        button.connect("clicked", choose)
        box.append(button)
    if len(names) == 1:
        hint = Gtk.Label(label="Dodaj postacie graczy w oknie\nKampanie (Ctrl+K)", margin_top=6,
                         margin_bottom=6, margin_start=6, margin_end=6)
        hint.add_css_class("dim-label")
        box.append(hint)
    menu = Gtk.MenuButton(icon_name="pan-down-symbolic", popover=popover, valign=Gtk.Align.CENTER,
                          tooltip_text="Wybierz postać gracza z kampanii")
    menu.add_css_class("flat")
    return menu
