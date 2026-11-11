"""Sprawdzenie środowiska: GUI (systemowy Python), .venv (transkrypcja), programy zewnętrzne i konfiguracja.

Uruchamiane systemowym Pythonem przez ./sprawdz-srodowisko, więc działa nawet przy zepsutym .venv
(np. po aktualizacji Fedory). `--napraw` odtwarza .venv (stare zostaje jako kopia do czasu sukcesu).
Tylko biblioteka standardowa.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import config

ROOT = config.PROJECT_ROOT
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / "bin" / "python"
VENV_INTERPRETER = "python3.11"  # dla nowszych Pythonów brakuje kół onnxruntime (wymaga go faster-whisper)
TORCH_CPU_INDEX = "https://download.pytorch.org/whl/cpu"
EXTRAS = "dev,anthropic,gemini"

OK, WARN, ERROR = "OK", "UWAGA", "BŁĄD"
SYMBOLS = {OK: "✓", WARN: "!", ERROR: "✗"}

# Sprawdzenie bibliotek w .venv - wynik jako JSON na stdout
VENV_PROBE = r"""
import json, sys
result = {"python": sys.version.split()[0], "moduly": {}}
for name in ("torch", "torchaudio", "torchcodec.decoders", "faster_whisper", "ctranslate2", "onnxruntime",
             "pyannote.audio", "anthropic", "google.genai"):
    try:
        module = __import__(name, fromlist=["_"])
        result["moduly"][name] = getattr(module, "__version__", "ok")
    except Exception as e:
        result["moduly"][name] = "BŁĄD: " + str(e).splitlines()[0][:200]
print(json.dumps(result))
"""


class Report:
    def __init__(self):
        self.results: list[tuple[str, str, str]] = []

    def add(self, status: str, name: str, details: str = "") -> None:
        self.results.append((status, name, details))
        print(f"  {SYMBOLS[status]} {name}" + (f" - {details}" if details else ""), flush=True)

    @property
    def errors(self) -> int:
        return sum(status == ERROR for status, _, _ in self.results)

    @property
    def warnings(self) -> int:
        return sum(status == WARN for status, _, _ in self.results)


def _run(cmd: list[str], timeout: int = 120, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)


def _clean_env() -> dict:
    """Środowisko bez PYTHONPATH (skrypt sam go ustawia dla src/) - .venv ma działać samodzielnie."""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    return env


# --- grupy sprawdzeń ---

def check_gui(report: Report) -> None:
    print("\nGUI (systemowy Python)")
    report.add(OK, f"Python {sys.version.split()[0]}", sys.executable)
    probe = ("import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1');"
             "from gi.repository import Gtk, Adw;"
             "print(f'{Gtk.get_major_version()}.{Gtk.get_minor_version()} {Adw.get_major_version()}.{Adw.get_minor_version()}')")
    proc = _run([sys.executable, "-c", probe])
    if proc.returncode == 0:
        gtk, adw = proc.stdout.split()
        adw_ok = tuple(map(int, adw.split("."))) >= (1, 5)  # Adw.Dialog, AlertDialog, PreferencesDialog
        report.add(OK if adw_ok else ERROR, f"GTK {gtk}, libadwaita {adw}",
                   "" if adw_ok else "GUI wymaga libadwaita ≥ 1.5")
    else:
        report.add(ERROR, "PyGObject / GTK 4 / libadwaita",
                   "zainstaluj: sudo dnf install python3-gobject gtk4 libadwaita")
        return

    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    proc = _run([sys.executable, "-c", "import rpg_chronicler.gui.window"], env=env)
    report.add(OK if proc.returncode == 0 else ERROR, "Moduły GUI",
               "" if proc.returncode == 0 else proc.stderr.strip().splitlines()[-1][:200])

    if shutil.which("gst-inspect-1.0"):
        missing = [desc for element, desc in (("flacdec", "FLAC"), ("faad", "AAC/M4A"))
                   if _run(["gst-inspect-1.0", "--exists", element]).returncode != 0
                   and not (element == "faad" and _run(["gst-inspect-1.0", "--exists", "fdkaacdec"]).returncode == 0)]
        report.add(WARN if missing else OK, "Odtwarzanie nagrań (GStreamer)",
                   f"brak dekodera: {', '.join(missing)} - odsłuch tych plików nie zadziała" if missing else "")


def check_venv(report: Report) -> None:
    print("\nŚrodowisko transkrypcji (.venv)")
    if not VENV_PYTHON.exists():
        target = os.readlink(VENV_PYTHON) if VENV_PYTHON.is_symlink() else ""
        report.add(ERROR, ".venv nie działa",
                   (f"brak interpretera {target} (np. po aktualizacji systemu)" if target else "brak .venv")
                   + " - uruchom: ./sprawdz-srodowisko --napraw")
        return

    try:
        proc = _run([str(VENV_PYTHON), "-c", VENV_PROBE], timeout=300, env=_clean_env())
        data = json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError) as e:
        report.add(ERROR, "Python w .venv", f"nie uruchamia się poprawnie: {e} - ./sprawdz-srodowisko --napraw")
        return
    report.add(OK, f"Python {data['python']} w .venv")

    required = ["torch", "torchaudio", "torchcodec.decoders", "faster_whisper", "ctranslate2", "onnxruntime",
                "pyannote.audio"]
    for name in required:
        version = data["moduly"].get(name, "brak")
        report.add(ERROR if version.startswith("BŁĄD") or version == "brak" else OK, name, version)
    torch_version = data["moduly"].get("torch", "")
    if "+cu" in torch_version or "+rocm" in torch_version:
        report.add(WARN, "torch z obsługą GPU", "program liczy na CPU - wersja CPU zajmuje ~4 GB mniej "
                                                "(./sprawdz-srodowisko --napraw)")
    for name, provider in (("anthropic", "anthropic"), ("google.genai", "gemini")):
        version = data["moduly"].get(name, "")
        if version.startswith("BŁĄD") and config.LLM_PROVIDER == provider:
            report.add(ERROR, f"{name} (wybrany dostawca AI)", version)

    proc = _run([str(VENV / "bin" / "rpg-chronicler"), "status"], timeout=120, env=_clean_env()) \
        if (VENV / "bin" / "rpg-chronicler").exists() else None
    if proc is None:
        report.add(ERROR, "Komenda rpg-chronicler", "brak - ./sprawdz-srodowisko --napraw")
    else:
        report.add(OK if proc.returncode == 0 else ERROR, "Komenda rpg-chronicler status",
                   "" if proc.returncode == 0 else (proc.stderr or proc.stdout).strip().splitlines()[-1][:200])


def check_tools(report: Report) -> None:
    print("\nProgramy i konfiguracja")
    for tool, needed_for, required in (("ffmpeg", "przycinanie ciszy", True), ("ffprobe", "przycinanie ciszy", True),
                                       ("rclone", "Google Drive", True)):
        report.add(OK if shutil.which(tool) else (ERROR if required else WARN), tool,
                   "" if shutil.which(tool) else f"brak - potrzebny do: {needed_for}")
    if shutil.which("rclone"):
        remotes = _run(["rclone", "listremotes"], timeout=30).stdout.split()
        remote = config.RCLONE_AUDIO_REMOTE.split(":")[0] + ":"
        report.add(OK if remote in remotes else ERROR, f"rclone: zdalny dysk {remote}",
                   "" if remote in remotes else "nie skonfigurowany - rclone config")
    if config.LLM_PROVIDER == "claude-code":
        report.add(OK if shutil.which("claude") else ERROR, "Claude Code (dostawca AI)",
                   "" if shutil.which("claude") else "brak komendy claude")
    report.add(OK if config.HUGGINGFACE_TOKEN else ERROR, "HUGGINGFACE_TOKEN",
               "" if config.HUGGINGFACE_TOKEN else "brak w .env - potrzebny do rozpoznawania głosów")

    hub = Path(os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface")) / "hub"
    for model, label in ((config.DIARIZATION_MODEL, "model diaryzacji"),
                         (f"Systran/faster-whisper-{config.MODEL_SIZE}", f"model Whisper {config.MODEL_SIZE}")):
        cached = (hub / ("models--" + model.replace("/", "--"))).exists()
        report.add(OK if cached else WARN, label, "" if cached else "nie pobrany - pobierze się przy pierwszej transkrypcji")

    for folder, label in ((config.AUDIO_DIR, "folder nagrań"), (config.TXT_DIR, "folder transkrypcji"),
                          (config.SUMMARY_DIR, "folder kronik")):
        report.add(OK if os.path.isdir(folder) else WARN, label, folder if os.path.isdir(folder) else f"brak: {folder}")

    from .gui.desktop import desktop_file_path
    desktop = desktop_file_path()
    if desktop.exists():
        launcher = ROOT / "rpg-chronicler-gui"
        valid = str(launcher) in desktop.read_text(encoding="utf-8")
        report.add(OK if valid else WARN, "Wpis w menu GNOME",
                   "" if valid else "wskazuje inny katalog - ./rpg-chronicler-gui --instaluj")


# --- naprawa .venv ---

def repair_venv() -> int:
    interpreter = shutil.which(VENV_INTERPRETER)
    if interpreter is None:
        print(f"[BŁĄD] Brak {VENV_INTERPRETER} - zainstaluj: sudo dnf install {VENV_INTERPRETER}")
        return 1
    backup = VENV.with_name(".venv.stare")
    if backup.exists():
        shutil.rmtree(backup)
    if VENV.exists():
        print(f"Przenoszę obecne .venv do {backup.name} (zostanie usunięte po udanej naprawie)...")
        VENV.rename(backup)

    steps = [
        [interpreter, "-m", "venv", str(VENV)],
        [str(VENV_PYTHON), "-m", "pip", "install", "--upgrade", "pip"],
        # Najpierw torch w wersji CPU - inaczej pip pobierze wersję z CUDA (~4 GB więcej)
        [str(VENV_PYTHON), "-m", "pip", "install", "--index-url", TORCH_CPU_INDEX, "torch", "torchaudio", "torchcodec"],
        [str(VENV_PYTHON), "-m", "pip", "install", "--extra-index-url", TORCH_CPU_INDEX, "-e", f".[{EXTRAS}]"],
    ]
    for step in steps:
        print(f"\n$ {' '.join(step)}", flush=True)
        if subprocess.run(step, cwd=ROOT, env=_clean_env()).returncode != 0:
            print("\n[BŁĄD] Naprawa nie powiodła się.")
            if backup.exists():
                shutil.rmtree(VENV, ignore_errors=True)
                backup.rename(VENV)
                print("Przywrócono poprzednie .venv.")
            return 1
    if backup.exists():
        shutil.rmtree(backup)
    print("\n[SUKCES] Odtworzono .venv. Sprawdzam ponownie...")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sprawdz-srodowisko",
                                     description="Sprawdza, czy GUI, .venv i narzędzia rpg-chronicler działają.")
    parser.add_argument("--napraw", action="store_true", help="odtwórz .venv (torch w wersji CPU) i sprawdź ponownie")
    args = parser.parse_args(argv)

    if args.napraw and repair_venv() != 0:
        return 1

    report = Report()
    check_gui(report)
    check_venv(report)
    check_tools(report)
    print(f"\nWynik: {report.errors} błędów, {report.warnings} uwag.")
    if report.errors and not args.napraw and any(".venv" in d or "--napraw" in d for _, _, d in report.results):
        print("Środowisko transkrypcji można odtworzyć: ./sprawdz-srodowisko --napraw")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
