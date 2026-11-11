import importlib
import tomllib

from rpg_chronicler import config, settings


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "ustawienia.toml"
    values = {"ai.dostawca": "gemini", "transkrypcja.watki": 4, "transkrypcja.pomijanie_ciszy": True,
              "foldery.nagrania": 'C:\\dziwna "ścieżka"'}
    settings.save(values, path)
    assert settings.load(path) == values
    assert tomllib.loads(path.read_text(encoding="utf-8"))["transkrypcja"] == {"watki": 4, "pomijanie_ciszy": True}


def test_missing_file_gives_empty_settings(tmp_path):
    assert settings.load(tmp_path / "brak.toml") == {}


def test_invalid_entries_are_skipped(tmp_path, capsys):
    path = tmp_path / "ustawienia.toml"
    path.write_text('[transkrypcja]\nwatki = "dużo"\npomijanie_ciszy = 1\nmodel = "small"\n[inne]\nx = 1\n',
                    encoding="utf-8")
    assert settings.load(path) == {"transkrypcja.model": "small"}
    assert capsys.readouterr().out.count("[OSTRZEŻENIE]") == 3


def test_broken_toml_does_not_crash(tmp_path, capsys):
    path = tmp_path / "ustawienia.toml"
    path.write_text("[transkrypcja\n", encoding="utf-8")
    assert settings.load(path) == {}
    assert "[OSTRZEŻENIE]" in capsys.readouterr().out


def test_update_none_restores_default(tmp_path):
    path = tmp_path / "ustawienia.toml"
    settings.update({"transkrypcja.model": "large-v3", "ai.dostawca": "gemini"}, path)
    assert settings.update({"transkrypcja.model": None}, path) == {"ai.dostawca": "gemini"}
    assert settings.load(path) == {"ai.dostawca": "gemini"}


def test_config_uses_user_settings(tmp_path, monkeypatch):
    path = tmp_path / "ustawienia.toml"
    settings.save({"transkrypcja.model": "small", "transkrypcja.pomijanie_ciszy": True,
                   "foldery.nagrania": "~/Nagrania", "ai.model_claude_code": "opus"}, path)
    monkeypatch.setenv(settings.ENV_VAR, str(path))
    try:
        importlib.reload(config)
        assert config.MODEL_SIZE == "small" and config.WHISPER_VAD is True
        assert config.AUDIO_DIR.endswith("/Nagrania") and not config.AUDIO_DIR.startswith("~")
        assert config.CLAUDE_CODE_MODEL == "opus"
    finally:
        monkeypatch.undo()
        importlib.reload(config)
    assert config.MODEL_SIZE == "medium"
