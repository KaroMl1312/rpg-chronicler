import hashlib
import os
from pathlib import Path

from . import glossary, memory, progress
from .campaigns import campaign_key, session_date
from .chronicle import brief_path
from .config import (CAMPAIGN_MEMORY, CHRONICLE_BRIEF, CHRONICLE_PART_SECONDS, CHRONICLE_TWO_STEP,
                     GLOSSARY_PROPOSALS, LLM_PROVIDER, SUMMARY_DIR)
from .llm import LLMClient, LLMError, get_client, with_retry
from .prompts import render
from .session import Session, list_sessions
from .speakers import identify_speakers, save_suggestion, suggest_speakers
from .quality import format_time
from .transcript import Transcript, load_speaker_mapping, save_speaker_mapping
from .voices import suggest_for_session


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


# --- kronika w dwóch krokach ---

PREVIOUS_EVENTS_LIMIT = 8000  # znaków z listy wydarzeń poprzedniej części (kontekst dla następnej)


def events_path(session: Session) -> str:
    """Lista wydarzeń sesji (krok pośredni kroniki) - obok kroniki, do wglądu."""
    return os.path.join(SUMMARY_DIR, f"{session.name}_wydarzenia.md")


def events_cache_dir(session: Session) -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(cache_home) / "rpg-chronicler" / "wydarzenia" / session.name


def session_events(client: LLMClient, session: Session, transcript: Transcript, mapping: dict[str, str],
                   parts: list[Transcript]) -> str:
    """Krok 1: lista wydarzeń z każdej części transkrypcji. Rzuca LLMError.

    Wynik każdej części jest zapamiętywany (klucz = treść zapytania), więc przerwany przebieg albo ponowne
    pisanie kroniki (--force) nie powtarza zapytań, dopóki nie zmieni się transkrypcja, mówcy lub prompt.
    """
    cache_dir = events_cache_dir(session)
    context = campaign_context(session, include_previous=False)
    mapping_info = speaker_mapping_info(mapping)
    sections, previous = [], ""
    for index, part in enumerate(parts, 1):
        time_range = f"{format_time(part.segments[0].start)}–{format_time(part.segments[-1].end)}"
        previous_block = ""
        if previous:
            previous_block = ("\n\nWydarzenia z poprzedniej części (tylko kontekst - nie powtarzaj ich):\n"
                              f"<poprzednia_czesc>\n{previous[-PREVIOUS_EVENTS_LIMIT:]}\n</poprzednia_czesc>")
        prompt = render("events", system_name=session.system_name, part=str(index), parts=str(len(parts)),
                        time_range=time_range, speaker_mapping_info=mapping_info, campaign_context=context,
                        previous_events=previous_block, transcript=part.compact_for_llm(mapping))
        cache = cache_dir / f"{hashlib.sha1(prompt.encode('utf-8')).hexdigest()}.md"
        try:
            text = cache.read_text(encoding="utf-8")
            print(f"[INFO] Wydarzenia części {index}/{len(parts)} ({time_range}) z pamięci podręcznej.")
        except OSError:
            progress.report("wydarzenia", session.name, index - 1, len(parts))
            print(f"[{client.name}] Wydarzenia części {index}/{len(parts)} ({time_range})...")
            text = with_retry(lambda: client.generate(prompt), f"wydarzenia {session.name} {index}/{len(parts)}")
            text = text.strip()
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache.write_text(text, encoding="utf-8")
        sections.append(f"## Część {index} z {len(parts)} ({time_range})\n\n{text}")
        previous = text
    events = "\n\n".join(sections)
    with open(events_path(session), "w", encoding="utf-8") as f:
        f.write(f"# Wydarzenia sesji {session.name}\n\n{events}\n")
    return events


def chronicle_source(client: LLMClient, session: Session, transcript: Transcript,
                     mapping: dict[str, str]) -> str:
    """Materiał dla kroniki: lista wydarzeń (dwa kroki, długie sesje) albo cała transkrypcja. Rzuca LLMError."""
    parts = transcript.split_parts(CHRONICLE_PART_SECONDS) if CHRONICLE_TWO_STEP else []
    if len(parts) > 1:
        events = session_events(client, session, transcript, mapping, parts)
        return (f"Oto szczegółowa, chronologiczna lista wydarzeń z całej sesji, sporządzona z transkrypcji "
                f"w {len(parts)} częściach. Opieraj się wyłącznie na niej - zawiera wszystkie fakty, imiona "
                f"i najlepsze cytaty (możesz je przytaczać). Napisz jedną spójną kronikę całej sesji, "
                f"bez dzielenia jej na te części:\n<wydarzenia>\n{events}\n</wydarzenia>")
    return f"Oto treść transkrypcji (format: „MÓWCA: wypowiedź”):\n{transcript.compact_for_llm(mapping)}"


def _print_header(session: Session) -> None:
    print(f"\n==================================================")
    print(f"Przetwarzanie pliku: {session.name} (System: {session.system_name})")
    print(f"==================================================")


class _LazyClient:
    """Tworzy klienta LLM dopiero przy pierwszym użyciu (np. nie wymaga klucza, gdy nie ma nic do zrobienia)."""

    def __init__(self, provider: str):
        self.provider = provider
        self._client: LLMClient | None = None

    def get(self) -> LLMClient:
        if self._client is None:
            self._client = get_client(self.provider)
        return self._client


def name_speakers(sessions: list[Session], provider: str = LLM_PROVIDER, force: bool = False,
                  suggest_only: bool = False) -> None:
    """Interaktywne nadawanie imion mówcom w sesjach, które nie mają jeszcze mapowania.

    `suggest_only`: tylko zapisuje sugestię AI do pliku .mowcy-sugestia.md, bez pytania o imiona (dla GUI).
    """
    print("\n--- Rozpoznawanie mówców ---")
    pending = [s for s in sessions if s.has_transcript and (force or suggest_only or not s.has_speakers)]
    pending = [(s, t) for s in pending if (t := s.load_transcript()).speakers]
    if not pending:
        print("Wszystkie transkrypcje mają już przypisanych mówców.")
        return

    llm = _LazyClient(provider)
    for session, transcript in pending:
        _print_header(session)
        progress.report("sugestia mówców", session.name)
        try:
            if suggest_only:
                suggestion = suggest_speakers(llm.get(), transcript, session.campaign)
                save_suggestion(session.speaker_suggestion_path, suggestion)
                print(suggestion)
                print(f"[SUKCES] Zapisano sugestię mówców w: {session.speaker_suggestion_path}")
                continue
            mapping = identify_speakers(llm.get(), transcript, session.campaign,
                                        session.speaker_suggestion_path, suggest_for_session(session))
        except LLMError as e:
            print(f"[OSTRZEŻENIE] {e}")
            if suggest_only:
                continue
            return
        if mapping:
            save_speaker_mapping(session.txt_path, mapping)
            print(f"[SUKCES] Zapisano mówców w: {session.speakers_path}")


def summarize_sessions(sessions: list[Session], provider: str = LLM_PROVIDER, *,
                       interactive: bool, allow_unnamed: bool = False, force: bool = False) -> None:
    """Generuje podsumowania dla sesji z transkrypcją.

    Sesje bez przypisanych mówców: w trybie interaktywnym pytamy, czy je nazwać;
    w nieinteraktywnym pomijamy (chyba że `allow_unnamed`), żeby nie tworzyć kronik bez imion.
    """
    print("\n--- Generowanie podsumowań przez AI ---")
    os.makedirs(SUMMARY_DIR, exist_ok=True)

    llm = _LazyClient(provider)
    for session in sessions:
        if not session.has_transcript:
            continue
        # Jeśli podsumowanie już istnieje lokalnie lub na GDrive -> pomijamy!
        if session.has_summary and not force:
            print(f"[POMINIĘTO] Podsumowanie dla {session.name} już istnieje.")
            continue

        transcript = session.load_transcript()
        mapping = load_speaker_mapping(session.txt_path)
        if not transcript.speakers:
            pass  # starsza transkrypcja bez rozpoznawania mówców - nie ma kogo nazywać
        elif mapping:
            print(f"[INFO] {session.name}: wczytano imiona mówców z pliku .mowcy.json")
        elif interactive:
            _print_header(session)
            user_choice = input(f"Czy chcesz spróbować nadać imiona dla wykrytych mówców w {session.name}? (y/n): ").strip().lower()
            if user_choice == "y":
                try:
                    mapping = identify_speakers(llm.get(), transcript, session.campaign,
                                                session.speaker_suggestion_path, suggest_for_session(session))
                except LLMError as e:
                    print(f"[OSTRZEŻENIE] {e}")
                    return
                if mapping:
                    save_speaker_mapping(session.txt_path, mapping)
        elif not allow_unnamed:
            print(f"[POMINIĘTO] {session.name}: brak przypisanych mówców. "
                  f"Uruchom: rpg-chronicler speakers {session.name} (lub summarize --allow-unnamed)")
            continue

        try:
            client = llm.get()
        except LLMError as e:
            print(f"[OSTRZEŻENIE] {e}")
            return

        try:
            source = chronicle_source(client, session, transcript, mapping)
            progress.report("kronika", session.name)
            print(f"\n[{client.name}] Generowanie podsumowania {session.name} w klimacie '{session.system_name}'...")
            prompt = render("summary",
                            system_name=session.system_name,
                            speaker_mapping_info=speaker_mapping_info(mapping),
                            campaign_context=campaign_context(session),
                            source=source)
            summary = with_retry(lambda: client.generate(prompt), f"podsumowanie {session.name}")
        except LLMError:
            print(f"[PORAŻKA] Pomijam {session.name}.")
            continue

        with open(session.summary_path, "w", encoding="utf-8") as f:
            f.write(summary)
        print(f"[SUKCES] Zapisano kronikę ({session.system_name}) w: {session.summary_path}")
        if CHRONICLE_BRIEF:
            try:
                write_brief(client, session, summary)
            except LLMError as e:
                print(f"[OSTRZEŻENIE] Nie udało się napisać skrótu kroniki: {e} "
                      f"(spróbuj: rpg-chronicler brief {session.name})")
        if GLOSSARY_PROPOSALS:
            propose_glossary(client, session, summary)
        if CAMPAIGN_MEMORY:
            update_campaign_memory(client, session, summary)


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


def write_brief(client: LLMClient, session: Session, chronicle: str) -> str:
    """Skrót kroniki: najważniejsze wydarzenia w jednym akapicie. Rzuca LLMError."""
    progress.report("skrót kroniki", session.name)
    prompt = render("brief", system_name=session.system_name, chronicle=chronicle)
    print(f"[{client.name}] Pisanie skrótu kroniki {session.name}...")
    brief = with_retry(lambda: client.generate(prompt), f"skrót {session.name}").strip()
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
    llm = _LazyClient(provider)
    for session in pending:
        try:
            write_brief(llm.get(), session, read_chronicle(session))
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
