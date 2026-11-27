from . import custom

# Linia w szablonie oddzielająca stały początek (wspólny dla kilku zapytań - do cache'owania w API) od reszty
CACHE_MARK = custom.CACHE_MARK


def _template(name: str, values: dict) -> str:
    """Szablon zmieniony przez użytkownika (okno „Prompty AI”) albo domyślny, z podstawionymi polami."""
    return custom.template(name).format(**values)


def render(name: str, **values: str) -> str:
    """Wczytuje szablon promptu `prompts/<name>.md` i podstawia wartości {pól}."""
    return _template(name, values).replace(f"\n{CACHE_MARK}\n", "\n")


def render_split(name: str, **values: str) -> tuple[str, str]:
    """Jak `render`, ale zwraca (stały początek, reszta) podzielone na linii CACHE_MARK.

    Sklejone dają dokładnie to samo co `render`; początek trafia do API jako osobny blok z cache.
    """
    text = _template(name, values)
    head, mark, tail = text.partition(f"\n{CACHE_MARK}\n")
    return (head + "\n", tail) if mark else ("", text)


def chronicle_blocks(chronicles: list[tuple[str, str]], limit: int | None = None) -> str:
    """Kroniki [(sesja, tekst)] (od najstarszej) jako bloki <kronika>; przy limicie znaków zostają najnowsze.

    Ten sam tekst trafia na początek kilku zapytań po nowej kronice (skrót, słownik, stan kampanii),
    dzięki czemu kolejne zapytania czytają go z cache API.
    """
    blocks, total = [], 0
    for name, text in reversed(chronicles):
        block = f"<kronika sesja=\"{name}\">\n{text.strip()}\n</kronika>"
        if limit is not None and blocks and total + len(block) > limit:
            break
        blocks.insert(0, block)
        total += len(block)
    return "\n\n".join(blocks) + "\n\n"
