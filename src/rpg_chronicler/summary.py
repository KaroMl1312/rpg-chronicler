import glob
import os

from .config import SUMMARY_DIR, TXT_DIR
from .llm import LLMError, get_client, with_retry
from .prompts import render
from .speakers import identify_speakers
from .transcript import compact_for_llm, load_speaker_mapping, save_speaker_mapping


def system_name_from_filename(base_name: str) -> str:
    if "_" not in base_name:
        return "RPG"
    return base_name.split("_")[0].replace("-", " ").title()


def speaker_mapping_info(mapping: dict[str, str]) -> str:
    if not mapping:
        return ""
    mapping_list = [f"- Kod {spk} to: {name}" for spk, name in mapping.items()]
    return ("\n\nOto oficjalna lista mapowania mówców w tej sesji:\n" + "\n".join(mapping_list)
            + "\nUżywaj tych imion i ról przy opisywaniu akcji konkretnych bohaterów!")


def generate_summaries():
    print("\n--- [3/4] Generowanie podsumowań przez AI ---")
    os.makedirs(SUMMARY_DIR, exist_ok=True)

    pending = []
    for txt_path in sorted(glob.glob(os.path.join(TXT_DIR, "*.txt"))):
        base_name = os.path.basename(txt_path)
        summary_path = os.path.join(SUMMARY_DIR, base_name.replace(".txt", "_podsumowanie.txt"))
        # Jeśli podsumowanie już istnieje lokalnie lub na GDrive -> pomijamy!
        if os.path.exists(summary_path):
            print(f"[POMINIĘTO] Podsumowanie dla {base_name} już istnieje.")
            continue
        pending.append((txt_path, summary_path))

    if not pending:
        return

    try:
        llm = get_client()
    except LLMError as e:
        print(f"[OSTRZEŻENIE] {e}")
        return

    for txt_path, summary_path in pending:
        base_name = os.path.basename(txt_path)
        system_name = system_name_from_filename(base_name)

        print(f"\n==================================================")
        print(f"Przetwarzanie pliku: {base_name} (System: {system_name})")
        print(f"==================================================")

        with open(txt_path, "r", encoding="utf-8") as f:
            transcript_text = f.read()

        # 1. Sprawdzamy czy mamy już zapisane mapowanie w pliku JSON
        mapping = load_speaker_mapping(txt_path)
        if mapping:
            print("[INFO] Wczytano zapisane wcześniej imiona mówców z pliku .mowcy.json")
        else:
            # 2. Jeśli brak mapowania, pytamy użytkownika czy chce spróbować zidentyfikować mówców
            user_choice = input(f"Czy chcesz spróbować nadać imiona dla wykrytych mówców w {base_name}? (y/n): ").strip().lower()
            if user_choice == "y":
                mapping = identify_speakers(llm, transcript_text, system_name)
                if mapping:
                    save_speaker_mapping(txt_path, mapping)

        # 3. Generowanie właściwego podsumowania
        print(f"\n[{llm.name}] Generowanie podsumowania w klimacie systemowym '{system_name}'...")
        prompt = render("summary",
                        system_name=system_name,
                        speaker_mapping_info=speaker_mapping_info(mapping),
                        transcript=compact_for_llm(transcript_text, mapping))
        try:
            summary = with_retry(lambda: llm.generate(prompt), f"podsumowanie {base_name}")
        except LLMError:
            print(f"[PORAŻKA] Pomijam {base_name}.")
            continue

        with open(summary_path, "w", encoding="utf-8") as f:
            f.write(summary)
        print(f"[SUKCES] Zapisano kronikę ({system_name}) w: {summary_path}")
