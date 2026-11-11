"""Komendy CLI: rpg-chronicler <komenda> [opcje]. Bez komendy uruchamia pełny przebieg (run)."""
import argparse
import os
import sys

from . import progress
from .config import DIARIZATION_MODEL, LLM_PROVIDER, WHISPER_CPU_THREADS
from .session import SessionNotFound, list_sessions

PROVIDERS = ["claude-code", "anthropic", "gemini"]


def cmd_status(args):
    sessions = list_sessions(args.sessions)
    if not sessions:
        print("Brak sesji (nagrań ani transkrypcji).")
        return
    width = max(len(s.name) for s in sessions)
    system_width = max(len("SYSTEM"), *(len(s.system_name) for s in sessions))
    mark = lambda ok: "✓" if ok else "-"
    transcript_mark = lambda s: "✓" if s.has_json else ("txt" if s.has_transcript else "-")
    print(f"{'SESJA'.ljust(width)}  {'SYSTEM'.ljust(system_width)}  AUDIO  TRANSKRYPCJA  MÓWCY  PODSUMOWANIE")
    for s in sessions:
        print(f"{s.name.ljust(width)}  {s.system_name.ljust(system_width)}  {mark(s.audio_path):^5}  "
              f"{transcript_mark(s):^12}  {mark(s.has_speakers):^5}  {mark(s.has_summary):^12}")
    if any(s.has_transcript and not s.has_json for s in sessions):
        print("\ntxt = starszy format transkrypcji; zamień na JSON komendą: rpg-chronicler migrate")


def cmd_migrate(args):
    import json
    from .transcript import Transcript

    pending = [s for s in list_sessions(args.sessions) if s.has_transcript and not s.has_json]
    if not pending:
        print("Wszystkie transkrypcje są już w formacie JSON.")
        return
    for s in pending:
        transcript = s.load_transcript()
        transcript.audio = os.path.basename(s.audio_path) if s.audio_path else None
        if transcript.segments:
            transcript.duration = transcript.segments[-1].end
        if args.dry_run:
            print(f"[PODGLĄD] {s.name}: {len(transcript.segments)} segmentów, mówcy: {len(transcript.speakers)}")
            continue
        # Zapisujemy tylko JSON - oryginalny .txt zostaje nietknięty
        with open(s.json_path, "w", encoding="utf-8") as f:
            json.dump(transcript.to_dict(), f, ensure_ascii=False, indent=1)
        print(f"[SUKCES] {s.name}: {len(transcript.segments)} segmentów -> {os.path.basename(s.json_path)}")


def cmd_sync(args):
    from .storage.drive import sync_from_gdrive
    sync_from_gdrive()


def cmd_upload(args):
    from .storage.drive import upload_to_gdrive
    upload_to_gdrive()


def cmd_transcribe(args):
    from .transcription.runner import transcribe_sessions
    transcribe_sessions(list_sessions(args.sessions))


def cmd_speakers(args):
    from .summary import name_speakers
    name_speakers(list_sessions(args.sessions), args.provider, force=args.force,
                  suggest_only=args.suggest_only)


def cmd_summarize(args):
    from .summary import summarize_sessions
    summarize_sessions(list_sessions(args.sessions), args.provider,
                       interactive=args.interactive, allow_unnamed=args.allow_unnamed, force=args.force)


def cmd_benchmark(args):
    from .transcription.benchmark import run_benchmark
    session = list_sessions([args.session])[0]
    if not session.audio_path:
        raise SessionNotFound(f"Sesja '{session.name}' nie ma lokalnego nagrania.")
    run_benchmark(session.audio_path, args.seconds, threads=args.threads, vad=args.vad,
                  batch_size=args.batch_size, diarization=not args.no_diarization,
                  diarization_models=args.diarization_models)


def _audio_session(name: str):
    session = list_sessions([name])[0]
    if not session.audio_path:
        raise SessionNotFound(f"Sesja '{session.name}' nie ma lokalnego nagrania.")
    return session


def _analysis(session, args, force: bool):
    from . import audio_trim
    analysis = None if force else audio_trim.load_analysis(session.name, session.audio_path)
    if analysis is None or (analysis.noise_db, analysis.min_silence) != (args.noise, args.min_silence):
        print(f"Wykrywanie ciszy w {os.path.basename(session.audio_path)} (może potrwać kilka minut)...")
        analysis = audio_trim.detect_silences(session.audio_path, session.name, args.noise, args.min_silence)
        audio_trim.save_analysis(session.name, analysis)
    return analysis


def cmd_silence(args):
    from . import audio_trim
    session = _audio_session(args.session)
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
    from . import audio_trim
    session = _audio_session(args.session)
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
    from .transcription.voiceprints import voiceprint_sessions
    from .voices import has_voiceprints

    sessions = list_sessions(args.sessions)
    if not args.sessions and not args.force:
        sessions = [s for s in sessions if not has_voiceprints(s)]
    done = voiceprint_sessions(sessions, force=args.force)
    print(f"\nPoliczono odciski głosu dla {done} sesji." if done else "Brak sesji do przetworzenia.")
    if args.sessions and len(args.sessions) == 1 and not args.no_suggest:
        _print_voice_suggestions(sessions[0])


def _print_voice_suggestions(session):
    from .voices import suggest_for_session
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


def _chronicle_session(name: str):
    session = list_sessions([name])[0]
    if not session.has_summary:
        raise SessionNotFound(f"Sesja '{session.name}' nie ma jeszcze kroniki.")
    return session


def _ensure_pdf(session, force: bool = False) -> str:
    from . import chronicle
    from .chronicle_pdf import write_pdf
    path = chronicle.pdf_path(session)
    if force or not chronicle.pdf_is_current(session):
        progress.report("PDF", session.name)
        write_pdf(session, path)
        print(f"[SUKCES] PDF: {path}")
    return path


def cmd_brief(args):
    from .summary import brief_sessions
    brief_sessions(list_sessions(args.sessions), args.provider, force=args.force)


def cmd_pdf(args):
    for name in args.sessions:
        _ensure_pdf(_chronicle_session(name), force=True)


def cmd_discord(args):
    from . import chronicle, discord
    from .llm import LLMError, get_client, with_retry
    from .prompts import render

    session = _chronicle_session(args.session)
    text = chronicle.read_chronicle(session)
    teaser = chronicle.read_teaser(session)
    if not teaser or args.new_teaser:
        progress.report("zapowiedź", session.name)
        prompt = render("teaser", system_name=session.system_name, chronicle=text)
        try:
            client = get_client(args.provider)
            print(f"[{client.name}] Pisanie zapowiedzi kroniki...")
            teaser = with_retry(lambda: client.generate(prompt), "zapowiedź kroniki").strip().strip('"„”')
        except LLMError as e:
            raise SessionNotFound(f"Nie udało się napisać zapowiedzi: {e}")
        chronicle.save_teaser(session, teaser)
        print(f"Zapowiedź:\n{teaser}\n")
    pdf = _ensure_pdf(session)
    if args.prepare:
        return

    webhook = chronicle.webhook_for(session.campaign.key)
    if not webhook:
        raise SessionNotFound(f"Kampania '{session.campaign.key}' nie ma ustawionego webhooka Discorda "
                              "(GUI: Kampanie → Discord).")
    if chronicle.load_sent(session) and not args.force:
        raise SessionNotFound(f"Kronikę wysłano już {chronicle.sent_text(session)} - użyj --force, żeby wysłać ponownie.")
    footer = " · ".join(p for p in (session.system_name, chronicle.session_date_text(session) or session.name) if p)
    message = discord.build_message(chronicle.chronicle_title(text), teaser, footer, os.path.basename(pdf))
    progress.report("wysyłanie na Discord", session.name)
    try:
        message_id = discord.send(webhook, message, pdf)
    except discord.DiscordError as e:
        raise SessionNotFound(str(e))
    chronicle.save_sent(session, message_id)
    print(f"[SUKCES] Wysłano kronikę {session.name} na Discord.")


def cmd_discord_test(args):
    from . import chronicle, discord
    from .campaigns import campaign_for

    campaign = campaign_for(f"{args.campaign}_")
    webhook = chronicle.webhook_for(campaign.key)
    if not webhook:
        raise SessionNotFound(f"Kampania '{args.campaign}' nie ma ustawionego webhooka Discorda.")
    message = discord.build_message(f"Kronikarz kampanii {campaign.key} melduje się!",
                                    "To wiadomość testowa - tutaj będą trafiać kroniki kolejnych sesji.",
                                    campaign.system, None)
    try:
        discord.send(webhook, message)
    except discord.DiscordError as e:
        raise SessionNotFound(str(e))
    print("[SUKCES] Wysłano wiadomość testową.")


def cmd_glossary(args):
    from . import glossary
    from .campaigns import campaign_for
    from .llm import LLMError, get_client

    campaign = campaign_for(f"{args.campaign}_")
    chronicles = glossary.chronicles_for(campaign.key, list_sessions())
    if not chronicles:
        raise SessionNotFound(f"Kampania '{args.campaign}' nie ma jeszcze żadnych kronik.")
    progress.report("propozycje słownika", campaign.key)
    try:
        proposals = glossary.extract_proposals(get_client(args.provider), campaign, chronicles)
    except (LLMError, glossary.GlossaryError) as e:
        raise SessionNotFound(f"Nie udało się zaproponować słownika: {e}")
    pending = glossary.add_proposals(campaign, proposals)
    for category in glossary.CATEGORIES:
        if proposals.get(category):
            print(f"{category}: {', '.join(proposals[category])}")
    if proposals.get(glossary.DESCRIPTION):
        print(f"opis: {proposals[glossary.DESCRIPTION]}")
    print(f"\n[SUKCES] Nowe propozycje: {glossary.count_proposals(proposals)}, oczekuje łącznie: "
          f"{glossary.count_proposals(pending)}. Zatwierdź je w GUI (Kampanie).")


def cmd_run(args):
    from .storage.drive import sync_from_gdrive, upload_to_gdrive
    from .summary import summarize_sessions
    from .transcription.runner import transcribe_sessions

    steps = 2 if args.offline else 4
    step = 0

    def header(title):
        nonlocal step
        step += 1
        print(f"\n===== [{step}/{steps}] {title} =====")

    if not args.offline:
        header("Google Drive → dysk")
        sync_from_gdrive()
    header("Transkrypcja")
    transcribe_sessions(list_sessions())
    header("Podsumowania")
    summarize_sessions(list_sessions(), args.provider,
                       interactive=args.interactive, allow_unnamed=args.allow_unnamed)
    if not args.offline:
        header("Dysk → Google Drive")
        upload_to_gdrive()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rpg-chronicler",
        description="Transkrypcje i kroniki sesji RPG z Google Drive.",
    )
    parser.set_defaults(func=cmd_run, provider=LLM_PROVIDER, interactive=None,
                        allow_unnamed=False, offline=False)
    sub = parser.add_subparsers(title="komendy", metavar="KOMENDA")

    def sessions_arg(p, help_text):
        p.add_argument("sessions", nargs="*", metavar="SESJA", help=help_text)

    def provider_arg(p):
        p.add_argument("--provider", choices=PROVIDERS, default=LLM_PROVIDER,
                       help=f"dostawca AI (domyślnie: {LLM_PROVIDER}, z LLM_PROVIDER w .env)")

    def interactive_args(p):
        group = p.add_mutually_exclusive_group()
        group.add_argument("--interactive", dest="interactive", action="store_true", default=None,
                           help="pytaj o mówców (domyślnie, gdy uruchomione w terminalu)")
        group.add_argument("--no-interactive", dest="interactive", action="store_false",
                           help="nigdy nie pytaj (np. dla crona)")
        p.add_argument("--allow-unnamed", action="store_true",
                       help="w trybie nieinteraktywnym podsumuj też sesje bez przypisanych mówców")

    p = sub.add_parser("run", help="pełny przebieg: sync → transkrypcja → podsumowania → upload (domyślne)")
    provider_arg(p)
    interactive_args(p)
    p.add_argument("--offline", action="store_true", help="pomiń pobieranie i wysyłkę na Google Drive")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("status", help="pokaż stan sesji")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie)")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("sync", help="pobierz nagrania, transkrypcje i podsumowania z Google Drive")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("transcribe", help="transkrybuj nagrania bez transkrypcji")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie)")
    p.set_defaults(func=cmd_transcribe)

    p = sub.add_parser("speakers", help="przypisz imiona mówcom (interaktywnie, z podpowiedzią AI)")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie bez mówców)")
    provider_arg(p)
    p.add_argument("--force", action="store_true", help="przypisz ponownie, nawet jeśli mapowanie istnieje")
    p.add_argument("--suggest-only", action="store_true",
                   help="tylko zapisz sugestię AI (.mowcy-sugestia.md), bez pytania o imiona")
    p.set_defaults(func=cmd_speakers)

    p = sub.add_parser("summarize", help="wygeneruj brakujące podsumowania")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie)")
    provider_arg(p)
    interactive_args(p)
    p.add_argument("--force", action="store_true", help="wygeneruj ponownie istniejące podsumowania")
    p.set_defaults(func=cmd_summarize)

    p = sub.add_parser("benchmark", help="zmierz szybkość transkrypcji na fragmencie nagrania")
    p.add_argument("session", metavar="SESJA", help="sesja z lokalnym nagraniem")
    p.add_argument("--seconds", type=int, default=300, help="długość fragmentu w sekundach (domyślnie 300)")
    p.add_argument("--threads", type=int, nargs="+", default=[WHISPER_CPU_THREADS],
                   help=f"liczby wątków do porównania, np. --threads 4 6 12 (domyślnie {WHISPER_CPU_THREADS})")
    p.add_argument("--vad", action="store_true", help="włącz pomijanie ciszy")
    p.add_argument("--batch-size", type=int, default=0, help="tryb wsadowy z podanym rozmiarem partii")
    p.add_argument("--no-diarization", action="store_true", help="pomiń pomiar rozpoznawania głosów")
    p.add_argument("--diarization-models", nargs="+", default=[DIARIZATION_MODEL], metavar="MODEL",
                   help=f"modele diaryzacji do porównania (domyślnie {DIARIZATION_MODEL})")
    p.add_argument("--no-whisper", dest="threads", action="store_const", const=[],
                   help="pomiń pomiar Whispera")
    p.set_defaults(func=cmd_benchmark)

    def silence_args(p):
        p.add_argument("session", metavar="SESJA", help="sesja z lokalnym nagraniem")
        p.add_argument("--noise", type=float, default=-40.0, metavar="DB",
                       help="próg ciszy w dB (domyślnie -40; wyżej, np. -35, przy szumach w tle)")
        p.add_argument("--min-silence", type=float, default=30.0, metavar="S",
                       help="najkrótsza wykrywana cisza w sekundach (domyślnie 30)")

    p = sub.add_parser("silence", help="wykryj ciszę w nagraniu i zaproponuj przycięcie")
    silence_args(p)
    p.add_argument("--force", action="store_true", help="wykryj ponownie, nawet jeśli jest zapisana analiza")
    p.set_defaults(func=cmd_silence)

    p = sub.add_parser("trim", help="przytnij ciszę na początku/końcu nagrania (oryginał trafia do oryginaly/)")
    silence_args(p)
    p.add_argument("--start", metavar="GG:MM:SS", help="początek zachowanego fragmentu (domyślnie: koniec ciszy)")
    p.add_argument("--end", metavar="GG:MM:SS", help="koniec zachowanego fragmentu (domyślnie: początek ciszy)")
    p.add_argument("--cut-gaps", type=float, default=0, metavar="MIN",
                   help="wytnij też przerwy w środku dłuższe niż MIN minut (domyślnie 0 = nie wycinaj)")
    p.add_argument("--force", action="store_true", help="przytnij mimo istniejącej transkrypcji")
    p.add_argument("--dry-run", action="store_true", help="tylko pokaż plan")
    p.set_defaults(func=cmd_trim)

    p = sub.add_parser("voices", help="policz odciski głosu mówców (do rozpoznawania graczy w kolejnych sesjach)")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie bez odcisków)")
    p.add_argument("--force", action="store_true", help="policz ponownie istniejące odciski")
    p.add_argument("--no-suggest", action="store_true", help="nie pokazuj podpowiedzi imion po policzeniu")
    p.set_defaults(func=cmd_voices)

    p = sub.add_parser("brief", help="napisz skrót kroniki (najważniejsze wydarzenia w jednym akapicie)")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie z kroniką bez aktualnego skrótu)")
    provider_arg(p)
    p.add_argument("--force", action="store_true", help="napisz ponownie, nawet jeśli skrót jest aktualny")
    p.set_defaults(func=cmd_brief)

    p = sub.add_parser("pdf", help="zapisz kronikę jako PDF (obok kroniki, w folderze kronik)")
    p.add_argument("sessions", nargs="+", metavar="SESJA")
    p.set_defaults(func=cmd_pdf)

    p = sub.add_parser("discord", help="wyślij kronikę na kanał Discord kampanii (zapowiedź + PDF)")
    p.add_argument("session", metavar="SESJA")
    provider_arg(p)
    p.add_argument("--przygotuj", dest="prepare", action="store_true",
                   help="tylko przygotuj zapowiedź i PDF, bez wysyłania")
    p.add_argument("--nowa-zapowiedz", dest="new_teaser", action="store_true", help="napisz zapowiedź od nowa (AI)")
    p.add_argument("--force", action="store_true", help="wyślij ponownie, nawet jeśli już wysłano")
    p.set_defaults(func=cmd_discord)

    p = sub.add_parser("discord-test", help="wyślij wiadomość testową na kanał Discord kampanii")
    p.add_argument("campaign", metavar="KAMPANIA")
    p.set_defaults(func=cmd_discord_test)

    p = sub.add_parser("glossary", help="AI proponuje słownik kampanii (nazwy) na podstawie jej kronik")
    p.add_argument("campaign", metavar="KAMPANIA", help="klucz kampanii, np. Warhammer")
    provider_arg(p)
    p.set_defaults(func=cmd_glossary)

    p = sub.add_parser("migrate", help="zamień starsze transkrypcje .txt na format JSON")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie)")
    p.add_argument("--dry-run", action="store_true", help="tylko pokaż, co zostanie zrobione")
    p.set_defaults(func=cmd_migrate)

    p = sub.add_parser("upload", help="wyślij transkrypcje i podsumowania na Google Drive")
    p.set_defaults(func=cmd_upload)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.interactive is None:
        args.interactive = sys.stdin.isatty()
    try:
        args.func(args)
    except SessionNotFound as e:
        print(f"[BŁĄD] {e}", file=sys.stderr)
        return 1
    except Exception as e:
        from .audio_trim import TrimError
        if not isinstance(e, (TrimError, ValueError)) or args.func not in (cmd_silence, cmd_trim):
            raise
        print(f"[BŁĄD] {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nPrzerwano.", file=sys.stderr)
        return 130
    return 0
