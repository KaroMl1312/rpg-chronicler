"""Sesje bez nagrania: kronika z notatek Mistrza Gry (`add-session`, przycisk „Dodaj sesję z notatek…” w GUI).

Notatki leżą w TXT_DIR jako `<nazwa>.notatki.md` (synchronizują się z Drive jak transkrypcje) i dla takiej
sesji zastępują transkrypcję: z nich powstaje kronika, poprawka kroniki i trafienia wyszukiwarki.
Nie ma nagrania, mówców, cytatów ani statystyk. Pierwsza linia pliku to opcjonalna lista obecnych postaci
(`<!-- obecni: Fen Wanderer, Sir Amos -->`) - zastępuje mapowanie mówców (dziennik postaci, kronika).
Kronika jest nieaktualna, gdy notatki są od niej nowsze. Tylko stdlib (GUI).
"""
import datetime
import os
import re
from dataclasses import dataclass

from . import session as _session
from .campaigns import session_date
from .session import NOTES_SUFFIX  # noqa: F401 (do importu z tego modułu)

ANNOTATION = "spisana z notatek Mistrza Gry"   # stopka Discorda, nagłówek PDF
PRESENT_RE = re.compile(r"\A<!--\s*obecni:(?P<names>.*?)-->[ \t]*\n?")
NAME_RE = re.compile(r"^[^\W_](?:[^\W_]|-)*$")       # klucz kampanii: bez spacji i „_” (ten oddziela datę)


class NotesError(Exception):
    pass


@dataclass(frozen=True)
class Notes:
    text: str
    present: tuple[str, ...] = ()


def notes_path(name: str) -> str:
    return _session.Session(name).notes_path


def parse(content: str) -> Notes:
    content = content.replace("\r\n", "\n")
    match = PRESENT_RE.match(content)
    present: tuple[str, ...] = ()
    if match:
        present = tuple(n.strip() for n in match["names"].split(",") if n.strip())
        content = content[match.end():]
    return Notes(content.strip(), present)


def format_notes(notes: Notes) -> str:
    header = f"<!-- obecni: {', '.join(notes.present)} -->\n\n" if notes.present else ""
    return header + notes.text.strip() + "\n"


def read_notes(session) -> Notes | None:
    try:
        with open(session.notes_path, encoding="utf-8") as f:
            return parse(f.read())
    except OSError:
        return None


def save_notes(name: str, notes: Notes) -> str:
    """Zapis atomowy (plik .part + os.replace); zwraca ścieżkę."""
    if not notes.text.strip():
        raise NotesError("Notatki są puste.")
    path = notes_path(name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(format_notes(notes))
    os.replace(tmp, path)
    return path


def session_name(campaign: str, date: datetime.date) -> str:
    """Nazwa sesji jak nagrań: `Kampania_RRMMDD`."""
    campaign = campaign.strip()
    if not NAME_RE.match(campaign):
        raise NotesError(f"Nazwa kampanii „{campaign}” nie może być pusta ani zawierać spacji i znaku „_”.")
    return f"{campaign}_{date:%y%m%d}"


def check_new_name(name: str) -> None:
    """Rzuca NotesError, gdy nazwa nie ma daty albo sesja o tej nazwie już istnieje (nagranie, transkrypcja…)."""
    if "_" not in name or session_date(name) is None:
        raise NotesError(f"Nazwa {name} nie ma daty sesji (Kampania_RRMMDD albo Kampania_DD_MM_RRRR).")
    existing = {s.name for s in _session.list_sessions()}
    if name in existing:
        raise NotesError(f"Sesja {name} już istnieje - wybierz inną datę albo edytuj jej notatki.")


def chronicle_is_stale(session) -> bool:
    """Notatki zmieniono po napisaniu kroniki - warto ją wygenerować ponownie."""
    try:
        return os.path.getmtime(session.notes_path) > os.path.getmtime(session.summary_path)
    except OSError:
        return False


def for_llm(notes: Notes) -> str:
    """Notatki do promptu kroniki (z listą obecnych postaci)."""
    present = f"Obecne postacie graczy: {', '.join(notes.present)}\n\n" if notes.present else ""
    return f"<notatki_mg>\n{present}{notes.text.strip()}\n</notatki_mg>"
