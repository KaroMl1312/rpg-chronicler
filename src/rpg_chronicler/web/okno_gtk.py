"""Okno nowego GUI na Linuksie: GTK 4 + WebKit 6 z systemowego Pythona (bez dodatkowych pakietów).

Uruchamiane przez `python -m rpg_chronicler.web` jako osobny proces: /usr/bin/python3 okno_gtk.py ADRES.
Nie importuje nic z programu (działa na innym Pythonie niż serwer). Linki spoza okna otwiera w przeglądarce.
"""
import os
import sys
from urllib.parse import urlparse

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("WebKit", "6.0")
from gi.repository import Gio, GLib, Gtk, WebKit  # noqa: E402

APP_ID = "pl.rpgchronicler.Kronikarz"


def main(url: str) -> int:
    local = urlparse(url).netloc

    def on_policy(_view, decision, kind):
        if kind not in (WebKit.PolicyDecisionType.NAVIGATION_ACTION, WebKit.PolicyDecisionType.NEW_WINDOW_ACTION):
            return False
        target = decision.get_navigation_action().get_request().get_uri()
        if urlparse(target).netloc == local:
            return False
        decision.ignore()
        if urlparse(target).scheme in ("http", "https"):
            Gtk.UriLauncher.new(target).launch(None, None, None)
        return True

    def on_close(window, view):
        """Strona zapisuje wpisane zmiany i pyta o trwające zadanie (confirmClose w app.js), potem zamykamy."""
        if window.closing:
            return True   # pytanie już jest na ekranie
        window.closing = True

        def answered(view_, result):
            window.closing = False
            try:
                close = view_.call_async_javascript_function_finish(result).to_boolean()
            except GLib.Error:
                close = True   # strona nie działa - nie blokujemy zamknięcia
            if close:
                window.destroy()

        view.call_async_javascript_function("return await confirmClose()", -1, None, None, None, None, answered)
        return True

    def activate(app):
        window = Gtk.ApplicationWindow(application=app, title="RPG Chronicles", default_width=1280, default_height=820)
        window.closing = False
        view = WebKit.WebView()
        window.connect("close-request", on_close, view)
        if os.environ.get("RPG_CHRONICLER_DEBUG"):
            view.get_settings().set_enable_developer_extras(True)
        view.connect("decide-policy", on_policy)
        view.load_uri(url)
        window.set_child(view)
        window.maximize()
        window.present()

    app = Gtk.Application(application_id=APP_ID, flags=Gio.ApplicationFlags.NON_UNIQUE)
    app.connect("activate", activate)
    return app.run([sys.argv[0]])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
