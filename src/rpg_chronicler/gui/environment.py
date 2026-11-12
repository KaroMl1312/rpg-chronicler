"""Baner „środowisko transkrypcji nie działa”: sprawdzenie .venv w tle przy starcie i instrukcja naprawy."""
from gi.repository import Adw, Gio, GLib

from ..config import PROJECT_ROOT


class EnvironmentBanner(Adw.Bin):
    def __init__(self):
        super().__init__()
        self._error = ""
        self.banner = Adw.Banner(button_label="Jak naprawić")
        self.banner.connect("button-clicked", lambda _b: self._show_help())
        self.set_child(self.banner)

    def check(self) -> None:
        """W tle: czy .venv (transkrypcja, AI) działa - np. po aktualizacji systemu może wskazywać na
        odinstalowanego Pythona. Pełne sprawdzenie: ./sprawdz-srodowisko."""
        venv_python = PROJECT_ROOT / ".venv" / "bin" / "python"
        if not venv_python.exists():
            self._show_error("brak działającego interpretera w .venv")
            return
        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        launcher.unsetenv("PYTHONPATH")
        try:
            process = launcher.spawnv([str(venv_python), "-c",
                                       "import faster_whisper, pyannote.audio, torchcodec.decoders"])
        except GLib.Error as e:
            self._show_error(e.message)
            return

        def done(proc, result):
            try:
                _ok, output, _err = proc.communicate_utf8_finish(result)
            except GLib.Error as e:
                output = e.message
            if not proc.get_successful():
                lines = [line for line in (output or "").splitlines() if line.strip()]
                self._show_error(lines[-1] if lines else "nieznany błąd")

        process.communicate_utf8_async(None, None, done)

    def _show_error(self, details: str) -> None:
        self._error = details
        self.banner.set_title("Środowisko transkrypcji (.venv) nie działa - transkrypcja, odciski głosu "
                              "i kroniki są niedostępne")
        self.banner.set_revealed(True)

    def _show_help(self) -> None:
        dialog = Adw.AlertDialog(
            heading="Napraw środowisko transkrypcji",
            body="Najczęściej to skutek aktualizacji systemu (zmiana wersji Pythona). W terminalu, w katalogu "
                 f"programu ({PROJECT_ROOT}), uruchom:\n\n./sprawdz-srodowisko --napraw\n\n"
                 "Odtworzy to .venv (kilka minut, pobiera ok. 1 GB). Potem uruchom aplikację ponownie.\n\n"
                 f"Szczegóły: {self._error}")
        dialog.add_response("ok", "Zamknij")
        dialog.present(self.get_root())
