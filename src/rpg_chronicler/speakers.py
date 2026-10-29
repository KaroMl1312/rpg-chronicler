from .llm import LLMClient, LLMError, with_retry
from .prompts import render
from .transcript import Transcript


def identify_speakers(llm: LLMClient, transcript: Transcript, system_name: str) -> dict[str, str]:
    """Prosi AI o charakterystykę mówców, a potem pyta użytkownika o ich imiona/role."""
    if not transcript.speakers:
        print("[INFO] W transkrypcji nie ma rozpoznanych mówców (SPEAKER_XX).")
        return {}

    prompt = render("speaker_identification",
                    system_name=system_name,
                    transcript=transcript.compact_for_llm())

    print(f"\n[{llm.name}] Analizowanie transkrypcji w celu rozpoznania ról...")
    try:
        suggestion = with_retry(lambda: llm.generate(prompt), "rozpoznawanie mówców")
    except LLMError:
        print("[PORAŻKA] Nie udało się uzyskać sugestii mówców. Możesz spróbować ponownie przy następnym uruchomieniu.")
        return {}

    print(f"\n--- Rozpoznani mówcy według {llm.name} ---")
    print(suggestion)
    print("---------------------------------------")

    mapping = {}
    print("\nPrzypisz imiona/role do wykrytych etykiet (pozostaw puste i wciśnij Enter, aby pominąć dany kod):")
    for spk in transcript.speakers:
        name_input = input(f"Kto to jest '{spk}'? (np. MG / Hans / Anna): ").strip()
        if name_input:
            mapping[spk] = name_input
    return mapping
