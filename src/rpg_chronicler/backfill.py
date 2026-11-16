"""„Uzupełnij wszystko”: plan brakujących i nieaktualnych dodatków do kronik (komenda `backfill`, menu GUI).

Starsze sesje powstały, zanim aplikacja pisała skróty, cytaty i PDF-y, a encyklopedie i dzienniki
postaci nie odświeżają się same po nowej kronice. Plan wynika tylko z plików (jak reszta stanu):
- skrót: brak albo starszy niż kronika (`chronicle.brief_is_current`),
- cytaty: brak pliku (poza sesjami z notatek - nie ma czego cytować),
- PDF: nieaktualny (`chronicle.pdf_is_current`) albo zmieni się, bo dojdzie skrót lub cytaty,
- encyklopedia: każda kampania z kronikami - brak albo starsza niż kronika, skrót lub stan kampanii,
- dziennik postaci: tylko istniejące - starsze niż kronika kampanii (wpisy są w cache, AI pisze tylko nowe).
Tylko stdlib (GUI pokazuje plan przed uruchomieniem).
"""
import glob
import os
import re
from dataclasses import dataclass

from . import diary, encyclopedia, memory
from . import session as _session
from .campaigns import campaign_key
from .chronicle import brief_is_current, brief_path, pdf_is_current, quotes_path

BRIEF, QUOTES, PDF, ENCYCLOPEDIA, DIARY = "skrót", "cytaty", "PDF", "encyklopedia", "dziennik"
KINDS = (BRIEF, QUOTES, PDF, ENCYCLOPEDIA, DIARY)   # kolejność wykonania (PDF po skrócie i cytatach)
AI_KINDS = {BRIEF, QUOTES, ENCYCLOPEDIA, DIARY}
TITLE_RE = re.compile(r"^# Dziennik: (?P<name>.+)$", re.MULTILINE)


@dataclass(frozen=True)
class Step:
    kind: str
    target: str          # nazwa sesji albo klucz kampanii
    character: str = ""  # dla dziennika

    @property
    def label(self) -> str:
        return f"{self.kind} {self.target}" + (f" ({self.character})" if self.character else "")


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def existing_diaries(key: str) -> list[tuple[str, str]]:
    """[(postać, ścieżka .md)] dzienników kampanii (imię z nagłówka „# Dziennik: …”)."""
    result = []
    for path in sorted(glob.glob(os.path.join(glob.escape(_session.SUMMARY_DIR), f"dziennik-{glob.escape(key)}-*.md"))):
        try:
            with open(path, encoding="utf-8") as f:
                match = TITLE_RE.search(f.read(500))
        except OSError:
            continue
        if match and diary.markdown_path(key, match["name"].strip()) == path:
            result.append((match["name"].strip(), path))
    return result


def plan(sessions) -> list[Step]:
    """Kroki do wykonania, w kolejności KINDS."""
    chronicled = [s for s in sessions if s.has_summary]
    steps: list[Step] = []
    for s in chronicled:
        brief = not brief_is_current(s)
        quotes = not s.has_notes and not os.path.exists(quotes_path(s))   # sesja z notatek nie ma cytatów
        if brief:
            steps.append(Step(BRIEF, s.name))
        if quotes:
            steps.append(Step(QUOTES, s.name))
        if brief or quotes or not pdf_is_current(s):
            steps.append(Step(PDF, s.name))

    by_campaign: dict[str, list] = {}
    for s in chronicled:
        by_campaign.setdefault(campaign_key(s.name), []).append(s)
    for key, group in sorted(by_campaign.items()):
        newest_chronicle = max(_mtime(s.summary_path) for s in group)
        newest = max([newest_chronicle, _mtime(memory.state_path(key))] + [_mtime(brief_path(s)) for s in group])
        if _mtime(encyclopedia.markdown_path(key)) < newest or any(Step(BRIEF, s.name) in steps for s in group):
            steps.append(Step(ENCYCLOPEDIA, key))
        for character, path in existing_diaries(key):
            if _mtime(path) < newest_chronicle:
                steps.append(Step(DIARY, key, character))
    return sorted(steps, key=lambda step: KINDS.index(step.kind))


def summary(steps: list[Step]) -> str:
    """„skróty: 2, cytaty: 3, …” do okna potwierdzenia w GUI i komunikatu w CLI."""
    names = {BRIEF: "skróty", QUOTES: "cytaty", PDF: "PDF-y", ENCYCLOPEDIA: "encyklopedie", DIARY: "dzienniki postaci"}
    parts = []
    for kind in KINDS:
        targets = [s.character or s.target for s in steps if s.kind == kind]
        if not targets:
            continue
        shown = ", ".join(targets[:4]) + (f" i {len(targets) - 4} więcej" if len(targets) > 4 else "")
        parts.append(f"{names[kind]}: {len(targets)} ({shown})")
    return "\n".join(parts)


def ai_requests(steps: list[Step]) -> int:
    """Przybliżona liczba zapytań do AI (dziennik: co najmniej jedno - wpisy z cache są za darmo)."""
    return sum(1 for s in steps if s.kind in AI_KINDS)
