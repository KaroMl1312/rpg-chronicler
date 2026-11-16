"""Wyszukiwarka po sesjach: kroniki i transkrypcje, z dopasowaniem odpornym na odmianę. Tylko stdlib (GUI).

Wyniki są posortowane od najstarszej sesji (data z nazwy), więc pierwszy wynik odpowiada na pytanie
„kiedy pierwszy raz pojawił się X”. Trafienia w transkrypcji mają czas - GUI odtwarza ten fragment nagrania.
Wieloczłonowe zapytanie („Ojciec Romulus”) musi trafić w okno kilku kolejnych wypowiedzi.
"""
import datetime
import os
from dataclasses import dataclass

from .campaigns import campaign_key, session_date
from .chronicle import MARKDOWN_MARKS_RE, chronicle_title
from .textmatch import matches_stems, query_stems, word_matches, words
from .transcript import Transcript, load_speaker_mapping

WINDOW = 3            # tyle kolejnych segmentów transkrypcji może obejmować jedno trafienie
SNIPPET_LIMIT = 240   # znaków fragmentu w wyniku
KIND_CHRONICLE = "kronika"
KIND_TRANSCRIPT = "transkrypcja"
KIND_NOTES = "notatki"     # sesja bez nagrania: notatki MG (liczą się jak transkrypcja)


@dataclass(frozen=True)
class Hit:
    session: str
    kind: str                      # KIND_CHRONICLE | KIND_TRANSCRIPT | KIND_NOTES
    text: str                      # fragment z trafieniem
    start: float | None = None     # transkrypcja: czas w nagraniu (s)
    end: float | None = None
    speaker: str | None = None     # transkrypcja: imię z mapowania mówców (albo SPEAKER_XX)
    heading: str | None = None     # kronika: najbliższy nagłówek nad akapitem


class TranscriptCache:
    """Wczytane transkrypcje, odświeżane po zmianie pliku (GUI szuka wiele razy)."""

    def __init__(self):
        self._items: dict[str, tuple[tuple, Transcript]] = {}

    def get(self, session) -> Transcript | None:
        path = session.json_path if session.has_json else session.txt_path
        try:
            stat = os.stat(path)
        except OSError:
            return None
        key = (path, stat.st_mtime_ns, stat.st_size)
        cached = self._items.get(session.name)
        if cached and cached[0] == key:
            return cached[1]
        try:
            transcript = session.load_transcript()
        except (OSError, ValueError):
            return None
        self._items[session.name] = (key, transcript)
        return transcript


def _shorten(text: str, limit: int = SNIPPET_LIMIT) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def search_chronicle(session_name: str, text: str, stems: list[tuple[str, ...]],
                     kind: str = KIND_CHRONICLE) -> list[Hit]:
    """Akapity kroniki albo notatek (i punkty list) z trafieniem; z nagłówkiem sekcji, w której są."""
    hits, heading = [], None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        plain = " ".join(MARKDOWN_MARKS_RE.sub("", stripped).split())
        if stripped.startswith("#") or (stripped.startswith("**") and stripped.endswith("**")):
            heading = chronicle_title(plain) or plain
        if matches_stems(words(stripped), stems):
            hits.append(Hit(session_name, kind, _shorten(plain), heading=heading))
    return hits


def search_transcript(session_name: str, transcript: Transcript, mapping: dict[str, str],
                      stems: list[tuple[str, ...]]) -> list[Hit]:
    """Trafienia w oknach do WINDOW kolejnych wypowiedzi; nakładające się okna liczą się raz."""
    segments = [s for s in transcript.segments if s.text.strip()]
    seg_words = [words(s.text) for s in segments]
    hits, next_free = [], 0
    for i in range(len(segments)):
        if i < next_free or not any(word_matches(w, alts) for w in seg_words[i] for alts in stems):
            continue  # okno zaczyna się od wypowiedzi, która sama zawiera któreś z szukanych słów
        for size in range(1, WINDOW + 1):
            window_words = [w for ws in seg_words[i:i + size] for w in ws]
            if matches_stems(window_words, stems):
                window = segments[i:i + size]
                speaker = window[0].speaker
                hits.append(Hit(session_name, KIND_TRANSCRIPT,
                                _shorten(" ".join(s.text.strip() for s in window)),
                                start=window[0].start, end=window[-1].end,
                                speaker=mapping.get(speaker, speaker) if speaker else None))
                next_free = i + size
                break
            if i + size >= len(segments):
                break
    return hits


def _order(session_name: str) -> tuple:
    return (session_date(session_name) or datetime.date.max, session_name)


def search(sessions, query: str, campaign: str | None = None, chronicles: bool = True,
           transcripts: bool = True, cache: TranscriptCache | None = None) -> list[Hit]:
    """Wszystkie trafienia (od najstarszej sesji; w sesji: najpierw kronika, potem transkrypcja wg czasu).

    `transcripts` obejmuje też notatki sesji bez nagrania.
    """
    stems = query_stems(query)
    if not stems:
        return []
    cache = cache or TranscriptCache()
    hits: list[Hit] = []
    for session in sorted(sessions, key=lambda s: _order(s.name)):
        if campaign and campaign_key(session.name) != campaign:
            continue
        if chronicles and session.has_summary:
            try:
                with open(session.summary_path, encoding="utf-8") as f:
                    hits += search_chronicle(session.name, f.read(), stems)
            except OSError:
                pass
        if transcripts and session.has_transcript:
            transcript = cache.get(session)
            if transcript is not None:
                hits += search_transcript(session.name, transcript, load_speaker_mapping(session.txt_path), stems)
        elif transcripts and session.has_notes:
            try:
                with open(session.notes_path, encoding="utf-8") as f:
                    hits += search_chronicle(session.name, f.read(), stems, KIND_NOTES)
            except OSError:
                pass
    return hits


def summary_line(hits: list[Hit]) -> str:
    """„12 trafień w 3 sesjach, pierwsze: Warhammer_260924”."""
    if not hits:
        return "Brak trafień."
    sessions = list(dict.fromkeys(h.session for h in hits))
    word = "trafienie" if len(hits) == 1 else ("trafienia" if 2 <= len(hits) % 10 <= 4
                                              and not 12 <= len(hits) % 100 <= 14 else "trafień")
    where = "sesjach" if len(sessions) > 1 else "sesji"
    return f"{len(hits)} {word} w {len(sessions)} {where}, pierwsze: {sessions[0]}"
