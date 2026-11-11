"""Postęp długich zadań w formie czytelnej dla GUI.

GUI uruchamia CLI ze zmienną środowiskową RPG_CHRONICLER_PROGRESS=json; wtedy CLI wypisuje
na stdout linie `@@postep {json}` zamiast pasków tqdm. W zwykłym terminalu nic się nie zmienia.
"""
import json
import os

ENV_VAR = "RPG_CHRONICLER_PROGRESS"
PREFIX = "@@postep "


def enabled() -> bool:
    return os.environ.get(ENV_VAR) == "json"


def report(stage: str, session: str | None = None,
           done: float | None = None, total: float | None = None) -> None:
    """Zgłasza etap pracy; `done`/`total` w dowolnych jednostkach (np. sekundy nagrania)."""
    if not enabled():
        return
    try:
        # float(): biblioteki (pyannote, numpy) podają własne typy liczbowe, których json nie zna
        data = {"etap": stage, "sesja": session,
                "zrobione": None if done is None else float(done),
                "razem": None if total is None else float(total)}
        print(PREFIX + json.dumps(data, ensure_ascii=False), flush=True)
    except (TypeError, ValueError):
        pass  # błąd raportowania postępu nie może przerwać transkrypcji


def parse(line: str) -> dict | None:
    """Zwraca dane postępu z linii wypisanej przez `report`, a dla innych linii None."""
    if not line.startswith(PREFIX):
        return None
    try:
        data = json.loads(line[len(PREFIX):])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def fraction(data: dict) -> float | None:
    """Ułamek 0..1 albo None, gdy postępu nie da się policzyć."""
    done, total = data.get("zrobione"), data.get("razem")
    if done is None or not total:
        return None
    return max(0.0, min(1.0, done / total))
