import os
import tempfile

# Testy nie mogą zależeć od ustawień użytkownika z ~/.config (wczytywanych przy imporcie config.py)
os.environ["RPG_CHRONICLER_SETTINGS"] = os.devnull + ".nie-istnieje"
# ...ani od jego folderów: config.py liczy ścieżki danych (~/Documents/...) przy imporcie
os.environ["HOME"] = tempfile.mkdtemp(prefix="rpg-chronicler-testy-")

import pytest  # noqa: E402

from rpg_chronicler import after_chronicle, campaigns, chronicle_events, llm, session  # noqa: E402


class FakeLLM:
    name = "Fake"

    def __init__(self, response="KRONIKA"):
        self.response = response
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return self.response


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory, monkeypatch):
    """Żaden test nie może czytać ani zmieniać plików użytkownika (pulpit, menu, cache, ustawienia)."""
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    for var, sub in (("XDG_DATA_HOME", ".local/share"), ("XDG_CONFIG_HOME", ".config"),
                     ("XDG_CACHE_HOME", ".cache"), ("XDG_STATE_HOME", ".local/state")):
        monkeypatch.setenv(var, str(home / sub))
    return home


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Tymczasowe katalogi danych, puste kampanie i atrapa LLM zamiast prawdziwego klienta."""
    dirs = {key: tmp_path / key for key in ("audio", "txt", "summary")}
    for path in dirs.values():
        path.mkdir()
    monkeypatch.setattr(session, "AUDIO_DIR", str(dirs["audio"]))
    monkeypatch.setattr(session, "TXT_DIR", str(dirs["txt"]))
    monkeypatch.setattr(session, "SUMMARY_DIR", str(dirs["summary"]))
    monkeypatch.setattr(campaigns, "load_campaigns", lambda: {})
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))  # analizy ciszy, propozycje słownika
    monkeypatch.setattr(after_chronicle, "GLOSSARY_PROPOSALS", False)       # testy włączają je jawnie
    monkeypatch.setattr(after_chronicle, "CHRONICLE_BRIEF", False)          # jw. - skrót kroniki
    monkeypatch.setattr(after_chronicle, "CHRONICLE_QUOTES", False)         # jw. - cytaty z sesji
    monkeypatch.setattr(chronicle_events, "CHRONICLE_TWO_STEP", False)       # jw. - kronika w dwóch krokach
    monkeypatch.setattr(after_chronicle, "CAMPAIGN_MEMORY", False)          # jw. - pamięć kampanii

    fake = FakeLLM()
    monkeypatch.setattr(llm, "get_client", lambda provider: fake)  # LazyClient i komendy CLI

    class Workspace:
        pass

    ws = Workspace()
    ws.dirs, ws.llm = dirs, fake

    def add_transcript(name, text):
        (dirs["txt"] / f"{name}.txt").write_text(text, encoding="utf-8")

    def add_audio(name, ext=".m4a"):
        (dirs["audio"] / f"{name}{ext}").write_bytes(b"")

    ws.add_transcript, ws.add_audio = add_transcript, add_audio
    return ws
