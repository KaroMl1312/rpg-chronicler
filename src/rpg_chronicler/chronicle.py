"""Kronika sesji do udostępnienia graczom: tytuł, zapowiedź, PDF i stan wysyłki na Discord.

Pliki leżą obok kroniki w SUMMARY_DIR (synchronizują się z Drive):
  <sesja>_skrot.txt      - skrót kroniki: najważniejsze wydarzenia w jednym akapicie (AI)
  <sesja>_zapowiedz.txt  - 2-3 zdania zapowiedzi (AI albo wpisane ręcznie)
  <sesja>_kronika.pdf    - kronika w PDF (chronicle_pdf.py)
  <sesja>_discord.json   - kiedy i dokąd wysłano
Tylko biblioteka standardowa (używa tego też GUI).
"""
import datetime
import json
import os
import re

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
    """PDF istnieje i jest nowszy niż kronika i jej skrót (skrót jest w PDF jako „W skrócie”)."""
    try:
        pdf_time = os.path.getmtime(pdf_path(session))
        if pdf_time < os.path.getmtime(session.summary_path):
            return False
        return not os.path.exists(brief_path(session)) or pdf_time >= os.path.getmtime(brief_path(session))
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


def sent_text(session: Session) -> str:
    """„12.11.2026 o 10:05” albo pusty tekst, gdy kroniki nie wysłano."""
    sent = load_sent(session).get("wyslano")
    try:
        when = datetime.datetime.fromisoformat(sent)
    except (TypeError, ValueError):
        return ""
    return f"{when:%d.%m.%Y} o {when:%H:%M}"
