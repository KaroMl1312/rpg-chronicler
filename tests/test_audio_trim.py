import os
import shutil
import subprocess

import pytest

from rpg_chronicler import audio_trim, cli
from rpg_chronicler.audio_trim import SilenceAnalysis

needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="brak ffmpeg")


def analysis(silences, duration=220.0):
    return SilenceAnalysis("Test.flac", 1, 1.0, duration, silences=silences)


def test_parse_timestamp():
    assert audio_trim.parse_timestamp("1:20:05") == 4805
    assert audio_trim.parse_timestamp("80:05") == 4805
    assert audio_trim.parse_timestamp("4805,5") == 4805.5
    for bad in ("", "abc", "1:2:3:4", "1:75", "-5"):
        with pytest.raises(ValueError):
            audio_trim.parse_timestamp(bad)


def test_suggest_range_cuts_leading_and_trailing_silence():
    a = analysis([(0, 40), (60, 150), (170, 220)])
    assert audio_trim.suggest_range(a) == (38, 172)
    assert audio_trim.suggest_range(analysis([(60, 150)])) == (0, 220)
    assert audio_trim.suggest_range(analysis([(0, 220)])) == (0, 220)  # sama cisza - bez propozycji


def test_keep_segments_cuts_long_gaps_with_margin():
    a = analysis([(0, 40), (60, 150), (170, 220)])
    assert audio_trim.keep_segments(a, 38, 172) == [(38, 172)]
    assert audio_trim.keep_segments(a, 38, 172, cut_gaps_minutes=1) == [(38, 62), (148, 172)]
    assert audio_trim.keep_segments(a, 38, 172, cut_gaps_minutes=2) == [(38, 172)]  # przerwa 90 s < 2 min
    with pytest.raises(audio_trim.TrimError):
        audio_trim.keep_segments(a, 100, 50)


def test_describe_plan():
    a = analysis([(0, 40), (60, 150), (170, 220)])
    text = audio_trim.describe_plan(a, [(38, 62), (148, 172)])
    assert text == "Zostaje 0:00:48 z 0:03:40 (od 0:00:38 do 0:02:52, bez 1 przerwy w środku)."


def test_cached_analysis_is_invalidated_when_audio_changes(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    audio = tmp_path / "Zakon_1.flac"
    audio.write_bytes(b"abc")
    stat = os.stat(audio)
    audio_trim.save_analysis("Zakon_1", SilenceAnalysis(audio.name, stat.st_size, stat.st_mtime, 10.0))
    assert audio_trim.load_analysis("Zakon_1", str(audio)).duration == 10.0
    audio.write_bytes(b"abcdef")
    assert audio_trim.load_analysis("Zakon_1", str(audio)) is None


def make_audio(path, codec_args=()):
    """40 s ciszy, 20 s tonu, 90 s ciszy, 20 s tonu, 50 s ciszy."""
    parts = ["anullsrc=r=8000:cl=mono:d=40", "sine=f=440:r=8000:d=20", "anullsrc=r=8000:cl=mono:d=90",
             "sine=f=660:r=8000:d=20", "anullsrc=r=8000:cl=mono:d=50"]
    inputs = [arg for part in parts for arg in ("-f", "lavfi", "-i", part)]
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *inputs, "-filter_complex",
                    "concat=n=5:v=0:a=1", *codec_args, str(path)], check=True)


@needs_ffmpeg
@pytest.mark.parametrize("ext, codec_args", [(".flac", ()), (".m4a", ("-c:a", "aac", "-b:a", "32k"))])
def test_detect_and_trim(tmp_path, ext, codec_args):
    audio = tmp_path / f"Test_1{ext}"
    make_audio(audio, codec_args)

    a = audio_trim.detect_silences(str(audio))
    assert [(round(s), round(e)) for s, e in a.silences] == [(0, 40), (60, 150), (170, 220)]

    segments = audio_trim.keep_segments(a, *audio_trim.suggest_range(a), cut_gaps_minutes=1)
    backup = audio_trim.trim_audio(str(audio), segments)
    assert backup == str(tmp_path / "oryginaly" / audio.name)
    assert abs(audio_trim.probe(backup)[0] - 220) < 0.5
    assert abs(audio_trim.probe(str(audio))[0] - 48) < 0.5
    assert sorted(p.name for p in tmp_path.iterdir()) == [audio.name, "oryginaly"]  # bez plików tymczasowych


def test_cli_trim_refuses_session_with_transcript(workspace, capsys):
    workspace.add_audio("Zakon_1", ".flac")
    workspace.add_transcript("Zakon_1", "[0.00s -> 1.00s] tekst\n")
    assert cli.main(["trim", "Zakon_1"]) == 1
    assert "ma już transkrypcję" in capsys.readouterr().err


@needs_ffmpeg
def test_flac_without_duration_header_is_measured_and_fixed_by_trim(tmp_path):
    """Dyktafony zapisują FLAC strumieniowo - bez długości w nagłówku (jak wyjście do potoku)."""
    good = tmp_path / "dobry.flac"
    make_audio(good)
    audio = tmp_path / "Test_1.flac"
    with open(audio, "wb") as out:
        subprocess.run(["ffmpeg", "-loglevel", "error", "-i", str(good), "-f", "flac", "pipe:1"],
                       stdout=out, check=True)
    good.unlink()
    assert not audio_trim.has_duration_header(str(audio))

    duration, codec = audio_trim.probe(str(audio))  # wcześniej: TrimError „Nie można odczytać nagrania”
    assert codec == "flac" and abs(duration - 220) < 0.5

    a = audio_trim.detect_silences(str(audio))
    audio_trim.trim_audio(str(audio), audio_trim.keep_segments(a, *audio_trim.suggest_range(a)))
    assert audio_trim.has_duration_header(str(audio))


def test_duration_header_check_is_cached_per_file_version(tmp_path, monkeypatch):
    audio = tmp_path / "Zakon_1.flac"
    audio.write_bytes(b"abc")
    calls = []

    class Result:
        stdout = "12.5\n"

    monkeypatch.setattr(audio_trim.shutil, "which", lambda _tool: "/usr/bin/ffprobe")
    monkeypatch.setattr(audio_trim.subprocess, "run", lambda *a, **k: calls.append(a) or Result())
    assert audio_trim.has_duration_header(str(audio)) and audio_trim.has_duration_header(str(audio))
    assert len(calls) == 1
    audio.write_bytes(b"abcdef")  # inny plik (np. po przycięciu) - sprawdzamy ponownie
    audio_trim.has_duration_header(str(audio))
    assert len(calls) == 2
