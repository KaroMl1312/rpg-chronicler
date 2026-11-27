"""Wersja programu i lista nowości (nowosci.md). Tylko stdlib.

Wersja 1.000 to pierwsze wydanie publiczne; każdy kolejny commit podbija ją o 0.001 i dopisuje wpis
na górze nowosci.md (nagłówek `## WERSJA – RRRR-MM-DD`, punkty po polsku). Test pilnuje zgodności.
"""
import re
from pathlib import Path

VERSION = "1.008"

CHANGELOG_PATH = Path(__file__).with_name("nowosci.md")
HEADER_RE = re.compile(r"^## (\d+\.\d{3}) – (\d{4}-\d{2}-\d{2})\s*$", re.MULTILINE)


def changelog() -> str:
    try:
        return CHANGELOG_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def releases(text: str | None = None) -> list[tuple[str, str]]:
    """(wersja, data) od najnowszej."""
    return HEADER_RE.findall(changelog() if text is None else text)
