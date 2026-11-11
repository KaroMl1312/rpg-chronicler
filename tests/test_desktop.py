import configparser

from rpg_chronicler.gui import desktop


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
