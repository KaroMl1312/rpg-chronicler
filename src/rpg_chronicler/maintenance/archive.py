"""Archiwizacja sesji: wszystkie pliki sesji trafiają do podfolderu `archiwum/` (lokalnie i na Google Drive).

`list_sessions` nie widzi podfolderów, więc sesja znika z listy, a pliki zostają. Na Drive pliki też są
przenoszone - inaczej `sync` pobrałby je z powrotem. Tylko stdlib (używane też przez GUI).
"""
import os
import shutil
from dataclasses import dataclass

from .. import session as _session

ARCHIVE_DIR_NAME = "archiwum"


class ArchiveError(Exception):
    pass


def belongs_to(filename: str, name: str, in_summary_dir: bool) -> bool:
    """Czy plik należy do sesji `name`.

    Nagrania i transkrypcje: `<nazwa>.<cokolwiek>` (.m4a, .txt, .mowcy.json, .glosy.json...).
    Kroniki: `<nazwa>_<rodzaj>.<rozszerzenie>` z rodzajem bez `_` (podsumowanie, skrot, kronika...) -
    dzięki temu `Sesja_cz2_podsumowanie.txt` nie jest brana za plik sesji `Sesja`.
    """
    if filename.startswith(f"{name}."):
        return True
    if in_summary_dir and filename.startswith(f"{name}_"):
        rest = filename[len(name) + 1:]
        return "_" not in rest and "." in rest
    return False


@dataclass(frozen=True)
class Move:
    src: str
    dst: str


def _dirs() -> list[tuple[str, bool]]:
    return [(_session.AUDIO_DIR, False), (_session.TXT_DIR, False), (_session.SUMMARY_DIR, True)]


def session_files(name: str) -> list[str]:
    """Ścieżki wszystkich lokalnych plików sesji (bez podfolderów)."""
    files = []
    for directory, in_summary in _dirs():
        try:
            entries = sorted(os.listdir(directory))
        except FileNotFoundError:
            continue
        files += [os.path.join(directory, f) for f in entries
                  if belongs_to(f, name, in_summary) and os.path.isfile(os.path.join(directory, f))]
    return files


def plan(name: str) -> list[Move]:
    moves = [Move(path, os.path.join(os.path.dirname(path), ARCHIVE_DIR_NAME, os.path.basename(path)))
             for path in session_files(name)]
    clashes = [m.dst for m in moves if os.path.exists(m.dst)]
    if clashes:
        raise ArchiveError(f"W archiwum są już pliki o tych nazwach: {', '.join(clashes)}")
    return moves


def archive_local(name: str, dry_run: bool = False) -> list[Move]:
    moves = plan(name)
    if not moves:
        raise ArchiveError(f"Sesja '{name}' nie ma żadnych plików do zarchiwizowania.")
    if not dry_run:
        for move in moves:
            os.makedirs(os.path.dirname(move.dst), exist_ok=True)
            shutil.move(move.src, move.dst)
    return moves


def remote_files(listing: list[str], name: str, in_summary_dir: bool) -> list[str]:
    """Pliki sesji z listy `rclone lsf` (tylko pliki z głównego folderu, bez podfolderów)."""
    return [f for f in listing if "/" not in f and belongs_to(f, name, in_summary_dir)]
