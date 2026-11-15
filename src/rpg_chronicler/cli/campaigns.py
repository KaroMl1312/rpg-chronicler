"""Komendy kampanii: słownik nazw i pamięć kampanii."""
from .. import progress
from ..session import SessionNotFound, list_sessions


def cmd_glossary(args):
    from .. import glossary
    from ..campaigns import campaign_for
    from ..llm import LLMError, get_client

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


def cmd_memory(args):
    from .. import glossary, memory
    from ..campaigns import campaign_for

    campaign = campaign_for(f"{args.campaign}_")
    if args.rebuild:
        from ..llm import LLMError, get_client
        chronicles = glossary.chronicles_for(campaign.key, list_sessions())
        if not chronicles:
            raise SessionNotFound(f"Kampania '{args.campaign}' nie ma jeszcze żadnych kronik.")
        progress.report("pamięć kampanii", campaign.key)
        try:
            memory.propose_from_chronicles(get_client(args.provider), campaign, chronicles)
        except LLMError as e:
            raise SessionNotFound(f"Nie udało się zbudować stanu kampanii: {e}")
    if args.accept:
        state = memory.accept_proposal(campaign.key)
        if state is None:
            raise SessionNotFound(f"Kampania '{campaign.key}' nie ma propozycji stanu do przyjęcia.")
        print(f"[SUKCES] Przyjęto stan kampanii {campaign.key} (po sesji {state.session}): "
              f"{memory.state_path(campaign.key)}")
        return

    state, proposal = memory.load_state(campaign.key), memory.load_proposal(campaign.key)
    if proposal is not None:
        print(f"=== Propozycja AI (po sesji {proposal.session}) ===\n{proposal.text}\n")
        print(f"Przyjmij: rpg-chronicler memory {campaign.key} --accept  (albo popraw i przyjmij w GUI: Kampanie)")
    elif state is not None:
        print(f"=== Stan kampanii {campaign.key} (po sesji {state.session or '?'}) ===\n{state.text}")
    else:
        print(f"Kampania {campaign.key} nie ma jeszcze stanu. Zbuduj go z kronik: "
              f"rpg-chronicler memory {campaign.key} --rebuild")
