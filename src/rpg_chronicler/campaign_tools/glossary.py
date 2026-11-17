"""Propozycje słownika kampanii od AI (na podstawie kronik) i ich zatwierdzanie.

Propozycje czekają w ~/.cache/rpg-chronicler/kampanie/<kampania>.json, aż użytkownik je przejrzy (GUI:
okno „Kampanie”); zatwierdzone trafiają do kampanie.toml. Moduł bez zależności zewnętrznych (używa go GUI);
wywołanie AI jest tylko w `extract_proposals`, które dostaje gotowego klienta LLM.
"""
import datetime
import json
import os
import re
from dataclasses import replace
from pathlib import Path

from ..campaigns import GLOSSARY_CATEGORIES, Campaign, campaign_key, session_date
from ..prompts import chronicle_blocks, render

PLAYER_CHARACTERS = "postacie_graczy"
DESCRIPTION = "opis"
CATEGORIES = [PLAYER_CHARACTERS, *GLOSSARY_CATEGORIES]  # kolejność wyświetlania
CHRONICLES_LIMIT = 150_000   # znaków kronik w jednym zapytaniu
MAX_PER_CATEGORY = 60


class GlossaryError(Exception):
    pass


# --- zapytanie do AI ---

def current_glossary_text(campaign: Campaign) -> str:
    lines = []
    if campaign.player_characters:
        lines.append(f"- postacie_graczy: {', '.join(campaign.player_characters)}")
    lines += [f"- {c}: {', '.join(campaign.names(c))}" for c in GLOSSARY_CATEGORIES if campaign.names(c)]
    return "\n".join(lines) or "(pusty)"


def build_prompt(campaign: Campaign, chronicles: list[tuple[str, str]]) -> tuple[str, str]:
    """(kroniki, polecenie) - `chronicles` = [(nazwa sesji, tekst kroniki)], od najstarszej.

    Kroniki idą na początek (wspólny z innymi zapytaniami po nowej kronice - cache w API).
    """
    wants_description = not campaign.context
    return chronicle_blocks(chronicles, CHRONICLES_LIMIT), render(
        "glossary_extraction",
        system_name=campaign.system,
        current_glossary=current_glossary_text(campaign),
        description_rule=("6. Dodatkowo w polu „opis” napisz 3–5 zdań o świecie i kampanii (gdzie toczy się akcja, "
                          "kim są bohaterowie, główny wątek) - posłuży jako opis kampanii dla AI.\n"
                          if wants_description else ""),
        description_field=', "opis": ""' if wants_description else "",
    )


def parse_response(text: str) -> dict:
    """Wyciąga obiekt JSON z odpowiedzi modelu i zostawia tylko poprawne pola (listy napisów, opis)."""
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise GlossaryError("Odpowiedź AI nie zawiera obiektu JSON.")
    try:
        data = json.loads(match[0])
    except json.JSONDecodeError as e:
        raise GlossaryError(f"Niepoprawny JSON w odpowiedzi AI: {e}") from e
    if not isinstance(data, dict):
        raise GlossaryError("Odpowiedź AI nie jest obiektem JSON.")
    result: dict = {}
    for category in CATEGORIES:
        values = data.get(category, [])
        if isinstance(values, list):
            names = [v.strip() for v in values if isinstance(v, str) and v.strip()]
            if names:
                result[category] = names[:MAX_PER_CATEGORY]
    description = data.get(DESCRIPTION)
    if isinstance(description, str) and description.strip():
        result[DESCRIPTION] = description.strip()
    return result


def known_names(campaign: Campaign) -> set[str]:
    return {name.casefold() for name in campaign.all_names()}


def new_only(proposals: dict, campaign: Campaign) -> dict:
    """Usuwa propozycje, które już są w słowniku kampanii (bez względu na wielkość liter) i powtórzenia."""
    known = known_names(campaign)
    result: dict = {}
    for category in CATEGORIES:
        names = []
        for name in proposals.get(category, []):
            if name.casefold() not in known:
                known.add(name.casefold())
                names.append(name)
        if names:
            result[category] = names
    if proposals.get(DESCRIPTION) and not campaign.context:
        result[DESCRIPTION] = proposals[DESCRIPTION]
    return result


def extract_proposals(llm, campaign: Campaign, chronicles: list[tuple[str, str]]) -> dict:
    """Pyta AI o nowe nazwy z kronik. Rzuca LLMError (połączenie) albo GlossaryError (zła odpowiedź)."""
    from ..llm import generate, with_retry  # import tutaj: GUI importuje ten moduł bez SDK LLM
    if not chronicles:
        return {}
    prefix, prompt = build_prompt(campaign, chronicles)
    print(f"[{llm.name}] Szukanie nazw w {len(chronicles)} kronikach kampanii {campaign.key}...")
    response = with_retry(lambda: generate(llm, prompt, prefix), f"słownik kampanii {campaign.key}")
    return new_only(parse_response(response), campaign)


# --- oczekujące propozycje ---

def proposals_dir() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(cache_home) / "rpg-chronicler" / "kampanie"


def proposals_path(key: str) -> Path:
    return proposals_dir() / f"{key}.json"


def load_proposals(key: str) -> dict:
    try:
        data = json.loads(proposals_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def pending_for(campaign: Campaign) -> dict:
    """Oczekujące propozycje bez nazw, które w międzyczasie trafiły do słownika (np. dodane ręcznie)."""
    return new_only(load_proposals(campaign.key), campaign)


def save_proposals(key: str, proposals: dict) -> None:
    path = proposals_path(key)
    if not any(proposals.get(c) for c in CATEGORIES) and not proposals.get(DESCRIPTION):
        path.unlink(missing_ok=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proposals, ensure_ascii=False, indent=1), encoding="utf-8")


def add_proposals(campaign: Campaign, proposals: dict) -> dict:
    """Dokłada nowe propozycje do oczekujących (bez duplikatów) i zwraca wynik."""
    pending = load_proposals(campaign.key)
    merged = {c: [*pending.get(c, []), *proposals.get(c, [])] for c in CATEGORIES}
    merged[DESCRIPTION] = pending.get(DESCRIPTION) or proposals.get(DESCRIPTION, "")
    merged = new_only(merged, campaign)
    save_proposals(campaign.key, merged)
    return merged


def count_proposals(proposals: dict) -> int:
    return sum(len(proposals.get(c, [])) for c in CATEGORIES) + bool(proposals.get(DESCRIPTION))


def accept(campaign: Campaign, accepted: dict) -> Campaign:
    """Kampania z dodanymi zaakceptowanymi propozycjami ({kategoria: [nazwy]}, opcjonalnie "opis")."""
    for category in GLOSSARY_CATEGORIES:
        if accepted.get(category):
            campaign = campaign.with_names(category, [*campaign.names(category), *accepted[category]])
    if accepted.get(PLAYER_CHARACTERS):
        characters = dict(campaign.player_characters)
        for name in accepted[PLAYER_CHARACTERS]:
            characters.setdefault(name, "")
        campaign = replace(campaign, player_characters=characters)
    if accepted.get(DESCRIPTION) and not campaign.context:
        campaign = replace(campaign, context=accepted[DESCRIPTION])
    return campaign


def remove_from_pending(key: str, handled: dict) -> None:
    """Usuwa z oczekujących propozycje już rozpatrzone (dodane albo odrzucone)."""
    pending = load_proposals(key)
    for category in CATEGORIES:
        done = {n.casefold() for n in handled.get(category, [])}
        remaining = [n for n in pending.get(category, []) if n.casefold() not in done]
        if remaining:
            pending[category] = remaining
        else:
            pending.pop(category, None)
    if handled.get(DESCRIPTION):
        pending.pop(DESCRIPTION, None)
    save_proposals(key, pending)


def chronicles_for(campaign_key_: str, sessions) -> list[tuple[str, str]]:
    """Kroniki sesji danej kampanii [(nazwa, tekst)] w kolejności dat (sesje bez daty na końcu)."""
    selected = [s for s in sessions if s.has_summary and campaign_key(s.name) == campaign_key_]
    selected.sort(key=lambda s: (session_date(s.name) or datetime.date.max, s.name))
    result = []
    for session in selected:
        try:
            with open(session.summary_path, encoding="utf-8") as f:
                result.append((session.name, f.read()))
        except OSError:
            continue
    return result
