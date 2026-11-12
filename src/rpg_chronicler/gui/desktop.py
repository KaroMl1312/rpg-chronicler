"""Wpis aplikacji w menu (.desktop + ikona) i skrót na pulpicie, w katalogach użytkownika.

Standard freedesktop - działa w GNOME, KDE i innych środowiskach. Bez GTK - testowane pytestem."""
import os
import shutil
import subprocess
from importlib.resources import files
from pathlib import Path

APP_ID = "pl.rpgchronicler.Kronikarz"  # musi być równe nazwie pliku .desktop, żeby GNOME dopasował okno i ikonę


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"))


def desktop_file_path() -> Path:
    return data_home() / "applications" / f"{APP_ID}.desktop"


def icon_path() -> Path:
    return data_home() / "icons" / "hicolor" / "scalable" / "apps" / f"{APP_ID}.svg"


def desktop_dir() -> Path:
    """Folder pulpitu wg ~/.config/user-dirs.dirs (np. ~/Pulpit w polskiej instalacji), domyślnie ~/Desktop."""
    home = os.path.expanduser("~")
    config_home = os.environ.get("XDG_CONFIG_HOME") or os.path.join(home, ".config")
    try:
        lines = Path(config_home, "user-dirs.dirs").read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        key, _, value = line.strip().partition("=")
        if key == "XDG_DESKTOP_DIR" and value:
            value = value.strip().strip('"').replace("$HOME", home)
            if os.path.isabs(value):
                return Path(value)
    return Path(home, "Desktop")


def shortcut_path() -> Path:
    return desktop_dir() / f"{APP_ID}.desktop"


def quote_exec_arg(arg: str) -> str:
    """Cytowanie argumentu linii Exec wg specyfikacji Desktop Entry (ścieżki ze spacjami)."""
    escaped = arg
    for char in ("\\", '"', "`", "$"):
        escaped = escaped.replace(char, "\\" + char)
    # Wartości kluczy .desktop same w sobie interpretują \\ - stąd drugie podwojenie odwrotnych ukośników
    # % to znak specjalny pól Exec (%f, %u...) - dosłowny procent to %%
    return '"' + escaped.replace("\\", "\\\\").replace("%", "%%") + '"'


def desktop_entry(launcher: str) -> str:
    return "\n".join([
        "[Desktop Entry]",
        "Type=Application",
        "Name=RPG Chronicler",
        "GenericName=Kronikarz sesji RPG",
        "Comment=Transkrypcje nagrań i kroniki sesji RPG",
        f"Exec={quote_exec_arg(launcher)}",
        f"Icon={APP_ID}",
        "Terminal=false",
        "Categories=AudioVideo;Audio;",
        "Keywords=RPG;transkrypcja;kronika;sesja;nagranie;",
        "StartupNotify=true",
        "",
    ])


def install(launcher: str) -> list[Path]:
    """Instaluje .desktop i ikonę dla bieżącego użytkownika; zwraca zapisane pliki."""
    icon = icon_path()
    icon.parent.mkdir(parents=True, exist_ok=True)
    icon.write_bytes(files(__package__).joinpath(f"{APP_ID}.svg").read_bytes())

    desktop = desktop_file_path()
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text(desktop_entry(launcher), encoding="utf-8")

    # Odświeżenie pamięci podręcznych - opcjonalne, środowisko i tak zauważy nowe pliki
    for command in (["update-desktop-database", str(desktop.parent)],
                    ["gtk-update-icon-cache", "-q", "-t", str(data_home() / "icons" / "hicolor")]):
        if shutil.which(command[0]):
            subprocess.run(command, check=False, capture_output=True)
    return [desktop, icon]


def install_shortcut(launcher: str) -> Path:
    """Skrót na pulpicie. Wymaga ikony z install(); prawo wykonania = „zaufany” w KDE i w rozszerzeniu DING (GNOME)."""
    shortcut = shortcut_path()
    shortcut.parent.mkdir(parents=True, exist_ok=True)
    shortcut.write_text(desktop_entry(launcher), encoding="utf-8")
    shortcut.chmod(0o755)
    if shutil.which("gio"):  # GNOME/DING dodatkowo patrzy na ten atrybut; w KDE bez znaczenia
        subprocess.run(["gio", "set", str(shortcut), "metadata::trusted", "true"], check=False, capture_output=True)
    return shortcut


def uninstall() -> list[Path]:
    removed = []
    for path in (desktop_file_path(), icon_path(), shortcut_path()):
        if path.exists():
            path.unlink()
            removed.append(path)
    return removed
