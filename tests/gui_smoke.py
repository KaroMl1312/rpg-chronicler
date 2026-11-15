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
        assert {s.name for s in win.sessions} == {FULL, AUDIO_ONLY}, [s.name for s in win.sessions]
    yield "okno", window

    def full_session():
        win.open_session(FULL, "summary")
        assert win.current.name == FULL
        texts = labels(win.chronicle_page)
        assert "Popraw…" in texts and "Wyślij na Discord" in texts, texts
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
    yield "skrót i cytaty", chronicle_modes

    def transcript_tab():
        win.view_stack.set_visible_child_name("transcript")
        assert any("segmentów" in t for t in labels(win.transcript_page))
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
        assert "Pamięć kampanii" in texts and "Encyklopedia kampanii" in texts, texts
        win._campaigns_dialog.force_close()
    yield "kampanie", campaigns

    def discord():
        session = next(s for s in win.sessions if s.name == FULL)
        dialog = DiscordDialog(session, win.start_task, lambda: "claude-code", win._register_task_button,
                               win.show_campaigns)
        assert dialog._quotes_switch is not None
    yield "discord", discord

    yield "ustawienia", lambda: SettingsDialog("claude-code", lambda _k: None, lambda: None)


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
