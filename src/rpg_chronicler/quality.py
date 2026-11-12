"""Kontrola jakości transkrypcji: podejrzanie mało tekstu, długie dziury, pętle Whispera, duplikaty sesji.

Progi dobrane na nazwanych sesjach użytkownika (2026-11): zwykle 82–107 słów na minutę nagrania,
najdłuższa przerwa ≤ 3 min, a powtórzenia tego samego zdania (≥ 3 słowa) pod rząd ≤ 7. Pętla Whispera
(np. „To jest to” co równe 2 s przez kilka minut ciszy) daje 8+ powtórzeń. Tylko stdlib (używane też przez GUI).
"""
import hashlib
import re
from dataclasses import dataclass

from .transcript import Transcript

MIN_WORDS_PER_MINUTE = 40      # poniżej - prawdopodobnie zgubiony tekst albo złe nagranie
MAX_GAP = 5 * 60               # sekundy bez żadnej wypowiedzi
LOOP_MIN_REPEATS = 8           # tyle samych zdań pod rząd = pętla Whispera
LOOP_MIN_WORDS = 3             # krótkie „nie, nie” czy „tak” powtarzają się naturalnie
SHORT_RECORDING = 30 * 60      # sesja RPG krótsza niż pół godziny - czy nagranie jest całe?
MISSING_END = 5 * 60           # transkrypcja kończy się tyle przed końcem nagrania


@dataclass(frozen=True)
class Issue:
    kind: str           # krotkie_nagranie | malo_tekstu | dziura | petla | brak_konca | pusta | duplikat
    message: str
    at: float | None = None   # sekunda nagrania, której dotyczy (do odsłuchu / podglądu)


def format_time(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def _normalized(text: str) -> str:
    return re.sub(r"[^\w ]+", "", text.lower()).strip()


def find_loops(transcript: Transcript) -> list[tuple[float, float, str, int]]:
    """Ciągi identycznych wypowiedzi: (początek, koniec, tekst, liczba powtórzeń)."""
    loops = []
    segments = transcript.segments
    i = 0
    while i < len(segments):
        text = _normalized(segments[i].text)
        j = i + 1
        while j < len(segments) and _normalized(segments[j].text) == text:
            j += 1
        if j - i >= LOOP_MIN_REPEATS and len(text.split()) >= LOOP_MIN_WORDS:
            loops.append((segments[i].start, segments[j - 1].end, segments[i].text.strip(), j - i))
        i = j
    return loops


def check(transcript: Transcript, audio_duration: float | None = None) -> list[Issue]:
    """Lista podejrzanych miejsc. `audio_duration` - długość nagrania, jeśli znana (inaczej z transkrypcji)."""
    segments = transcript.segments
    if not segments:
        return [Issue("pusta", "Transkrypcja jest pusta.")]

    issues = []
    last_end = segments[-1].end
    duration = audio_duration or transcript.duration or last_end

    if duration < SHORT_RECORDING:
        issues.append(Issue("krotkie_nagranie", f"Nagranie trwa tylko {format_time(duration)} - czy jest całe?"))

    if audio_duration and audio_duration - last_end > MISSING_END:
        issues.append(Issue("brak_konca", f"Transkrypcja kończy się na {format_time(last_end)}, "
                                          f"a nagranie trwa {format_time(audio_duration)}.", last_end))

    words = sum(len(s.text.split()) for s in segments)
    if duration >= 10 * 60:
        per_minute = words / (duration / 60)
        if per_minute < MIN_WORDS_PER_MINUTE:
            issues.append(Issue("malo_tekstu", f"Mało tekstu: {per_minute:.0f} słów na minutę nagrania "
                                               f"(zwykle 80–110)."))

    gaps = [(0.0, segments[0].start)] + [(a.end, b.start) for a, b in zip(segments, segments[1:])]
    for start, end in gaps:
        if end - start >= MAX_GAP:
            issues.append(Issue("dziura", f"Brak tekstu przez {format_time(end - start)} "
                                          f"({format_time(start)} – {format_time(end)}).", start))

    for start, end, text, count in find_loops(transcript):
        issues.append(Issue("petla", f"Powtórzone {count}× „{text}” ({format_time(start)} – {format_time(end)}) "
                                     "- prawdopodobnie zmyślone przez Whispera w ciszy.", start))
    return issues


def fingerprint(transcript: Transcript) -> str:
    """Skrót samego tekstu (bez mówców i czasów) - ta sama treść = kopia sesji."""
    digest = hashlib.sha1()
    for s in transcript.segments:
        digest.update(_normalized(s.text).encode("utf-8") + b"\n")
    return digest.hexdigest()


def find_duplicates(fingerprints: dict[str, str]) -> dict[str, list[str]]:
    """Sesja -> inne sesje z identyczną treścią transkrypcji."""
    groups: dict[str, list[str]] = {}
    for name, fp in fingerprints.items():
        groups.setdefault(fp, []).append(name)
    return {name: [other for other in names if other != name]
            for names in groups.values() if len(names) > 1 for name in names}


def _audio_duration(session) -> float | None:
    if not session.audio_path:
        return None
    from .audio_trim import TrimError, probe
    try:
        return probe(session.audio_path)[0]
    except (TrimError, OSError):
        return None


def check_sessions(sessions, probe_audio: bool = False) -> dict[str, list[Issue]]:
    """Kontrola wielu sesji naraz (łącznie z wykrywaniem kopii). Pomija sesje bez transkrypcji.

    `probe_audio` - odczytaj długość nagrań ffprobe'em (wykrywa transkrypcję urwaną przed końcem nagrania).
    """
    results: dict[str, list[Issue]] = {}
    fingerprints: dict[str, str] = {}
    for session in sessions:
        if not session.has_transcript:
            continue
        try:
            transcript = session.load_transcript()
        except (OSError, ValueError) as e:
            results[session.name] = [Issue("pusta", f"Nie można wczytać transkrypcji: {e}")]
            continue
        results[session.name] = check(transcript, _audio_duration(session) if probe_audio else None)
        if transcript.segments:
            fingerprints[session.name] = fingerprint(transcript)
    for name, others in find_duplicates(fingerprints).items():
        results[name].append(Issue("duplikat", f"Ta sama treść co: {', '.join(others)} - jedna z sesji jest "
                                               "zbędna (rpg-chronicler archive SESJA)."))
    return results
