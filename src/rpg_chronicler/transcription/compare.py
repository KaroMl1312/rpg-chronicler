"""Porównanie transkrypcji różnych modeli Whispera (benchmark --whisper-models). Tylko stdlib - testowane pytestem.

Bez ręcznie poprawionego wzorca nie da się policzyć błędów, więc to wskaźniki pomocnicze: ile słów,
ile nazw ze słownika kampanii model zapisał, jak bardzo teksty modeli się różnią. Ostatecznie decyduje
przeczytanie tekstów zapisanych przez --save-text.
"""
import difflib

from ..textmatch import contains_name, words


def agreement(a: str, b: str) -> float:
    """Zgodność słów dwóch tekstów (0-1): jaka część słów jest wspólna w tej samej kolejności."""
    wa, wb = words(a), words(b)
    if not wa and not wb:
        return 1.0
    return difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio()


def names_found(text: str, names: list[str]) -> list[str]:
    """Nazwy ze słownika kampanii, które występują w tekście (wszystkie słowa nazwy, w dowolnej odmianie)."""
    return [name for name in names if contains_name(text, name)]


def uses_previous_text(model_size: str) -> bool:
    """Czy Whisper ma warunkować kolejne fragmenty na poprzednim tekście (domyślne zachowanie).

    Modele turbo w tym trybie zapętlają się na nagraniach sesji: pomiar 2026-11 (Warhammer_261105, 10 min
    od 30. minuty) dał „Tak?” ×34 i „No” co 30 s zamiast monologu MG - 241-842 słów zamiast ~1200.
    Bez warunkowania turbo zapisuje tyle co medium (~1150 słów) ok. 2,5× szybciej.
    """
    return "turbo" not in model_size


def format_segments(segments) -> str:
    """Tekst do czytania: „[mm:ss] wypowiedź” w liniach (czas od początku fragmentu)."""
    lines = []
    for s in segments:
        minutes, seconds = divmod(int(s.start), 60)
        lines.append(f"[{minutes:02d}:{seconds:02d}] {s.text.strip()}")
    return "\n".join(lines) + "\n"
