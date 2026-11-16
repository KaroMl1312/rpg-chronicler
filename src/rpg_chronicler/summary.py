"""Kronika sesji: nazwanie mówców i pisanie kronik (`summarize`).

Kontekst kampanii - context.py, kronika w dwóch krokach - chronicle_events.py,
dodatki po kronice (skrót, cytaty, słownik, stan kampanii) - after_chronicle.py, poprawki - revision.py.
"""
import os

from . import after_chronicle, memory, progress
from . import session as _session
from .chronicle_events import chronicle_source
from .campaigns import campaign_key
from .config import LLM_PROVIDER
from .context import campaign_context, speaker_mapping_info
from .llm import LazyClient, LLMError, with_retry
from .prompts import render
from .session import Session
from .speakers import identify_speakers, save_suggestion, suggest_speakers
from .transcript import load_speaker_mapping, save_speaker_mapping
from .voices import suggest_for_session


def _print_header(session: Session) -> None:
    print(f"\n==================================================")
    print(f"Przetwarzanie pliku: {session.name} (System: {session.system_name})")
    print(f"==================================================")


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

    llm = LazyClient(provider)
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
    os.makedirs(_session.SUMMARY_DIR, exist_ok=True)

    llm = LazyClient(provider)
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

        warning = memory.unaccepted_warning(campaign_key(session.name), session.name)
        if warning:
            print(f"[OSTRZEŻENIE] {warning} Zatwierdź ją przed kroniką: "
                  f"rpg-chronicler memory {campaign_key(session.name)} --accept (albo w GUI: Kampanie).")

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
        after_chronicle.run_all(client, session, summary)
