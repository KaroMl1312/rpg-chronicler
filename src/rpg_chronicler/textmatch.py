"""Dopasowanie słów odporne na polską odmianę (wyszukiwarka, encyklopedia, benchmark). Tylko stdlib.

Zamiast lematyzacji: porównujemy początki słów. „Altdorf” trafia „Altdorfie”, „Ulrich” - „Ulricha”,
„Eustachos” - „Eustachosa”. Krótkie słowa (≤ 4 litery) muszą pasować od początku w całości.
"""
import re

WORD_RE = re.compile(r"\w+", re.UNICODE)


def words(text: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(text)]


def stem(token: str) -> str:
    """Początek słowa odporny na końcówki: obcina do 2 ostatnich liter, ale zostawia co najmniej 4."""
    token = token.lower()
    return token[:max(4, len(token) - 2)] if len(token) > 4 else token


def variants(token: str) -> tuple[str, ...]:
    """Rdzenie słowa: zwykły i bez ruchomego „e” („kupiec” → „kupc…” trafia „kupca”, „Marek” → „Marka”)."""
    token = token.lower()
    result = [stem(token)]
    if len(token) >= 5 and token.endswith("iec"):
        result.append(token[:-3] + "c")             # kupiec → kupc(a), starzec → starc(a)
    elif len(token) >= 5 and token[-2:] in ("ec", "ek"):
        result.append(token[:-2] + token[-1])       # Marek → Mark(a), wędrowiec obsłużony wyżej
    return tuple(result)


def query_stems(query: str, min_length: int = 2) -> list[tuple[str, ...]]:
    return [variants(t) for t in words(query) if len(t) >= min_length]


def word_matches(word: str, alternatives: tuple[str, ...]) -> bool:
    return any(word.startswith(a) for a in alternatives)


def matches_stems(text_words: list[str], stems: list[tuple[str, ...]]) -> bool:
    """Czy każde słowo zapytania (którykolwiek jego rdzeń) zaczyna któreś słowo tekstu."""
    return bool(stems) and all(any(word_matches(w, alts) for w in text_words) for alts in stems)


def contains_name(text: str, name: str) -> bool:
    """Czy nazwa (wszystkie jej słowa ≥ 3 litery, w dowolnej odmianie) występuje w tekście."""
    return matches_stems(words(text), query_stems(name, min_length=3))
