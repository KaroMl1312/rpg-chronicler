"""Dziennik postaci: wydarzenia kolejnych sesji kampanii z perspektywy jednej postaci (wpisy pisze AI).

Jeden wpis na sesję z kroniką, w której postać była (mówiła na sesji wg mapowania mówców albo pojawia się
w kronice - także skrótem imienia, „Fen” dla „Fen Wanderer”). Wpis powstaje z kroniki i listy wydarzeń
sesji (jeśli jest - więcej szczegółów), z cytatami postaci i poprzednim wpisem (ten sam głos i rodzaj
gramatyczny). Wpisy są w cache (~/.cache/rpg-chronicler/dziennik/), dopóki nie zmieni się prompt, więc
odświeżenie dziennika po nowej sesji pyta AI tylko o nowy wpis.
Wynik: SUMMARY_DIR/dziennik-<kampania>-<postać>.md i .pdf (trafiają na Drive, można je dać graczowi).
Moduł bez zależności zewnętrznych (GUI sprawdza ścieżki); LLM i PDF tylko w funkcjach z klientem.
"""
import datetime
import hashlib
import os
import re
from pathlib import Path

from . import session as _session
from .campaigns import Campaign, campaign_key, session_date
from .chronicle import chronicle_title, read_quotes
from .prompts import chronicle_blocks, render
from .textmatch import contains_name
from .transcript import load_speaker_mapping

EVENTS_LIMIT = 40_000   # znaków listy wydarzeń w zapytaniu (dłuższa jest ucinana)
# Słowa, które w imieniu postaci nie są jej skrótem („Sir Amos” → „Amos”, ale nie „Sir”)
TITLE_WORDS = {"sir", "pan", "pani", "lord", "lady", "brat", "siostra", "ojciec", "matka", "mistrz",
               "von", "van", "der", "de", "del", "di", "la", "le"}
ABSENT = "BRAK"


class DiaryError(Exception):
    pass


def _slug(name: str) -> str:
    return re.sub(r"[^\w-]+", "_", name.strip()).strip("_") or "postac"


def markdown_path(key: str, character: str) -> str:
    return os.path.join(_session.SUMMARY_DIR, f"dziennik-{key}-{_slug(character)}.md")


def pdf_path(key: str, character: str) -> str:
    return os.path.join(_session.SUMMARY_DIR, f"dziennik-{key}-{_slug(character)}.pdf")


def aliases(character: str) -> list[str]:
    """Imię i jego skróty: „Fen Wanderer” → [„Fen Wanderer”, „Fen”, „Wanderer”] (kroniki i mówcy używają skrótów)."""
    words = character.split()
    short = [w for w in words if len(w) >= 3 and w.casefold() not in TITLE_WORDS] if len(words) > 1 else []
    return [character, *short]


def _is_alias(name: str, character: str) -> bool:
    return name.strip().casefold() in {a.casefold() for a in aliases(character)}


def canonical_character(campaign: Campaign, name: str) -> str:
    """Pisownia postaci z kampanii („fen” albo „Fen” → „Fen Wanderer”); inne imiona (np. BN-ów) bez zmian."""
    for known in campaign.player_characters:
        if known.casefold() == name.strip().casefold():
            return known
    for known in campaign.player_characters:
        if _is_alias(name, known):
            return known
    return name.strip()


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def was_present(session, campaign: Campaign, character: str, chronicle: str) -> bool:
    """Postać (albo skrót jej imienia) jest w kronice albo mówiła na sesji (mapowanie mówców, gracz → postać)."""
    if any(contains_name(chronicle, name) for name in aliases(character)):
        return True
    if not session.has_transcript:
        return False
    from .voices import NameResolver
    resolver = NameResolver(campaign)
    return any(_is_alias(resolver.resolve(n), character)
               for n in load_speaker_mapping(session.txt_path).values() if n.strip())


def diary_sessions(campaign: Campaign, character: str, sessions) -> list:
    """[(sesja, kronika)] kampanii, w których była postać, od najstarszej."""
    selected = [s for s in sessions if campaign_key(s.name) == campaign.key and s.has_summary]
    selected.sort(key=lambda s: (session_date(s.name) or datetime.date.max, s.name))
    result = []
    for s in selected:
        chronicle = _read(s.summary_path)
        if chronicle and was_present(s, campaign, character, chronicle):
            result.append((s, chronicle))
    return result


def entry_prompt(session, campaign: Campaign, character: str, chronicle: str,
                 previous: str = "") -> tuple[str, str]:
    """(prefiks, prompt): kronika i lista wydarzeń sesji (wspólne dla dzienników różnych postaci) + polecenie.

    `previous` - poprzedni wpis: wzór głosu i rodzaju gramatycznego (inaczej wpisy pisane osobno się rozjeżdżają).
    """
    prefix = chronicle_blocks([(session.name, chronicle)])
    # jak chronicle_events.events_path (bez importu - tamten moduł ciągnie klienta LLM, a GUI używa tego)
    events = _read(os.path.join(_session.SUMMARY_DIR, f"{session.name}_wydarzenia.md")).strip()
    if events:
        prefix += f"<wydarzenia sesja=\"{session.name}\">\n{events[:EVENTS_LIMIT]}\n</wydarzenia>\n\n"
    info = campaign.prompt_info()
    quotes = [q for q in read_quotes(session) if _is_alias(q.who, character)]
    own = "".join(f"- „{q.text}”\n" for q in quotes)
    short = aliases(character)[1:]
    prompt = render("diary", system_name=campaign.system, character=character,
                    also_known=f" (w materiale także: {', '.join(short)})" if short else "",
                    campaign_info=f"\nInformacje o kampanii:\n{info}\n" if info else "",
                    own_quotes=f"\nSłowa postaci {character} z tej sesji (możesz je przywołać):\n{own}" if own else "",
                    previous_entry=_previous_block(previous))
    return prefix, prompt


def _previous_block(previous: str) -> str:
    if not previous.strip():
        return ""
    return ("\nPoprzedni wpis w tym dzienniku - pisz dalej tym samym głosem, w tym samym rodzaju gramatycznym "
            f"i tonie, ale go nie powtarzaj:\n<poprzedni_wpis>\n{previous.strip()}\n</poprzedni_wpis>\n")


def _cache_path(key: str, text: str) -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]
    return Path(cache_home) / "rpg-chronicler" / "dziennik" / key / f"{digest}.md"


def write_entry(get_client, session, campaign: Campaign, character: str, chronicle: str, force: bool = False,
                previous: str = "") -> str:
    """Wpis dziennika o sesji (z cache, chyba że `force`). Pusty tekst = postaci nie było. Rzuca LLMError.

    `get_client()` daje klienta LLM - wołane dopiero, gdy wpisu nie ma w cache.
    """
    from .llm import generate, with_retry  # import tutaj: GUI importuje ten moduł bez SDK LLM

    prefix, prompt = entry_prompt(session, campaign, character, chronicle, previous)
    cache = _cache_path(campaign.key, prefix + prompt)
    if not force:
        try:
            return cache.read_text(encoding="utf-8")
        except OSError:
            pass
    llm = get_client()
    print(f"[{llm.name}] Dziennik postaci {character}: wpis o sesji {session.name}...")
    text = with_retry(lambda: generate(llm, prompt, prefix), f"dziennik {character} {session.name}").strip()
    if re.fullmatch(rf"\W*{ABSENT}\W*", text):
        text = ""
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(text, encoding="utf-8")
    return text


def _date_text(name: str) -> str:
    date = session_date(name)
    return date.strftime("%d.%m.%Y") if date else name


def render_markdown(campaign: Campaign, character: str, entries: list[tuple[str, str, str]]) -> str:
    """entries: [(sesja, tytuł kroniki, wpis)] od najstarszej."""
    from .encyclopedia import short_title

    today = datetime.date.today().strftime("%d.%m.%Y")
    header = campaign.system if campaign.system == campaign.key else f"{campaign.system} · kampania {campaign.key}"
    lines = [f"# Dziennik: {character}", "",
             f"*{header} · wpisy: {len(entries)} · stan na {today}*", ""]
    for name, title, text in entries:
        lines += [f"## {_date_text(name)} — {short_title(title)}", "", text.strip(), ""]
    return "\n".join(lines).rstrip() + "\n"


def build(get_client, campaign: Campaign, character: str, sessions, force: bool = False, progress=None) -> str:
    """Markdown dziennika postaci. `get_client()` - klient LLM; `progress(zrobione, razem)` - postęp."""
    selected = diary_sessions(campaign, character, sessions)
    if not selected:
        raise DiaryError(f"Postać {character} nie pojawia się w kronikach kampanii {campaign.key}.")
    entries = []
    for index, (session, chronicle) in enumerate(selected):
        if progress is not None:
            progress(index, len(selected))
        previous = entries[-1][2] if entries else ""
        text = write_entry(get_client, session, campaign, character, chronicle, force, previous)
        if text:
            entries.append((session.name, chronicle_title(chronicle, session.name), text))
    if not entries:
        raise DiaryError(f"AI nie znalazło postaci {character} w żadnej sesji kampanii {campaign.key}.")
    return render_markdown(campaign, character, entries)
