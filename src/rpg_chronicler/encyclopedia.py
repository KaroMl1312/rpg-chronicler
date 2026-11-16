"""Encyklopedia kampanii: oś czasu sesji, stan kampanii i hasła (postacie, miejsca, przedmioty) z kronik.

Wynik to SUMMARY_DIR/encyklopedia-<kampania>.md i .pdf (synchronizują się z Drive, można je dać graczom).
Hasła: słownik kampanii + to, co AI znajdzie w kronikach (jedno zapytanie na kampanię, odpowiedź
zapamiętana w cache, dopóki nie zmienią się kroniki ani słownik). W których sesjach występuje hasło,
liczy kod (textmatch), nie AI. Bez AI (`--no-ai`) encyklopedia ma tylko hasła ze słownika, bez opisów.
Moduł bez zależności zewnętrznych (GUI sprawdza ścieżki); PDF tworzy chronicle_pdf (.venv).
"""
import datetime
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import session as _session
from .campaigns import GLOSSARY_CATEGORIES, Campaign, campaign_key, session_date
from .chronicle import brief_is_current, chronicle_title, read_brief
from .prompts import chronicle_blocks, render
from .textmatch import contains_name

PLAYER_CHARACTERS = "postacie_graczy"
CATEGORY_TITLES = {PLAYER_CHARACTERS: "Postacie graczy", **GLOSSARY_CATEGORIES}
CHRONICLES_LIMIT = 200_000   # znaków kronik w zapytaniu o hasła (przy limicie zostają najnowsze)


class EncyclopediaError(Exception):
    pass


@dataclass
class Entry:
    name: str
    category: str
    description: str = ""
    sessions: list[str] = field(default_factory=list)   # sesje (od najstarszej), w których kronikach jest
    ai_sessions: list[str] = field(default_factory=list)  # sesje wskazane przez AI (skróty, nieregularna odmiana)


def markdown_path(key: str) -> str:
    return os.path.join(_session.SUMMARY_DIR, f"encyklopedia-{key}.md")


def pdf_path(key: str) -> str:
    return os.path.join(_session.SUMMARY_DIR, f"encyklopedia-{key}.pdf")


# --- hasła ---

def glossary_entries(campaign: Campaign) -> list[Entry]:
    """Hasła ze słownika z opisami z kampanii (wpisane ręcznie albo przyjęte wcześniej mają pierwszeństwo przed AI)."""
    entries = [Entry(name, PLAYER_CHARACTERS, campaign.description(name)) for name in campaign.player_characters]
    for category in GLOSSARY_CATEGORIES:
        entries += [Entry(name, category, campaign.description(name)) for name in campaign.names(category)]
    return entries


def fill_descriptions(campaign: Campaign, from_ai: list[Entry]) -> tuple[Campaign, list[str]]:
    """Kampania z opisami od AI dla nazw ze słownika, które opisu nie mają (istniejących nie zmienia)."""
    by_name = {e.name.casefold(): e.description for e in from_ai if e.description}
    filled = []
    for name in campaign.all_names():
        if not campaign.description(name) and by_name.get(name.casefold()):
            campaign = campaign.with_description(name, by_name[name.casefold()])
            filled.append(name)
    return campaign, filled


def parse_entries(text: str) -> list[Entry]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise EncyclopediaError("Odpowiedź AI nie zawiera obiektu JSON.")
    try:
        data = json.loads(match[0])
    except json.JSONDecodeError as e:
        raise EncyclopediaError(f"Niepoprawny JSON w odpowiedzi AI: {e}") from e
    entries = []
    for item in data.get("hasla", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict) or not str(item.get("nazwa", "")).strip():
            continue
        category = str(item.get("kategoria", "")).strip()
        sessions = item.get("sesje", [])
        sessions = [str(s).strip() for s in sessions if str(s).strip()] if isinstance(sessions, list) else []
        entries.append(Entry(str(item["nazwa"]).strip(), category if category in CATEGORY_TITLES else "inne",
                             str(item.get("opis", "")).strip(), ai_sessions=sessions))
    return entries


def merge(base: list[Entry], from_ai: list[Entry]) -> list[Entry]:
    """Hasła słownika z opisami od AI + nowe hasła od AI (bez duplikatów; słownik decyduje o kategorii)."""
    result = {e.name.casefold(): Entry(e.name, e.category, e.description, ai_sessions=list(e.ai_sessions))
              for e in base}
    for entry in from_ai:
        known = result.get(entry.name.casefold())
        if known is not None:
            known.description = known.description or entry.description
            known.ai_sessions = known.ai_sessions or entry.ai_sessions
        else:
            result[entry.name.casefold()] = entry
    return list(result.values())


def add_occurrences(entries: list[Entry], chronicles: list[tuple[str, str]]) -> None:
    """Sesje z hasłem: dopasowanie wszystkich słów nazwy (w odmianie) + sesje wskazane przez AI, które
    łapie skróty i nieregularną odmianę. Nazwy spoza tych kronik (np. zmyślone przez AI) są pomijane."""
    for entry in entries:
        entry.sessions = [name for name, text in chronicles
                          if contains_name(text, entry.name) or name in entry.ai_sessions]


def _cache_path(key: str, prompt: str) -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    digest = hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:16]
    return Path(cache_home) / "rpg-chronicler" / "encyklopedia" / f"{key}-{digest}.json"


def ai_entries(llm, campaign: Campaign, chronicles: list[tuple[str, str]]) -> list[Entry]:
    """Hasła z opisami od AI (zapamiętane w cache dla tych samych kronik i słownika). Rzuca LLMError."""
    from .glossary import current_glossary_text
    from .llm import generate, with_retry  # import tutaj: GUI importuje ten moduł bez SDK LLM

    prefix = chronicle_blocks(chronicles, CHRONICLES_LIMIT)
    prompt = render("encyclopedia", system_name=campaign.system, current_glossary=current_glossary_text(campaign))
    cache = _cache_path(campaign.key, prefix + prompt)
    try:
        return parse_entries(cache.read_text(encoding="utf-8"))
    except (OSError, EncyclopediaError):
        pass
    print(f"[{llm.name}] Opisywanie haseł encyklopedii kampanii {campaign.key} ({len(chronicles)} kronik)...")
    response = with_retry(lambda: generate(llm, prompt, prefix), f"encyklopedia {campaign.key}")
    entries = parse_entries(response)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(response, encoding="utf-8")
    return entries


# --- dokument ---

TITLE_PREFIX_RE = re.compile(r"^\W*kronika\s+sesji(\s*\[[^\]]*\])?\s*:\s*", re.IGNORECASE)


def short_title(title: str) -> str:
    """„📜 Kronika Sesji [Warhammer]: Noc Nietoperzy” → „Noc Nietoperzy”."""
    return TITLE_PREFIX_RE.sub("", title).strip() or title


def _date_text(name: str) -> str:
    date = session_date(name)
    return date.strftime("%d.%m.%Y") if date else name


def timeline(sessions) -> list[tuple[str, str, str]]:
    """[(data, tytuł kroniki, skrót)] dla sesji z kroniką, od najstarszej."""
    rows = []
    for s in sorted(sessions, key=lambda s: (session_date(s.name) or datetime.date.max, s.name)):
        try:
            with open(s.summary_path, encoding="utf-8") as f:
                title = short_title(chronicle_title(f.read(), s.name))
        except OSError:
            continue
        brief = read_brief(s) if brief_is_current(s) else ""
        rows.append((_date_text(s.name), title, brief))
    return rows


def _demote_headings(text: str) -> str:
    """Nagłówki ## stanu kampanii stają się ### (pod sekcją „Stan kampanii”)."""
    return re.sub(r"^(#{2,5}) ", lambda m: "#" + m[1] + " ", text, flags=re.MULTILINE)


def render_markdown(campaign: Campaign, entries: list[Entry], timeline_rows, state=None) -> str:
    today = datetime.date.today().strftime("%d.%m.%Y")
    lines = [f"# Encyklopedia kampanii {campaign.key}", "",
             f"*{campaign.system} · {len(timeline_rows)} sesji · stan na {today}*", ""]
    if campaign.context:
        lines += [campaign.context.strip(), ""]

    lines += ["## Oś czasu", ""]
    for index, (date, title, brief) in enumerate(timeline_rows, 1):
        lines += [f"### {index}. {date} — {title}", ""]
        if brief:
            lines += [brief.strip(), ""]

    if state is not None and state.text:
        after = f" (po sesji {_date_text(state.session)})" if state.session else ""
        lines += [f"## Stan kampanii{after}", "", _demote_headings(state.text.strip()), ""]

    for category, title in CATEGORY_TITLES.items():
        group = sorted((e for e in entries if e.category == category), key=lambda e: e.name.casefold())
        if not group:
            continue
        lines += [f"## {title}", ""]
        for entry in group:
            text = f"**{entry.name}**"
            if entry.description:
                text += f" — {entry.description}"
            if entry.sessions:
                text += f" *Sesje: {', '.join(_date_text(s) for s in entry.sessions)}.*"
            else:
                text += " *Nie pojawia się w kronikach.*"
            lines += [text, ""]
    return "\n".join(lines).rstrip() + "\n"


def build(campaign: Campaign, sessions, llm=None) -> str:
    """Markdown encyklopedii. `llm` - klient AI do opisów haseł (None = tylko słownik, bez opisów)."""
    from .glossary import chronicles_for
    from .memory import load_state

    campaign_sessions = [s for s in sessions if campaign_key(s.name) == campaign.key and s.has_summary]
    chronicles = chronicles_for(campaign.key, campaign_sessions)
    if not chronicles:
        raise EncyclopediaError(f"Kampania {campaign.key} nie ma jeszcze żadnych kronik.")
    entries = glossary_entries(campaign)
    if llm is not None:
        entries = merge(entries, ai_entries(llm, campaign, chronicles))
    add_occurrences(entries, chronicles)
    return render_markdown(campaign, entries, timeline(campaign_sessions), load_state(campaign.key))
