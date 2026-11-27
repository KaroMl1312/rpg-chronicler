"""Dane nowego okna (etap 4): panel nagrania przed transkrypcją, uwagi jakości, statystyki, „Uzupełnij brakujące”.

Jak api.py - bez HTTP, słowniki gotowe do JSON-a.
"""
import os

from .. import audio_trim, quality, stats
from .text import format_minutes
from ..maintenance import backfill
from ..session import list_sessions
from ..transcript import Transcript, load_speaker_mapping
from .api import find_session

SENSITIVITY = [(-45.0, "Tylko całkowita cisza"), (-40.0, "Standardowa"),
               (-35.0, "Cisza z szumem w tle"), (-30.0, "Głośne tło (wentylator, ulica)")]
EDGE = 0.5   # sekundy: zakres różniący się o mniej to całe nagranie


def _duration(seconds: float) -> str:
    return format_minutes(seconds) if seconds >= 60 else f"{round(seconds)} s"


# --- panel nagrania ------------------------------------------------------------------------------------------

def _audio(name: str):
    session = find_session(name)
    if not session.audio_path or not os.path.exists(session.audio_path):
        raise ValueError("Brak lokalnego nagrania tej sesji")
    return session


def recording(name: str) -> dict:
    session = _audio(name)
    path = session.audio_path
    error = ""
    try:
        audio_trim.require_ffmpeg()
    except audio_trim.TrimError as e:
        error = str(e)
    analysis = None if error else audio_trim.load_analysis(session.name, path)
    size = os.path.getsize(path)
    details = [f"{size / 1e9:.2f} GB" if size >= 1e8 else f"{size / 1e6:.1f} MB"]
    result = {"file": os.path.basename(path), "error": error, "header_ok": audio_trim.has_duration_header(path),
              "sensitivity": [{"value": value, "label": label} for value, label in SENSITIVITY],
              "noise": audio_trim.DEFAULT_NOISE_DB, "analysis": None, "version": str(os.stat(path).st_mtime_ns)}
    if analysis is not None:
        details.insert(0, format_minutes(analysis.duration))
        start, end = audio_trim.suggest_range(analysis)
        result["noise"] = analysis.noise_db
        result["analysis"] = {
            "duration": analysis.duration, "min_silence": analysis.min_silence,
            "total": _duration(analysis.silence_total),
            "silences": [{"start": s, "end": e, "duration": _duration(e - s),
                          "label": f"{audio_trim.format_timestamp(s)} – {audio_trim.format_timestamp(e)}"}
                         for s, e in analysis.silences],
            "start": audio_trim.format_timestamp(start), "end": audio_trim.format_timestamp(end)}
    result["details"] = " · ".join(details)
    return result


def trim_plan(name: str, start: str, end: str, gaps: float) -> dict:
    """Co zostanie po przycięciu (podgląd na osi czasu) i argumenty komendy `trim`. Błąd w polu → {"error": …}."""
    session = _audio(name)
    analysis = audio_trim.load_analysis(session.name, session.audio_path)
    if analysis is None:
        return {"error": "Nagranie zmieniło się - wykryj ciszę ponownie."}
    try:
        begin = min(audio_trim.parse_timestamp(start), analysis.duration)
        finish = min(audio_trim.parse_timestamp(end), analysis.duration)
        segments = audio_trim.keep_segments(analysis, begin, finish, gaps)
    except (ValueError, audio_trim.TrimError) as e:
        return {"error": str(e)}
    if not segments:
        return {"error": "Nie ma nic do zachowania."}
    inside = [e - s for s, e in analysis.silences if s > begin and e < finish]
    whole = len(segments) == 1 and segments[0][0] <= EDGE and segments[0][1] >= analysis.duration - EDGE
    changes = not whole or not audio_trim.has_duration_header(session.audio_path)
    fmt = audio_trim.format_timestamp
    return {"error": "", "segments": segments, "text": audio_trim.describe_plan(analysis, segments), "changes": changes,
            "start": begin, "end": finish, "longest": _duration(max(inside)) if inside and max(inside) >= 60 else "",
            "backup": audio_trim.BACKUP_DIR_NAME,
            "args": ["trim", session.name, "--start", fmt(begin), "--end", fmt(finish), "--cut-gaps", f"{gaps:g}",
                     "--noise", f"{analysis.noise_db:g}", "--min-silence", f"{analysis.min_silence:g}"]}


# --- transkrypcja: informacje, uwagi jakości, statystyki ---------------------------------------------------------

def transcript_info(session, transcript: Transcript) -> dict:
    parts = []
    duration = transcript.duration or (transcript.segments[-1].end if transcript.segments else 0)
    if duration:
        parts.append(f"nagranie {format_minutes(duration)}")
    parts.append(f"{len(transcript.segments)} segmentów")
    if transcript.speakers:
        parts.append(f"{len(transcript.speakers)} mówców")
    if not session.has_json:
        parts.append("starszy format .txt")
    issues = quality.check(transcript)
    return {"info": " · ".join(parts), "issues": [{"kind": i.kind, "text": i.message, "at": i.at} for i in issues],
            "loops": any(i.kind == "petla" for i in issues), "undo_loops": bool(quality.backups(session)),
            "stats": bool(transcript.segments)}


def session_stats(name: str, campaign: bool = False) -> dict:
    """Statystyki sesji albo suma wszystkich sesji jej kampanii."""
    session = find_session(name)
    sessions = [session]
    if campaign and session.campaign.key:
        sessions = [s for s in list_sessions() if s.campaign.key == session.campaign.key]
    results = [stats.session_stats(s.load_transcript(), load_speaker_mapping(s.txt_path), s.campaign)
               for s in sessions if s.has_transcript]
    if not results:
        raise ValueError("Brak transkrypcji do policzenia")
    total = stats.merge_stats(results) if campaign else results[0]
    fmt = stats.format_duration
    summary = [f"Nagranie {fmt(total.duration)}, gra {fmt(total.play_seconds)}, {stats.breaks_text(total)}"]
    if total.gm_seconds:
        players = sum(s.seconds for s in total.players)
        summary.append(f"MG {total.share(total.gm_seconds):.0%} · gracze {total.share(players):.0%} czasu mówienia")
    return {"campaign": session.campaign.key, "count": len(results), "summary": summary,
            "speakers": [{"name": s.name, "share": round(total.share(s.seconds), 4), "time": fmt(s.seconds),
                          "details": f"{s.utterances} wypowiedzi, {s.words} słów"} for s in total.speakers]}


# --- uzupełnij brakujące -------------------------------------------------------------------------------------------

def backfill_plan() -> dict:
    steps = backfill.plan(list_sessions())
    return {"count": len(steps), "summary": backfill.summary(steps), "requests": backfill.ai_requests(steps)}
