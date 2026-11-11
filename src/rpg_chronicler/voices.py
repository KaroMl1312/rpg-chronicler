"""Rozpoznawanie mówców po głosie: odciski głosu sesji, profile głosów kampanii i dopasowanie.

Odcisk głosu (wektor z modelu pyannote/wespeaker) liczy `transcription/voiceprints.py` i zapisuje
w `<sesja>.glosy.json` obok transkrypcji. Ten moduł (tylko biblioteka standardowa, używa go też GUI)
buduje profile z sesji tej samej kampanii, które mają nazwanych mówców, i podpowiada imiona.

Progi dobrane na nazwanych sesjach użytkownika (test „każda sesja na podstawie pozostałych”):
podpowiedź „pewna” była trafna w ok. 96% przypadków, „możliwa” w ok. 78%.
"""
import difflib
import json
import math
import os
from dataclasses import dataclass

from .campaigns import Campaign, campaign_key
from .session import Session, list_sessions
from .transcript import load_speaker_mapping

FORMAT_VERSION = 1
EMBEDDING_MODEL = "pyannote/wespeaker-voxceleb-resnet34-LM"

CONFIDENT_SCORE = 0.65    # podobieństwo do najbliższego znanego odcisku
CONFIDENT_MARGIN = 0.10   # przewaga nad drugim kandydatem
HINT_SCORE = 0.50         # poniżej - nie podpowiadamy wcale
FUZZY_NAME_RATIO = 0.85   # „Eustahos” i „Eustachos” to ta sama postać (literówki w nazwach mówców)
GAME_MASTER = "MG"


@dataclass(frozen=True)
class Voiceprint:
    vector: tuple[float, ...]   # znormalizowany (długość 1)
    seconds: float              # ile mowy posłużyło do policzenia odcisku


@dataclass(frozen=True)
class Suggestion:
    name: str
    score: float                # podobieństwo 0..1 (do wyświetlenia jako %)
    confident: bool
    alternatives: tuple[tuple[str, float], ...] = ()


# --- zapis i odczyt ---

def voices_path(session: Session) -> str:
    return os.path.splitext(session.txt_path)[0] + ".glosy.json"


def save_voiceprints(path: str, voiceprints: dict[str, Voiceprint]) -> None:
    data = {
        "version": FORMAT_VERSION,
        "model": EMBEDDING_MODEL,
        "mowcy": {spk: {"wektor": [round(x, 5) for x in vp.vector], "sekundy": round(vp.seconds, 1)}
                  for spk, vp in voiceprints.items()},
    }
    tmp_path = path + ".part"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp_path, path)


def load_voiceprints(path: str) -> dict[str, Voiceprint]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("model") != EMBEDDING_MODEL:
            return {}  # odciski z innego modelu są nieporównywalne
        return {spk: Voiceprint(_normalized(item["wektor"]), float(item.get("sekundy", 0)))
                for spk, item in data.get("mowcy", {}).items()}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def has_voiceprints(session: Session) -> bool:
    return os.path.exists(voices_path(session))


# --- nazwy ---

class NameResolver:
    """Ujednolica nazwy mówców w kampanii: wielkość liter, literówki, gracz → jego postać."""

    def __init__(self, campaign: Campaign):
        self.canonical: list[str] = [GAME_MASTER, *campaign.player_characters]
        self.players = {player.casefold(): name for name, player in campaign.player_characters.items() if player}

    def resolve(self, name: str) -> str:
        name = name.strip()
        if name.casefold() in self.players:
            return self.players[name.casefold()]
        for known in self.canonical:
            if name.casefold() == known.casefold() or \
                    difflib.SequenceMatcher(None, name.casefold(), known.casefold()).ratio() >= FUZZY_NAME_RATIO:
                return known
        self.canonical.append(name)
        return name


# --- profile i dopasowanie ---

def campaign_profiles(campaign: Campaign, exclude: str | None = None,
                      sessions: list[Session] | None = None) -> dict[str, list[Voiceprint]]:
    """Imię -> odciski głosu z nazwanych sesji tej kampanii (bez sesji `exclude`)."""
    resolver = NameResolver(campaign)
    profiles: dict[str, list[Voiceprint]] = {}
    for session in sessions if sessions is not None else list_sessions():
        if session.name == exclude or campaign_key(session.name) != campaign.key or not session.has_speakers:
            continue
        mapping = load_speaker_mapping(session.txt_path)
        for spk, voiceprint in load_voiceprints(voices_path(session)).items():
            if mapping.get(spk, "").strip():
                profiles.setdefault(resolver.resolve(mapping[spk]), []).append(voiceprint)
    return profiles


def learning_candidates(campaign: Campaign, sessions: list[Session] | None = None) -> list[Session]:
    """Nazwane sesje kampanii z nagraniem, dla których nie policzono jeszcze odcisków głosu."""
    return [s for s in (sessions if sessions is not None else list_sessions())
            if campaign_key(s.name) == campaign.key and s.has_speakers and s.audio_path and not has_voiceprints(s)]


def suggest(voiceprints: dict[str, Voiceprint], profiles: dict[str, list[Voiceprint]]) -> dict[str, Suggestion]:
    """Podpowiedzi imion dla mówców sesji. Kilka etykiet może dostać to samo imię (diaryzacja dzieli osoby)."""
    if not profiles:
        return {}
    suggestions = {}
    for spk, voiceprint in voiceprints.items():
        nearest, combined = {}, {}
        for name, prints in profiles.items():
            nearest[name] = max(_dot(voiceprint.vector, p.vector) for p in prints)
            combined[name] = (nearest[name] + _dot(voiceprint.vector, _mean(prints))) / 2
        ranked_nearest = sorted(nearest.values(), reverse=True)
        best_name = max(nearest, key=nearest.get)
        margin = ranked_nearest[0] - (ranked_nearest[1] if len(ranked_nearest) > 1 else 0.0)
        confident = ranked_nearest[0] >= CONFIDENT_SCORE and margin >= CONFIDENT_MARGIN

        ranked = sorted(combined.items(), key=lambda item: -item[1])
        name, score = (best_name, combined[best_name]) if confident else ranked[0]
        if not confident and score < HINT_SCORE:
            continue
        alternatives = tuple((n, round(s, 3)) for n, s in ranked if n != name)[:2]
        suggestions[spk] = Suggestion(name, round(max(0.0, score), 3), confident, alternatives)
    return suggestions


def suggest_for_session(session: Session, sessions: list[Session] | None = None) -> dict[str, Suggestion]:
    voiceprints = load_voiceprints(voices_path(session))
    if not voiceprints:
        return {}
    return suggest(voiceprints, campaign_profiles(session.campaign, exclude=session.name, sessions=sessions))


def _normalized(vector) -> tuple[float, ...]:
    length = math.sqrt(sum(x * x for x in vector)) or 1.0
    return tuple(float(x) / length for x in vector)


def _dot(a, b) -> float:
    return sum(x * y for x, y in zip(a, b))


def _mean(prints: list[Voiceprint]) -> tuple[float, ...]:
    """Średni odcisk ważony czasem mowy (znormalizowany)."""
    total = sum(p.seconds for p in prints) or len(prints)
    size = len(prints[0].vector)
    mean = [0.0] * size
    for p in prints:
        weight = (p.seconds or 1.0) / total
        for i, x in enumerate(p.vector):
            mean[i] += weight * x
    return _normalized(mean)
