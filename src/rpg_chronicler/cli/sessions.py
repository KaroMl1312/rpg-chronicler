"""Komendy przebiegu: stan sesji, Drive, transkrypcja, mówcy, kroniki, migracja i archiwizacja."""
import os

from ..session import list_sessions


def cmd_status(args):
    from ..quality import check_sessions

    sessions = list_sessions(args.sessions)
    if not sessions:
        print("Brak sesji (nagrań ani transkrypcji).")
        return
    issues = check_sessions(sessions)
    width = max(len(s.name) for s in sessions)
    system_width = max(len("SYSTEM"), *(len(s.system_name) for s in sessions))
    mark = lambda ok: "✓" if ok else "-"
    transcript_mark = lambda s: "✓" if s.has_json else ("txt" if s.has_transcript else "-")
    print(f"{'SESJA'.ljust(width)}  {'SYSTEM'.ljust(system_width)}  AUDIO  TRANSKRYPCJA  MÓWCY  PODSUMOWANIE  UWAGI")
    for s in sessions:
        count = len(issues.get(s.name, []))
        print(f"{s.name.ljust(width)}  {s.system_name.ljust(system_width)}  {mark(s.audio_path):^5}  "
              f"{transcript_mark(s):^12}  {mark(s.has_speakers):^5}  {mark(s.has_summary):^12}  "
              f"{'!' * min(count, 3) if count else ''}")
    if any(issues.values()):
        print("\n! = podejrzane miejsca w transkrypcji; szczegóły: rpg-chronicler check")
    if any(s.has_transcript and not s.has_json for s in sessions):
        print("\ntxt = starszy format transkrypcji; zamień na JSON komendą: rpg-chronicler migrate")


def cmd_check(args):
    from ..quality import check_sessions

    sessions = list_sessions(args.sessions)
    results = check_sessions(sessions, probe_audio=True)
    if not results:
        print("Brak transkrypcji do sprawdzenia.")
        return
    bad = {name: issues for name, issues in results.items() if issues}
    for name, issues in bad.items():
        print(f"\n{name}:")
        for issue in issues:
            print(f"  [OSTRZEŻENIE] {issue.message}")
    ok = len(results) - len(bad)
    print(f"\nSprawdzono {len(results)} transkrypcji: {ok} bez uwag, {len(bad)} z uwagami.")


def cmd_migrate(args):
    import json

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


def cmd_archive(args):
    from ..archive import ArchiveError, archive_local

    failed = False
    for s in list_sessions(args.sessions):
        prefix = "[PODGLĄD] " if args.dry_run else ""
        try:
            moves = archive_local(s.name, dry_run=args.dry_run)
        except ArchiveError as e:
            print(f"[BŁĄD] {e}")
            failed = True
            continue
        for move in moves:
            print(f"  {prefix}{move.src} -> {os.path.relpath(move.dst, os.path.dirname(move.src))}")
        if not args.offline:
            from ..storage.drive import archive_on_gdrive
            try:
                archive_on_gdrive(s.name, dry_run=args.dry_run)
            except Exception as e:
                print(f"[OSTRZEŻENIE] Nie udało się przenieść plików {s.name} na Google Drive: {e}. "
                      "Bez tego `sync` pobierze je z powrotem - powtórz komendę albo przenieś je ręcznie.")
                failed = True
                continue
        if not args.dry_run:
            print(f"[SUKCES] {s.name}: zarchiwizowano ({len(moves)} plików lokalnie).")
    return 1 if failed else 0


def cmd_sync(args):
    from ..storage.drive import sync_from_gdrive
    sync_from_gdrive()


def cmd_upload(args):
    from ..storage.drive import upload_to_gdrive
    upload_to_gdrive()


def cmd_transcribe(args):
    from ..transcription.runner import transcribe_sessions
    transcribe_sessions(list_sessions(args.sessions))


def cmd_speakers(args):
    from ..summary import name_speakers
    name_speakers(list_sessions(args.sessions), args.provider, force=args.force,
                  suggest_only=args.suggest_only)


def cmd_summarize(args):
    from ..summary import summarize_sessions
    summarize_sessions(list_sessions(args.sessions), args.provider,
                       interactive=args.interactive, allow_unnamed=args.allow_unnamed, force=args.force)


def cmd_run(args):
    from ..storage.drive import sync_from_gdrive, upload_to_gdrive
    from ..summary import summarize_sessions
    from ..transcription.runner import transcribe_sessions

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
