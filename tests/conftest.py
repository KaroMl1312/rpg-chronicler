import os

# Testy nie mogą zależeć od ustawień użytkownika z ~/.config (wczytywanych przy imporcie config.py)
os.environ["RPG_CHRONICLER_SETTINGS"] = os.devnull + ".nie-istnieje"

import pytest  # noqa: E402

from rpg_chronicler import campaigns, session, summary  # noqa: E402


class FakeLLM:
    name = "Fake"

    def __init__(self, response="KRONIKA"):
        self.response = response
        self.prompts = []

    def generate(self, prompt):
        self.prompts.append(prompt)
        return self.response


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """Tymczasowe katalogi danych, puste kampanie i atrapa LLM zamiast prawdziwego klienta."""
    dirs = {key: tmp_path / key for key in ("audio", "txt", "summary")}
    for path in dirs.values():
        path.mkdir()
    monkeypatch.setattr(session, "AUDIO_DIR", str(dirs["audio"]))
    monkeypatch.setattr(session, "TXT_DIR", str(dirs["txt"]))
    monkeypatch.setattr(session, "SUMMARY_DIR", str(dirs["summary"]))
    monkeypatch.setattr(summary, "SUMMARY_DIR", str(dirs["summary"]))
    monkeypatch.setattr(campaigns, "load_campaigns", lambda: {})

    llm = FakeLLM()
    monkeypatch.setattr(summary, "get_client", lambda provider: llm)

    class Workspace:
        pass

    ws = Workspace()
    ws.dirs, ws.llm = dirs, llm

    def add_transcript(name, text):
        (dirs["txt"] / f"{name}.txt").write_text(text, encoding="utf-8")

    def add_audio(name, ext=".m4a"):
        (dirs["audio"] / f"{name}{ext}").write_bytes(b"")

    ws.add_transcript, ws.add_audio = add_transcript, add_audio
    return ws
