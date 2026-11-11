"""Uruchamianie komend CLI w osobnym procesie (Gio.Subprocess) i odczyt ich wyjścia i postępu."""
import codecs
import re
import shutil
import signal

from gi.repository import Gio, GLib, GObject

from .. import progress
from ..config import PROJECT_ROOT

CANCEL_TIMEOUT = 10  # sekundy od Ctrl+C do wymuszonego zakończenia
LINE_END_RE = re.compile(r"(\r\n|\r|\n)")


def cli_command() -> list[str] | None:
    """CLI z .venv projektu (tam są torch, whisper, SDK LLM), a w ostateczności z PATH."""
    venv_cli = PROJECT_ROOT / ".venv" / "bin" / "rpg-chronicler"
    if venv_cli.exists():
        return [str(venv_cli)]
    found = shutil.which("rpg-chronicler")
    return [found] if found else None


class TaskRunner(GObject.Object):
    """Jedno zadanie naraz. Sygnały:

    - line(tekst): linia wyjścia do logu,
    - status(tekst): linia nadpisywana w miejscu (np. postęp rclone) - tylko do paska stanu,
    - progress(etap, sesja, ułamek): ułamek -1 oznacza postęp nieokreślony,
    - finished(tytuł, sukces, opis).
    """

    __gsignals__ = {
        "line": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "status": (GObject.SignalFlags.RUN_FIRST, None, (str,)),
        "progress": (GObject.SignalFlags.RUN_FIRST, None, (str, str, float)),
        "finished": (GObject.SignalFlags.RUN_FIRST, None, (str, bool, str)),
    }

    def __init__(self):
        super().__init__()
        self.title: str | None = None
        self._process: Gio.Subprocess | None = None
        self._buffer = ""
        self._decoder = None
        self._cancelled = False

    @property
    def running(self) -> bool:
        return self._process is not None

    def start(self, title: str, args: list[str]) -> str | None:
        """Uruchamia `rpg-chronicler <args>`; zwraca opis błędu albo None."""
        if self.running:
            return "Inne zadanie jest w toku."
        command = cli_command()
        if command is None:
            return "Nie znaleziono rpg-chronicler (.venv/bin/rpg-chronicler). Utwórz środowisko - patrz CLAUDE.md."

        launcher = Gio.SubprocessLauncher.new(Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
        launcher.setenv(progress.ENV_VAR, "json", True)
        launcher.setenv("PYTHONUNBUFFERED", "1", True)
        launcher.unsetenv("PYTHONPATH")  # GUI działa na systemowym Pythonie z PYTHONPATH=src
        launcher.set_stdin_file_path("/dev/null")  # input() w CLI nie może zawiesić zadania
        launcher.set_cwd(str(PROJECT_ROOT))
        try:
            self._process = launcher.spawnv(command + args)
        except GLib.Error as e:
            return f"Nie udało się uruchomić zadania: {e.message}"

        self.title = title
        self._buffer = ""
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._cancelled = False
        self.emit("line", f"$ rpg-chronicler {' '.join(args)}")
        self._read_more(self._process)
        return None

    def cancel(self) -> None:
        if not self.running:
            return
        process = self._process
        self._cancelled = True
        process.send_signal(signal.SIGINT)  # CLI kończy się czysto (KeyboardInterrupt)

        def force_exit():
            if self._process is process:
                process.force_exit()
            return GLib.SOURCE_REMOVE

        GLib.timeout_add_seconds(CANCEL_TIMEOUT, force_exit)

    # --- odczyt wyjścia ---

    def _read_more(self, process: Gio.Subprocess) -> None:
        process.get_stdout_pipe().read_bytes_async(65536, GLib.PRIORITY_DEFAULT, None, self._on_read, process)

    def _on_read(self, stream, result, process) -> None:
        try:
            data = stream.read_bytes_finish(result).get_data()
        except GLib.Error as e:
            self.emit("line", f"[BŁĄD] Odczyt wyjścia zadania: {e.message}")
            data = b""
        if data:
            self._feed(self._decoder.decode(data))
            self._read_more(process)
        else:
            self._feed(self._decoder.decode(b"", final=True))
            if self._buffer:
                self._handle_line(self._buffer, transient=False)
                self._buffer = ""
            process.wait_async(None, self._on_exit)

    def _feed(self, text: str) -> None:
        parts = LINE_END_RE.split(self._buffer + text)
        # parts = [tekst, separator, tekst, separator, ..., reszta]
        for line, separator in zip(parts[0:-1:2], parts[1::2]):
            self._handle_line(line, transient=separator == "\r")
        self._buffer = parts[-1]

    def _handle_line(self, line: str, transient: bool) -> None:
        data = progress.parse(line)
        if data is not None:
            fraction = progress.fraction(data)
            self.emit("progress", data.get("etap") or "", data.get("sesja") or "",
                      -1.0 if fraction is None else fraction)
        elif transient:
            if line.strip():
                self.emit("status", line.strip())
        else:
            self.emit("line", line)

    def _on_exit(self, process, result) -> None:
        try:
            process.wait_finish(result)
        except GLib.Error:
            pass
        if process.get_if_exited():
            code = process.get_exit_status()
            success = code == 0 and not self._cancelled
            description = "przerwano" if self._cancelled else ("zakończono" if code == 0 else f"błąd (kod {code})")
        else:
            success, description = False, "przerwano" if self._cancelled else "zakończono sygnałem"
        title = self.title or ""
        self._process, self.title = None, None
        self.emit("line", f"--- {title}: {description} ---")
        self.emit("finished", title, success, description)
