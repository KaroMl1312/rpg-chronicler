"""Komendy nagrań: pomiar szybkości, cisza i przycinanie, odciski głosu."""
import os

from ..session import SessionNotFound, list_sessions
from .common import audio_session


def cmd_benchmark(args):
    from ..transcription.benchmark import run_benchmark
    session = list_sessions([args.session])[0]
    if not session.audio_path:
        raise SessionNotFound(f"Sesja '{session.name}' nie ma lokalnego nagrania.")
    from ..transcription.runner import name_hints
    names = session.campaign.all_names()
    run_benchmark(session.audio_path, args.seconds, threads=args.threads, vad=args.vad,
                  batch_size=args.batch_size, diarization=not args.no_diarization,
                  diarization_models=args.diarization_models, whisper_models=args.whisper_models,
                  offset=args.offset, hotwords=name_hints(session), names=names, save_text=args.save_text)


def _analysis(session, args, force: bool):
    from .. import audio_trim
    analysis = None if force else audio_trim.load_analysis(session.name, session.audio_path)
    if analysis is None or (analysis.noise_db, analysis.min_silence) != (args.noise, args.min_silence):
        print(f"Wykrywanie ciszy w {os.path.basename(session.audio_path)} (może potrwać kilka minut)...")
        analysis = audio_trim.detect_silences(session.audio_path, session.name, args.noise, args.min_silence)
        audio_trim.save_analysis(session.name, analysis)
    return analysis


def cmd_silence(args):
    from .. import audio_trim
    session = audio_session(args.session)
    analysis = _analysis(session, args, args.force)
    fmt = audio_trim.format_timestamp
    print(f"\nNagranie: {fmt(analysis.duration)}, cisza łącznie: {fmt(analysis.silence_total)} "
          f"(fragmenty ≥ {analysis.min_silence:g} s, poniżej {analysis.noise_db:g} dB)")
    for start, end in analysis.silences:
        print(f"  cisza {fmt(start)} – {fmt(end)}  ({fmt(end - start)})")
    start, end = audio_trim.suggest_range(analysis)
    segments = audio_trim.keep_segments(analysis, start, end)
    print("\nPropozycja: " + audio_trim.describe_plan(analysis, segments))
    print(f"Przytnij: rpg-chronicler trim {session.name}  (albo --start/--end/--cut-gaps)")


def cmd_trim(args):
    from .. import audio_trim
    session = audio_session(args.session)
    if session.has_transcript and not args.force:
        raise audio_trim.TrimError(
            f"Sesja '{session.name}' ma już transkrypcję - po przycięciu czasy przestałyby pasować do nagrania. "
            "Użyj --force, jeśli na pewno chcesz.")
    analysis = _analysis(session, args, force=False)
    start, end = audio_trim.suggest_range(analysis)
    start = audio_trim.parse_timestamp(args.start) if args.start else start
    end = audio_trim.parse_timestamp(args.end) if args.end else end
    segments = audio_trim.keep_segments(analysis, start, end, args.cut_gaps)
    print(audio_trim.describe_plan(analysis, segments))
    if len(segments) == 1 and segments[0][0] <= 0.5 and segments[0][1] >= analysis.duration - 0.5:
        if audio_trim.has_duration_header(session.audio_path):
            print("Nie ma czego przycinać.")
            return
        print("Nie ma czego przycinać, ale plik nie ma zapisanej długości - zapisuję go od nowa (bez straty jakości).")
    if args.dry_run:
        return
    backup = audio_trim.trim_audio(session.audio_path, segments, session.name)
    print(f"[SUKCES] Przycięto {os.path.basename(session.audio_path)}. Oryginał: {backup}")


def cmd_voices(args):
    from ..voices import has_voiceprints

    sessions = list_sessions(args.sessions)
    if not args.sessions and not args.force:
        sessions = [s for s in sessions if not has_voiceprints(s)]
    candidates = [s for s in sessions if s.audio_path and s.has_transcript and (args.force or not has_voiceprints(s))]
    done = 0
    if candidates:  # torch i pyannote ładujemy tylko, gdy jest co liczyć
        from ..transcription.voiceprints import voiceprint_sessions
        done = voiceprint_sessions(candidates, force=args.force)
    print(f"\nPoliczono odciski głosu dla {done} sesji." if done else "Brak sesji do przetworzenia.")
    if args.sessions and len(args.sessions) == 1 and not args.no_suggest:
        _print_voice_suggestions(sessions[0])


def _print_voice_suggestions(session):
    from ..voices import suggest_for_session
    suggestions = suggest_for_session(session)
    if not suggestions:
        print("Brak podpowiedzi - nazwij mówców w innych sesjach tej kampanii, żeby program poznał ich głosy.")
        return
    print(f"\nRozpoznane głosy ({session.name}):")
    for spk in sorted(suggestions):
        s = suggestions[spk]
        kind = "pewne" if s.confident else "możliwe"
        others = ", ".join(f"{n} {score:.0%}" for n, score in s.alternatives)
        print(f"  {spk}: {s.name} ({s.score:.0%}, {kind})" + (f"   [inne: {others}]" if others else ""))
