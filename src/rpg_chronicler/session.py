"""Sesja RPG = jedno nagranie i wszystkie pliki z niego wytworzone."""
import glob
import os
from dataclasses import dataclass

from .campaigns import Campaign, campaign_for
from .config import AUDIO_DIR, SUMMARY_DIR, SUPPORTED_EXTS, TXT_DIR
from .transcript import Transcript, load_transcript, speakers_json_path

TRANSCRIPT_JSON_SUFFIX = ".transkrypcja.json"


class SessionNotFound(Exception):
    pass


@dataclass(frozen=True)
class Session:
    name: str
    audio_path: str | None = None

    @property
    def txt_path(self) -> str:
        return os.path.join(TXT_DIR, f"{self.name}.txt")

    @property
    def json_path(self) -> str:
        return os.path.join(TXT_DIR, f"{self.name}{TRANSCRIPT_JSON_SUFFIX}")

    @property
    def speakers_path(self) -> str:
        return speakers_json_path(self.txt_path)

    @property
    def summary_path(self) -> str:
        return os.path.join(SUMMARY_DIR, f"{self.name}_podsumowanie.txt")

    @property
    def campaign(self) -> Campaign:
        return campaign_for(self.name)

    @property
    def system_name(self) -> str:
        return self.campaign.system

    @property
    def has_transcript(self) -> bool:
        return self.has_json or os.path.exists(self.txt_path)

    @property
    def has_json(self) -> bool:
        return os.path.exists(self.json_path)

    @property
    def has_speakers(self) -> bool:
        return os.path.exists(self.speakers_path)

    @property
    def has_summary(self) -> bool:
        return os.path.exists(self.summary_path)

    def load_transcript(self) -> Transcript:
        return load_transcript(self.json_path, self.txt_path)


def _name_from_path(path: str, suffix: str) -> str:
    return os.path.basename(path)[:-len(suffix)]


def list_sessions(names: list[str] | None = None) -> list[Session]:
    """Zwraca sesje znalezione na podstawie nagrań i transkrypcji (opcjonalnie tylko wskazane)."""
    audio = {}
    for ext in SUPPORTED_EXTS:
        for path in glob.glob(os.path.join(AUDIO_DIR, f"*{ext}")):
            audio[os.path.splitext(os.path.basename(path))[0]] = path
    transcripts = {_name_from_path(p, ".txt") for p in glob.glob(os.path.join(TXT_DIR, "*.txt"))}
    transcripts |= {_name_from_path(p, TRANSCRIPT_JSON_SUFFIX)
                    for p in glob.glob(os.path.join(TXT_DIR, f"*{TRANSCRIPT_JSON_SUFFIX}"))}

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
