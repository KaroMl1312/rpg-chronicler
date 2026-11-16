"""Okno „Dodaj sesję z notatek”: sesja bez nagrania (kampania, data, obecne postacie, notatki MG).

To samo okno edytuje notatki istniejącej sesji z notatek (nazwa się wtedy nie zmienia). Zapis od razu
do <nazwa>.notatki.md (notes.save_notes); kronikę pisze zadanie `summarize` uruchamiane przez okno główne.
"""
import datetime
from typing import Callable

from gi.repository import Adw, Gio, GLib, Gtk

from .. import notes
from ..campaigns import campaign_key, load_campaigns
from ..session import Session, list_sessions

NOTES_HINT = ("Notatki MG z przebiegu sesji, najlepiej w punktach: kto, gdzie, co się stało, co zdobyto, "
              "co ustalono. AI rozwinie je w kronikę, ale nie dopisze zdarzeń, których tu nie ma.")


def known_campaigns() -> list[str]:
    """Kampanie z kampanie.toml i z nazw sesji, alfabetycznie."""
    keys = set(load_campaigns()) | {k for s in list_sessions() if (k := campaign_key(s.name))}
    return sorted(keys, key=str.casefold)


class NotesDialog(Adw.Dialog):
    """`on_saved(nazwa, napisz_kronikę)` - po zapisie notatek."""

    def __init__(self, on_saved: Callable[[str, bool], None], campaign: str | None = None,
                 session: Session | None = None):
        editing = session is not None
        super().__init__(title="Notatki sesji" if editing else "Dodaj sesję z notatek",
                         content_width=640, content_height=720)
        self._on_saved = on_saved
        self._session = session
        self._date = datetime.date.today()
        current = notes.read_notes(session) if editing else None
        self._present = set(current.present) if current else None   # None = wszyscy z kampanii

        page = Adw.PreferencesPage()
        group = Adw.PreferencesGroup(
            description=None if editing else "Sesja, która nie była nagrywana: kronika powstanie z notatek MG. "
                                             "Nie będzie nagrania, mówców ani cytatów.")
        page.add(group)
        if editing:
            group.add(Adw.ActionRow(title="Sesja", subtitle=session.name, css_classes=["property"]))
        else:
            self.campaign_row = Adw.EntryRow(title="Kampania", text=campaign or "")
            self.campaign_row.connect("changed", lambda _r: self._update())
            choices = known_campaigns()
            if choices:
                menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
                popover = Gtk.Popover(child=menu)
                for key in choices:
                    item = Gtk.Button(label=key, css_classes=["flat"])
                    item.connect("clicked", lambda _b, k=key: (popover.popdown(), self.campaign_row.set_text(k)))
                    menu.append(item)
                self.campaign_row.add_suffix(Gtk.MenuButton(icon_name="pan-down-symbolic", popover=popover,
                                                            valign=Gtk.Align.CENTER, css_classes=["flat"],
                                                            tooltip_text="Wybierz kampanię"))
            group.add(self.campaign_row)

            self.calendar = Gtk.Calendar()
            self.calendar.connect("day-selected", self._on_day_selected)
            self.date_button = Gtk.MenuButton(label=self._date_label(), valign=Gtk.Align.CENTER,
                                              popover=Gtk.Popover(child=self.calendar))
            date_row = Adw.ActionRow(title="Data sesji")
            date_row.add_suffix(self.date_button)
            group.add(date_row)
            self.name_row = Adw.ActionRow(title="Nazwa sesji", css_classes=["property"])
            group.add(self.name_row)

        self.present_group = Adw.PreferencesGroup(
            title="Obecne postacie graczy",
            description="Trafią do kroniki i dziennika postaci (zamiast rozpoznawania mówców).")
        page.add(self.present_group)
        self._present_rows: list[tuple[str, Adw.SwitchRow]] = []

        notes_group = Adw.PreferencesGroup(title="Notatki", description=NOTES_HINT)
        load = Gtk.Button(label="Wczytaj z pliku…", valign=Gtk.Align.CENTER, css_classes=["flat"])
        load.connect("clicked", lambda _b: self._load_file())
        notes_group.set_header_suffix(load)
        self.buffer = Gtk.TextBuffer(text=current.text if current else "")
        self.buffer.connect("changed", lambda _b: self._update())
        view = Gtk.TextView(buffer=self.buffer, wrap_mode=Gtk.WrapMode.WORD_CHAR, top_margin=10, bottom_margin=10,
                            left_margin=12, right_margin=12, accepts_tab=False)
        view.add_css_class("card")
        notes_group.add(Gtk.ScrolledWindow(child=view, min_content_height=260, hscrollbar_policy=Gtk.PolicyType.NEVER))
        page.add(notes_group)

        options = Adw.PreferencesGroup()
        rewrite = editing and session.has_summary
        self.generate_row = Adw.SwitchRow(title="Napisz kronikę od nowa" if rewrite else "Od razu napisz kronikę",
                                          active=not rewrite,
                                          subtitle="Zadanie AI uruchomi się po zapisaniu notatek")
        options.add(self.generate_row)
        page.add(options)

        self.save_button = Gtk.Button(label="Zapisz" if editing else "Dodaj sesję", css_classes=["suggested-action"])
        self.save_button.connect("clicked", lambda _b: self._save())
        cancel = Gtk.Button(label="Anuluj")
        cancel.connect("clicked", lambda _b: self.close())
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        header.pack_start(cancel)
        header.pack_end(self.save_button)
        self.error = Gtk.Label(wrap=True, xalign=0, margin_start=24, margin_end=24, margin_bottom=12,
                               css_classes=["error"], visible=False)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(page)
        box.append(self.error)
        page.set_vexpand(True)
        view_root = Adw.ToolbarView(content=box)
        view_root.add_top_bar(header)
        self.set_child(view_root)
        self._campaign_shown = None
        self._update()

    # ------------------------------------------------------------ stan okna

    def _date_label(self) -> str:
        return self._date.strftime("%d.%m.%Y")

    def _on_day_selected(self, calendar) -> None:
        date = calendar.get_date()
        self._date = datetime.date(date.get_year(), date.get_month(), date.get_day_of_month())
        self.date_button.set_label(self._date_label())
        self.date_button.popdown()
        self._update()

    def campaign(self) -> str:
        return campaign_key(self._session.name) if self._session else self.campaign_row.get_text().strip()

    def session_name(self) -> str:
        """Nazwa nowej sesji; rzuca NotesError (zła kampania albo zajęta nazwa)."""
        if self._session is not None:
            return self._session.name
        name = notes.session_name(self.campaign(), self._date)
        notes.check_new_name(name)
        return name

    def _rebuild_present(self, key: str) -> None:
        for _name, row in self._present_rows:
            self.present_group.remove(row)
        self._present_rows = []
        campaign = load_campaigns().get(key) if key else None
        characters = list(campaign.player_characters) if campaign else []
        for name in sorted(self._present or (), key=str.casefold):   # obecni spoza listy kampanii (ręcznie)
            if name not in characters:
                characters.append(name)
        for name in characters:
            row = Adw.SwitchRow(title=name, active=self._present is None or name in self._present)
            self.present_group.add(row)
            self._present_rows.append((name, row))
        self.present_group.set_visible(bool(characters))

    def selected_present(self) -> tuple[str, ...]:
        return tuple(name for name, row in self._present_rows if row.get_active())

    def _update(self) -> None:
        key = self.campaign()
        if key != self._campaign_shown:
            self._campaign_shown = key
            self._rebuild_present(key)
        error, missing = "", not key or not self._text().strip()   # brak danych - bez komunikatu, tylko szary przycisk
        if key:
            try:
                name = self.session_name()
            except notes.NotesError as e:
                error, name = str(e), "—"
            if self._session is None:
                self.name_row.set_subtitle(name)
        self.error.set_label(error)
        self.error.set_visible(bool(error))
        self.save_button.set_sensitive(not error and not missing)

    def _text(self) -> str:
        return self.buffer.get_text(self.buffer.get_start_iter(), self.buffer.get_end_iter(), False)

    # ------------------------------------------------------------ akcje

    def _load_file(self) -> None:
        text_filter = Gtk.FileFilter(name="Notatki (.txt, .md)")
        for pattern in ("*.txt", "*.md", "*.markdown"):
            text_filter.add_pattern(pattern)
        filters = Gio.ListStore.new(Gtk.FileFilter)
        filters.append(text_filter)
        dialog = Gtk.FileDialog(title="Wczytaj notatki", filters=filters)

        def opened(_dialog, result):
            try:
                file = dialog.open_finish(result)
                ok, data, _etag = file.load_contents(None)
            except GLib.Error:
                return   # anulowano albo nie da się odczytać
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                text = data.decode("cp1250", errors="replace")
            self.buffer.set_text(notes.parse(text).text)

        dialog.open(self.get_root(), None, opened)

    def _save(self) -> None:
        try:
            name = self.session_name()
            notes.save_notes(name, notes.Notes(self._text(), self.selected_present()))
        except (notes.NotesError, OSError) as e:
            self.error.set_label(str(e))
            self.error.set_visible(True)
            return
        generate = self.generate_row.get_active()
        self.close()
        self._on_saved(name, generate)
