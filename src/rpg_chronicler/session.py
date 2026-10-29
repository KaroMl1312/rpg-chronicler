"""Sesja RPG = jedno nagranie i wszystkie pliki z niego wytworzone."""
import glob
import os
from dataclasses import dataclass

from .config import AUDIO_DIR, SUMMARY_DIR, SUPPORTED_EXTS, TXT_DIR
from .transcript import speakers_json_path


class SessionNotFound(Exception):
    pass


def system_name_from_filename(base_name: str) -> str:
    """'warhammer-fantasy_sesja12' -> 'Warhammer Fantasy'; bez '_' w nazwie -> 'RPG'."""
    if "_" not in base_name:
        return "RPG"
    return base_name.split("_")[0].replace("-", " ").title()


@dataclass(frozen=True)
class Session:
    name: str
    audio_path: str | None = None

    @property
    def txt_path(self) -> str:
        return os.path.join(TXT_DIR, f"{self.name}.txt")

    @property
    def speakers_path(self) -> str:
        return speakers_json_path(self.txt_path)

    @property
    def summary_path(self) -> str:
        return os.path.join(SUMMARY_DIR, f"{self.name}_podsumowanie.txt")

    @property
    def system_name(self) -> str:
        return system_name_from_filename(self.name)

    @property
    def has_transcript(self) -> bool:
        return os.path.exists(self.txt_path)

    @property
    def has_speakers(self) -> bool:
        return os.path.exists(self.speakers_path)

    @property
    def has_summary(self) -> bool:
        return os.path.exists(self.summary_path)


def list_sessions(names: list[str] | None = None) -> list[Session]:
    """Zwraca sesje znalezione na podstawie nagrań i transkrypcji (opcjonalnie tylko wskazane)."""
    audio = {}
    for ext in SUPPORTED_EXTS:
        for path in glob.glob(os.path.join(AUDIO_DIR, f"*{ext}")):
            audio[os.path.splitext(os.path.basename(path))[0]] = path
    transcripts = {os.path.basename(p)[:-len(".txt")] for p in glob.glob(os.path.join(TXT_DIR, "*.txt"))}

    sessions = {name: Session(name, audio.get(name)) for name in audio.keys() | transcripts}
    if not names:
        return [sessions[name] for name in sorted(sessions)]

    selected = []
    for name in names:
        # Pozwalamy podać nazwę pliku z rozszerzeniem lub ścieżką
        key, ext = os.path.splitext(os.path.basename(name))
        if ext.lower() not in (*SUPPORTED_EXTS, ".txt"):
            key = os.path.basename(name)
        if key not in sessions:
            raise SessionNotFound(f"Nie znaleziono sesji '{name}'. Sprawdź listę: rpg-chronicler status")
        selected.append(sessions[key])
    return selected
