"""Komendy kronik: skrót, cytaty, poprawki, PDF, Discord, wyszukiwarka, encyklopedia i dziennik postaci."""
import os

from .. import progress
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
    footer = " · ".join(p for p in (session.system_name, chronicle.session_date_text(session) or session.name) if p)
    quotes = [] if args.no_quotes else chronicle.read_quotes(session)
    message = discord.build_message(chronicle.chronicle_title(text), teaser, footer, os.path.basename(pdf), quotes)
    progress.report("wysyłanie na Discord", session.name)
    try:
        message_id = discord.send(webhook, message, pdf)
    except discord.DiscordError as e:
        raise SessionNotFound(str(e))
    chronicle.save_sent(session, message_id)
    print(f"[SUKCES] Wysłano kronikę {session.name} na Discord.")


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
    from ..search import KIND_CHRONICLE, search, summary_line
    from ..quality import format_time

    hits = search(list_sessions(), args.query, campaign=args.campaign,
                  chronicles=not args.transcripts_only, transcripts=not args.chronicles_only)
    print(summary_line(hits))
    current = None
    for hit in hits[:args.limit]:
        if hit.session != current:
            current = hit.session
            print(f"\n== {hit.session}")
        if hit.kind == KIND_CHRONICLE:
            print(f"  [kronika{' · ' + hit.heading if hit.heading else ''}] {hit.text}")
        else:
            print(f"  [{format_time(hit.start)}{' · ' + hit.speaker if hit.speaker else ''}] {hit.text}")
    if len(hits) > args.limit:
        print(f"\n… i {len(hits) - args.limit} więcej (--limit N)")


def cmd_encyclopedia(args):
    from .. import encyclopedia
    from ..campaigns import campaign_for
    from ..chronicle_pdf import write_markdown_pdf

    campaign = campaign_for(f"{args.campaign}_")
    llm = None
    if not args.no_ai:
        from ..llm import get_client
        llm = get_client(args.provider)
    progress.report("encyklopedia", campaign.key)
    from ..llm import LLMError
    try:
        text = encyclopedia.build(campaign, list_sessions(), llm)
    except (LLMError, encyclopedia.EncyclopediaError) as e:
        raise SessionNotFound(f"Nie udało się utworzyć encyklopedii: {e}")
    os.makedirs(os.path.dirname(encyclopedia.markdown_path(campaign.key)), exist_ok=True)
    with open(encyclopedia.markdown_path(campaign.key), "w", encoding="utf-8") as f:
        f.write(text)
    progress.report("PDF", campaign.key)
    write_markdown_pdf(text, encyclopedia.pdf_path(campaign.key), campaign.system)
    print(f"[SUKCES] Encyklopedia kampanii {campaign.key}: {encyclopedia.pdf_path(campaign.key)} "
          f"(i {os.path.basename(encyclopedia.markdown_path(campaign.key))})")


def cmd_diary(args):
    from .. import diary
    from ..campaigns import campaign_for
    from ..chronicle_pdf import write_markdown_pdf
    from ..llm import LLMError, LazyClient

    campaign = campaign_for(f"{args.campaign}_")
    character = diary.canonical_character(campaign, args.character)
    llm = LazyClient(args.provider)   # wpisy z cache nie potrzebują klienta
    try:
        text = diary.build(llm.get, campaign, character, list_sessions(), force=args.force,
                           progress=lambda done, total: progress.report("dziennik postaci", character, done, total))
    except (LLMError, diary.DiaryError) as e:
        raise SessionNotFound(f"Nie udało się utworzyć dziennika: {e}")
    path = diary.markdown_path(campaign.key, character)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    progress.report("PDF", character)
    write_markdown_pdf(text, diary.pdf_path(campaign.key, character), campaign.system)
    print(f"[SUKCES] Dziennik postaci {character}: {diary.pdf_path(campaign.key, character)} "
          f"(i {os.path.basename(path)})")
