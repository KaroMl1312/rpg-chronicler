"""Komendy przebiegu: stan sesji, Drive, transkrypcja, mówcy, kroniki, migracja i archiwizacja."""
import os

from ..session import list_sessions


def cmd_status(args):
    from .. import chronicle
    from ..quality import check_sessions

    sessions = list_sessions(args.sessions)
    if not sessions:
        print("Brak sesji (nagrań ani transkrypcji).")
        return
    issues = check_sessions(sessions)
    width = max(len(s.name) for s in sessions)
    system_width = max(len("SYSTEM"), *(len(s.system_name) for s in sessions))
    mark = lambda ok: "✓" if ok else "-"
    transcript_mark = lambda s: "✓" if s.has_json else ("txt" if s.has_transcript else
                                                        ("notatki" if s.has_notes else "-"))
    discord_mark = {chronicle.NOT_SENT: "-", chronicle.SENT: "✓", chronicle.SENT_OLDER: "starsza"}
    print(f"{'SESJA'.ljust(width)}  {'SYSTEM'.ljust(system_width)}  AUDIO  TRANSKRYPCJA  MÓWCY  PODSUMOWANIE  "
          "DISCORD  UWAGI")
    for s in sessions:
        count = len(issues.get(s.name, []))
        print(f"{s.name.ljust(width)}  {s.system_name.ljust(system_width)}  {mark(s.audio_path):^5}  "
              f"{transcript_mark(s):^12}  {mark(s.has_speakers):^5}  {mark(s.has_summary):^12}  "
              f"{discord_mark[chronicle.discord_state(s)] if s.has_summary else '':^7}  "
              f"{'!' * min(count, 3) if count else ''}")
    if any(issues.values()):
        print("\n! = podejrzane miejsca w transkrypcji; szczegóły: rpg-chronicler check")
    if any(s.has_transcript and not s.has_json for s in sessions):
        print("\ntxt = starszy format transkrypcji; zamień na JSON komendą: rpg-chronicler migrate")
    if any(s.has_summary and chronicle.discord_state(s) == chronicle.SENT_OLDER for s in sessions):
        print("\nstarsza = na Discordzie jest wersja sprzed poprawki kroniki")
    if any(s.has_summary and chronicle.discord_state(s) == chronicle.NOT_SENT for s in sessions):
        print("\nKronikę wysłano ręcznie? Oznacz ją: rpg-chronicler discord SESJA --oznacz")
    if any(s.has_notes for s in sessions):
        print("\nnotatki = sesja bez nagrania, kronika z notatek MG (rpg-chronicler add-session)")


def cmd_add_session(args):
    """Sesja bez nagrania: zapisuje notatki MG jako <nazwa>.notatki.md (kronikę pisze potem `summarize`)."""
    import sys

    from .. import notes
    from ..session import Session, SessionNotFound

    if args.file == "-":
        text = sys.stdin.read()
    else:
        try:
            with open(args.file, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            raise SessionNotFound(f"Nie można odczytać notatek: {e}")
    session = Session(args.session)
    try:
        if session.has_notes and args.replace:
            pass   # poprawione notatki istniejącej sesji z notatek
        else:
            notes.check_new_name(args.session)
        present = tuple(n.strip() for n in (args.present or "").split(",") if n.strip())
        if not present and session.has_notes and args.replace:
            present = notes.read_notes(session).present   # bez --obecni zostają dotychczasowi obecni
        path = notes.save_notes(args.session, notes.Notes(notes.parse(text).text, present))
    except notes.NotesError as e:
        raise SessionNotFound(str(e))
    print(f"[SUKCES] Zapisano notatki sesji {args.session} w: {path}")
    if session.has_summary:
        print(f"[INFO] Kronika jest starsza niż notatki - wygeneruj ją ponownie: "
              f"rpg-chronicler summarize {args.session} --force")
    else:
        print(f"[INFO] Kronikę napiszesz komendą: rpg-chronicler summarize {args.session}")


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
    loops = [name for name, issues in bad.items() if any(i.kind == "petla" for i in issues)]
    if loops:
        print(f"Powtórzenia Whispera usuniesz (z kopią): rpg-chronicler fix-loops {' '.join(loops)}")


def cmd_fix_loops(args):
    from ..quality import find_loops, fix_loops, format_time, remove_loops, undo_fix

    sessions = [s for s in list_sessions(args.sessions) if s.has_transcript]
    if args.undo:
        for s in sessions:
            if undo_fix(s):
                print(f"[SUKCES] {s.name}: przywrócono transkrypcję sprzed usunięcia powtórzeń.")
            elif args.sessions:
                print(f"[POMINIĘTO] {s.name}: brak kopii do przywrócenia.")
        return
    found = False
    for s in sessions:
        transcript = s.load_transcript()
        loops = find_loops(transcript)
        if not loops:
            if args.sessions:
                print(f"[POMINIĘTO] {s.name}: brak powtórzeń.")
            continue
        found = True
        print(f"\n{s.name}:")
        for start, end, text, count in loops:
            print(f"  {count}× „{text}” ({format_time(start)} – {format_time(end)})")
        if args.dry_run:
            print(f"  [INFO] Do usunięcia: {remove_loops(transcript)[1]} wypowiedzi (--dry-run, bez zmian).")
        else:
            removed = fix_loops(s)
            print(f"[SUKCES] {s.name}: usunięto {removed} powtórzonych wypowiedzi (cofnięcie: "
                  f"rpg-chronicler fix-loops {s.name} --undo).")
    if not found:
        print("Brak powtórzeń Whispera do usunięcia.")


def cmd_stats(args):
    from ..campaigns import campaign_key
    from ..stats import format_report, merge_stats, session_stats
    from ..transcript import load_speaker_mapping

    sessions = [s for s in list_sessions(args.sessions) if s.has_transcript
                and (not args.campaign or campaign_key(s.name).casefold() == args.campaign.casefold())]
    if not sessions:
        print("Brak transkrypcji do policzenia.")
        return
    all_stats = []
    for s in sessions:
        stats = session_stats(s.load_transcript(), load_speaker_mapping(s.txt_path), s.campaign)
        all_stats.append(stats)
        print(f"\n{s.name}:\n{format_report(stats)}")
    if len(all_stats) > 1:
        print(f"\nRazem, sesje: {len(all_stats)}:\n{format_report(merge_stats(all_stats))}")


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
    from ..maintenance.archive import ArchiveError, archive_local

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


def cmd_delete(args):
    """Usuwa kronikę / wszystko poza nagraniem / całą sesję - najpierw z Drive (do kosza), potem lokalnie."""
    from ..maintenance import deletion
    from ..session import SessionNotFound

    if args.undo:
        try:
            restored = deletion.restore(args.session)
        except deletion.DeletionError as e:
            raise SessionNotFound(str(e))
        for path in restored:
            print(f"  przywrócono: {path}")
        print(f"[SUKCES] Przywrócono {len(restored)} plików sesji {args.session}. Na Google Drive trafią przy "
              f"wysyłaniu (rpg-chronicler upload); nagranie odzyskasz z kosza Google Drive.")
        return 0

    try:
        plan = deletion.plan(args.session, args.scope)
    except deletion.DeletionError as e:
        raise SessionNotFound(str(e))
    prefix = "[PODGLĄD] " if args.dry_run else ""
    print(f"{prefix}Usuwanie ({deletion.SCOPE_LABELS[plan.scope]}) sesji {plan.name}:")
    for path in plan.files:
        print(f"  {prefix}{path} -> kosz")
    if plan.scope == deletion.SESSION and not args.dry_run and not args.yes:
        if not args.interactive:
            raise SessionNotFound("Usunięcie całej sesji z nagraniem wymaga potwierdzenia: dodaj --yes.")
        answer = input(f"To usunie CAŁĄ sesję razem z nagraniem. Wpisz jej nazwę ({plan.name}), żeby potwierdzić: ")
        if answer.strip() != plan.name:
            print("[POMINIĘTO] Nazwa się nie zgadza - nic nie usunięto.")
            return 1

    if not args.offline:
        from ..storage.drive import delete_on_gdrive
        try:
            delete_on_gdrive(plan.name, plan, dry_run=args.dry_run)
        except Exception as e:
            # Bez usunięcia z Drive `sync` pobrałby pliki z powrotem - lokalnie też nic nie ruszamy
            raise SessionNotFound(f"Nie udało się usunąć plików z Google Drive: {e}. Nic nie usunięto "
                                  f"(tylko lokalnie: --offline - ale wtedy `sync` pobierze je z powrotem).")
    if args.dry_run:
        return 0
    entry = deletion.delete_local(plan)
    print(f"[SUKCES] Usunięto {len(plan.files)} plików sesji {plan.name} "
          f"({deletion.SCOPE_LABELS[plan.scope]}). Kopia: {entry} (rpg-chronicler delete {plan.name} --undo).")
    for warning in deletion.campaign_warnings(plan.name):
        print(f"[INFO] {warning}")
    return 0


def cmd_sync(args):
    from ..storage.drive import sync_from_gdrive
    sync_from_gdrive()


def cmd_upload(args):
    from ..storage.drive import upload_to_gdrive
    upload_to_gdrive()


def cmd_transcribe(args):
    from ..transcription.runner import transcribe_sessions
    transcribe_sessions(list_sessions(args.sessions), args.engine, args.threshold)


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
    transcribe_sessions(list_sessions(), args.engine, args.threshold)
    header("Podsumowania")
    summarize_sessions(list_sessions(), args.provider,
                       interactive=args.interactive, allow_unnamed=args.allow_unnamed)
    if not args.offline:
        header("Dysk → Google Drive")
        upload_to_gdrive()
