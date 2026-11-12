"""Synchronizacja z Google Drive przez rclone."""
import os
import subprocess

from ..config import (
    AUDIO_DIR,
    RCLONE_AUDIO_REMOTE,
    RCLONE_SUMMARY_REMOTE,
    RCLONE_TXT_REMOTE,
    SUMMARY_DIR,
    TXT_DIR,
)


def rclone_copy(src: str, dst: str, quiet: bool = False, extra: tuple[str, ...] = ()) -> None:
    """Kopiuje pliki rclone'em; rzuca CalledProcessError przy niepowodzeniu."""
    subprocess.run(["rclone", "copy", src, dst, "--quiet" if quiet else "-P", *extra], check=True)


def sync_from_gdrive():
    print("--- Pobieranie nowych plików z Google Drive ---")
    for path in (AUDIO_DIR, TXT_DIR, SUMMARY_DIR):
        os.makedirs(path, exist_ok=True)

    # Pobieramy też gotowe transkrypcje (z .mowcy.json) i podsumowania, żeby wiedzieć co już zostało zrobione
    for remote, local in ((RCLONE_TXT_REMOTE, TXT_DIR), (RCLONE_SUMMARY_REMOTE, SUMMARY_DIR)):
        try:
            # --update: nie nadpisujemy nowszych plików zmienionych lokalnie (kampanie.toml, mówcy) starszymi z Drive
            rclone_copy(remote, local, quiet=True, extra=("--update",))
        except Exception as e:
            print(f"[OSTRZEŻENIE] Nie udało się pobrać {remote}: {e}")

    try:
        # --ignore-existing: nie nadpisujemy lokalnych nagrań (np. przyciętych) oryginałami z Drive
        rclone_copy(RCLONE_AUDIO_REMOTE, AUDIO_DIR, extra=("--ignore-existing",))
        print("Pobieranie zakończone z sukcesem.")
    except Exception as e:
        print(f"[OSTRZEŻENIE] Błąd podczas pobierania rclone: {e}")


def upload_to_gdrive():
    print("\n--- Wysyłanie plików na Google Drive ---")

    print("Wysyłanie transkrypcji...")
    try:
        rclone_copy(TXT_DIR, RCLONE_TXT_REMOTE, extra=("--update",))
        print("Transkrypcje wysłane z sukcesem.")
    except Exception as e:
        print(f"[BŁĄD] Nie udało się wysłać transkrypcji: {e}")

    print("Wysyłanie podsumowań AI...")
    try:
        rclone_copy(SUMMARY_DIR, RCLONE_SUMMARY_REMOTE, extra=("--update",))
        print("Podsumowania wysłane z sukcesem.")
    except Exception as e:
        print(f"[BŁĄD] Nie udało się wysłać podsumowań: {e}")


def archive_on_gdrive(name: str, dry_run: bool = False) -> int:
    """Przenosi pliki sesji na Drive do podfolderu archiwum/ (inaczej `sync` pobrałby je z powrotem).

    Zwraca liczbę przeniesionych (w podglądzie: znalezionych) plików.
    """
    import tempfile

    from ..archive import ARCHIVE_DIR_NAME, remote_files

    total = 0
    for remote, in_summary in ((RCLONE_AUDIO_REMOTE, False), (RCLONE_TXT_REMOTE, False),
                               (RCLONE_SUMMARY_REMOTE, True)):
        listing = subprocess.run(["rclone", "lsf", remote, "--files-only"], check=True,
                                 capture_output=True, text=True).stdout.splitlines()
        files = remote_files(listing, name, in_summary)
        for f in files:
            print(f"  {'[PODGLĄD] ' if dry_run else ''}{remote}/{f} -> {ARCHIVE_DIR_NAME}/")
        total += len(files)
        if dry_run or not files:
            continue
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as lst:
            lst.write("\n".join(files) + "\n")
        try:
            subprocess.run(["rclone", "move", remote, f"{remote.rstrip('/')}/{ARCHIVE_DIR_NAME}",
                            "--files-from-raw", lst.name, "--quiet"], check=True)
        finally:
            os.unlink(lst.name)
    return total
