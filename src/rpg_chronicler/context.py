"""Kontekst kampanii dla AI: imiona mówców, opis kampanii ze słownikiem, stan kampanii i poprzednia kronika."""
from . import memory
from .campaigns import campaign_key, session_date
from .session import Session, list_sessions


def speaker_mapping_info(mapping: dict[str, str]) -> str:
    if not mapping:
        return ""
    mapping_list = [f"- Kod {spk} to: {name}" for spk, name in mapping.items()]
    return ("\n\nOto oficjalna lista mapowania mówców w tej sesji:\n" + "\n".join(mapping_list)
            + "\nUżywaj tych imion i ról przy opisywaniu akcji konkretnych bohaterów!")


PREVIOUS_CHRONICLE_LIMIT = 20000  # znaków - dłuższą poprzednią kronikę przycinamy


def previous_session(session: Session) -> Session | None:
    """Ostatnia wcześniejsza sesja tej samej kampanii, która ma już kronikę (wg daty w nazwie)."""
    key, date = campaign_key(session.name), session_date(session.name)
    if key is None or date is None:
        return None
    candidates = [(d, s) for s in list_sessions() if s.name != session.name and s.has_summary
                  and campaign_key(s.name) == key and (d := session_date(s.name)) is not None and d < date]
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def campaign_context(session: Session, include_previous: bool = True) -> str:
    """Opis kampanii, słownik nazw, stan kampanii sprzed sesji i poprzednia kronika - ciągłość i pisownia."""
    parts = []
    info = session.campaign.prompt_info()
    if info:
        parts.append(f"Informacje o kampanii (użyj ich, by poprawnie zapisywać imiona i nazwy):\n{info}")
    state = memory.state_for_prompt(session.campaign.key, session.name)
    if state is not None:
        after = f" po sesji {state.session}" if state.session else ""
        parts.append(f"Stan kampanii{after} (pamięć kampanii: drużyna, zasoby, otwarte wątki, BN-i) - "
                     f"tło dla ciągłości; opisuj wyłącznie wydarzenia z nowej sesji:\n"
                     f"<stan_kampanii>\n{state.text}\n</stan_kampanii>")
    previous = previous_session(session) if include_previous else None
    if previous is not None:
        try:
            with open(previous.summary_path, encoding="utf-8") as f:
                text = f.read().strip()[:PREVIOUS_CHRONICLE_LIMIT]
        except OSError:
            text = ""
        if text:
            parts.append(f"Kronika poprzedniej sesji ({previous.name}) - tylko dla ciągłości fabuły, wątków i imion; "
                         f"nie streszczaj jej ponownie, opisuj wyłącznie wydarzenia z nowej transkrypcji:\n"
                         f"<poprzednia_kronika>\n{text}\n</poprzednia_kronika>")
    return "".join(f"\n\n{part}" for part in parts)
