import sys

try:
    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Adw, Gio, Gtk
except (ImportError, ValueError) as e:
    sys.exit(f"[BŁĄD] GUI wymaga PyGObject z GTK 4 i libadwaita (systemowy Python, pakiet python3-gobject): {e}")

from .desktop import APP_ID


class Application(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.set_accels_for_action("win.refresh", ["<Control>r", "F5"])
        self.set_accels_for_action("win.preferences", ["<Control>comma"])
        self.set_accels_for_action("win.campaigns", ["<Control>k"])
        self.set_accels_for_action("win.search", ["<Control>f"])
        self.set_accels_for_action("win.add-notes", ["<Control>n"])
        self.set_accels_for_action("window.close", ["<Control>w"])
        self.set_accels_for_action("app.quit", ["<Control>q"])
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.get_active_window() and self.get_active_window().close())
        self.add_action(quit_action)

    def do_startup(self):
        Adw.Application.do_startup(self)
        Gtk.Window.set_default_icon_name(APP_ID)

    def do_activate(self):
        from .window import MainWindow
        window = self.get_active_window() or MainWindow(self)
        window.present()


def main(argv: list[str] | None = None) -> int:
    return Application().run(argv if argv is not None else sys.argv)
