"""Dane dla nowego okna: sesje, transkrypcje, kroniki, ustawienia i klucze - jako słowniki gotowe do JSON-a.

Bez HTTP i bez GTK, więc testowane zwykłym pytestem. Kroniki zamieniamy na HTML biblioteką markdown (jest w .venv);
tekst od AI jest najpierw escapowany, żeby nie mógł wstawić do okna własnego HTML-a.
"""
import os

from .. import chronicle, envfile, notes, settings
from ..campaigns import campaign_key
from ..config import (CAMPAIGN_MEMORY, CHRONICLE_BRIEF, CHRONICLE_QUOTES, CHRONICLE_TWO_STEP, CLAUDE_CODE_MODEL,
                      GLOSSARY_PROPOSALS, LLM_PROVIDER, MODEL_SIZE, RCLONE_AUDIO_REMOTE, RCLONE_SUMMARY_REMOTE,
                      RCLONE_TXT_REMOTE, WHISPER_CPU_THREADS, WHISPER_NAME_HINTS, WHISPER_VAD)
from ..gui.text import (campaign_filter_options, format_timestamp, has_speaker_labels, session_campaign, session_stage,
                        transcript_blocks)
from .. import session as session_module
from ..session import Session, SessionNotFound, list_sessions
from ..version import VERSION, changelog

PROVIDERS = [("claude-code", "Claude Code (plan Pro/Max)"), ("anthropic", "Claude API (płatne)"), ("gemini", "Gemini")]
SPEAKER_COLORS = 8  # liczba kolorów mówców w style.css (.mowca-0 … .mowca-7)


def markdown_html(text: str) -> str:
    import markdown
    # Bez „<” tekst nie wstawi znaczników; „>” zostaje, bo w Markdown oznacza cytat
    return markdown.markdown(text.replace("&", "&amp;").replace("<", "&lt;"), extensions=["sane_lists"])


def current_provider() -> str:
    return settings.load().get("ai.dostawca", LLM_PROVIDER)


def find_session(name: str) -> Session:
    sessions = list_sessions([name])
    if not sessions:
        raise SessionNotFound(f"Nie ma sesji {name}")
    return sessions[0]


# --- lista sesji ---

def session_item(session: Session) -> dict:
    stage, done = session_stage(session)
    return {"name": session.name, "campaign": session_campaign(session), "stage": stage, "done": done,
            "discord": chronicle.discord_state(session), "notes": session.has_notes and not session.has_transcript}


def state() -> dict:
    sessions = list_sessions()
    return {
        "version": VERSION,
        "provider": current_provider(),
        "providers": [{"key": k, "label": label} for k, label in PROVIDERS],
        "sessions": [session_item(s) for s in sessions],
        "filters": [{"key": k, "label": label} for k, label in campaign_filter_options(sessions)],
        "folders": {"nagrania": session_module.AUDIO_DIR, "transkrypcje": session_module.TXT_DIR,
                    "kroniki": session_module.SUMMARY_DIR},
    }


# --- jedna sesja ---

def _provider_label(key: str) -> str:
    return dict(PROVIDERS).get(key, key)


def session_detail(name: str) -> dict:
    session = find_session(name)
    stage, done = session_stage(session)
    text = chronicle.read_chronicle(session) if session.has_summary else ""
    brief = chronicle.read_brief(session) if session.has_summary else ""
    quotes = chronicle.read_quotes(session) if session.has_summary else []
    sent = chronicle.discord_label(session)
    from_notes = session.has_notes and not session.has_transcript
    if from_notes:
        info = f"{session.system_name} · z notatek MG" + (
            " · notatki zmieniono po kronice - wygeneruj ponownie" if notes.chronicle_is_stale(session)
            else f" · {sent}" if sent else "")
    else:
        info = f"{session.system_name} · " + (sent or f"{_provider_label(current_provider())} przy ponownym "
                                                       "generowaniu")
    pdf = chronicle.pdf_path(session)
    key = campaign_key(session.name)
    from ..campaign_tools import memory
    return {
        "name": session.name,
        "campaign": key,
        "system": session.system_name,
        "date": chronicle.session_date_text(session),
        "stage": stage,
        "done": done,
        "audio": bool(session.audio_path),
        "has_transcript": session.has_transcript,
        "has_notes": session.has_notes,
        "from_notes": from_notes,
        "has_speakers": session.has_speakers,
        "has_summary": session.has_summary,
        "info": info,
        "title": chronicle.chronicle_title(text) if text else "",
        "chronicle_html": markdown_html(text) if text else "",
        "brief_html": markdown_html(brief) if brief else "",
        "brief_current": bool(brief) and chronicle.brief_is_current(session),
        "quotes": [{"text": q.text, "who": q.who, "start": q.start, "end": q.end,
                    "time": chronicle.format_quote_time(q)} for q in quotes],
        "pdf": os.path.exists(pdf),
        "pdf_current": os.path.exists(pdf) and chronicle.pdf_is_current(session),
        "discord": chronicle.discord_state(session),
        "discord_label": sent,
        # przed generowaniem kroniki okno pyta, jak w GTK: mówcy bez imion, niezatwierdzony stan kampanii
        "unnamed_speakers": session.has_transcript and not session.has_speakers and has_speaker_labels(session),
        "memory_warning": memory.unaccepted_warning(key, session.name) if key else None,
        "previous_versions": bool(text) and bool(chronicle.previous_versions(session)),
    }


def transcript(name: str) -> dict:
    """Wypowiedzi z kolorem mówcy (kolejność pierwszego pojawienia się) albo notatki MG jako HTML."""
    session = find_session(name)
    if not session.has_transcript:
        read = notes.read_notes(session) if session.has_notes else None
        return {"kind": "notatki" if read else "brak",
                "present": list(read.present) if read else [],
                "html": markdown_html(read.text) if read else ""}
    from ..transcript import load_speaker_mapping
    mapping = load_speaker_mapping(session.txt_path)
    colors: dict[str, int] = {}
    blocks = []
    for start, speaker, text in transcript_blocks(session.load_transcript(), mapping):
        if speaker is not None and speaker not in colors:
            colors[speaker] = len(colors) % SPEAKER_COLORS
        blocks.append({"start": start, "time": format_timestamp(start), "speaker": speaker,
                       "color": colors.get(speaker), "text": text})
    return {"kind": "transkrypcja", "blocks": blocks, "speakers": list(colors)}


# --- ustawienia ---

def _field(key, label, kind, default, hint="", options=None):
    values = settings.load()
    return {"key": key, "label": label, "kind": kind, "value": values.get(key, default), "hint": hint,
            "options": [{"key": k, "label": v} for k, v in options] if options else None}


def settings_payload() -> dict:
    cpu = os.cpu_count() or 2
    whisper = [("small", "Small – szybki, wyraźnie mniej dokładny"), ("medium", "Medium – dobry kompromis dla polskiego"),
               ("large-v3-turbo", "Large v3 Turbo – ok. 2,5× szybszy od Medium"),
               ("large-v3", "Large v3 – najdokładniejszy, ok. 2,6× wolniejszy od Medium")]
    groups = [
        {"title": "Sztuczna inteligencja", "description": "Kto pisze kroniki i podpowiada, kim są mówcy.", "fields": [
            _field("ai.dostawca", "Dostawca", "choice", LLM_PROVIDER, options=PROVIDERS),
            _field("ai.model_claude_code", "Model w Claude Code", "choice", CLAUDE_CODE_MODEL or "",
                   "Dotyczy tylko dostawcy Claude Code",
                   [("", "Domyślny dla konta"), ("sonnet", "Sonnet"), ("opus", "Opus"), ("haiku", "Haiku")]),
            _field("ai.propozycje_slownika", "Propozycje do słownika kampanii", "bool", GLOSSARY_PROPOSALS,
                   "Po każdej nowej kronice AI wypisuje nowe nazwy do zatwierdzenia"),
            _field("ai.skrot_kroniki", "Skrót kroniki", "bool", CHRONICLE_BRIEF,
                   "Po każdej nowej kronice AI streszcza ją w jednym akapicie"),
            _field("ai.cytaty", "Cytaty z sesji", "bool", CHRONICLE_QUOTES,
                   "Po cytacie każdej postaci i 2–3 najciekawsze wypowiedzi (PDF, Discord)"),
            _field("ai.kronika_etapami", "Kronika w dwóch krokach", "bool", CHRONICLE_TWO_STEP,
                   "Najpierw lista wydarzeń z każdych ~45 minut, potem kronika - mniej pominięć w długich sesjach"),
            _field("ai.pamiec_kampanii", "Pamięć kampanii", "bool", CAMPAIGN_MEMORY,
                   "Po każdej kronice AI aktualizuje stan kampanii (do zatwierdzenia w zakładce Kampanie)"),
        ]},
        {"title": "Transkrypcja", "description": "Zmiany obowiązują od następnej transkrypcji.", "fields": [
            _field("transkrypcja.model", "Model Whisper", "choice", MODEL_SIZE,
                   "Nowy model pobiera się przy pierwszym użyciu (do ok. 3 GB)", whisper),
            _field("transkrypcja.watki", "Wątki procesora", "int", WHISPER_CPU_THREADS,
                   f"Zwykle najszybciej przy liczbie rdzeni fizycznych ({max(1, cpu // 2)})", None),
            _field("transkrypcja.pomijanie_ciszy", "Pomijanie ciszy", "bool", WHISPER_VAD,
                   "Szybciej przy długich przerwach; może uciąć bardzo ciche wypowiedzi"),
            _field("transkrypcja.podpowiedz_nazw", "Podpowiadaj nazwy z kampanii", "bool", WHISPER_NAME_HINTS,
                   "Whisper dostaje słownik kampanii i poprawniej zapisuje imiona"),
        ]},
        {"title": "Foldery na dysku", "description": "Zmiana folderów działa po ponownym uruchomieniu programu.",
         "fields": [
             _field("foldery.nagrania", "Nagrania", "text", session_module.AUDIO_DIR),
             _field("foldery.transkrypcje", "Transkrypcje", "text", session_module.TXT_DIR),
             _field("foldery.podsumowania", "Kroniki", "text", session_module.SUMMARY_DIR),
         ]},
        {"title": "Google Drive (rclone)", "description": "Foldery zdalne w formacie remote:ścieżka.", "fields": [
            _field("google_drive.nagrania", "Nagrania", "text", RCLONE_AUDIO_REMOTE),
            _field("google_drive.transkrypcje", "Transkrypcje", "text", RCLONE_TXT_REMOTE),
            _field("google_drive.podsumowania", "Kroniki", "text", RCLONE_SUMMARY_REMOTE),
        ]},
    ]
    saved = envfile.read()
    keys = [{"title": s.title, "description": s.description,
             "keys": [{"name": k.name, "title": k.title, "secret": k.secret, "set": bool(saved.get(k.name)),
                       "value": "" if k.secret else saved.get(k.name, "")} for k in s.keys],
             "links": [{"title": t, "hint": h, "url": u} for t, h, u in s.links]} for s in envfile.SERVICES]
    return {"groups": groups, "keys": keys, "env_path": str(envfile.path())}


def save_setting(key: str, value) -> dict:
    kind = settings.field_type(key)
    if kind is None:
        raise ValueError(f"Nieznane ustawienie: {key}")
    if kind is bool:
        value = bool(value)
    elif kind is int:
        value = int(value)
    else:
        value = str(value).strip()
        if key.startswith("google_drive.") and ":" not in value:
            raise ValueError("Podaj folder w formacie remote:ścieżka")
    settings.update({key: value})
    return {"ok": True}


def save_key(name: str, value: str) -> dict:
    known = {k.name: k for s in envfile.SERVICES for k in s.keys}
    if name not in known:
        raise ValueError(f"Nieznany klucz: {name}")
    value = envfile.clean(value)
    envfile.update({name: value})
    prefix = known[name].prefix
    warning = (f"{known[name].title} zwykle zaczyna się od „{prefix}” - sprawdź, czy to właściwy klucz"
               if value and prefix and not value.startswith(prefix) else "")
    return {"ok": True, "set": bool(value), "warning": warning}


def changelog_html() -> dict:
    return {"version": VERSION, "html": markdown_html(changelog() or "Brak listy nowości.")}


def openable(path: str) -> bool:
    """Okno otwiera w systemowym programie tylko pliki z folderów danych (PDF-y, encyklopedie…)."""
    real = os.path.realpath(path)
    return os.path.isfile(real) and any(
        os.path.commonpath([real, os.path.realpath(folder)]) == os.path.realpath(folder)
        for folder in (session_module.AUDIO_DIR, session_module.TXT_DIR, session_module.SUMMARY_DIR))
