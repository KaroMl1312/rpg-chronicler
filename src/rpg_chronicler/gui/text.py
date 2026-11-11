"""Logika GUI niezależna od GTK (formatowanie, stan sesji) - testowana zwykłym pytestem."""
import os
import re

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
    if not session.has_transcript:
        return ("czeka na transkrypcję", False) if session.audio_path else ("brak nagrania", False)
    if not session.has_speakers and has_speaker_labels(session):
        return "mówcy bez imion", False
    if not session.has_summary:
        return "czeka na kronikę", False
    return "gotowe", True


def session_signature(session: Session) -> tuple:
    """Zmienia się, gdy zmieni się którykolwiek plik sesji - wtedy trzeba odświeżyć widok."""
    paths = (session.audio_path, session.json_path, session.txt_path, session.speakers_path,
             session.speaker_suggestion_path, session.summary_path)
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
