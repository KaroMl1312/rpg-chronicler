"""Pamięć kampanii: stan świata po ostatniej sesji (drużyna, zasoby, otwarte wątki, BN-i, miejsca).

Zatwierdzony stan leży w TXT_DIR/stan-kampanii-<kampania>.md (synchronizuje się z Drive, jak kampanie.toml).
Po każdej nowej kronice AI proponuje zaktualizowany stan; propozycja czeka w
~/.cache/rpg-chronicler/stan-kampanii/<kampania>.json, aż użytkownik ją przyjmie (GUI: okno „Kampanie”,
CLI: `memory KAMPANIA --accept`). Kolejne kroniki przed zatwierdzeniem aktualizują tę samą propozycję.

Kronika sesji dostaje stan tylko wtedy, gdy opisuje on czas sprzed tej sesji - inaczej (np. przy ponownym
generowaniu starszej kroniki) AI znałoby przyszłość. Moduł bez zależności zewnętrznych (używa go GUI);
wywołania AI są tylko w funkcjach dostających gotowego klienta LLM.
"""
import datetime
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from .. import session as _session
from ..campaigns import Campaign, session_date
from ..prompts import chronicle_blocks, render

STATE_PREFIX = "stan-kampanii-"
HEADER_RE = re.compile(r"^<!-- po sesji: (?P<session>.*?) -->\n?")
CHRONICLES_LIMIT = 150_000   # znaków kronik przy budowaniu stanu od zera
STATE_LIMIT = 12_000         # dłuższy stan od AI przycinamy (prompt każe zmieścić się w ~6000 znaków)


@dataclass(frozen=True)
class State:
    text: str
    session: str | None   # po której sesji opisuje świat (None = nieznane, np. wpisany ręcznie)


# --- zatwierdzony stan ---

def state_path(key: str) -> str:
    return os.path.join(_session.TXT_DIR, f"{STATE_PREFIX}{key}.md")


def _parse(content: str) -> State:
    match = HEADER_RE.match(content)
    if match:
        return State(content[match.end():].strip(), match["session"].strip() or None)
    return State(content.strip(), None)


def load_state(key: str) -> State | None:
    try:
        with open(state_path(key), encoding="utf-8") as f:
            state = _parse(f.read())
    except OSError:
        return None
    return state if state.text else None


def save_state(key: str, text: str, session: str | None) -> None:
    path = state_path(key)
    text = text.strip()
    if not text:
        if os.path.exists(path):
            os.unlink(path)
        return
    header = f"<!-- po sesji: {session} -->\n" if session else ""
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(header + text + "\n")
    os.replace(tmp, path)


# --- propozycje od AI ---

def proposals_dir() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(cache_home) / "rpg-chronicler" / "stan-kampanii"


def proposal_path(key: str) -> Path:
    return proposals_dir() / f"{key}.json"


def load_proposal(key: str) -> State | None:
    try:
        data = json.loads(proposal_path(key).read_text(encoding="utf-8"))
        return State(str(data["text"]).strip(), data.get("session"))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_proposal(key: str, state: State) -> None:
    path = proposal_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"text": state.text, "session": state.session}, ensure_ascii=False, indent=1),
                    encoding="utf-8")


def discard_proposal(key: str) -> None:
    proposal_path(key).unlink(missing_ok=True)


def accept_proposal(key: str, text: str | None = None) -> State | None:
    """Zapisuje propozycję jako stan kampanii (`text` - wersja poprawiona przez użytkownika)."""
    proposal = load_proposal(key)
    if proposal is None:
        return None
    state = State((text if text is not None else proposal.text).strip(), proposal.session)
    save_state(key, state.text, state.session)
    discard_proposal(key)
    return state


# --- kolejność sesji ---

def _date(name: str | None) -> datetime.date | None:
    return session_date(name) if name else None


def is_before(state: State, session_name: str) -> bool:
    """Czy stan opisuje świat sprzed sesji `session_name` (tylko taki wolno podać AI piszącemu jej kronikę)."""
    if state.session is None:
        return True   # stan wpisany ręcznie - ufamy użytkownikowi
    if state.session == session_name:
        return False
    state_date, date = _date(state.session), _date(session_name)
    if state_date is None or date is None:
        return False
    return state_date < date


def is_newer(session_name: str, state: State | None) -> bool:
    """Czy sesja jest późniejsza niż ta, po której zapisano stan (czyli warto go nią zaktualizować)."""
    if state is None or state.session is None:
        return True
    date, state_date = _date(session_name), _date(state.session)
    if date is None or state_date is None:
        return session_name != state.session
    return date > state_date


def state_for_prompt(key: str | None, session_name: str) -> State | None:
    if not key:
        return None
    state = load_state(key)
    return state if state is not None and is_before(state, session_name) else None


def unaccepted_proposal(key: str | None, session_name: str) -> State | None:
    """Niezatwierdzona propozycja stanu sprzed sesji - AI piszące jej kronikę jej nie zobaczy (tylko stan
    zatwierdzony), więc kronika może nie znać ostatnich wydarzeń kampanii."""
    if not key:
        return None
    proposal = load_proposal(key)
    return proposal if proposal is not None and is_before(proposal, session_name) else None


def unaccepted_warning(key: str | None, session_name: str) -> str | None:
    """Komunikat dla użytkownika (CLI i GUI) albo None, gdy nie ma czego zatwierdzać."""
    proposal = unaccepted_proposal(key, session_name)
    if proposal is None:
        return None
    state = state_for_prompt(key, session_name)
    if state is None:
        used = "żadnego stanu kampanii (nic jeszcze nie zatwierdzono)"
    else:
        used = f"stan zatwierdzony po sesji {state.session}" if state.session else "stan wpisany ręcznie"
    after = f" (po sesji {proposal.session})" if proposal.session else ""
    return f"Kampania {key} ma niezatwierdzoną propozycję stanu{after}. Kronika {session_name} dostanie {used}."


# --- zapytania do AI ---

def clean_response(text: str) -> str:
    """Odpowiedź AI bez ewentualnego bloku kodu i wstępu przed pierwszym nagłówkiem."""
    text = text.strip()
    fenced = re.fullmatch(r"```(?:markdown|md)?\n(.*)\n```", text, re.DOTALL)
    if fenced:
        text = fenced[1].strip()
    heading = text.find("## ")
    if heading > 0:
        text = text[heading:]
    return text[:STATE_LIMIT].strip()


def update_prompt(campaign: Campaign, previous: State | None, session_name: str,
                  chronicle: str) -> tuple[str, str]:
    """(kronika, polecenie) - kronika na początku, wspólna z innymi zapytaniami po niej (cache w API)."""
    return chronicle_blocks([(session_name, chronicle)]), render(
        "campaign_state",
        system_name=campaign.system,
        campaign_info=campaign.prompt_info() or "(brak)",
        previous_state=previous.text if previous else "(brak - to pierwszy zapis stanu kampanii)")


def build_prompt(campaign: Campaign, chronicles: list[tuple[str, str]]) -> tuple[str, str]:
    """Stan od zera z wielu kronik (od najstarszej); przy limicie zostają najnowsze."""
    return chronicle_blocks(chronicles, CHRONICLES_LIMIT), render(
        "campaign_state",
        system_name=campaign.system,
        campaign_info=campaign.prompt_info() or "(brak)",
        previous_state="(brak - zbuduj stan od zera na podstawie wszystkich kronik powyżej)")


def propose_update(llm, campaign: Campaign, session_name: str, chronicle: str) -> State | None:
    """Po nowej kronice: AI aktualizuje stan (zatwierdzony albo oczekującą propozycję) i zapisuje propozycję.

    Zwraca propozycję albo None, gdy sesja nie jest nowsza od stanu. Rzuca LLMError.
    """
    from ..llm import generate, with_retry  # import tutaj: GUI importuje ten moduł bez SDK LLM
    base = load_proposal(campaign.key) or load_state(campaign.key)
    if not is_newer(session_name, base):
        return None
    prefix, prompt = update_prompt(campaign, base, session_name, chronicle)
    print(f"[{llm.name}] Aktualizacja stanu kampanii {campaign.key} po sesji {session_name}...")
    text = clean_response(with_retry(lambda: generate(llm, prompt, prefix), f"stan kampanii {campaign.key}"))
    proposal = State(text, session_name)
    save_proposal(campaign.key, proposal)
    return proposal


def propose_from_chronicles(llm, campaign: Campaign, chronicles: list[tuple[str, str]]) -> State | None:
    """Stan od zera ze wszystkich kronik kampanii (od najstarszej). Rzuca LLMError."""
    from ..llm import generate, with_retry
    if not chronicles:
        return None
    prefix, prompt = build_prompt(campaign, chronicles)
    print(f"[{llm.name}] Budowanie stanu kampanii {campaign.key} z {len(chronicles)} kronik...")
    text = clean_response(with_retry(lambda: generate(llm, prompt, prefix), f"stan kampanii {campaign.key}"))
    proposal = State(text, chronicles[-1][0])
    save_proposal(campaign.key, proposal)
    return proposal
