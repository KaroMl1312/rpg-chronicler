"""Komendy CLI: rpg-chronicler <komenda> [opcje]. Bez komendy uruchamia pełny przebieg (run)."""
import argparse
import sys

from .config import LLM_PROVIDER
from .session import SessionNotFound, list_sessions

PROVIDERS = ["claude-code", "anthropic", "gemini"]


def cmd_status(args):
    sessions = list_sessions(args.sessions)
    if not sessions:
        print("Brak sesji (nagrań ani transkrypcji).")
        return
    width = max(len(s.name) for s in sessions)
    mark = lambda ok: "✓" if ok else "-"
    print(f"{'SESJA'.ljust(width)}  AUDIO  TRANSKRYPCJA  MÓWCY  PODSUMOWANIE")
    for s in sessions:
        print(f"{s.name.ljust(width)}  {mark(s.audio_path):^5}  {mark(s.has_transcript):^12}  "
              f"{mark(s.has_speakers):^5}  {mark(s.has_summary):^12}")


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
    name_speakers(list_sessions(args.sessions), args.provider, force=args.force)


def cmd_summarize(args):
    from .summary import summarize_sessions
    summarize_sessions(list_sessions(args.sessions), args.provider,
                       interactive=args.interactive, allow_unnamed=args.allow_unnamed, force=args.force)


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
    p.set_defaults(func=cmd_speakers)

    p = sub.add_parser("summarize", help="wygeneruj brakujące podsumowania")
    sessions_arg(p, "nazwy sesji (domyślnie wszystkie)")
    provider_arg(p)
    interactive_args(p)
    p.add_argument("--force", action="store_true", help="wygeneruj ponownie istniejące podsumowania")
    p.set_defaults(func=cmd_summarize)

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
