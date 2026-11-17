"""Komendy kronik: skrót, cytaty, poprawki, PDF, Discord, wyszukiwarka, encyklopedia i dziennik postaci."""
import os

from .. import notes, progress
from ..session import SessionNotFound, list_sessions
from .common import chronicle_session, ensure_pdf


def cmd_brief(args):
    from ..after_chronicle import brief_sessions
    brief_sessions(list_sessions(args.sessions), args.provider, force=args.force)


def cmd_quotes(args):
    from ..after_chronicle import quotes_sessions
    quotes_sessions(list_sessions(args.sessions), args.provider, force=args.force)


def cmd_revise(args):
    from .. import chronicle
    session = chronicle_session(args.session)
    if args.undo:
        restored = chronicle.restore_previous(session)
        if restored is None:
            raise SessionNotFound(f"Kronika {session.name} nie ma poprzedniej wersji do przywrócenia.")
        print(f"[SUKCES] Przywrócono poprzednią wersję kroniki {session.name}. "
              f"Skrót kroniki odśwież komendą: rpg-chronicler brief {session.name}")
        return
    if not args.instruction or not args.instruction.strip():
        raise SessionNotFound("Podaj polecenie, np.: rpg-chronicler revise SESJA \"to nie Hans, tylko Hanna\"")
    from ..llm import LLMError, get_client
    from ..revision import RevisionError, revise_chronicle
    try:
        revise_chronicle(get_client(args.provider), session, args.instruction)
    except (LLMError, RevisionError) as e:
        raise SessionNotFound(f"Nie udało się poprawić kroniki: {e}")


def cmd_pdf(args):
    for name in args.sessions:
        ensure_pdf(chronicle_session(name), force=True)


def cmd_discord(args):
    from .. import chronicle, discord
    from ..llm import LLMError, get_client, with_retry
    from ..prompts import render

    session = chronicle_session(args.session)
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
    pdf = ensure_pdf(session)
    if args.prepare:
        return

    webhook = chronicle.webhook_for(session.campaign.key)
    if not webhook:
        raise SessionNotFound(f"Kampania '{session.campaign.key}' nie ma ustawionego webhooka Discorda "
                              "(GUI: Kampanie → Discord).")
    if chronicle.load_sent(session) and not args.force:
        raise SessionNotFound(f"Kronikę wysłano już {chronicle.sent_text(session)} - użyj --force, żeby wysłać ponownie.")
    footer = " · ".join(p for p in (session.system_name, chronicle.session_date_text(session) or session.name,
                                    notes.ANNOTATION if session.has_notes else "") if p)
    quotes = [] if args.no_quotes else chronicle.read_quotes(session)
    message = discord.build_message(chronicle.chronicle_title(text), teaser, footer, os.path.basename(pdf), quotes)
    progress.report("wysyłanie na Discord", session.name)
    try:
        message_id = discord.send(webhook, message, pdf)
    except discord.DiscordError as e:
        raise SessionNotFound(str(e))
    chronicle.save_sent(session, message_id)
    print(f"[SUKCES] Wysłano kronikę {session.name} na Discord.")


def cmd_recap(args):
    """„Poprzednio w kampanii…”: pisze tekst (gdy go nie ma, jest nieaktualny albo --force) i opcjonalnie wysyła."""
    from .. import chronicle, discord, prep
    from ..campaigns import campaign_for
    from ..llm import LLMError, get_client

    campaign = campaign_for(f"{args.campaign}_")
    sessions = list_sessions()
    path = prep.recap_path(campaign.key)
    after, text = prep.read(path)
    if args.force or not prep.is_current(path, campaign.key, sessions):
        progress.report("poprzednio w kampanii", campaign.key)
        try:
            text = prep.write_recap(get_client(args.provider), campaign, sessions)
        except (LLMError, prep.PrepError) as e:
            raise SessionNotFound(f"Nie udało się napisać „{prep.RECAP_TITLE}…”: {e}")
        after, _ = prep.read(path)
        print(f"[SUKCES] Zapisano w: {path}")
    print(f"\n{text}\n")
    if not args.discord:
        return
    webhook = chronicle.webhook_for(campaign.key)
    if not webhook:
        raise SessionNotFound(f"Kampania '{campaign.key}' nie ma ustawionego webhooka Discorda "
                              "(GUI: Kampanie → Discord).")
    message = discord.build_message(f"{prep.RECAP_TITLE} {campaign.key}…", text,
                                    f"{campaign.system} · przed kolejną sesją (po {after})", None)
    progress.report("wysyłanie na Discord", campaign.key)
    try:
        discord.send(webhook, message)
    except discord.DiscordError as e:
        raise SessionNotFound(str(e))
    print(f"[SUKCES] Wysłano „{prep.RECAP_TITLE}…” na Discord kampanii {campaign.key}.")


def cmd_gm_notes(args):
    from .. import prep
    from ..campaigns import campaign_for
    from ..llm import LLMError, get_client

    campaign = campaign_for(f"{args.campaign}_")
    progress.report("notatki MG", campaign.key)
    try:
        text = prep.write_gm_notes(get_client(args.provider), campaign, list_sessions())
    except (LLMError, prep.PrepError) as e:
        raise SessionNotFound(f"Nie udało się napisać notatek MG: {e}")
    from ..chronicle_pdf import write_markdown_pdf
    progress.report("PDF", campaign.key)
    write_markdown_pdf(text, prep.gm_notes_pdf_path(campaign.key), campaign.system)   # .md zapisał prep (z nagłówkiem)
    print(f"[SUKCES] Notatki MG kampanii {campaign.key}: {prep.gm_notes_pdf_path(campaign.key)}")


def cmd_ask(args):
    from .. import ask
    from ..campaigns import campaign_for
    from ..llm import LLMError, get_client

    campaign = campaign_for(f"{args.campaign}_")
    progress.report("pytanie do kronikarza", campaign.key)
    try:
        answer = ask.ask(get_client(args.provider), campaign, list_sessions(), args.question)
    except (LLMError, ask.AskError) as e:
        raise SessionNotFound(f"Kronikarz nie odpowiedział: {e}")
    print(f"\n{answer.answer}\n")
    if answer.sessions:
        print(f"[INFO] Sesje: {', '.join(answer.sessions)}")


def cmd_image(args):
    """Propozycja obrazka hasła kampanii (Cloudflare FLUX); z --zachowaj od razu jako zdjęcie hasła."""
    from .. import images
    from ..campaigns import campaign_for
    from ..llm import LLMError, get_client

    campaign = campaign_for(f"{args.campaign}_")
    name = next((n for n in campaign.all_names() if n.casefold() == args.name.strip().casefold()), args.name.strip())
    progress.report("obrazek", name)
    try:
        path = images.generate_candidate(get_client(args.provider), images.get_image_client(), campaign, name,
                                         args.hints or "")
        if args.keep:
            path = images.keep_candidate(campaign.key, name)
    except (LLMError, images.ImageError) as e:
        raise SessionNotFound(f"Nie udało się wygenerować obrazka: {e}")
    print(f"[SUKCES] {'Zdjęcie' if args.keep else 'Propozycja obrazka'} „{name}”: {path}")
    if not args.keep:
        print(f"[INFO] Zachowasz ją w oknie Kampanie (strona hasła) albo: rpg-chronicler image {campaign.key} "
              f"\"{name}\" --zachowaj (wygeneruje nowy).")


def cmd_discord_test(args):
    from .. import chronicle, discord
    from ..campaigns import campaign_for

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


def cmd_search(args):
    from ..search import search, summary_line
    from ..quality import format_time

    hits = search(list_sessions(), args.query, campaign=args.campaign,
                  chronicles=not args.transcripts_only, transcripts=not args.chronicles_only)
    print(summary_line(hits))
    current = None
    for hit in hits[:args.limit]:
        if hit.session != current:
            current = hit.session
            print(f"\n== {hit.session}")
        if hit.start is None:   # kronika albo notatki
            print(f"  [{hit.kind}{' · ' + hit.heading if hit.heading else ''}] {hit.text}")
        else:
            print(f"  [{format_time(hit.start)}{' · ' + hit.speaker if hit.speaker else ''}] {hit.text}")
    if len(hits) > args.limit:
        print(f"\n… i {len(hits) - args.limit} więcej (--limit N)")


def _write_markdown(text: str, md_path: str, pdf_path: str, system: str) -> None:
    from ..chronicle_pdf import write_markdown_pdf
    os.makedirs(os.path.dirname(md_path), exist_ok=True)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(text)
    write_markdown_pdf(text, pdf_path, system)


def fill_descriptions(campaign, llm):
    """Uzupełnia puste opisy haseł kampanii opisami z encyklopedii AI (z cache, gdy kroniki się nie zmieniły).

    Zwraca kampanię po zmianach. Rzuca LLMError / EncyclopediaError."""
    from .. import encyclopedia
    from ..campaigns import update_campaign
    from ..glossary import chronicles_for
    chronicles = chronicles_for(campaign.key, list_sessions())
    if not chronicles:
        raise encyclopedia.EncyclopediaError(f"Kampania {campaign.key} nie ma jeszcze żadnych kronik.")
    progress.report("opisy haseł", campaign.key)
    updated, filled = encyclopedia.fill_descriptions(campaign, encyclopedia.ai_entries(llm, campaign, chronicles))
    if filled:
        update_campaign(updated)
        print(f"[SUKCES] Opisy haseł kampanii {campaign.key}: dodano {len(filled)} ({', '.join(filled[:8])}"
              f"{'…' if len(filled) > 8 else ''}).")
    else:
        print(f"[INFO] Kampania {campaign.key}: brak nowych opisów do dodania.")
    missing = [n for n in updated.all_names() if not updated.description(n)]
    if missing:
        print(f"[INFO] Bez opisu ({len(missing)}): {', '.join(missing[:10])}{'…' if len(missing) > 10 else ''} "
              f"- AI nie znalazło ich w kronikach; opis można wpisać w oknie Kampanie.")
    return updated


def write_encyclopedia(campaign, llm) -> None:
    """Encyklopedia kampanii (.md + PDF). `llm` None = bez opisów AI. Rzuca LLMError / EncyclopediaError.

    Z AI najpierw uzupełnia puste opisy haseł w kampanii (ta sama odpowiedź AI, z cache)."""
    from .. import encyclopedia
    if llm is not None:
        campaign = fill_descriptions(campaign, llm)
    progress.report("encyklopedia", campaign.key)
    text = encyclopedia.build(campaign, list_sessions(), llm)
    progress.report("PDF", campaign.key)
    _write_markdown(text, encyclopedia.markdown_path(campaign.key), encyclopedia.pdf_path(campaign.key),
                    campaign.system)
    print(f"[SUKCES] Encyklopedia kampanii {campaign.key}: {encyclopedia.pdf_path(campaign.key)} "
          f"(i {os.path.basename(encyclopedia.markdown_path(campaign.key))})")


def write_diary(campaign, character: str, get_client, force: bool = False) -> None:
    """Dziennik postaci (.md + PDF). Rzuca LLMError / DiaryError."""
    from .. import diary
    text = diary.build(get_client, campaign, character, list_sessions(), force=force,
                       progress=lambda done, total: progress.report("dziennik postaci", character, done, total))
    progress.report("PDF", character)
    path = diary.markdown_path(campaign.key, character)
    _write_markdown(text, path, diary.pdf_path(campaign.key, character), campaign.system)
    print(f"[SUKCES] Dziennik postaci {character}: {diary.pdf_path(campaign.key, character)} "
          f"(i {os.path.basename(path)})")


def cmd_encyclopedia(args):
    from .. import encyclopedia
    from ..campaigns import campaign_for
    from ..llm import LLMError, get_client

    campaign = campaign_for(f"{args.campaign}_")
    try:
        write_encyclopedia(campaign, None if args.no_ai else get_client(args.provider))
    except (LLMError, encyclopedia.EncyclopediaError) as e:
        raise SessionNotFound(f"Nie udało się utworzyć encyklopedii: {e}")


def cmd_describe(args):
    from .. import encyclopedia
    from ..campaigns import campaign_for
    from ..llm import LLMError, get_client

    try:
        fill_descriptions(campaign_for(f"{args.campaign}_"), get_client(args.provider))
    except (LLMError, encyclopedia.EncyclopediaError) as e:
        raise SessionNotFound(f"Nie udało się uzupełnić opisów: {e}")


def cmd_diary(args):
    from .. import diary
    from ..campaigns import campaign_for
    from ..llm import LazyClient, LLMError

    campaign = campaign_for(f"{args.campaign}_")
    character = diary.canonical_character(campaign, args.character)
    llm = LazyClient(args.provider)   # wpisy z cache nie potrzebują klienta
    try:
        write_diary(campaign, character, llm.get, force=args.force)
    except (LLMError, diary.DiaryError) as e:
        raise SessionNotFound(f"Nie udało się utworzyć dziennika: {e}")


def cmd_backfill(args):
    from .. import backfill, diary, encyclopedia
    from ..after_chronicle import QuotesError, write_brief, write_quotes
    from ..campaigns import campaign_for
    from ..chronicle import read_chronicle
    from ..llm import LazyClient, LLMError

    sessions = {s.name: s for s in list_sessions()}
    steps = backfill.plan(list(sessions.values()))
    if not steps:
        print("Wszystko jest aktualne - nie ma czego uzupełniać.")
        return
    print(f"Do uzupełnienia (zapytań do AI: ok. {backfill.ai_requests(steps)}):\n{backfill.summary(steps)}")
    if args.dry_run:
        return

    llm = LazyClient(args.provider)
    done, failed = 0, []
    for index, step in enumerate(steps):
        progress.report("uzupełnianie", step.label, index, len(steps))
        try:
            if step.kind == backfill.BRIEF:
                session = sessions[step.target]
                write_brief(llm.get(), session, read_chronicle(session))
            elif step.kind == backfill.QUOTES:
                session = sessions[step.target]
                write_quotes(llm.get(), session, read_chronicle(session))
            elif step.kind == backfill.PDF:
                ensure_pdf(sessions[step.target], force=True)
            elif step.kind == backfill.ENCYCLOPEDIA:
                write_encyclopedia(campaign_for(f"{step.target}_"), llm.get())
            elif step.kind == backfill.DIARY:
                write_diary(campaign_for(f"{step.target}_"), step.character, llm.get)
            done += 1
        except LLMError as e:
            print(f"[OSTRZEŻENIE] {step.label}: {e}")
            failed.append(step.label)
            if not e.retryable:
                print("[PORAŻKA] AI jest niedostępne - przerywam uzupełnianie.")
                break
        except (QuotesError, encyclopedia.EncyclopediaError, diary.DiaryError, OSError) as e:
            print(f"[OSTRZEŻENIE] {step.label}: {e}")
            failed.append(step.label)
    failed_text = f" Nie udało się: {', '.join(failed)}." if failed else ""
    print(f"\n[SUKCES] Uzupełniono: {done} z {len(steps)}.{failed_text}")
