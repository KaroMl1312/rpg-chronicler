"""Test dymny GUI: buduje wszystkie widoki na danych z tests/test_gui_smoke.py (uruchamiany systemowym Pythonem).

Wypisuje „OK <krok>” po każdym kroku; błąd w dowolnym kroku kończy proces kodem 1. Ostrzeżenia GTK
(Gtk-CRITICAL, Gtk-WARNING) sprawdza wywołujący test na stderr.
"""
import sys
import traceback

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from rpg_chronicler.gui import window as window_module  # noqa: E402
from rpg_chronicler.gui.discord_dialog import DiscordDialog  # noqa: E402
from rpg_chronicler.gui.search_dialog import SearchDialog  # noqa: E402
from rpg_chronicler.gui.settings_dialog import SettingsDialog  # noqa: E402

FULL = "Warhammer_261105"      # transkrypcja, mówcy, kronika, skrót, cytaty
AUDIO_ONLY = "Warhammer_261112"  # samo nagranie - panel przed transkrypcją
OTHER = "Fallout_261014"         # samo nagranie innej kampanii - filtr listy sesji


def labels(widget, found=None) -> list[str]:
    found = [] if found is None else found
    if isinstance(widget, (Gtk.Label, Gtk.Button)) and widget.get_label():
        found.append(widget.get_label())
    child = widget.get_first_child()
    while child is not None:
        labels(child, found)
        child = child.get_next_sibling()
    return found


def _walk(widget):
    yield widget
    child = widget.get_first_child()
    while child is not None:
        yield from _walk(child)
        child = child.get_next_sibling()


def steps(win):
    def window():
        assert {s.name for s in win.sessions} == {FULL, AUDIO_ONLY, OTHER}, [s.name for s in win.sessions]
    yield "okno", window

    def campaign_filter():
        def shown():
            return [name for name, row in win._rows.items() if row.get_child_visible()]
        assert win.filter_dropdown.get_visible() and len(shown()) == 3, shown()
        win.filter_dropdown.set_selected(win._filter_keys.index("Fallout"))
        assert win.campaign_filter == "Fallout" and shown() == [OTHER], shown()
        win.refresh(force=True)                      # wybór przetrwa przebudowę listy
        assert shown() == [OTHER], shown()
        win.open_session(FULL, "summary")            # sesja spoza filtra → filtr się zdejmuje
        assert win.campaign_filter is None and len(shown()) == 3, shown()
    yield "filtr kampanii", campaign_filter

    def full_session():
        win.open_session(FULL, "summary")
        assert win.current.name == FULL
        texts = labels(win.chronicle_page)
        assert "Popraw…" in texts and "Wyślij na Discord" in texts, texts
        menu = next(w for w in _walk(win.chronicle_page) if isinstance(w, Gtk.MenuButton)
                    and w.get_icon_name() == "view-more-symbolic")
        assert "Generuj ponownie" in labels(menu.get_popover()), labels(menu.get_popover())
    yield "kronika", full_session

    def chronicle_modes():
        for mode, expected in (("skrot", "Dotarliście do Doliny."), ("cytaty", "„Tak?”"), ("kronika", "Popraw…")):
            win.chronicle_page._mode = mode
            win.chronicle_page.show_session(win.current)
            stack = win.chronicle_page.get_child().get_last_child()
            visible = stack.get_visible_child() if isinstance(stack, Gtk.Stack) else win.chronicle_page
            texts = labels(visible) + labels(win.chronicle_page)
            if mode == "skrot":  # skrót jest w TextView, nie w etykiecie
                view = next(w for w in _walk(visible) if isinstance(w, Gtk.TextView))
                buffer = view.get_buffer()
                texts.append(buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False))
            assert any(expected in t for t in texts), (mode, texts)
            if mode == "cytaty":  # cytat z czasem i nagraniem ma przycisk odsłuchu
                assert len(win.chronicle_page._play_buttons) == 1, win.chronicle_page._play_buttons
    yield "skrót i cytaty", chronicle_modes

    def transcript_tab():
        win.view_stack.set_visible_child_name("transcript")
        assert any("segmentów" in t for t in labels(win.transcript_page))
        menu = next(w for w in _walk(win.transcript_page) if isinstance(w, Gtk.MenuButton)
                    and w.get_label() == "Statystyki")
        texts = labels(menu.get_popover())
        assert "MG" in texts and "Fen" in texts and any("80%" in t for t in texts), texts
        issues = next(w for w in _walk(win.transcript_page) if isinstance(w, Gtk.MenuButton)
                      and w.get_icon_name() == "dialog-warning-symbolic")
        assert "Usuń powtórzenia" in labels(issues.get_popover()), labels(issues.get_popover())
        menu.popup()
        menu.popdown()
    yield "transkrypcja", transcript_tab

    yield "mówcy", lambda: win.view_stack.set_visible_child_name("speakers")
    yield "poprawka kroniki", lambda: win.chronicle_page._ask_revision(win.current)

    def recording_panel():
        win.open_session(AUDIO_ONLY, "transcript")
        assert win.transcript_page.recording_panel is not None
    yield "panel nagrania", recording_panel

    def search():
        dialog = SearchDialog(lambda: win.sessions, win.player, win.open_session, None)
        dialog.present(win)
        dialog.entry.set_text("Romulus")
        dialog._run()
        assert dialog.status.get_text().startswith("2 trafienia"), dialog.status.get_text()
        dialog.close()
    yield "wyszukiwarka", search

    def campaigns():
        win.show_campaigns("Warhammer")
        page = win._campaigns_dialog.nav.get_visible_page()
        texts = labels(page)
        assert "Pamięć kampanii" in texts and "Encyklopedia kampanii" in texts and "Dzienniki postaci" in texts, texts
        assert "Sir Amos" in texts and "Utwórz" in texts, texts
        win._campaigns_dialog.force_close()
    yield "kampanie", campaigns

    def discord():
        session = next(s for s in win.sessions if s.name == FULL)
        dialog = DiscordDialog(session, win.start_task, lambda: "claude-code", win._register_task_button,
                               win.show_campaigns)
        assert dialog._quotes_switch is not None
    yield "discord", discord

    yield "ustawienia", lambda: SettingsDialog("claude-code", lambda _k: None, lambda: None)

    def backfill():
        win.show_backfill()
        dialog = win.get_visible_dialog()
        assert isinstance(dialog, Adw.AlertDialog), dialog
        assert "PDF-y: 1 (Warhammer_261105)" in dialog.get_body(), dialog.get_body()
        dialog.force_close()
    yield "uzupełnianie", backfill

    def notes_session():
        import datetime
        from rpg_chronicler.gui.notes_dialog import NotesDialog
        win.show_notes_dialog(None)
        dialog = win.get_visible_dialog()
        assert isinstance(dialog, NotesDialog), dialog
        dialog.campaign_row.set_text("Warhammer")
        dialog._date = datetime.date(2026, 1, 2)
        assert not dialog.save_button.get_sensitive()          # bez notatek
        dialog.buffer.set_text("- Drużyna dotarła do Ubersreiku.")
        assert dialog.save_button.get_sensitive() and dialog.name_row.get_subtitle() == "Warhammer_260102"
        assert [name for name, _row in dialog._present_rows] == ["Fen", "Sir Amos"]
        dialog._present_rows[1][1].set_active(False)
        dialog.generate_row.set_active(False)
        dialog._save()
        assert win.current.name == "Warhammer_260102" and win.current.has_notes
        assert win.view_stack.get_page(win.transcript_page).get_title() == "Notatki"
        assert not win.view_stack.get_page(win.speakers_page).get_visible()
        texts = labels(win.transcript_page)
        assert "Edytuj notatki…" in texts and any("obecni: Fen" in t for t in texts), texts
        assert "Generuj kronikę" in labels(win.chronicle_page), labels(win.chronicle_page)

        win.show_notes_dialog(win.current)                      # edycja: nazwa stała, notatki wczytane
        edit = win.get_visible_dialog()
        assert edit.save_button.get_sensitive() and "Ubersreiku" in edit._text()
        edit.force_close()
        win.open_session(FULL, "transcript")                    # zwykła sesja: znów „Transkrypcja” i „Mówcy”
        assert win.view_stack.get_page(win.speakers_page).get_visible()
    yield "notatki", notes_session

    def delete_dialogs():
        win.open_session(FULL, "summary")
        for scope in ("kronika", "od-nowa", "sesja"):
            assert win.lookup_action(f"delete-{scope}").get_enabled(), scope
        win.confirm_delete("kronika")
        dialog = win.get_visible_dialog()
        assert dialog.get_heading() == "Usunąć kronikę?" and dialog.get_response_enabled("delete")
        assert any("Warhammer_261105_podsumowanie.txt" in t for t in labels(dialog.get_extra_child()))
        dialog.force_close()
        win.confirm_delete("sesja")
        dialog = win.get_visible_dialog()
        assert not dialog.get_response_enabled("delete")        # najpierw „Rozumiem…”
        check = next(w for w in _walk(dialog.get_extra_child()) if isinstance(w, Gtk.CheckButton))
        check.set_active(True)
        assert dialog.get_response_enabled("delete")
        dialog.force_close()
        win.open_session("Warhammer_260102", "transcript")      # sesja z notatek: bez kroniki i nagrania
        assert not win.lookup_action("delete-kronika").get_enabled()
        assert not win.lookup_action("delete-od-nowa").get_enabled()
    yield "usuwanie", delete_dialogs

    def entry_descriptions():
        from rpg_chronicler.campaigns import load_campaigns
        from rpg_chronicler.gui.entry_page import EntryPage
        win.show_campaigns("Warhammer")
        page = win._campaigns_dialog.nav.get_visible_page()
        rows = [w for w in _walk(page) if isinstance(w, Adw.ActionRow) and w.get_title() == "Ojciec Romulus"]
        assert rows and rows[0].get_subtitle() == "Kapłan Morra." and rows[0].get_has_tooltip(), rows
        assert any("Opisane: 1 z 3" in (w.get_description() or "") for w in _walk(page)
                   if isinstance(w, Adw.PreferencesGroup))
        page.open_entry("Sir Amos", "Postać gracza")
        entry = win._campaigns_dialog.nav.get_visible_page()
        assert isinstance(entry, EntryPage) and entry.text() == ""
        assert "Dodaj zdjęcie…" in labels(entry)
        entry.buffer.set_text("Rycerz z Bretonii.")
        win._campaigns_dialog.nav.pop()                          # zapis przy wyjściu ze strony
        assert load_campaigns()["Warhammer"].description("Sir Amos") == "Rycerz z Bretonii."
        win._campaigns_dialog.force_close()
    yield "opisy haseł", entry_descriptions

    def before_session():
        from rpg_chronicler import ask, prep
        with open(prep.recap_path("Warhammer"), "w", encoding="utf-8") as f:
            f.write(f"<!-- po sesji: {FULL} -->\nPoprzednio… szukaliście Romulusa.\n")
        answer = ask.Answer("Kim jest Romulus?", f"Kapłanem [{FULL}].", [FULL], "2026-11-16T20:00")
        ask._save_history("Warhammer", [answer])
        win.show_campaigns("Warhammer")
        page = win._campaigns_dialog.nav.get_visible_page()
        texts = labels(page)
        assert "Przed sesją" in texts and "Zapytaj kronikarza" in texts and "Notatki MG" in texts, texts
        assert "Poprzednio… szukaliście Romulusa." in texts and "Kapłanem [Warhammer_261105]." in texts, texts
        recap = next(w for w in _walk(page)
                     if isinstance(w, Adw.ExpanderRow) and w.get_title().startswith("Poprzednio"))
        assert recap.get_subtitle() == f"po sesji {FULL}", recap.get_subtitle()
        link = next(w for w in _walk(page) if isinstance(w, Gtk.Button) and w.get_label() == FULL)
        win.open_session(AUDIO_ONLY, "transcript")
        link.emit("clicked")                                     # odpowiedź → kronika sesji
        assert win._campaigns_dialog is None and win.current.name == FULL
        assert win.view_stack.get_visible_child_name() == "summary"
    yield "przed sesją", before_session

    def ai_image():
        import struct
        import zlib
        from rpg_chronicler import images
        from rpg_chronicler.campaigns import image_path
        from rpg_chronicler.gui.entry_page import EntryPage

        def png(width=4, height=4):   # najmniejszy poprawny PNG (szary kwadrat)
            def chunk(kind, data):
                return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
            rows = b"".join(b"\0" + b"\x80\x80\x80" * width for _ in range(height))
            return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                    + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))

        win.show_campaigns("Warhammer")
        page = win._campaigns_dialog.nav.get_visible_page()
        page.open_entry("Ojciec Romulus", "Postacie niezależne (NPC)")
        entry = win._campaigns_dialog.nav.get_visible_page()
        assert isinstance(entry, EntryPage) and "Wygeneruj obrazek (AI)" in labels(entry), labels(entry)
        directory = images.candidates_dir("Warhammer")
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "ojciec_romulus__20261116-200000-000000.jpg").write_bytes(png())   # rozszerzenie jak z API
        (directory / "ojciec_romulus__20261116-200000-000000.txt").write_text("An old priest.", encoding="utf-8")
        win._campaigns_dialog.reload()                           # jak po zakończeniu zadania „image”
        texts = labels(entry)
        assert "Propozycja AI - jeszcze nie zapisana" in texts and "Zachowaj" in texts, texts
        keep = next(w for w in _walk(entry) if isinstance(w, Gtk.Button) and w.get_label() == "Zachowaj")
        keep.emit("clicked")
        assert image_path("Warhammer", "Ojciec Romulus") is not None
        assert images.candidate("Warhammer", "Ojciec Romulus") is None
        assert "Zmień zdjęcie…" in labels(entry)
        win._campaigns_dialog.force_close()
    yield "obrazek AI", ai_image


def main() -> int:
    app = Adw.Application(application_id="pl.rpgchronicler.TestDymny")
    result = {"code": 1}

    def activate(application):
        win = window_module.MainWindow(application)
        win.present()

        def run():
            try:
                for name, step in steps(win):
                    step()
                    print(f"OK {name}", flush=True)
                result["code"] = 0
            except Exception:
                traceback.print_exc()
            application.quit()
            return GLib.SOURCE_REMOVE

        GLib.idle_add(run)
        GLib.timeout_add_seconds(60, lambda: (print("PRZEKROCZONO CZAS", flush=True), application.quit()))

    app.connect("activate", activate)
    app.run([])
    return result["code"]


if __name__ == "__main__":
    sys.exit(main())
