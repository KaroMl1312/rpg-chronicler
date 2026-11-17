"""Kronika sesji do udostępnienia graczom: tytuł, zapowiedź, PDF i stan wysyłki na Discord.

Pliki leżą obok kroniki w SUMMARY_DIR (synchronizują się z Drive):
  <sesja>_skrot.txt      - skrót kroniki: najważniejsze wydarzenia w jednym akapicie (AI)
  <sesja>_cytaty.txt     - najlepsze cytaty z sesji, po jednym w linii: [0:05:34–0:05:41] „cytat” — Postać
                           (AI, można poprawiać; czas = fragment nagrania do odsłuchu, opcjonalny)
  <sesja>_zapowiedz.txt  - 2-3 zdania zapowiedzi (AI albo wpisane ręcznie)
  <sesja>_kronika.pdf    - kronika w PDF (chronicle_pdf.py)
  <sesja>_discord.json   - kiedy i dokąd wysłano
Tylko biblioteka standardowa (używa tego też GUI).
"""
import datetime
import json
import math
import os
import re
from dataclasses import dataclass

from . import settings
from .campaigns import session_date
from .session import Session

MARKDOWN_MARKS_RE = re.compile(r"[*_`#]+")


def brief_path(session: Session) -> str:
    return session.summary_path.replace("_podsumowanie.txt", "_skrot.txt")


def read_brief(session: Session) -> str:
    try:
        with open(brief_path(session), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def brief_is_current(session: Session) -> bool:
    """Skrót istnieje i jest nowszy niż kronika (po ponownym wygenerowaniu kroniki trzeba go odświeżyć)."""
    try:
        return os.path.getmtime(brief_path(session)) >= os.path.getmtime(session.summary_path)
    except OSError:
        return False


# --- cytaty z sesji ---

# „[0:05:34–0:05:41] „cytat” — Postać” (czas opcjonalny: bez niego cytat działa, tylko bez odsłuchu)
QUOTE_RE = re.compile(r"^\s*[-*]?\s*(?:\[(?P<start>[\d:.]+)(?:\s*[–-]\s*(?P<end>[\d:.]+))?\]\s*)?"
                      r"[„\"”](?P<text>.+?)[”\"“]\s*(?:[—–-]+\s*(?P<who>.+?))?\s*$")


@dataclass(frozen=True)
class Quote:
    text: str
    who: str = ""
    start: float | None = None   # sekunda nagrania, w której padł cytat
    end: float | None = None     # koniec wypowiedzi (do odsłuchu)


def _parse_time(text: str | None) -> float | None:
    if not text:
        return None
    seconds = 0.0
    try:
        for part in text.split(":"):
            seconds = seconds * 60 + float(part)
    except ValueError:
        return None
    return seconds


def _format_time(seconds: float, round_up: bool = False) -> str:
    seconds = math.ceil(seconds) if round_up else int(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def quotes_path(session: Session) -> str:
    return session.summary_path.replace("_podsumowanie.txt", "_cytaty.txt")


def parse_quotes(content: str) -> list[Quote]:
    """Linie „[czas] „cytat” — Postać” → cytaty; linie w innym formacie są pomijane."""
    quotes = []
    for line in content.splitlines():
        match = QUOTE_RE.match(line)
        if match and match["text"].strip():
            quotes.append(Quote(match["text"].strip(), (match["who"] or "").strip(),
                                _parse_time(match["start"]), _parse_time(match["end"])))
    return quotes


def format_quote_time(quote: Quote) -> str:
    if quote.start is None:
        return ""
    # koniec w górę - odsłuch nie urywa końcówki wypowiedzi
    return _format_time(quote.start) + (f"–{_format_time(quote.end, round_up=True)}" if quote.end is not None else "")


def format_quotes(quotes: list[Quote]) -> str:
    lines = []
    for q in quotes:
        time = format_quote_time(q)
        lines.append((f"[{time}] " if time else "") + f"„{q.text}”" + (f" — {q.who}" if q.who else ""))
    return "".join(line + "\n" for line in lines)


def read_quotes(session: Session) -> list[Quote]:
    try:
        with open(quotes_path(session), encoding="utf-8") as f:
            return parse_quotes(f.read())
    except OSError:
        return []


def save_quotes(session: Session, quotes: list[Quote]) -> None:
    with open(quotes_path(session), "w", encoding="utf-8") as f:
        f.write(format_quotes(quotes))


def teaser_path(session: Session) -> str:
    return session.summary_path.replace("_podsumowanie.txt", "_zapowiedz.txt")


def pdf_path(session: Session) -> str:
    return session.summary_path.replace("_podsumowanie.txt", "_kronika.pdf")


def sent_path(session: Session) -> str:
    return session.summary_path.replace("_podsumowanie.txt", "_discord.json")


def read_chronicle(session: Session) -> str:
    with open(session.summary_path, encoding="utf-8") as f:
        return f.read()


# --- poprzednie wersje kroniki (poprawki poleceniem: `revise`, przycisk „Popraw…”) ---

def versions_dir(session: Session) -> str:
    """Poprzednie wersje kroniki - lokalnie w cache (nie na Drive), do cofnięcia poprawki."""
    cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(cache_home, "rpg-chronicler", "kroniki-poprzednie", session.name)


def previous_versions(session: Session) -> list[str]:
    """Ścieżki poprzednich wersji, od najnowszej."""
    try:
        names = sorted((n for n in os.listdir(versions_dir(session)) if n.endswith(".txt")), reverse=True)
    except OSError:
        return []
    return [os.path.join(versions_dir(session), n) for n in names]


def save_version(session: Session) -> str:
    """Kopia obecnej kroniki przed poprawką; zwraca jej ścieżkę."""
    os.makedirs(versions_dir(session), exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = os.path.join(versions_dir(session), f"{stamp}.txt")
    with open(path, "w", encoding="utf-8") as f:
        f.write(read_chronicle(session))
    return path


def write_chronicle(session: Session, text: str) -> None:
    tmp = session.summary_path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, session.summary_path)


def restore_previous(session: Session) -> str | None:
    """Przywraca ostatnią poprzednią wersję (i usuwa ją z listy); None, gdy nie ma czego cofać."""
    versions = previous_versions(session)
    if not versions:
        return None
    with open(versions[0], encoding="utf-8") as f:
        write_chronicle(session, f.read())
    os.unlink(versions[0])
    return versions[0]


def chronicle_title(text: str, fallback: str = "Kronika sesji") -> str:
    """Tytuł z pierwszej niepustej linii kroniki (bez znaczników Markdown), np. „📜 Kronika Sesji [X]: …”."""
    for line in text.splitlines():
        line = MARKDOWN_MARKS_RE.sub("", line).strip()
        if line and not re.fullmatch(r"[-=_ ]+", line):
            return line[:250]
    return fallback


def session_date_text(session: Session) -> str:
    date = session_date(session.name)
    if date is None:
        return ""
    months = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca", "lipca", "sierpnia", "września",
              "października", "listopada", "grudnia"]
    return f"{date.day} {months[date.month - 1]} {date.year}"


def read_teaser(session: Session) -> str:
    try:
        with open(teaser_path(session), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def save_teaser(session: Session, text: str) -> None:
    with open(teaser_path(session), "w", encoding="utf-8") as f:
        f.write(text.strip() + "\n")


def pdf_is_current(session: Session) -> bool:
    """PDF istnieje i jest nowszy niż kronika, jej skrót i cytaty (są w PDF: „W skrócie”, „Cytaty sesji”)."""
    try:
        pdf_time = os.path.getmtime(pdf_path(session))
        if pdf_time < os.path.getmtime(session.summary_path):
            return False
        return all(not os.path.exists(path) or pdf_time >= os.path.getmtime(path)
                   for path in (brief_path(session), quotes_path(session)))
    except OSError:
        return False


# --- Discord ---

def webhook_for(campaign_key: str) -> str:
    """Adres webhooka kampanii (z lokalnych ustawień, nie z Drive)."""
    return settings.load().get(f"discord.{campaign_key}", "") if campaign_key else ""


def set_webhook(campaign_key: str, url: str | None) -> None:
    settings.update({f"discord.{campaign_key}": url or None})


def load_sent(session: Session) -> dict:
    try:
        with open(sent_path(session), encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_sent(session: Session, message_id: str | None) -> None:
    data = {"wyslano": datetime.datetime.now().isoformat(timespec="seconds"), "wiadomosc": message_id}
    with open(sent_path(session), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


NOT_SENT, SENT, SENT_OLDER = "", "wyslano", "zmieniona-po-wyslaniu"


def mark_sent(session: Session) -> None:
    """Ręczne oznaczenie „jest na Discordzie” (np. kronika wysłana, zanim aplikacja zapisywała wysyłki)."""
    data = {"wyslano": datetime.datetime.now().isoformat(timespec="seconds"), "wiadomosc": None, "recznie": True}
    with open(sent_path(session), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def unmark_sent(session: Session) -> None:
    try:
        os.remove(sent_path(session))
    except FileNotFoundError:
        pass


def discord_state(session: Session) -> str:
    """NOT_SENT, SENT albo SENT_OLDER (kronikę poprawiono albo napisano od nowa po wysłaniu)."""
    try:
        when = datetime.datetime.fromisoformat(load_sent(session).get("wyslano"))
    except (TypeError, ValueError):
        return NOT_SENT
    try:
        changed = os.path.getmtime(session.summary_path) > when.timestamp() + 1
    except OSError:
        changed = False
    return SENT_OLDER if changed else SENT


def discord_label(session: Session) -> str:
    """Krótki opis stanu wysyłki do listy sesji i zakładki Kronika (pusty, gdy nie wysłano)."""
    state = discord_state(session)
    if state == NOT_SENT:
        return ""
    manual = " (oznaczone ręcznie)" if load_sent(session).get("recznie") else ""
    if state == SENT_OLDER:
        return f"na Discordzie starsza wersja ({sent_text(session)}){manual}"
    return f"wysłano na Discord {sent_text(session)}{manual}"


def sent_text(session: Session) -> str:
    """„12.11.2026 o 10:05” albo pusty tekst, gdy kroniki nie wysłano."""
    sent = load_sent(session).get("wyslano")
    try:
        when = datetime.datetime.fromisoformat(sent)
    except (TypeError, ValueError):
        return ""
    return f"{when:%d.%m.%Y} o {when:%H:%M}"
