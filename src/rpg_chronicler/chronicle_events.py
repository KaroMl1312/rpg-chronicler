"""Kronika w dwóch krokach: z każdej części transkrypcji (~45 min) lista wydarzeń, potem kronika z tych list.

Listy części są zapamiętywane w ~/.cache/rpg-chronicler/wydarzenia/<sesja>/ (klucz = treść zapytania).
"""
import hashlib
import os
from pathlib import Path

from . import progress
from . import session as _session
from .config import CHRONICLE_PART_SECONDS, CHRONICLE_TWO_STEP
from .context import campaign_context, speaker_mapping_info
from .llm import LLMClient, generate, with_retry
from .prompts import render_split
from .quality import format_time
from .session import Session
from .transcript import Transcript


PREVIOUS_EVENTS_LIMIT = 8000  # znaków z listy wydarzeń poprzedniej części (kontekst dla następnej)


def events_path(session: Session) -> str:
    """Lista wydarzeń sesji (krok pośredni kroniki) - obok kroniki, do wglądu."""
    return os.path.join(_session.SUMMARY_DIR, f"{session.name}_wydarzenia.md")


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
        # Początek (zasady, mówcy, kampania) jest taki sam dla wszystkich części - cache w API
        prefix, prompt = render_split(
            "events", system_name=session.system_name, part=str(index), parts=str(len(parts)),
            time_range=time_range, speaker_mapping_info=mapping_info, campaign_context=context,
            previous_events=previous_block, transcript=part.compact_for_llm(mapping))
        cache = cache_dir / f"{hashlib.sha1((prefix + prompt).encode('utf-8')).hexdigest()}.md"
        try:
            text = cache.read_text(encoding="utf-8")
            print(f"[INFO] Wydarzenia części {index}/{len(parts)} ({time_range}) z pamięci podręcznej.")
        except OSError:
            progress.report("wydarzenia", session.name, index - 1, len(parts))
            print(f"[{client.name}] Wydarzenia części {index}/{len(parts)} ({time_range})...")
            text = with_retry(lambda: generate(client, prompt, prefix),
                              f"wydarzenia {session.name} {index}/{len(parts)}")
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
