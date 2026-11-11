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
