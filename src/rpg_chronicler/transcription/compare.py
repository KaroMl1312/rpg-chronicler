"""Porównanie transkrypcji różnych modeli Whispera (benchmark --whisper-models). Tylko stdlib - testowane pytestem.

Bez ręcznie poprawionego wzorca nie da się policzyć błędów, więc to wskaźniki pomocnicze: ile słów,
ile nazw ze słownika kampanii model zapisał, jak bardzo teksty modeli się różnią. Ostatecznie decyduje
przeczytanie tekstów zapisanych przez --save-text.
"""
import difflib
import re

WORD_RE = re.compile(r"\w+", re.UNICODE)


def words(text: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(text)]


def agreement(a: str, b: str) -> float:
    """Zgodność słów dwóch tekstów (0-1): jaka część słów jest wspólna w tej samej kolejności."""
    wa, wb = words(a), words(b)
    if not wa and not wb:
        return 1.0
    return difflib.SequenceMatcher(None, wa, wb, autojunk=False).ratio()


def _stem(token: str) -> str:
    """Początek słowa odporny na polską odmianę: „Altdorf” trafia też „Altdorfie”, „Eustachos” - „Eustachosa”."""
    token = token.lower()
    return token[:max(4, len(token) - 2)] if len(token) > 4 else token


def names_found(text: str, names: list[str]) -> list[str]:
    """Nazwy ze słownika kampanii, które występują w tekście (wszystkie słowa nazwy, w dowolnej odmianie)."""
    text_words = words(text)
    found = []
    for name in names:
        tokens = [t for t in words(name) if len(t) >= 3]
        if tokens and all(any(w.startswith(_stem(t)) for w in text_words) for t in tokens):
            found.append(name)
    return found


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
