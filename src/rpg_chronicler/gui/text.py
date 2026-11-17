"""Logika GUI niezależna od GTK (formatowanie, stan sesji) - testowana zwykłym pytestem."""
import os
import re

from ..campaigns import campaign_key
from ..chronicle import sent_path
from ..notes import chronicle_is_stale
from ..session import Session
from ..transcript import Transcript

SPEAKER_LABEL_RE = re.compile(r"SPEAKER_\d+")


def format_timestamp(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def format_minutes(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60:02d} min"


def has_speaker_labels(session: Session) -> bool:
    """Czy transkrypcja ma etykiety SPEAKER_XX (szybko, bez parsowania całego pliku)."""
    path = session.json_path if session.has_json else session.txt_path
    try:
        with open(path, encoding="utf-8") as f:
            return SPEAKER_LABEL_RE.search(f.read()) is not None
    except OSError:
        return False


def session_stage(session: Session) -> tuple[str, bool]:
    """(opis następnego kroku, czy sesja jest ukończona)."""
    if not session.has_transcript and session.has_notes:   # sesja bez nagrania - kronika z notatek MG
        if not session.has_summary:
            return "z notatek · czeka na kronikę", False
        if chronicle_is_stale(session):
            return "z notatek · notatki nowsze niż kronika", False
        return "z notatek · gotowe", True
    if not session.has_transcript:
        return ("czeka na transkrypcję", False) if session.audio_path else ("brak nagrania", False)
    if not session.has_speakers and has_speaker_labels(session):
        return "mówcy bez imion", False
    if not session.has_summary:
        return "czeka na kronikę", False
    return "gotowe", True


ALL_CAMPAIGNS = None   # filtr listy sesji: wszystkie kampanie
NO_CAMPAIGN = ""       # sesje bez „_” w nazwie


def session_campaign(session: Session) -> str:
    """Klucz kampanii do filtra listy sesji (NO_CAMPAIGN, gdy nazwa nie ma prefiksu)."""
    return campaign_key(session.name) or NO_CAMPAIGN


def campaign_filter_options(sessions: list[Session]) -> list[tuple[str | None, str]]:
    """[(klucz, etykieta)] do filtra: „Wszystkie”, potem kampanie alfabetycznie, na końcu bez kampanii."""
    counts: dict[str, int] = {}
    for s in sessions:
        counts[session_campaign(s)] = counts.get(session_campaign(s), 0) + 1
    keys = sorted((k for k in counts if k != NO_CAMPAIGN), key=str.casefold)
    if NO_CAMPAIGN in counts:
        keys.append(NO_CAMPAIGN)
    return [(ALL_CAMPAIGNS, f"Wszystkie ({len(sessions)})")] + [
        (k, f"{k or 'Bez kampanii'} ({counts[k]})") for k in keys]


def session_signature(session: Session) -> tuple:
    """Zmienia się, gdy zmieni się którykolwiek plik sesji - wtedy trzeba odświeżyć widok."""
    paths = (session.audio_path, session.json_path, session.txt_path, session.speakers_path,
             session.speaker_suggestion_path, session.summary_path, session.notes_path, sent_path(session))
    signature = []
    for path in paths:
        try:
            signature.append(os.path.getmtime(path) if path else None)
        except OSError:
            signature.append(None)
    return tuple(signature)


def transcript_blocks(transcript: Transcript, mapping: dict[str, str]) -> list[tuple[float, str | None, str]]:
    """Wypowiedzi do wyświetlenia: (czas startu, mówca lub None, tekst); kolejne segmenty mówcy sklejone."""
    blocks: list[tuple[float, str | None, str]] = []
    for s in transcript.segments:
        text = s.text.strip()
        if not text:
            continue
        speaker = mapping.get(s.speaker, s.speaker) if s.speaker else None
        if blocks and speaker is not None and blocks[-1][1] == speaker:
            start, _, previous = blocks[-1]
            blocks[-1] = (start, speaker, f"{previous} {text}")
        else:
            blocks.append((s.start, speaker, text))
    return blocks


MARKDOWN_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def markdown_spans(line: str) -> tuple[str, list[tuple[str, str | None]]]:
    """Bardzo prosty Markdown dla kroniki: zwraca (styl linii, [(tekst, styl fragmentu)]).

    Styl linii: "h1"/"h2"/"h3" dla nagłówków, "rule" dla linii poziomej (---), "" dla zwykłej linii;
    punkty listy (* / -) zamieniane na „•”; fragmenty: "bold" albo None.
    """
    style = ""
    if re.fullmatch(r"\s*([-*_])(\s*\1){2,}\s*", line):
        return "rule", []
    heading = re.match(r"^(#{1,3})\s+(.*)$", line)
    if heading:
        style, line = f"h{len(heading[1])}", heading[2]
    bullet = re.match(r"^(\s*)[*-]\s+(.*)$", line)
    if bullet:
        line = f"{bullet[1]}•  {bullet[2]}"
    spans: list[tuple[str, str | None]] = []
    position = 0
    for match in MARKDOWN_BOLD_RE.finditer(line):
        if match.start() > position:
            spans.append((line[position:match.start()], None))
        spans.append((match[1], "bold"))
        position = match.end()
    if position < len(line):
        spans.append((line[position:], None))
    return style, spans


def estimate_remaining(elapsed: float, fraction: float) -> float | None:
    """Szacowany pozostały czas na podstawie dotychczasowego tempa."""
    if fraction <= 0.02 or elapsed < 20:
        return None
    return elapsed * (1 - fraction) / fraction


# --- propozycje AI (słownik, stan kampanii) ---

def proposals_snapshot() -> dict[str, dict]:
    """Stan oczekujących propozycji: liczba nazw do słownika i czas zmiany propozycji stanu, per kampania."""
    from ..campaign_tools import glossary, memory
    glossary_counts = {path.stem: glossary.count_proposals(glossary.load_proposals(path.stem))
                       for path in glossary.proposals_dir().glob("*.json")}
    try:
        memory_times = {path.stem: path.stat().st_mtime for path in memory.proposals_dir().glob("*.json")}
    except OSError:
        memory_times = {}
    return {"slownik": glossary_counts, "stan": memory_times}


def new_proposals(before: dict[str, dict], after: dict[str, dict]) -> list[tuple[str, str]]:
    """Co przybyło w czasie zadania: [(kampania, komunikat)]. Nowa kronika aktualizuje tę samą propozycję
    stanu, więc liczy się zmiana czasu pliku, a w słowniku - wzrost liczby nazw."""
    messages = []
    for key, mtime in after.get("stan", {}).items():
        if mtime != before.get("stan", {}).get(key):
            messages.append((key, f"Nowy stan kampanii {key} do przejrzenia"))
    for key, count in after.get("slownik", {}).items():
        if count > before.get("slownik", {}).get(key, 0):
            messages.append((key, f"Nowe propozycje do słownika kampanii {key}: {count}"))
    return messages


# --- wyszukiwarka ---

def highlight_markup(text: str, query: str) -> str:
    """Tekst jako Pango markup z pogrubionymi słowami pasującymi do zapytania (w dowolnej odmianie)."""
    from html import escape

    from ..textmatch import WORD_RE, query_stems, word_matches

    stems = query_stems(query)
    parts, last = [], 0
    for match in WORD_RE.finditer(text):
        if any(word_matches(match[0].lower(), alts) for alts in stems):
            parts += [escape(text[last:match.start()]), f"<b>{escape(match[0])}</b>"]
            last = match.end()
    parts.append(escape(text[last:]))
    return "".join(parts)
