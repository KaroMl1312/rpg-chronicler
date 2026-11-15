"""Dodatki po nowej kronice: skrót, cytaty, propozycje słownika i stanu kampanii.

Wszystkie zaczynają się od tej samej kroniki (prompts.chronicle_blocks) - w API Anthropic czytają ją z cache.
`run_all` woła je po kolei wg ustawień; błąd jednego dodatku nie przerywa pozostałych.
"""
import json
import os
import re

from . import glossary, memory, progress
from .chronicle import brief_path
from .chronicle_events import events_path
from .config import CAMPAIGN_MEMORY, CHRONICLE_BRIEF, CHRONICLE_QUOTES, GLOSSARY_PROPOSALS, LLM_PROVIDER
from .llm import LazyClient, LLMClient, LLMError, generate, with_retry
from .prompts import chronicle_blocks, render
from .session import Session, list_sessions
from .transcript import load_speaker_mapping


def run_all(client: LLMClient, session: Session, chronicle: str) -> None:
    """Dodatki włączone w ustawieniach (ai.skrot_kroniki, ai.cytaty, ai.propozycje_slownika, ai.pamiec_kampanii)."""
    if CHRONICLE_BRIEF:
        try:
            write_brief(client, session, chronicle)
        except LLMError as e:
            print(f"[OSTRZEŻENIE] Nie udało się napisać skrótu kroniki: {e} "
                  f"(spróbuj: rpg-chronicler brief {session.name})")
    if CHRONICLE_QUOTES:
        try:
            write_quotes(client, session, chronicle)
        except (LLMError, QuotesError) as e:
            print(f"[OSTRZEŻENIE] Nie udało się wybrać cytatów: {e} (spróbuj: rpg-chronicler quotes {session.name})")
    if GLOSSARY_PROPOSALS:
        propose_glossary(client, session, chronicle)
    if CAMPAIGN_MEMORY:
        update_campaign_memory(client, session, chronicle)


def write_brief(client: LLMClient, session: Session, chronicle: str) -> str:
    """Skrót kroniki: najważniejsze wydarzenia w jednym akapicie. Rzuca LLMError."""
    progress.report("skrót kroniki", session.name)
    # Kronika na początku - ten sam początek mają zapytania o słownik i stan kampanii (cache w API)
    prefix = chronicle_blocks([(session.name, chronicle)])
    prompt = render("brief", system_name=session.system_name)
    print(f"[{client.name}] Pisanie skrótu kroniki {session.name}...")
    brief = with_retry(lambda: generate(client, prompt, prefix), f"skrót {session.name}").strip()
    with open(brief_path(session), "w", encoding="utf-8") as f:
        f.write(brief + "\n")
    print(f"[SUKCES] Zapisano skrót kroniki w: {brief_path(session)}")
    return brief


def brief_sessions(sessions: list[Session], provider: str = LLM_PROVIDER, force: bool = False) -> None:
    """Skróty dla kronik, które go nie mają (albo mają starszy niż kronika); `force` - wszystkie wskazane."""
    from .chronicle import brief_is_current, read_chronicle
    pending = [s for s in sessions if s.has_summary and (force or not brief_is_current(s))]
    if not pending:
        print("Wszystkie kroniki mają aktualne skróty.")
        return
    llm = LazyClient(provider)
    for session in pending:
        try:
            write_brief(llm.get(), session, read_chronicle(session))
        except LLMError as e:
            print(f"[OSTRZEŻENIE] {session.name}: {e}")
            if not e.retryable:
                return


# --- cytaty z sesji ---


MAX_QUOTES = 5


class QuotesError(Exception):
    pass


def quotes_source(session: Session) -> tuple[str, str]:
    """(materiał, opis do promptu): cytaty z listy wydarzeń (kronika w dwóch krokach) albo transkrypcja."""
    try:
        with open(events_path(session), encoding="utf-8") as f:
            events = f.read()
    except OSError:
        events = ""
    sections = re.findall(r"^#{2,4}\s*Cytaty\s*\n(.*?)(?=^#{1,4}\s|\Z)", events, re.MULTILINE | re.DOTALL)
    candidates = "\n".join(part.strip() for part in sections if part.strip())
    if candidates:
        return (f"<kandydaci>\n{candidates}\n</kandydaci>",
                "cytaty wybrane wcześniej z kolejnych części nagrania (kandydaci)")
    if session.has_transcript:
        text = session.load_transcript().compact_for_llm(load_speaker_mapping(session.txt_path))
        return f"<transkrypcja>\n{text}\n</transkrypcja>", "transkrypcja nagrania (format „MÓWCA: wypowiedź”)"
    raise QuotesError("brak transkrypcji, z której można wybrać cytaty")


def parse_quotes_response(text: str) -> list[tuple[str, str]]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise QuotesError("Odpowiedź AI nie zawiera obiektu JSON.")
    try:
        data = json.loads(match[0])
    except json.JSONDecodeError as e:
        raise QuotesError(f"Niepoprawny JSON w odpowiedzi AI: {e}") from e
    quotes = []
    for item in data.get("cytaty", []) if isinstance(data, dict) else []:
        if isinstance(item, dict):
            quote = str(item.get("cytat", "")).strip().strip("„”\"").strip()
            if quote:
                quotes.append((quote, str(item.get("kto", "")).strip()))
    if not quotes:
        raise QuotesError("AI nie wybrało żadnego cytatu.")
    return quotes[:MAX_QUOTES]


def write_quotes(client: LLMClient, session: Session, chronicle: str) -> list[tuple[str, str]]:
    """Najlepsze cytaty z sesji do <sesja>_cytaty.txt. Rzuca LLMError albo QuotesError."""
    from .chronicle import quotes_path, save_quotes

    source, description = quotes_source(session)
    info = session.campaign.prompt_info()
    # Kronika na początku - wspólny początek ze skrótem, słownikiem i stanem kampanii (cache w API)
    prefix = chronicle_blocks([(session.name, chronicle)])
    prompt = render("quotes", system_name=session.system_name, source_description=description, source=source,
                    campaign_info=f"\nInformacje o kampanii (pisownia imion):\n{info}\n" if info else "")
    progress.report("cytaty", session.name)
    print(f"[{client.name}] Wybieranie cytatów z sesji {session.name}...")
    quotes = parse_quotes_response(with_retry(lambda: generate(client, prompt, prefix), f"cytaty {session.name}"))
    save_quotes(session, quotes)
    print(f"[SUKCES] Zapisano {len(quotes)} cytatów w: {quotes_path(session)}")
    return quotes


def quotes_sessions(sessions: list[Session], provider: str = LLM_PROVIDER, force: bool = False) -> None:
    """Cytaty dla sesji z kroniką, które ich nie mają (`force` - wszystkie wskazane)."""
    from .chronicle import quotes_path, read_chronicle
    pending = [s for s in sessions if s.has_summary and (force or not os.path.exists(quotes_path(s)))]
    if not pending:
        print("Wszystkie kroniki mają już cytaty.")
        return
    llm = LazyClient(provider)
    for session in pending:
        try:
            write_quotes(llm.get(), session, read_chronicle(session))
        except QuotesError as e:
            print(f"[OSTRZEŻENIE] {session.name}: {e}")
        except LLMError as e:
            print(f"[OSTRZEŻENIE] {session.name}: {e}")
            if not e.retryable:
                return


def propose_glossary(client: LLMClient, session: Session, chronicle: str) -> None:
    """Po nowej kronice: AI proponuje nowe nazwy do słownika kampanii. Błąd nie przerywa pracy."""
    campaign = session.campaign
    if not campaign.key:
        return
    progress.report("propozycje słownika", session.name)
    try:
        proposals = glossary.extract_proposals(client, campaign, [(session.name, chronicle)])
    except (LLMError, glossary.GlossaryError) as e:
        print(f"[OSTRZEŻENIE] Nie udało się zaproponować nazw do słownika: {e}")
        return
    pending = glossary.add_proposals(campaign, proposals)
    if proposals:
        print(f"[INFO] Nowe propozycje do słownika kampanii {campaign.key}: {glossary.count_proposals(proposals)} "
              f"(oczekuje {glossary.count_proposals(pending)}) - przejrzyj je w GUI (Kampanie).")


def update_campaign_memory(client: LLMClient, session: Session, chronicle: str) -> None:
    """Po nowej kronice: propozycja stanu kampanii (od zera z wszystkich kronik, gdy stanu jeszcze nie ma)."""
    campaign = session.campaign
    if not campaign.key:
        return
    progress.report("pamięć kampanii", session.name)
    try:
        if memory.load_state(campaign.key) is None and memory.load_proposal(campaign.key) is None:
            proposal = memory.propose_from_chronicles(client, campaign,
                                                      glossary.chronicles_for(campaign.key, list_sessions()))
        else:
            proposal = memory.propose_update(client, campaign, session.name, chronicle)
    except LLMError as e:
        print(f"[OSTRZEŻENIE] Nie udało się zaktualizować stanu kampanii: {e} "
              f"(spróbuj: rpg-chronicler memory {campaign.key} --rebuild)")
        return
    if proposal is not None:
        print(f"[INFO] Nowa propozycja stanu kampanii {campaign.key} (po sesji {proposal.session}) - przejrzyj ją "
              f"w GUI (Kampanie) albo: rpg-chronicler memory {campaign.key} --accept")
