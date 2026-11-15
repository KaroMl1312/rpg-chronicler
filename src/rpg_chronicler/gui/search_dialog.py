"""Okno „Szukaj w sesjach” (Ctrl+F): kroniki i transkrypcje, odsłuch fragmentu, przejście do sesji."""
from typing import Callable

from gi.repository import Adw, GLib, Gtk

from ..campaigns import campaign_key
from ..quality import format_time
from ..search import KIND_CHRONICLE, Hit, TranscriptCache, search, summary_line
from ..session import Session
from .player import SnippetPlayer
from .text import highlight_markup

MAX_ROWS = 300      # więcej wyników nikt nie przegląda, a lista by zwalniała
PLAY_MARGIN = 1.0   # sekundy nagrania przed i po trafieniu


class SearchDialog(Adw.Dialog):
    def __init__(self, sessions: Callable[[], list[Session]], player: SnippetPlayer,
                 open_session: Callable[[str, str], None], campaign: str | None = None):
        super().__init__(title="Szukaj w sesjach", content_width=820, content_height=720)
        self._sessions = sessions
        self._player = player
        self._open_session = open_session
        self._cache = TranscriptCache()
        self._play_buttons: dict[tuple, Gtk.Button] = {}
        self._player_handler = player.connect("changed", lambda _p: self._update_play_icons())
        self.connect("closed", lambda _d: (player.stop(), player.disconnect(self._player_handler)))

        self.entry = Gtk.SearchEntry(placeholder_text="Imię, miejsce, przedmiot… (odmiana nie przeszkadza)",
                                     hexpand=True, search_delay=350)
        self.entry.connect("search-changed", lambda _e: self._run())
        self.entry.connect("activate", lambda _e: self._run())

        keys = sorted({k for s in sessions() if (k := campaign_key(s.name))}, key=str.casefold)
        self._campaigns = [None, *keys]
        self.campaign_drop = Gtk.DropDown.new_from_strings(["Wszystkie kampanie", *keys])
        if campaign in keys:
            self.campaign_drop.set_selected(self._campaigns.index(campaign))
        self.campaign_drop.connect("notify::selected", lambda *_: self._run())

        self.chronicles_toggle = Gtk.ToggleButton(label="Kroniki", active=True)
        self.transcripts_toggle = Gtk.ToggleButton(label="Transkrypcje", active=True)
        for toggle in (self.chronicles_toggle, self.transcripts_toggle):
            toggle.connect("toggled", lambda *_: self._run())
        kinds = Gtk.Box(css_classes=["linked"])
        kinds.append(self.chronicles_toggle)
        kinds.append(self.transcripts_toggle)

        filters = Gtk.Box(spacing=8, margin_start=12, margin_end=12, margin_top=6, margin_bottom=6)
        filters.append(self.entry)
        filters.append(self.campaign_drop)
        filters.append(kinds)

        self.status = Gtk.Label(xalign=0, margin_start=16, margin_bottom=6, css_classes=["dim-label"],
                                label="Wyniki od najstarszej sesji - pierwszy to pierwsze pojawienie się.")
        self.results = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE, css_classes=["boxed-list"],
                                   margin_start=12, margin_end=12, margin_bottom=12, valign=Gtk.Align.START)
        scrolled = Gtk.ScrolledWindow(child=self.results, vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(filters)
        box.append(self.status)
        box.append(scrolled)
        view = Adw.ToolbarView(content=box)
        view.add_top_bar(Adw.HeaderBar())
        self.set_child(view)
        GLib.idle_add(lambda: self.entry.grab_focus() and False)

    def _run(self) -> None:
        self._player.stop()
        self.results.remove_all()
        self._play_buttons = {}
        query = self.entry.get_text().strip()
        if not query:
            self.status.set_text("Wyniki od najstarszej sesji - pierwszy to pierwsze pojawienie się.")
            return
        sessions = {s.name: s for s in self._sessions()}
        hits = search(sessions.values(), query, campaign=self._campaigns[self.campaign_drop.get_selected()],
                      chronicles=self.chronicles_toggle.get_active(),
                      transcripts=self.transcripts_toggle.get_active(), cache=self._cache)
        more = f" (pokazano {MAX_ROWS})" if len(hits) > MAX_ROWS else ""
        self.status.set_text(summary_line(hits) + more)
        for hit in hits[:MAX_ROWS]:
            self.results.append(self._row(hit, sessions.get(hit.session), query))

    def _row(self, hit: Hit, session: Session | None, query: str) -> Gtk.Widget:
        if hit.kind == KIND_CHRONICLE:
            title = f"{hit.session} · kronika" + (f" · {hit.heading}" if hit.heading else "")
        else:
            title = f"{hit.session} · {format_time(hit.start)}" + (f" · {hit.speaker}" if hit.speaker else "")
        row = Adw.ActionRow(title=GLib.markup_escape_text(title), subtitle=highlight_markup(hit.text, query),
                            subtitle_lines=4)
        if hit.kind != KIND_CHRONICLE and session is not None and session.audio_path:
            key = (hit.session, hit.start)
            play = Gtk.Button(icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER,
                              tooltip_text="Odsłuchaj ten fragment nagrania", css_classes=["flat"])
            play.connect("clicked", lambda _b: self._player.toggle(
                session.audio_path, max(0.0, hit.start - PLAY_MARGIN), hit.end + PLAY_MARGIN, key))
            self._play_buttons[key] = play
            row.add_suffix(play)
        page = "summary" if hit.kind == KIND_CHRONICLE else "transcript"
        go = Gtk.Button(icon_name="go-next-symbolic", valign=Gtk.Align.CENTER, css_classes=["flat"],
                        tooltip_text="Otwórz sesję (" + ("kronikę" if page == "summary" else "transkrypcję") + ")")
        go.connect("clicked", lambda _b: (self.close(), self._open_session(hit.session, page)))
        row.add_suffix(go)
        return row

    def _update_play_icons(self) -> None:
        for key, button in self._play_buttons.items():
            playing = self._player.current_key == key
            button.set_icon_name("media-playback-stop-symbolic" if playing else "media-playback-start-symbolic")

