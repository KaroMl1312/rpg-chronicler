from .llm import LLMClient, LLMError, with_retry
from .prompts import render
from .transcript import compact_for_llm, detect_speakers


def identify_speakers(llm: LLMClient, transcript_text: str, system_name: str) -> dict[str, str]:
    """Prosi AI o charakterystykę mówców, a potem pyta użytkownika o ich imiona/role."""
    prompt = render("speaker_identification",
                    system_name=system_name,
                    transcript=compact_for_llm(transcript_text))

    print(f"\n[{llm.name}] Analizowanie transkrypcji w celu rozpoznania ról...")
    try:
        suggestion = with_retry(lambda: llm.generate(prompt), "rozpoznawanie mówców")
    except LLMError:
        print("[PORAŻKA] Nie udało się uzyskać sugestii mówców. Możesz spróbować ponownie przy następnym uruchomieniu.")
        return {}

    print(f"\n--- Rozpoznani mówcy według {llm.name} ---")
    print(suggestion)
    print("---------------------------------------")

    detected_speakers = detect_speakers(transcript_text)
    if not detected_speakers:
        print("[INFO] W pliku nie znaleziono etykiet typu [SPEAKER_XX].")
        return {}

    mapping = {}
    print("\nPrzypisz imiona/role do wykrytych etykiet (pozostaw puste i wciśnij Enter, aby pominąć dany kod):")
    for spk in detected_speakers:
        name_input = input(f"Kto to jest '{spk}'? (np. MG / Hans / Anna): ").strip()
        if name_input:
            mapping[spk] = name_input
    return mapping
