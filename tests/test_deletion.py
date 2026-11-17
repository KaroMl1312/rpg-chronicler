"""Usuwanie kroniki / wszystkiego poza nagraniem / całej sesji (`delete`, deletion.py)."""
import datetime
import os
import subprocess

import pytest

from rpg_chronicler import cli, notes
from rpg_chronicler.maintenance import deletion
from rpg_chronicler.campaign_tools import memory
from rpg_chronicler.session import list_sessions
from rpg_chronicler.storage import drive

NAME = "Warhammer_261105"


@pytest.fixture
def full_session(workspace):
    dirs = workspace.dirs
    workspace.add_audio(NAME)
    (dirs["audio"] / "oryginaly").mkdir()
    (dirs["audio"] / "oryginaly" / f"{NAME}.m4a").write_bytes(b"przed przycieciem")
    workspace.add_transcript(NAME, "[SPEAKER_00] [0.00s -> 1.00s] Witajcie.\n")
    (dirs["txt"] / f"{NAME}.mowcy.json").write_text('{"SPEAKER_00": "MG"}', encoding="utf-8")
    for kind in ("podsumowanie.txt", "skrot.txt", "cytaty.txt", "kronika.pdf", "discord.json"):
        (dirs["summary"] / f"{NAME}_{kind}").write_text("x", encoding="utf-8")
    (dirs["summary"] / f"{NAME}_cz2_podsumowanie.txt").write_text("inna sesja", encoding="utf-8")
    (dirs["txt"] / "kampanie.toml").write_text("", encoding="utf-8")
    events = os.path.join(os.environ["XDG_CACHE_HOME"], "rpg-chronicler", "wydarzenia", NAME)
    os.makedirs(events)
    workspace.events_cache = events
    return workspace


def _names(paths):
    return sorted(os.path.basename(p) for p in paths)


def test_plan_scopes(full_session):
    chronicle = deletion.plan(NAME, deletion.CHRONICLE)
    assert _names(chronicle.files) == [f"{NAME}_{k}" for k in ("cytaty.txt", "discord.json", "kronika.pdf",
                                                                "podsumowanie.txt", "skrot.txt")]
    assert chronicle.caches == (full_session.events_cache,) and chronicle.remote_kinds == ("summary",)
    restart = deletion.plan(NAME, deletion.RESTART)
    assert set(_names(restart.files)) - set(_names(chronicle.files)) == {f"{NAME}.txt", f"{NAME}.mowcy.json"}
    everything = deletion.plan(NAME, deletion.SESSION)
    assert len(everything.files) == len(restart.files) + 2          # nagranie i oryginał sprzed przycięcia
    assert everything.remote_kinds == ("audio", "txt", "summary")
    assert "oryginaly/: Warhammer_261105.m4a" in deletion.describe(everything)


def test_plan_refusals(workspace):
    notes.save_notes("Zakon_261116", notes.Notes("- punkt"))
    with pytest.raises(deletion.DeletionError, match="nie ma nagrania"):
        deletion.plan("Zakon_261116", deletion.RESTART)
    with pytest.raises(deletion.DeletionError, match="nie ma lokalnie kroniki"):
        deletion.plan("Zakon_261116", deletion.CHRONICLE)
    with pytest.raises(deletion.DeletionError, match="Nie znaleziono"):
        deletion.plan("Nie_istnieje", deletion.SESSION)
    assert _names(deletion.plan("Zakon_261116", deletion.SESSION).files) == ["Zakon_261116.notatki.md"]


def test_delete_chronicle_and_undo(full_session, capsys):
    assert cli.main(["delete", NAME, "--offline"]) == 0
    [session] = list_sessions()
    assert not session.has_summary and session.has_transcript and session.has_speakers
    assert not os.path.exists(full_session.events_cache)
    assert (full_session.dirs["summary"] / f"{NAME}_cz2_podsumowanie.txt").exists()   # inna sesja zostaje
    assert "[SUKCES] Usunięto 5 plików" in capsys.readouterr().out

    assert cli.main(["delete", NAME, "--undo"]) == 0
    assert list_sessions()[0].has_summary
    assert cli.main(["delete", NAME, "--undo"]) == 1   # kosz pusty


def test_delete_whole_session_needs_confirmation(full_session, capsys):
    assert cli.main(["delete", NAME, "--zakres", "sesja", "--offline"]) == 1   # pytest: stdin to nie terminal
    assert "--yes" in capsys.readouterr().err and len(list_sessions()) == 1
    assert cli.main(["delete", NAME, "--zakres", "sesja", "--offline", "--yes"]) == 0
    assert list_sessions() == []
    assert not os.listdir(full_session.dirs["audio"] / "oryginaly")
    assert cli.main(["delete", NAME, "--undo"]) == 0
    assert list_sessions()[0].audio_path and (full_session.dirs["audio"] / "oryginaly" / f"{NAME}.m4a").exists()


def test_restart_keeps_audio(full_session):
    assert cli.main(["delete", NAME, "--zakres", "od-nowa", "--offline"]) == 0
    [session] = list_sessions()
    assert session.audio_path and not session.has_transcript and not session.has_summary


def test_drive_first_to_trash_and_failure_keeps_local(full_session, monkeypatch):
    calls = []
    listing = {drive.RCLONE_SUMMARY_REMOTE: [f"{NAME}_podsumowanie.txt", f"{NAME}_cz2_podsumowanie.txt",
                                             "archiwum/", f"Fallout_261014_podsumowanie.txt"]}

    def fake_run(cmd, **kwargs):
        if cmd[1] == "lsf":
            return subprocess.CompletedProcess(cmd, 0, stdout="\n".join(listing.get(cmd[2], [])), stderr="")
        files = open(cmd[cmd.index("--files-from-raw") + 1], encoding="utf-8").read().split()
        calls.append((cmd[1], cmd[2], files, "--drive-use-trash=true" in cmd))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(drive.subprocess, "run", fake_run)
    assert cli.main(["delete", NAME]) == 0
    assert calls == [("delete", drive.RCLONE_SUMMARY_REMOTE, [f"{NAME}_podsumowanie.txt"], True)]

    def failing(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(drive.subprocess, "run", failing)
    assert cli.main(["delete", NAME, "--zakres", "od-nowa"]) == 1
    assert list_sessions()[0].has_transcript                 # nic nie usunięto lokalnie


def test_trash_purge_and_campaign_warnings(full_session):
    memory.save_state("Warhammer", "## Drużyna\n- Fen", NAME)
    assert any("memory Warhammer --rebuild" in w for w in deletion.campaign_warnings(NAME))
    old = datetime.datetime(2026, 1, 1, 12, 0, 0)
    deletion.delete_local(deletion.plan(NAME, deletion.CHRONICLE), now=old)
    assert deletion.purge_old(now=old + datetime.timedelta(days=deletion.TRASH_DAYS - 1)) == 0
    assert deletion.purge_old(now=old + datetime.timedelta(days=deletion.TRASH_DAYS + 1)) == 1
    with pytest.raises(deletion.DeletionError):
        deletion.restore(NAME)
