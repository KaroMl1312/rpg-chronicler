import configparser
import sys

import pytest

from rpg_chronicler.gui import desktop

# Wpis w menu i skrót na pulpicie to pliki .desktop (freedesktop) - na Windowsie ich nie ma
pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="pliki .desktop są tylko na Linuksie")


def test_exec_quoting_for_path_with_spaces():
    assert desktop.quote_exec_arg("/home/u/Zachowane z hdd/rpg") == '"/home/u/Zachowane z hdd/rpg"'
    assert desktop.quote_exec_arg('/a"b$c%d') == '"/a\\\\"b\\\\$c%%d"'


def test_install_and_uninstall(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    monkeypatch.setattr(desktop.shutil, "which", lambda _cmd: None)  # bez odświeżania cache systemu

    written = desktop.install("/home/u/Zachowane z hdd/rpg-chronicler-gui")
    entry_path, icon = written
    assert entry_path == tmp_path / "applications" / f"{desktop.APP_ID}.desktop"
    assert icon.read_text(encoding="utf-8").startswith("<svg")

    parser = configparser.ConfigParser(interpolation=None)
    parser.optionxform = str
    parser.read(entry_path, encoding="utf-8")
    entry = parser["Desktop Entry"]
    assert entry["Exec"] == '"/home/u/Zachowane z hdd/rpg-chronicler-gui"'
    assert entry["Icon"] == desktop.APP_ID and entry["Terminal"] == "false"

    assert desktop.uninstall() == written
    assert not entry_path.exists() and not icon.exists()


def test_desktop_dir_from_user_dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    assert desktop.desktop_dir() == tmp_path / "Desktop"
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "user-dirs.dirs").write_text('XDG_DESKTOP_DIR="$HOME/Pulpit"\n', encoding="utf-8")
    assert desktop.desktop_dir() == tmp_path / "Pulpit"


def test_shortcut_on_desktop(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setattr(desktop, "desktop_dir", lambda: tmp_path / "Pulpit")
    monkeypatch.setattr(desktop.shutil, "which", lambda _cmd: None)

    shortcut = desktop.install_shortcut("/opt/rpg-chronicler-gui")
    assert shortcut == tmp_path / "Pulpit" / f"{desktop.APP_ID}.desktop"
    assert shortcut.stat().st_mode & 0o111  # wykonywalny = zaufany w KDE
    assert desktop.uninstall() == [shortcut]
