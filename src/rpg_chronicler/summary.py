import os

from . import glossary, progress
from .campaigns import campaign_key, session_date
from .config import GLOSSARY_PROPOSALS, LLM_PROVIDER, SUMMARY_DIR
from .llm import LLMClient, LLMError, get_client, with_retry
from .prompts import render
from .session import Session, list_sessions
from .speakers import identify_speakers, save_suggestion, suggest_speakers
from .transcript import load_speaker_mapping, save_speaker_mapping
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


def campaign_context(session: Session) -> str:
    """Opis kampanii, postacie graczy, słownik nazw i poprzednia kronika - dla ciągłości i poprawnej pisowni."""
    parts = []
    info = session.campaign.prompt_info()
    if info:
        parts.append(f"Informacje o kampanii (użyj ich, by poprawnie zapisywać imiona i nazwy):\n{info}")
    previous = previous_session(session)
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

        progress.report("kronika", session.name)
        print(f"\n[{client.name}] Generowanie podsumowania {session.name} w klimacie '{session.system_name}'...")
        prompt = render("summary",
                        system_name=session.system_name,
                        speaker_mapping_info=speaker_mapping_info(mapping),
                        campaign_context=campaign_context(session),
                        transcript=transcript.compact_for_llm(mapping))
        try:
            summary = with_retry(lambda: client.generate(prompt), f"podsumowanie {session.name}")
        except LLMError:
            print(f"[PORAŻKA] Pomijam {session.name}.")
            continue

        with open(session.summary_path, "w", encoding="utf-8") as f:
            f.write(summary)
        print(f"[SUKCES] Zapisano kronikę ({session.system_name}) w: {session.summary_path}")
        if GLOSSARY_PROPOSALS:
            propose_glossary(client, session, summary)


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
