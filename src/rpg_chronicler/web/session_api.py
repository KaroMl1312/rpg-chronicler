"""Dane nowego okna do pracy z sesją (etap 2): mówcy, Discord, notatki MG, usuwanie, wyszukiwarka, nagranie.

Jak api.py - bez HTTP, słowniki gotowe do JSON-a. Logika ta sama co w oknie GTK (gui/speakers_page.py itd.).
"""
import datetime
import os

from .. import chronicle, discord, notes, voices
from ..campaigns import campaign_key, load_campaigns
from ..gui.text import format_minutes, format_timestamp, highlight_markup
from ..maintenance import deletion
from ..search import KIND_CHRONICLE, KIND_NOTES, TranscriptCache, search, summary_line
from ..session import list_sessions
from ..transcript import load_speaker_mapping, save_speaker_mapping
from .api import find_session, markdown_html

SAMPLE_COUNT = 5
SAMPLE_TEXT_LIMIT = 220
SEARCH_LIMIT = 300
_search_cache = TranscriptCache()


# --- mówcy -------------------------------------------------------------------------------------------

def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def _voice(s: voices.Suggestion | None) -> dict | None:
    if s is None:
        return None
    return {"name": s.name, "score": round(s.score, 2), "confident": s.confident,
            "alternatives": [{"name": n, "score": round(v, 2)} for n, v in s.alternatives]}


def speakers(name: str) -> dict:
    session = find_session(name)
    if not session.has_transcript:
        return {"state": "brak-transkrypcji"}
    transcript = session.load_transcript()
    if not transcript.speakers:
        return {"state": "bez-mowcow"}
    sessions = list_sessions()
    suggestions = voices.suggest_for_session(session, sessions)
    mapping = load_speaker_mapping(session.txt_path)
    stats = transcript.speaker_stats()

    to_compute = [s.name for s in voices.learning_candidates(session.campaign, sessions) if s.name != session.name]
    this_missing = bool(session.audio_path) and not voices.has_voiceprints(session)
    if this_missing:
        to_compute.insert(0, session.name)
    if to_compute:
        parts = ["Ta sesja nie ma jeszcze policzonych odcisków głosu."] if this_missing else []
        others = len(to_compute) - this_missing
        if others:
            parts.append(f"{others} nazwanych sesji kampanii nie ma odcisków - z nich program pozna głosy graczy.")
        voice_info = " ".join(parts) + " Zajmuje to ok. 10 s na sesję."
    elif suggestions:
        confident = sum(s.confident for s in suggestions.values())
        voice_info = (f"Rozpoznano po głosie: {confident} pewnie, {len(suggestions) - confident} możliwie "
                      "(podpowiedzi przy mówcach).")
    else:
        voice_info = ("Nazwij mówców w kilku sesjach tej kampanii - w kolejnych program rozpozna graczy po głosie "
                      "i sam podpowie imiona.")

    names = ["MG", *session.campaign.player_characters]
    for s in suggestions.values():
        for n in (s.name, *(alt for alt, _ in s.alternatives)):
            if n.casefold() not in {x.casefold() for x in names}:
                names.append(n)

    rows = []
    # Najpierw najdłużej mówiący (MG i gracze), na końcu przypadkowe głosy i szumy
    for spk in sorted(transcript.speakers, key=lambda spk: -stats.get(spk, (0, 0.0))[1]):
        count, seconds = stats.get(spk, (0, 0.0))
        samples = [{"start": x.start, "end": x.end, "time": format_timestamp(x.start), "seconds": round(x.end - x.start),
                    "text": x.text if len(x.text) <= SAMPLE_TEXT_LIMIT else x.text[:SAMPLE_TEXT_LIMIT] + "…"}
                   for x in transcript.speaker_samples(spk, SAMPLE_COUNT)]
        rows.append({"label": spk, "name": mapping.get(spk, ""), "count": count, "minutes": format_minutes(seconds),
                     "voice": _voice(suggestions.get(spk)), "samples": samples})
    # Nowa sesja bez imion: pewne rozpoznania głosu do wpisania (zapis dopiero po zatwierdzeniu)
    prefill = ({spk: s.name for spk, s in suggestions.items() if s.confident}
               if not session.has_speakers else {})
    suggestion = _read_text(session.speaker_suggestion_path)
    return {"state": "ok", "rows": rows, "suggestion_html": markdown_html(suggestion) if suggestion else "",
            "voice_info": voice_info, "to_compute": to_compute, "has_suggestions": bool(suggestions),
            "names": [{"name": n, "player": session.campaign.player_characters.get(n, "")} for n in names],
            "prefill": prefill, "audio": bool(session.audio_path and os.path.exists(session.audio_path))}


def save_speakers(name: str, mapping: dict) -> dict:
    session = find_session(name)
    known = set(session.load_transcript().speakers)
    cleaned = {str(k): str(v).strip() for k, v in mapping.items() if k in known and str(v).strip()}
    if not cleaned:
        raise ValueError("Wpisz imię przynajmniej jednego mówcy")
    save_speaker_mapping(session.txt_path, cleaned)
    return {"ok": True, "has_summary": session.has_summary}


# --- nagranie ------------------------------------------------------------------------------------

def audio_path(name: str) -> str:
    session = find_session(name)
    if not session.audio_path or not os.path.exists(session.audio_path):
        raise ValueError("Brak lokalnego nagrania tej sesji")
    return session.audio_path


# --- Discord ---------------------------------------------------------------------------------------

def discord_info(name: str) -> dict:
    session = find_session(name)
    key = session.campaign.key
    quotes = chronicle.read_quotes(session)
    return {"campaign": key, "webhook": bool(chronicle.webhook_for(key)), "teaser": chronicle.read_teaser(session),
            "quotes": [f"„{q.text}”" + (f" — {q.who}" if q.who else "") for q in quotes],
            "pdf_name": os.path.basename(chronicle.pdf_path(session)), "pdf_current": chronicle.pdf_is_current(session),
            "sent": chronicle.sent_text(session), "resend": bool(chronicle.load_sent(session))}


def save_webhook(campaign: str, url: str) -> dict:
    if not discord.is_valid_webhook(url):
        raise ValueError("To nie jest adres webhooka Discorda (https://discord.com/api/webhooks/…)")
    chronicle.set_webhook(campaign, url.strip())
    return {"ok": True}


def save_teaser(name: str, text: str) -> dict:
    session = find_session(name)
    if text.strip():
        chronicle.save_teaser(session, text.strip())
    else:  # wyczyszczona zapowiedź - AI napisze nową przy wysyłaniu
        try:
            os.remove(chronicle.teaser_path(session))
        except FileNotFoundError:
            pass
    return {"ok": True}


def set_sent(name: str, sent: bool) -> dict:
    session = find_session(name)
    (chronicle.mark_sent if sent else chronicle.unmark_sent)(session)
    return {"ok": True}


# --- notatki MG ------------------------------------------------------------------------------------

def known_campaigns() -> list[str]:
    keys = set(load_campaigns()) | {k for s in list_sessions() if (k := campaign_key(s.name))}
    return sorted(keys, key=str.casefold)


def notes_form(name: str | None, campaign: str | None) -> dict:
    """Dane okna notatek: nowa sesja (name None) albo edycja istniejącej."""
    current = notes.read_notes(find_session(name)) if name else None
    key = campaign_key(name) if name else (campaign or "")
    return {"campaigns": known_campaigns(), "campaign": key, "text": current.text if current else "",
            "present": list(current.present) if current else None,
            "characters": characters(key), "has_summary": bool(name) and find_session(name).has_summary}


def characters(key: str) -> list[str]:
    campaign = load_campaigns().get(key) if key else None
    return list(campaign.player_characters) if campaign else []


def notes_name(campaign: str, date: str) -> dict:
    """Nazwa nowej sesji z kampanii i daty (RRRR-MM-DD) albo powód, dla którego nie można jej użyć."""
    try:
        name = notes.session_name(campaign.strip(), datetime.date.fromisoformat(date))
        notes.check_new_name(name)
    except (notes.NotesError, ValueError) as e:
        return {"name": "", "error": str(e), "characters": characters(campaign.strip())}
    return {"name": name, "error": "", "characters": characters(campaign.strip())}


def save_notes(name: str | None, campaign: str, date: str, text: str, present: list[str]) -> dict:
    if not name:
        info = notes_name(campaign, date)
        if info["error"]:
            raise ValueError(info["error"])
        name = info["name"]
    try:
        notes.save_notes(name, notes.Notes(text, tuple(present)))
    except notes.NotesError as e:
        raise ValueError(str(e)) from e
    return {"name": name}


# --- usuwanie --------------------------------------------------------------------------------------

def delete_plan(name: str, scope: str) -> dict:
    session = find_session(name)
    try:
        plan = deletion.plan(name, scope)
    except deletion.DeletionError as e:
        raise ValueError(str(e)) from e
    headings = {deletion.CHRONICLE: "Usunąć kronikę?", deletion.RESTART: "Zacząć sesję od nowa?",
                deletion.SESSION: "Usunąć całą sesję?"}
    effects = {
        deletion.CHRONICLE: "Kronika, skrót, cytaty, PDF i zapowiedź znikną. Transkrypcja"
                            + (" i notatki zostają" if session.has_notes else " i mówcy zostają")
                            + " - kronikę można potem napisać od nowa.",
        deletion.RESTART: "Zostanie tylko nagranie. Znikną transkrypcja, mówcy, odciski głosu, kronika i wszystko, "
                          "co z niej powstało - sesja wróci do etapu „czeka na transkrypcję”.",
        deletion.SESSION: "Sesja zniknie z listy: nagranie, transkrypcja albo notatki, kronika i wszystko, "
                          "co z nich powstało.",
    }
    body = (f"{effects[scope]}\n\nPliki ({len(plan.files)}) zostaną usunięte z dysku i z Google Drive. "
            f"Przez {deletion.TRASH_DAYS} dni będą w koszu Google Drive i w koszu aplikacji "
            f"(przywrócenie: rpg-chronicler delete {name} --undo).")
    return {"heading": headings[scope], "body": body, "files": deletion.describe(plan),
            "confirm": "Rozumiem, że usuwam całą sesję razem z nagraniem" if scope == deletion.SESSION else "",
            "button": "Usuń i zacznij od nowa" if scope == deletion.RESTART else "Usuń",
            "label": deletion.SCOPE_LABELS[scope], "warnings": deletion.campaign_warnings(name)}


def delete_options(name: str) -> list[dict]:
    session = find_session(name)
    return [{"scope": deletion.CHRONICLE, "label": "Usuń kronikę…", "enabled": session.has_summary},
            {"scope": deletion.RESTART, "label": "Zacznij od nowa (zostaw nagranie)…",
             "enabled": session.audio_path is not None and (session.has_source or session.has_summary)},
            {"scope": deletion.SESSION, "label": "Usuń całą sesję…", "enabled": True}]


# --- wyszukiwarka ----------------------------------------------------------------------------------

def run_search(query: str, campaign: str | None, chronicles: bool, transcripts: bool) -> dict:
    sessions = {s.name: s for s in list_sessions()}
    hits = search(sessions.values(), query, campaign=campaign or None, chronicles=chronicles,
                  transcripts=transcripts, cache=_search_cache) if query.strip() else []
    rows = []
    for hit in hits[:SEARCH_LIMIT]:
        session = sessions.get(hit.session)
        rows.append({
            "session": hit.session, "kind": hit.kind, "heading": hit.heading, "speaker": hit.speaker,
            "time": format_timestamp(hit.start) if hit.start is not None else "",
            "start": hit.start, "end": hit.end, "html": highlight_markup(hit.text, query),
            "tab": "kronika" if hit.kind == KIND_CHRONICLE else "transkrypcja",
            "audio": hit.start is not None and session is not None and bool(session.audio_path),
            "notes": hit.kind == KIND_NOTES,
        })
    more = f" (pokazano {SEARCH_LIMIT})" if len(hits) > SEARCH_LIMIT else ""
    return {"summary": (summary_line(hits) + more) if query.strip() else
            "Wyniki od najstarszej sesji - pierwszy to pierwsze pojawienie się.", "hits": rows,
            "campaigns": known_campaigns()}
