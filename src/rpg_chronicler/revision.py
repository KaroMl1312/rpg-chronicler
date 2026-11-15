"""Poprawka kroniki poleceniem dla AI (`revise`, przycisk „Popraw…”); poprzednie wersje w chronicle.py."""
from . import progress
from .after_chronicle import write_brief
from .chronicle_events import events_path
from .config import CHRONICLE_BRIEF
from .llm import LLMClient, LLMError, generate, with_retry
from .prompts import chronicle_blocks, render
from .session import Session
from .transcript import load_speaker_mapping


MIN_REVISED_RATIO = 0.3  # poprawiona kronika krótsza niż 30% obecnej = AI zgubiło treść, nie zapisujemy


class RevisionError(Exception):
    pass


def revision_source(session: Session) -> tuple[str, str]:
    """(materiał źródłowy, opis do promptu): lista wydarzeń z kroniki w dwóch krokach albo transkrypcja."""
    try:
        with open(events_path(session), encoding="utf-8") as f:
            return f.read().strip(), " oraz lista wydarzeń sesji spisana z nagrania (materiał źródłowy)"
    except OSError:
        pass
    if session.has_transcript:
        transcript = session.load_transcript().compact_for_llm(load_speaker_mapping(session.txt_path))
        return transcript, " oraz transkrypcja nagrania sesji (materiał źródłowy)"
    return "", ""


def revise_chronicle(client: LLMClient, session: Session, instruction: str) -> str:
    """Poprawia kronikę wg polecenia; poprzednia wersja trafia do kopii (chronicle.restore_previous).

    Rzuca LLMError albo RevisionError (gdy odpowiedź AI wygląda na uciętą). Po poprawce odświeża skrót.
    """
    from .chronicle import read_chronicle, save_version, write_chronicle

    current = read_chronicle(session)
    source, source_note = revision_source(session)
    prefix = chronicle_blocks([(session.name, current)])
    if source:
        prefix += f"<material_zrodlowy>\n{source}\n</material_zrodlowy>\n\n"
    info = session.campaign.prompt_info()
    prompt = render("revise", system_name=session.system_name, source_note=source_note,
                    campaign_info=f"\nInformacje o kampanii (pisownia imion i nazw):\n{info}\n" if info else "",
                    instruction=instruction.strip())
    progress.report("poprawka kroniki", session.name)
    print(f"[{client.name}] Poprawianie kroniki {session.name}: {instruction.strip()}")
    revised = with_retry(lambda: generate(client, prompt, prefix), f"poprawka {session.name}").strip()
    fenced = revised.startswith("```") and revised.endswith("```")
    if fenced:
        revised = revised.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if len(revised) < MIN_REVISED_RATIO * len(current.strip()):
        raise RevisionError(f"Poprawiona kronika ma {len(revised)} znaków zamiast ok. {len(current.strip())} - "
                            "wygląda na uciętą, nie zapisuję. Spróbuj ponownie albo sformułuj polecenie inaczej.")
    backup = save_version(session)
    write_chronicle(session, revised + "\n")
    print(f"[SUKCES] Poprawiono kronikę {session.name} (poprzednia wersja: {backup})")
    if CHRONICLE_BRIEF:
        try:
            write_brief(client, session, revised)
        except LLMError as e:
            print(f"[OSTRZEŻENIE] Nie udało się odświeżyć skrótu kroniki: {e}")
    return revised
