from typing import Iterable, NamedTuple

UNKNOWN_SPEAKER = "SPEAKER_UNKNOWN"


class Turn(NamedTuple):
    start: float
    end: float
    speaker: str


def assign_speakers(segments: Iterable, turns: list[Turn]) -> list[str]:
    """Dla każdego segmentu (z .start/.end) zwraca mówcę o największym pokryciu czasowym.

    Segmenty muszą być posortowane po czasie startu. Zamiast przeszukiwać wszystkie tury
    dla każdego segmentu, przesuwamy wskaźnik - tury zakończone przed segmentem
    nie mogą pokryć się z żadnym kolejnym.
    """
    turns = sorted(turns)
    speakers = []
    first = 0
    for segment in segments:
        while first < len(turns) and turns[first].end <= segment.start:
            first += 1

        speaker, max_overlap = UNKNOWN_SPEAKER, 0.0
        for turn in turns[first:]:
            if turn.start >= segment.end:
                break
            overlap = min(segment.end, turn.end) - max(segment.start, turn.start)
            if overlap > max_overlap:
                speaker, max_overlap = turn.speaker, overlap
        speakers.append(speaker)
    return speakers
