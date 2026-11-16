"""Przed kolejną sesją: „Poprzednio w kampanii…” (do przeczytania na głos) i notatki MG.

- Poprzednio (`recap KAMPANIA`): ostatnia kronika kampanii + krótko otwarte wątki ze stanu kampanii;
  SUMMARY_DIR/poprzednio-<kampania>.md, opcjonalnie na Discord (`--discord`, webhook kampanii).
- Notatki MG (`gm-notes KAMPANIA`): otwarte wątki, obietnice, niewykorzystane tropy, BN-i, pytania - ze
  wszystkich kronik i stanu kampanii; SUMMARY_DIR/notatki-mg-<kampania>.md + PDF (na Drive, nie na Discord).
Oba pliki mają w 1. linii `<!-- po sesji: NAZWA -->` - są nieaktualne, gdy pojawi się nowsza kronika.
Zapytania zaczynają się od kronik jak skrót (Poprzednio) i encyklopedia (notatki) - wspólny cache API.
Moduł bez zależności zewnętrznych (GUI sprawdza pliki); LLM tylko w funkcjach z klientem.
"""
import os
import re

from . import memory
from . import session as _session
from .campaigns import Campaign, campaign_key, session_date
from .prompts import chronicle_blocks, render

HEADER_RE = re.compile(r"\A<!-- po sesji: (?P<session>.*?) -->\n?")
CHRONICLES_LIMIT = 200_000   # jak encyklopedia (ten sam początek zapytania - cache)
RECAP_TITLE = "Poprzednio w kampanii"


class PrepError(Exception):
    pass


def recap_path(key: str) -> str:
    return os.path.join(_session.SUMMARY_DIR, f"poprzednio-{key}.md")


def gm_notes_path(key: str) -> str:
    return os.path.join(_session.SUMMARY_DIR, f"notatki-mg-{key}.md")


def gm_notes_pdf_path(key: str) -> str:
    return os.path.join(_session.SUMMARY_DIR, f"notatki-mg-{key}.pdf")


def campaign_chronicles(key: str, sessions) -> list[tuple[str, str]]:
    from .glossary import chronicles_for
    return chronicles_for(key, sessions)


def latest_session(key: str, sessions):
    """Ostatnia (wg daty z nazwy) sesja kampanii z kroniką albo None."""
    chronicled = [s for s in sessions if s.has_summary and campaign_key(s.name) == key and session_date(s.name)]
    return max(chronicled, key=lambda s: (session_date(s.name), s.name), default=None)


def read(path: str) -> tuple[str | None, str]:
    """(po której sesji, treść) pliku z nagłówkiem; (None, "") gdy go nie ma."""
    try:
        with open(path, encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None, ""
    match = HEADER_RE.match(content)
    if match:
        return match["session"].strip() or None, content[match.end():].strip()
    return None, content.strip()


def is_current(path: str, key: str, sessions) -> bool:
    """Plik powstał po ostatniej kronice kampanii (ta sama sesja w nagłówku i nowszy niż jej kronika)."""
    latest = latest_session(key, sessions)
    after, text = read(path)
    if latest is None or not text or after != latest.name:
        return False
    try:
        return os.path.getmtime(path) >= os.path.getmtime(latest.summary_path)
    except OSError:
        return False


def _write(path: str, session_name: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(f"<!-- po sesji: {session_name} -->\n{text.strip()}\n")
    os.replace(tmp, path)


def prompt_context(campaign: Campaign) -> tuple[str, str]:
    """(informacje o kampanii, stan kampanii) jako bloki do promptu."""
    info = campaign.prompt_info()
    state = memory.load_state(campaign.key) or memory.load_proposal(campaign.key)
    after = f" po sesji {state.session}" if state is not None and state.session else ""
    return (f"\nInformacje o kampanii (pisownia imion i nazw):\n{info}\n" if info else "",
            f"\nStan kampanii{after}:\n<stan_kampanii>\n{state.text}\n</stan_kampanii>\n" if state is not None else "")


def _clean(text: str) -> str:
    text = text.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return text


# --- Poprzednio w kampanii… ---

def recap_prompt(campaign: Campaign, session_name: str, chronicle: str) -> tuple[str, str]:
    """(prefiks, prompt): kronika ostatniej sesji na początku - ten sam prefiks co skrót kroniki."""
    info, state = prompt_context(campaign)
    return chronicle_blocks([(session_name, chronicle)]), render(
        "recap", system_name=campaign.system, session_name=session_name, campaign_info=info, state=state)


def write_recap(llm, campaign: Campaign, sessions) -> str:
    """Pisze i zapisuje „Poprzednio w kampanii…”; zwraca tekst. Rzuca LLMError albo PrepError."""
    from .llm import generate, with_retry  # import tutaj: GUI importuje ten moduł bez SDK LLM

    latest = latest_session(campaign.key, sessions)
    if latest is None:
        raise PrepError(f"Kampania {campaign.key} nie ma jeszcze żadnej kroniki.")
    with open(latest.summary_path, encoding="utf-8") as f:
        chronicle = f.read()
    prefix, prompt = recap_prompt(campaign, latest.name, chronicle)
    print(f"[{llm.name}] „{RECAP_TITLE}…” kampanii {campaign.key} (po sesji {latest.name})...")
    text = _clean(with_retry(lambda: generate(llm, prompt, prefix), f"poprzednio {campaign.key}"))
    _write(recap_path(campaign.key), latest.name, text)
    return text


# --- notatki MG ---

def gm_notes_prompt(campaign: Campaign, chronicles: list[tuple[str, str]]) -> tuple[str, str]:
    """(prefiks, prompt): wszystkie kroniki na początku - ten sam prefiks co encyklopedia i pytania."""
    info, state = prompt_context(campaign)
    return chronicle_blocks(chronicles, CHRONICLES_LIMIT), render(
        "gm_notes", system_name=campaign.system, session_name=chronicles[-1][0], campaign_info=info, state=state)


def render_gm_notes(campaign: Campaign, session_name: str, notes: str) -> str:
    from .chronicle import session_date_text

    when = session_date_text(_session.Session(session_name)) or session_name
    return (f"# Notatki MG: {campaign.key}\n\n*{campaign.system} · przed sesją po {when} · tylko dla Mistrza Gry*\n\n"
            f"{notes.strip()}\n")


def write_gm_notes(llm, campaign: Campaign, sessions) -> str:
    """Pisze i zapisuje notatki MG (.md); zwraca Markdown. PDF robi komenda. Rzuca LLMError albo PrepError."""
    from .llm import generate, with_retry

    chronicles = campaign_chronicles(campaign.key, sessions)
    latest = latest_session(campaign.key, sessions)
    if not chronicles or latest is None:
        raise PrepError(f"Kampania {campaign.key} nie ma jeszcze żadnej kroniki.")
    prefix, prompt = gm_notes_prompt(campaign, chronicles)
    print(f"[{llm.name}] Notatki MG kampanii {campaign.key} ({len(chronicles)} kronik)...")
    notes = _clean(with_retry(lambda: generate(llm, prompt, prefix), f"notatki MG {campaign.key}"))
    text = render_gm_notes(campaign, latest.name, notes)
    _write(gm_notes_path(campaign.key), latest.name, text)
    return text
