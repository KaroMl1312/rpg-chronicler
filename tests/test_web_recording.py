"""Nowe okno, etap 4: panel nagrania, uwagi jakości, statystyki, „Uzupełnij brakujące” (web/recording_api.py)."""
import os

import pytest

from rpg_chronicler import audio_trim
from rpg_chronicler.audio_trim import SilenceAnalysis
from rpg_chronicler.web import api, recording_api

LOOP = ("[SPEAKER_00] [0.00s -> 2.00s] Start.\n"
        + "".join(f"[SPEAKER_00] [{10 + 2 * i}.00s -> {12 + 2 * i}.00s] To jest to\n" for i in range(9))
        + "[SPEAKER_01] [30.00s -> 34.00s] Koniec.\n")


@pytest.fixture
def recorded(workspace, monkeypatch):
    workspace.add_audio("Zakon_261015")
    monkeypatch.setattr(audio_trim, "require_ffmpeg", lambda: None)
    monkeypatch.setattr(audio_trim, "has_duration_header", lambda path: True)
    path = str(workspace.dirs["audio"] / "Zakon_261015.m4a")
    stat = os.stat(path)
    audio_trim.save_analysis("Zakon_261015", SilenceAnalysis("Zakon_261015.m4a", stat.st_size, stat.st_mtime, 220.0,
                                                             silences=[(0, 40), (60, 150), (170, 220)]))
    workspace.audio_path = path
    return workspace


def test_recording_panel_proposal(recorded):
    data = recording_api.recording("Zakon_261015")
    assert data["analysis"]["start"] == "0:00:38" and data["analysis"]["end"] == "0:02:52"
    assert [s["label"] for s in data["analysis"]["silences"]][0] == "0:00:00 – 0:00:40"
    with pytest.raises(Exception):
        recording_api.recording("Nie_ma")


def test_trim_plan_matches_command(recorded, monkeypatch):
    plan = recording_api.trim_plan("Zakon_261015", "0:00:38", "0:02:52", 1)
    assert plan["segments"] == [(38, 62), (148, 172)] and plan["changes"]
    assert plan["args"] == ["trim", "Zakon_261015", "--start", "0:00:38", "--end", "0:02:52", "--cut-gaps", "1",
                            "--noise", "-40", "--min-silence", "30"]
    from rpg_chronicler.cli.parser import build_parser
    args = build_parser().parse_args(plan["args"])
    assert (args.noise, args.min_silence, args.cut_gaps) == (-40.0, 30.0, 1.0)

    assert "Niepoprawny czas" in recording_api.trim_plan("Zakon_261015", "abc", "0:02:52", 0)["error"]
    assert recording_api.trim_plan("Zakon_261015", "0:02:00", "0:01:00", 0)["error"]
    whole = recording_api.trim_plan("Zakon_261015", "0", "0:03:40", 0)
    assert whole["changes"] is False                       # nie ma czego przycinać…
    monkeypatch.setattr(audio_trim, "has_duration_header", lambda path: False)
    assert recording_api.trim_plan("Zakon_261015", "0", "0:03:40", 0)["changes"] is True   # …chyba że brak nagłówka

    os.utime(recorded.audio_path, (1, 1))                  # nagranie podmienione po analizie
    assert "wykryj ciszę ponownie" in recording_api.trim_plan("Zakon_261015", "0", "0:03:40", 0)["error"]
    assert recording_api.recording("Zakon_261015")["analysis"] is None


def test_missing_ffmpeg_is_reported(recorded, monkeypatch):
    def missing():
        raise audio_trim.TrimError("Brak programu ffmpeg")
    monkeypatch.setattr(audio_trim, "require_ffmpeg", missing)
    data = recording_api.recording("Zakon_261015")
    assert data["error"] == "Brak programu ffmpeg" and data["analysis"] is None


def test_transcript_issues_and_stats(workspace):
    workspace.add_transcript("Zakon_261015", LOOP)
    workspace.add_transcript("Zakon_261022", "[SPEAKER_00] [0.00s -> 10.00s] Dalej.\n")
    workspace.add_transcript("Inna_261022", "[SPEAKER_00] [0.00s -> 10.00s] Obca kampania.\n")
    for name in ("Zakon_261015", "Zakon_261022"):
        (workspace.dirs["txt"] / f"{name}.mowcy.json").write_text('{"SPEAKER_00": "MG", "SPEAKER_01": "Fen"}',
                                                                  encoding="utf-8")
    data = api.transcript("Zakon_261015")
    assert data["loops"] and not data["undo_loops"] and "11 segmentów" in data["info"]
    assert any(i["kind"] == "petla" and i["at"] == 10.0 for i in data["issues"])

    one = recording_api.session_stats("Zakon_261015")
    assert [s["name"] for s in one["speakers"]] == ["MG", "Fen"] and one["count"] == 1
    assert recording_api.session_stats("Zakon_261015", campaign=True)["count"] == 2


def test_backfill_plan(workspace):
    assert recording_api.backfill_plan()["count"] == 0
    workspace.add_transcript("Zakon_261015", LOOP)
    (workspace.dirs["summary"] / "Zakon_261015_podsumowanie.txt").write_text("Kronika.", encoding="utf-8")
    plan = recording_api.backfill_plan()
    assert "skróty: 1 (Zakon_261015)" in plan["summary"] and plan["requests"] >= 2
