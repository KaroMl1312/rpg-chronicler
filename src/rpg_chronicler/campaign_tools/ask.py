"""„Zapytaj kronikarza” (`ask KAMPANIA "PYTANIE"`, zakładka Kampanie): odpowiedź AI z kronik i stanu kampanii.

Odpowiedź wskazuje sesje w nawiasach kwadratowych ([Warhammer_261015]); kod wyłuskuje z niej tylko nazwy
istniejących sesji tej kampanii (GUI robi z nich przyciski „przejdź do kroniki”). Historia pytań kampanii
jest lokalnie w ~/.cache/rpg-chronicler/pytania/<kampania>.json (najnowsze na początku, do HISTORY_LIMIT).
Zapytanie zaczyna się od kronik jak encyklopedia i notatki MG (wspólny cache API).
Moduł bez zależności zewnętrznych (GUI czyta historię); LLM tylko w `ask`.
"""
import datetime
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from ..campaigns import Campaign
from .prep import CHRONICLES_LIMIT, campaign_chronicles, prompt_context
from ..prompts import chronicle_blocks, render

HISTORY_LIMIT = 30
REFERENCE_RE = re.compile(r"\[([^\[\]\n]+?)\]")


class AskError(Exception):
    pass


@dataclass
class Answer:
    question: str
    answer: str
    sessions: list[str] = field(default_factory=list)   # wskazane sesje (istniejące), w kolejności w odpowiedzi
    asked: str = ""                                      # kiedy (ISO)


def history_path(key: str) -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return Path(cache_home) / "rpg-chronicler" / "pytania" / f"{key}.json"


def load_history(key: str) -> list[Answer]:
    try:
        data = json.loads(history_path(key).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    result = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, dict) and item.get("question") and item.get("answer"):
            result.append(Answer(str(item["question"]), str(item["answer"]),
                                 [str(s) for s in item.get("sessions", []) if isinstance(s, str)],
                                 str(item.get("asked", ""))))
    return result


def _save_history(key: str, history: list[Answer]) -> None:
    path = history_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(a) for a in history[:HISTORY_LIMIT]], ensure_ascii=False, indent=1),
                    encoding="utf-8")


def remove_from_history(key: str, index: int) -> None:
    history = load_history(key)
    if 0 <= index < len(history):
        del history[index]
        _save_history(key, history)


def referenced_sessions(answer: str, known: list[str]) -> list[str]:
    """Nazwy sesji z nawiasów [..] odpowiedzi (także kilka w jednym: [A, B]), tylko istniejące, bez powtórzeń."""
    found = []
    for group in REFERENCE_RE.findall(answer):
        for name in re.split(r"[,;]\s*", group):
            name = name.strip()
            if name in known and name not in found:
                found.append(name)
    return found


def ask_prompt(campaign: Campaign, chronicles: list[tuple[str, str]], question: str) -> tuple[str, str]:
    info, state = prompt_context(campaign)
    return chronicle_blocks(chronicles, CHRONICLES_LIMIT), render(
        "ask", system_name=campaign.system, campaign_info=info, state=state, question=question.strip())


def ask(llm, campaign: Campaign, sessions, question: str) -> Answer:
    """Pyta AI i dopisuje odpowiedź na początek historii. Rzuca LLMError albo AskError."""
    from ..llm import generate, with_retry  # import tutaj: GUI importuje ten moduł bez SDK LLM

    if not question.strip():
        raise AskError("Pytanie jest puste.")
    chronicles = campaign_chronicles(campaign.key, sessions)
    if not chronicles:
        raise AskError(f"Kampania {campaign.key} nie ma jeszcze żadnej kroniki.")
    prefix, prompt = ask_prompt(campaign, chronicles, question)
    print(f"[{llm.name}] Kronikarz kampanii {campaign.key}: {question.strip()}")
    text = with_retry(lambda: generate(llm, prompt, prefix), f"pytanie {campaign.key}").strip()
    answer = Answer(question.strip(), text, referenced_sessions(text, [name for name, _ in chronicles]),
                    datetime.datetime.now().isoformat(timespec="minutes"))
    _save_history(campaign.key, [answer, *load_history(campaign.key)])
    return answer
