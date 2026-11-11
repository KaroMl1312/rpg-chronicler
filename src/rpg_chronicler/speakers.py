from .campaigns import Campaign
from .llm import LLMClient, LLMError, with_retry
from .prompts import render
from .transcript import Transcript


def campaign_info(campaign: Campaign) -> str:
    """Postacie graczy z kampanii - AI może wtedy przypisać mówców do konkretnych postaci."""
    if not campaign.player_characters:
        return ""
    names = ", ".join(campaign.player_characters)
    return (f"- W tej kampanii gracze prowadzą postacie: {names}. Jeśli rozpoznasz, którą postać prowadzi "
            "dany mówca, napisz to wprost, używając dokładnie tej pisowni imienia.\n")


def suggest_speakers(llm: LLMClient, transcript: Transcript, campaign: Campaign) -> str:
    """Prosi AI o charakterystykę mówców. Rzuca LLMError, gdy się nie uda."""
    prompt = render("speaker_identification",
                    system_name=campaign.system,
                    campaign_info=campaign_info(campaign),
                    transcript=transcript.compact_for_llm())
    print(f"\n[{llm.name}] Analizowanie transkrypcji w celu rozpoznania ról...")
    return with_retry(lambda: llm.generate(prompt), "rozpoznawanie mówców")


def ask_speaker_names(transcript: Transcript, voice_suggestions: dict | None = None) -> dict[str, str]:
    """Pyta w terminalu o imię/rolę dla każdej etykiety SPEAKER_XX.

    Pewna podpowiedź z rozpoznania głosu jest odpowiedzią domyślną (Enter ją przyjmuje, „-” pomija mówcę).
    """
    voice_suggestions = voice_suggestions or {}
    mapping = {}
    print("\nPrzypisz imiona/role do wykrytych etykiet (Enter bez tekstu pomija dany kod"
          + (", a przy rozpoznanym głosie przyjmuje podpowiedź; „-” pomija" if voice_suggestions else "") + "):")
    for spk in transcript.speakers:
        suggestion = voice_suggestions.get(spk)
        hint = ""
        if suggestion is not None:
            hint = (f" [{suggestion.name}]" if suggestion.confident
                    else f" (może {suggestion.name}, {suggestion.score:.0%})")
        name_input = input(f"Kto to jest '{spk}'?{hint} (np. MG / Hans / Anna): ").strip()
        if name_input == "-":
            continue
        if not name_input and suggestion is not None and suggestion.confident:
            name_input = suggestion.name
        if name_input:
            mapping[spk] = name_input
    return mapping


def identify_speakers(llm: LLMClient, transcript: Transcript, campaign: Campaign,
                      suggestion_path: str | None = None, voice_suggestions: dict | None = None) -> dict[str, str]:
    """Prosi AI o charakterystykę mówców, a potem pyta użytkownika o ich imiona/role."""
    if not transcript.speakers:
        print("[INFO] W transkrypcji nie ma rozpoznanych mówców (SPEAKER_XX).")
        return {}

    try:
        suggestion = suggest_speakers(llm, transcript, campaign)
    except LLMError:
        print("[PORAŻKA] Nie udało się uzyskać sugestii mówców. Możesz spróbować ponownie przy następnym uruchomieniu.")
        return {}
    if suggestion_path:
        save_suggestion(suggestion_path, suggestion)

    print(f"\n--- Rozpoznani mówcy według {llm.name} ---")
    print(suggestion)
    print("---------------------------------------")
    return ask_speaker_names(transcript, voice_suggestions)


def save_suggestion(path: str, suggestion: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        f.write(suggestion)
