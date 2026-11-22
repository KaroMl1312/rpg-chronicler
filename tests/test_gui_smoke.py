"""Test dymny GUI w Broadway (bez ekranu): wszystkie widoki budują się bez błędów i ostrzeżeń GTK.

GUI działa na systemowym Pythonie (PyGObject), więc test uruchamia tests/gui_smoke.py jako osobny proces.
Pomija się, gdy nie ma gtk4-broadwayd albo GTK/libadwaita (np. w CI); wyłączenie: pytest -m "not gui".
"""
import os
import random
import shutil
import subprocess
import sys
import time
import wave
from pathlib import Path

import pytest

from rpg_chronicler.transcript import Segment, Transcript, save_speaker_mapping, save_transcript

SYSTEM_PYTHON = "/usr/bin/python3"
ROOT = Path(__file__).resolve().parents[1]
GTK_CHECK = ("import gi; gi.require_version('Gtk', '4.0'); gi.require_version('Adw', '1'); "
             "from gi.repository import Adw")


def _gui_available() -> bool:
    if not shutil.which("gtk4-broadwayd") or not os.path.exists(SYSTEM_PYTHON):
        return False
    return subprocess.run([SYSTEM_PYTHON, "-c", GTK_CHECK], capture_output=True).returncode == 0


pytestmark = [pytest.mark.gui,
              pytest.mark.skipif(not _gui_available(), reason="brak gtk4-broadwayd albo GTK 4/libadwaita")]


def _make_data(base: Path) -> dict[str, str]:
    dirs = {name: base / name for name in ("nagrania", "transkrypcje", "kroniki", "home")}
    for path in dirs.values():
        path.mkdir()

    loop = [Segment(7.0 + i, 8.0 + i, "To jest to", "SPEAKER_00") for i in range(8)]  # pętla Whispera
    transcript = Transcript(segments=[Segment(0.0, 4.0, "Szukamy Romulusa w Dolinie.", "SPEAKER_00"),
                                      Segment(4.0, 7.0, "Tak?", "SPEAKER_01"), *loop], duration=15.0)
    txt = dirs["transkrypcje"] / "Warhammer_261105.txt"
    save_transcript(transcript, str(dirs["transkrypcje"] / "Warhammer_261105.transkrypcja.json"), str(txt))
    save_speaker_mapping(str(txt), {"SPEAKER_00": "MG", "SPEAKER_01": "Fen"})
    (dirs["transkrypcje"] / "kampanie.toml").write_text(
        '[Warhammer]\nsystem = "Warhammer"\nnpc = ["Ojciec Romulus"]\n'
        '[Warhammer.opisy]\n"Ojciec Romulus" = "Kapłan Morra."\n'
        '[Warhammer.postacie_graczy]\nFen = ""\n"Sir Amos" = "Ola"\n',
        encoding="utf-8")

    summary = dirs["kroniki"]
    (summary / "Warhammer_261105_podsumowanie.txt").write_text(
        "# Kronika Sesji: Noc Nietoperzy\n\n**Świt**\n- Kapłanka wskazała Ojca Romulusa.\n", encoding="utf-8")
    time.sleep(0.01)  # skrót i cytaty nowsze niż kronika
    (summary / "Warhammer_261105_skrot.txt").write_text("Dotarliście do Doliny.\n", encoding="utf-8")
    (summary / "Warhammer_261105_cytaty.txt").write_text("[0:00:04–0:00:07] „Tak?” — Fen\n", encoding="utf-8")

    for name, seconds in (("Warhammer_261112", 1), ("Warhammer_261105", 8), ("Fallout_261014", 1)):  # cisza
        with wave.open(str(dirs["nagrania"] / f"{name}.wav"), "wb") as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b"\0\0" * 16000 * seconds)

    settings = base / "ustawienia.toml"
    settings.write_text("[foldery]\n" + "".join(f'{key} = "{dirs[name]}"\n' for key, name in
                                                (("nagrania", "nagrania"), ("transkrypcje", "transkrypcje"),
                                                 ("podsumowania", "kroniki"))), encoding="utf-8")
    env_file = base / ".env"
    env_file.write_text("HUGGINGFACE_TOKEN=hf_test\n", encoding="utf-8")
    home = dirs["home"]
    return {"RPG_CHRONICLER_SETTINGS": str(settings), "RPG_CHRONICLER_ENV": str(env_file), "HOME": str(home), "XDG_CONFIG_HOME": str(home / ".config"),
            "XDG_CACHE_HOME": str(home / ".cache"), "XDG_DATA_HOME": str(home / ".local/share")}


def test_all_views_build_without_gtk_warnings(tmp_path):
    display = f":{random.randint(60, 99)}"
    broadway = subprocess.Popen(["gtk4-broadwayd", display], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(1)
        assert broadway.poll() is None, "gtk4-broadwayd nie wystartował"
        env = {**os.environ, **_make_data(tmp_path), "GDK_BACKEND": "broadway", "BROADWAY_DISPLAY": display,
               "PYTHONPATH": str(ROOT / "src"), "GSETTINGS_BACKEND": "memory",
               "CLOUDFLARE_ACCOUNT_ID": "test", "CLOUDFLARE_API_TOKEN": "test"}   # przycisk obrazka (bez sieci)
        env.pop("RPG_CHRONICLER_PROGRESS", None)
        proc = subprocess.run([SYSTEM_PYTHON, str(ROOT / "tests" / "gui_smoke.py")], env=env, cwd=ROOT,
                              capture_output=True, text=True, timeout=120)
    finally:
        broadway.terminate()
        broadway.wait(timeout=10)

    report = f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert proc.returncode == 0, report
    done = [line[3:] for line in proc.stdout.splitlines() if line.startswith("OK ")]
    assert done == ["okno", "filtr kampanii", "kronika", "znacznik Discorda", "skrót i cytaty", "transkrypcja",
                    "mówcy", "poprawka kroniki", "panel nagrania", "wyszukiwarka", "kampanie", "discord", "ustawienia",
                    "nowości", "uzupełnianie", "notatki", "usuwanie", "opisy haseł",
                    "przed sesją", "obrazek AI"], report
    # Adwaita-WARNING łapie m.in. okno szersze niż ekran (Broadway ma 1024 px) - zbyt wiele przycisków na pasku
    problems = [line for line in proc.stderr.splitlines()
                if "-CRITICAL" in line or "Gtk-WARNING" in line or "Adwaita-WARNING" in line]
    assert not problems, report


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
