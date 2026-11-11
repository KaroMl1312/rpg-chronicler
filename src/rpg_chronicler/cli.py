"""Komendy CLI: rpg-chronicler <komenda> [opcje]. Bez komendy uruchamia pełny przebieg (run)."""
import argparse
import os
import sys

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
    except KeyboardInterrupt:
        print("\nPrzerwano.", file=sys.stderr)
        return 130
    return 0
